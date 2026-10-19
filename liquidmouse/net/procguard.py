"""Vita e morte di cloudflared legate a quella del programma (solo Windows).

Due problemi, entrambi con l'indirizzo pubblico del tunnel che resta aperto
verso una porta di nessuno:

- se il programma muore senza passare da `stop()` (crash, kill dal task
  manager, spegnimento brusco), `cloudflared.exe` continua a girare: un
  *Job Object* con KILL_ON_JOB_CLOSE lo fa terminare dal sistema operativo
  appena l'ultimo handle del job si chiude, cioè quando muore il nostro
  processo, comunque muoia;
- se un avvio precedente ha lasciato un cloudflared orfano (versioni senza il
  job, o job non disponibile), `terminate_stale` lo chiude all'avvio, ma solo
  se il suo eseguibile è esattamente quello della nostra cartella `bin`: un
  cloudflared dell'utente (nel PATH, o di un altro servizio) non si tocca.

Le chiamate a kernel32 stanno in `_Win32Api`; `KillOnCloseJob` e
`terminate_stale` ricevono l'API come argomento, così la logica gira nei test
su Linux con un finto. Su Linux/macOS l'API reale non esiste e tutto è inerte.
"""

import ctypes
import os
import sys
from typing import Protocol

from liquidmouse.events import log_message
from liquidmouse.theme import COLOR_MUTED

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x2
MAX_PATH_CHARS = 32768


class _BasicLimits(ctypes.Structure):
    # JOBOBJECT_BASIC_LIMIT_INFORMATION; SIZE_T e ULONG_PTR = c_size_t.
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(nome, ctypes.c_uint64) for nome in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: 144 byte su Windows a 64 bit.
    _fields_ = [("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _ProcessEntry(ctypes.Structure):
    # PROCESSENTRY32W
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32),
                ("szExeFile", ctypes.c_wchar * 260)]


class ProcApi(Protocol):
    """Ciò che serve di kernel32; `_Win32Api` è l'implementazione vera."""

    def create_job(self): ...
    def set_kill_on_close(self, job) -> bool: ...
    def assign(self, job, pid: int) -> bool: ...
    def close(self, handle) -> None: ...
    def find_processes(self, name: str) -> list[tuple[int, str]]: ...
    def terminate(self, pid: int) -> bool: ...


class _Win32Api:
    def __init__(self) -> None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, DW, BOOL = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        k.CreateJobObjectW.restype, k.CreateJobObjectW.argtypes = H, [H, ctypes.c_wchar_p]
        k.SetInformationJobObject.restype = BOOL
        k.SetInformationJobObject.argtypes = [H, ctypes.c_int, H, DW]
        k.AssignProcessToJobObject.restype = BOOL
        k.AssignProcessToJobObject.argtypes = [H, H]
        k.OpenProcess.restype, k.OpenProcess.argtypes = H, [DW, BOOL, DW]
        k.CloseHandle.restype, k.CloseHandle.argtypes = BOOL, [H]
        k.TerminateProcess.restype = BOOL
        k.TerminateProcess.argtypes = [H, ctypes.c_uint]
        k.CreateToolhelp32Snapshot.restype = H
        k.CreateToolhelp32Snapshot.argtypes = [DW, DW]
        for nome in ("Process32FirstW", "Process32NextW"):
            f = getattr(k, nome)
            f.restype, f.argtypes = BOOL, [H, ctypes.POINTER(_ProcessEntry)]
        k.QueryFullProcessImageNameW.restype = BOOL
        k.QueryFullProcessImageNameW.argtypes = [
            H, DW, ctypes.c_wchar_p, ctypes.POINTER(DW)]
        self._k = k

    def create_job(self):
        return self._k.CreateJobObjectW(None, None) or None

    def set_kill_on_close(self, job) -> bool:
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return bool(self._k.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info), ctypes.sizeof(info)))

    def assign(self, job, pid: int) -> bool:
        proc = self._k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid)
        if not proc:
            return False
        try:
            return bool(self._k.AssignProcessToJobObject(job, proc))
        finally:
            self._k.CloseHandle(proc)

    def close(self, handle) -> None:
        self._k.CloseHandle(handle)

    def find_processes(self, name: str) -> list[tuple[int, str]]:
        """(pid, percorso dell'eseguibile) dei processi con quel nome file."""
        trovati = []
        snap = self._k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        # INVALID_HANDLE_VALUE = -1 (c_void_p lo restituisce come 2**64 - 1)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return trovati
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            ok = self._k.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == name.lower():
                    percorso = self._image_path(entry.th32ProcessID)
                    if percorso:
                        trovati.append((entry.th32ProcessID, percorso))
                ok = self._k.Process32NextW(snap, ctypes.byref(entry))
        finally:
            self._k.CloseHandle(snap)
        return trovati

    def _image_path(self, pid: int) -> str | None:
        h = self._k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
            size = ctypes.c_uint32(MAX_PATH_CHARS)
            if self._k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            self._k.CloseHandle(h)

    def terminate(self, pid: int) -> bool:
        h = self._k.OpenProcess(PROCESS_TERMINATE, 0, pid)
        if not h:
            return False
        try:
            return bool(self._k.TerminateProcess(h, 1))
        finally:
            self._k.CloseHandle(h)


def default_api() -> ProcApi | None:
    """L'API di kernel32, o None dove non esiste (Linux, macOS)."""
    if sys.platform != "win32":
        return None
    try:
        return _Win32Api()
    except Exception:
        return None


class KillOnCloseJob:
    """Job Object che termina i suoi processi quando il nostro muore.

    Si crea lazy alla prima `assign` e se ne tiene l'handle per tutta la vita
    del processo: è proprio la chiusura di quell'handle (da parte del sistema,
    alla morte del processo) a far terminare i figli. Mai chiuderlo a mano
    prima dell'uscita. Senza API (non Windows) o su errore, `assign` ritorna
    False e il chiamante continua senza job (resta `stop()` e atexit).
    """

    def __init__(self, api: ProcApi | None = None) -> None:
        self._api = api if api is not None else default_api()
        self._job = None
        self._fallito = False

    @property
    def available(self) -> bool:
        return self._api is not None and not self._fallito

    def _ensure(self):
        if self._job is not None or not self.available:
            return self._job
        job = self._api.create_job()
        if job and self._api.set_kill_on_close(job):
            self._job = job
        else:
            if job:
                self._api.close(job)
            self._fallito = True
        return self._job

    def assign(self, pid: int) -> bool:
        """Mette il processo `pid` nel job. False se non è stato possibile."""
        job = self._ensure()
        if job is None:
            return False
        return self._api.assign(job, pid)


def _norm(percorso: str) -> str:
    return os.path.normcase(os.path.realpath(percorso))


def terminate_stale(bin_path, api: ProcApi | None = None) -> int:
    """Chiude i cloudflared rimasti da un avvio precedente.

    Solo quelli il cui eseguibile è `bin_path` (la nostra copia in
    %APPDATA%/LiquidMouse/bin): il confronto è sul percorso completo, non sul
    nome, perché `cloudflared.exe` è un nome che usano anche altri. Ritorna
    quanti ne ha chiusi. Non solleva.
    """
    api = api if api is not None else default_api()
    if api is None:
        return 0
    try:
        nostro = _norm(str(bin_path))
        chiusi = 0
        for pid, percorso in api.find_processes(os.path.basename(str(bin_path))):
            if _norm(percorso) != nostro:
                continue
            if api.terminate(pid):
                chiusi += 1
                log_message(f"Tunnel: chiuso un cloudflared rimasto da prima (pid {pid})",
                            color=COLOR_MUTED)
        return chiusi
    except Exception:
        return 0
