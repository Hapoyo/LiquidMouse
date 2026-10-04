"""Backend PTY per il terminale remoto.

Due implementazioni con la stessa interfaccia a byte: pywinpty quando è
installato, altrimenti ConPTY diretto via ctypes (nessuna dipendenza, ma
richiede Windows 10 1809+). `make_pty` sceglie.

Il modulo si importa anche fuori da Windows — `ctypes.wintypes` è portabile,
solo `ctypes.windll` non lo è — così i test degli altri moduli del pacchetto
non devono saltare l'import.
"""

import ctypes
import ctypes.wintypes as _wt
import subprocess
import sys
import threading

from liquidmouse.events import log_message
from liquidmouse.theme import COLOR_MUTED

_k32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

try:
    import winpty as _winpty_mod
    WINPTY_AVAILABLE = True
except Exception:
    _winpty_mod = None
    WINPTY_AVAILABLE = False


class _COORD(ctypes.Structure):
    _fields_ = [("X", _wt.SHORT), ("Y", _wt.SHORT)]


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb",              _wt.DWORD),
        ("lpReserved",      _wt.LPWSTR),
        ("lpDesktop",       _wt.LPWSTR),
        ("lpTitle",         _wt.LPWSTR),
        ("dwX",             _wt.DWORD),
        ("dwY",             _wt.DWORD),
        ("dwXSize",         _wt.DWORD),
        ("dwYSize",         _wt.DWORD),
        ("dwXCountChars",   _wt.DWORD),
        ("dwYCountChars",   _wt.DWORD),
        ("dwFillAttribute", _wt.DWORD),
        ("dwFlags",         _wt.DWORD),
        ("wShowWindow",     _wt.WORD),
        ("cbReserved2",     _wt.WORD),
        ("lpReserved2",     ctypes.c_char_p),
        ("hStdInput",       _wt.HANDLE),
        ("hStdOutput",      _wt.HANDLE),
        ("hStdError",       _wt.HANDLE),
    ]


class _STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess",    _wt.HANDLE),
        ("hThread",     _wt.HANDLE),
        ("dwProcessId", _wt.DWORD),
        ("dwThreadId",  _wt.DWORD),
    ]


_EXTENDED_STARTUPINFO_PRESENT        = 0x00080000
_CREATE_NO_WINDOW                    = 0x08000000
_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_STILL_ACTIVE = 259
_INFINITE = 0xFFFFFFFF
_DUPLICATE_SAME_ACCESS = 0x00000002
# Pseudo-handle restituito da GetCurrentProcess(): costante, non va chiuso.
_CURRENT_PROCESS = _wt.HANDLE(-1)

READ_SIZE = 4096


class ConPTY:
    """ConPTY diretto via ctypes — nessuna dipendenza esterna.

    Quando il processo figlio termina (es. `exit` in cmd.exe) conhost tiene
    aperto il lato di scrittura della pipe di output: `ReadFile` non riceve EOF
    finché qualcuno non chiama `ClosePseudoConsole`. Senza, il read loop della
    sessione restava bloccato per sempre, con la sessione ancora "attiva" e un
    thread dell'executor occupato. Per questo un thread di attesa chiude la
    pseudo-console appena il processo esce (`_wait_exit`).
    """

    def __init__(self, argv: list, cwd: str, cols: int = 120, rows: int = 40):
        if _k32 is None:
            raise OSError("ConPTY richiede Windows")
        # Protegge gli handle condivisi fra il thread di attesa e _cleanup():
        # ognuno va chiuso una volta sola, da chi lo toglie per primo.
        self._close_lock = threading.Lock()
        self._waiter: threading.Thread | None = None
        self._hproc = self._hpc = self._stdin_w = self._stdout_r = None
        # Buffer di lettura riusato: _read_loop chiama read() in continuazione e
        # allocarne uno nuovo da 4 KB a ogni giro era spreco puro.
        self._read_buf = (ctypes.c_char * READ_SIZE)()
        h_sin_r, h_sin_w, h_sout_r, h_sout_w = (_wt.HANDLE() for _ in range(4))

        if not _k32.CreatePipe(ctypes.byref(h_sin_r), ctypes.byref(h_sin_w), None, 0):
            raise OSError(f"CreatePipe(stdin) err {_k32.GetLastError()}")
        if not _k32.CreatePipe(ctypes.byref(h_sout_r), ctypes.byref(h_sout_w), None, 0):
            _k32.CloseHandle(h_sin_r); _k32.CloseHandle(h_sin_w)
            raise OSError(f"CreatePipe(stdout) err {_k32.GetLastError()}")

        hpc = _wt.HANDLE()
        hr = _k32.CreatePseudoConsole(_COORD(cols, rows), h_sin_r, h_sout_w, 0, ctypes.byref(hpc))
        _k32.CloseHandle(h_sin_r); _k32.CloseHandle(h_sout_w)
        if hr != 0:
            _k32.CloseHandle(h_sin_w); _k32.CloseHandle(h_sout_r)
            raise OSError(f"CreatePseudoConsole hr={hr:#010x}")

        self._hpc, self._stdin_w, self._stdout_r = hpc, h_sin_w, h_sout_r

        attr_sz = ctypes.c_size_t(0)
        _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_sz))
        attr_buf = (ctypes.c_byte * attr_sz.value)()
        attr_ptr = ctypes.cast(attr_buf, ctypes.c_void_p)
        if not _k32.InitializeProcThreadAttributeList(attr_ptr, 1, 0, ctypes.byref(attr_sz)):
            raise OSError(f"InitializeProcThreadAttributeList err {_k32.GetLastError()}")
        try:
            _k32.UpdateProcThreadAttribute(attr_ptr, 0,
                _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, hpc, ctypes.sizeof(hpc), None, None)

            si = _STARTUPINFOEX()
            ctypes.memset(ctypes.byref(si), 0, ctypes.sizeof(si))
            si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEX)
            si.lpAttributeList = attr_ptr

            pi = _PROCESS_INFORMATION()
            cmd_str = subprocess.list2cmdline(argv) if isinstance(argv, list) else argv
            ok = _k32.CreateProcessW(None, cmd_str, None, None, False,
                _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW,
                None, cwd, ctypes.byref(si), ctypes.byref(pi))
            if not ok:
                err = _k32.GetLastError()
                self._cleanup()
                raise OSError(f"CreateProcessW err={err} cmd={cmd_str!r}")
        finally:
            _k32.DeleteProcThreadAttributeList(attr_ptr)
        self._hproc = pi.hProcess
        _k32.CloseHandle(pi.hThread)
        self._start_exit_waiter()

    def _start_exit_waiter(self) -> None:
        """Avvia il thread che chiude la pseudo-console all'uscita del processo.

        Il thread aspetta su un **duplicato** dell'handle del processo, suo e
        chiuso da lui: `_cleanup()` può così chiudere `self._hproc` in qualsiasi
        momento senza chiudere un handle su cui un altro thread sta aspettando.
        """
        dup = _wt.HANDLE()
        if not _k32.DuplicateHandle(_CURRENT_PROCESS, _wt.HANDLE(self._hproc),
                                    _CURRENT_PROCESS, ctypes.byref(dup),
                                    _wt.DWORD(0), False, _wt.DWORD(_DUPLICATE_SAME_ACCESS)):
            # Senza thread si torna al comportamento precedente: la sessione si
            # chiude solo con un kill esplicito. Da dire, non da far fallire.
            log_message(f"ConPTY: DuplicateHandle err {_k32.GetLastError()}, "
                        "uscita del processo non rilevata", color=COLOR_MUTED)
            return
        self._waiter = threading.Thread(target=self._wait_exit, args=(dup,),
                                        name="conpty-exit", daemon=True)
        self._waiter.start()

    def _wait_exit(self, hproc) -> None:
        """Corpo del thread di attesa: processo uscito → pseudo-console chiusa."""
        try:
            _k32.WaitForSingleObject(hproc, _wt.DWORD(_INFINITE))
        finally:
            _k32.CloseHandle(hproc)
        # Chiudere la pseudo-console fa ricevere EOF alla ReadFile in corso nel
        # read loop, che chiude la sessione e avvisa i viewer (term_closed).
        self._close_pseudoconsole()

    def _close_pseudoconsole(self) -> None:
        """Chiude la pseudo-console una volta sola, chiunque arrivi per primo.

        La chiamata avviene fuori dal lock: sulle build di Windows che
        aspettano lo svuotamento dell'output, ClosePseudoConsole può bloccare
        finché il read loop non ha letto tutto, e non deve tenere fermo chi
        chiama _cleanup() nel frattempo.
        """
        with self._close_lock:
            hpc, self._hpc = self._hpc, None
        if hpc:
            try:
                _k32.ClosePseudoConsole(hpc)
            except Exception:
                pass

    def read(self, size: int = READ_SIZE) -> bytes:
        buf = self._read_buf if size == READ_SIZE else (ctypes.c_char * size)()
        n = _wt.DWORD(0)
        ok = _k32.ReadFile(self._stdout_r, buf, size, ctypes.byref(n), None)
        if not ok or n.value == 0:
            raise EOFError("ConPTY EOF")
        return bytes(buf[:n.value])

    def write(self, data) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        # WriteFile può scrivere meno di quanto chiesto (pipe quasi piena): il
        # resto va riprovato, altrimenti si perdono tasti in mezzo a un incolla.
        # Gli errori salgono: prima erano ignorati e l'input spariva in silenzio.
        while data:
            h = self._stdin_w
            if not h:
                raise OSError("ConPTY chiuso")
            n = _wt.DWORD(0)
            if not _k32.WriteFile(h, data, len(data), ctypes.byref(n), None):
                raise OSError(f"WriteFile err {_k32.GetLastError()}")
            if n.value == 0:
                raise OSError("WriteFile non ha scritto nulla")
            data = data[n.value:]

    def isalive(self) -> bool:
        if not self._hproc:
            return False
        ec = _wt.DWORD()
        _k32.GetExitCodeProcess(self._hproc, ctypes.byref(ec))
        return ec.value == _STILL_ACTIVE

    @property
    def exitstatus(self) -> int:
        if not self._hproc:
            return 0
        ec = _wt.DWORD()
        _k32.GetExitCodeProcess(self._hproc, ctypes.byref(ec))
        return 0 if ec.value == _STILL_ACTIVE else ec.value

    def set_size(self, rows: int, cols: int) -> None:
        hpc = self._hpc  # il thread di attesa può azzerarlo in qualsiasi momento
        if hpc:
            try:
                _k32.ResizePseudoConsole(hpc, _COORD(cols, rows))
            except Exception:
                pass

    def close(self) -> None:
        if self._hproc:
            try:
                _k32.TerminateProcess(self._hproc, 0)
            except Exception:
                pass
        self._cleanup()

    def _cleanup(self) -> None:
        """Chiude pseudo-console e handle. Idempotente e sicura rispetto al
        thread di attesa: gli handle si prendono e si azzerano sotto lock."""
        self._close_pseudoconsole()
        with self._close_lock:
            handles = [self._stdin_w, self._stdout_r, self._hproc]
            self._hproc = self._stdin_w = self._stdout_r = None
        for h in handles:
            if h:
                try:
                    _k32.CloseHandle(h)
                except Exception:
                    pass


class PyWinPTY:
    """Wrapper pywinpty con la stessa interfaccia a byte di ConPTY."""

    def __init__(self, argv: list, cwd: str, cols: int = 120, rows: int = 40):
        self._p = _winpty_mod.PtyProcess.spawn(argv, dimensions=(rows, cols), cwd=cwd)

    def read(self, size: int = READ_SIZE) -> bytes:
        s = self._p.read(size)
        if s is None or s == "":
            if not self._p.isalive():
                raise EOFError("PtyProcess EOF")
            return b""
        return s.encode("utf-8", errors="replace") if isinstance(s, str) else s

    def write(self, data) -> None:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        self._p.write(data)

    def isalive(self) -> bool:
        try:
            return self._p.isalive()
        except Exception:
            return False

    @property
    def exitstatus(self) -> int:
        try:
            return self._p.exitstatus or 0
        except Exception:
            return 0

    def set_size(self, rows: int, cols: int) -> None:
        try:
            self._p.setwinsize(rows, cols)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._p.close(force=True)
        except Exception:
            pass


def make_pty(argv: list, cwd: str, cols: int = 120, rows: int = 40):
    """Sceglie il backend: pywinpty quando disponibile, ConPTY come fallback."""
    if WINPTY_AVAILABLE:
        try:
            return PyWinPTY(argv, cwd, cols, rows)
        except Exception as e:
            log_message(f"pywinpty fallita ({e}), fallback ConPTY", color=COLOR_MUTED)
    return ConPTY(argv, cwd, cols, rows)
