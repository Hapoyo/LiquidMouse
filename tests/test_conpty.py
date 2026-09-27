"""ConPTY via ctypes: chiusura all'uscita del processo, senza Windows.

`kernel32` è sostituito da un finto che simula pipe, pseudo-console e processo
e registra ogni ClosePseudoConsole / CloseHandle. Il punto da proteggere: il
thread che aspetta l'uscita del processo e `_cleanup()` (chiamata da kill)
possono correre in parallelo, e nessun handle deve essere chiuso due volte.
"""

import ctypes
import threading
from collections import Counter

import pytest

from liquidmouse.terminal import conpty

HPC, PROC, THREAD, DUP = 100, 200, 201, 300


def _valore(h):
    """Valore numerico di un handle passato come int o come oggetto ctypes."""
    return getattr(h, "value", h)


class FintoKernel32:
    def __init__(self):
        # Pipe numerate da 10000 in su: non devono mai coincidere con gli
        # handle fissi della pseudo-console e del processo qui sopra.
        self._prossimo = 10_000
        self.uscito = threading.Event()   # il processo figlio è terminato
        self.chiusi = Counter()           # handle → numero di CloseHandle
        self.pseudo_chiuse = Counter()    # hpc → numero di ClosePseudoConsole
        self.attese = Counter()
        self._lock = threading.Lock()

    # --- creazione ---
    def CreatePipe(self, p_read, p_write, sa, size):
        p_read._obj.value = self._prossimo
        p_write._obj.value = self._prossimo + 1
        self._prossimo += 2
        return 1

    def CreatePseudoConsole(self, coord, h_in, h_out, flags, p_hpc):
        p_hpc._obj.value = HPC
        return 0

    def InitializeProcThreadAttributeList(self, lista, count, flags, p_size):
        p_size._obj.value = 64
        return 1

    def UpdateProcThreadAttribute(self, *args):
        return 1

    def DeleteProcThreadAttributeList(self, lista):
        pass

    def CreateProcessW(self, app, cmd, pa, ta, inherit, flags, env, cwd, p_si, p_pi):
        p_pi._obj.hProcess = PROC
        p_pi._obj.hThread = THREAD
        return 1

    def DuplicateHandle(self, src_proc, h, dst_proc, p_dup, access, inherit, options):
        assert _valore(h) == PROC
        p_dup._obj.value = DUP
        return 1

    def GetLastError(self):
        return 0

    # --- ciclo di vita ---
    def WaitForSingleObject(self, h, timeout):
        with self._lock:
            self.attese[_valore(h)] += 1
        self.uscito.wait()
        return 0

    def TerminateProcess(self, h, code):
        self.uscito.set()
        return 1

    def ClosePseudoConsole(self, hpc):
        with self._lock:
            self.pseudo_chiuse[_valore(hpc)] += 1

    def CloseHandle(self, h):
        with self._lock:
            self.chiusi[_valore(h)] += 1
        return 1


@pytest.fixture
def k32(monkeypatch):
    finto = FintoKernel32()
    monkeypatch.setattr(conpty, "_k32", finto)
    return finto


def _attendi_thread(pty):
    assert pty._waiter is not None
    pty._waiter.join(timeout=2)
    assert not pty._waiter.is_alive(), "il thread di attesa non è terminato"


def _nessun_doppione(k32):
    doppi = {h: n for h, n in k32.chiusi.items() if n > 1}
    assert not doppi, f"handle chiusi più volte: {doppi}"
    assert all(n == 1 for n in k32.pseudo_chiuse.values()), k32.pseudo_chiuse


class TestUscitaDelProcesso:
    def test_il_thread_aspetta_su_un_duplicato(self, k32):
        pty = conpty.ConPTY(["cmd.exe"], cwd=".")
        k32.uscito.set()
        _attendi_thread(pty)
        assert k32.attese == Counter({DUP: 1})
        assert k32.chiusi[DUP] == 1

    def test_uscita_chiude_la_pseudo_console(self, k32):
        # È ciò che fa arrivare l'EOF alla ReadFile del read loop.
        pty = conpty.ConPTY(["cmd.exe"], cwd=".")
        assert k32.pseudo_chiuse[HPC] == 0
        k32.uscito.set()
        _attendi_thread(pty)
        assert k32.pseudo_chiuse[HPC] == 1
        assert pty._hpc is None

    def test_uscita_poi_close_non_richiude_niente(self, k32):
        # Ordine della sessione: processo uscito → EOF → sessions chiama close().
        pty = conpty.ConPTY(["cmd.exe"], cwd=".")
        k32.uscito.set()
        _attendi_thread(pty)
        pty.close()
        pty.close()  # idempotente
        _nessun_doppione(k32)
        assert k32.pseudo_chiuse[HPC] == 1
        assert k32.chiusi[PROC] == 1

    def test_kill_prima_dell_uscita(self, k32):
        # term_kill: close() termina il processo, il thread si sveglia e trova
        # la pseudo-console già chiusa.
        pty = conpty.ConPTY(["cmd.exe"], cwd=".")
        pty.close()
        _attendi_thread(pty)
        _nessun_doppione(k32)
        assert k32.pseudo_chiuse[HPC] == 1
        assert k32.chiusi[PROC] == 1
        assert k32.chiusi[DUP] == 1

    def test_corsa_fra_cleanup_e_thread(self, k32):
        # Uscita e _cleanup() nello stesso istante, ripetuto: il lock deve far
        # vincere uno solo dei due su ogni handle.
        for _ in range(200):
            k32.uscito.clear()
            k32.chiusi.clear()
            k32.pseudo_chiuse.clear()
            pty = conpty.ConPTY(["cmd.exe"], cwd=".")
            via = threading.Barrier(2)

            def pulisci():
                via.wait()
                pty._cleanup()

            t = threading.Thread(target=pulisci)
            t.start()
            via.wait()
            k32.uscito.set()
            t.join(timeout=2)
            _attendi_thread(pty)
            _nessun_doppione(k32)
            assert k32.pseudo_chiuse[HPC] == 1


class TestSenzaDuplicato:
    def test_duplicatehandle_fallita_non_blocca_l_avvio(self, k32, monkeypatch):
        monkeypatch.setattr(k32, "DuplicateHandle", lambda *a: 0)
        pty = conpty.ConPTY(["cmd.exe"], cwd=".")
        assert pty._waiter is None
        pty.close()
        _nessun_doppione(k32)


def test_il_modulo_non_usa_windll_fuori_da_windows():
    # Il modulo si importa in CI su Linux: l'unico accesso a windll resta
    # quello protetto dal controllo di piattaforma.
    import sys
    if sys.platform != "win32":
        assert conpty._k32 is None
    assert isinstance(conpty._CURRENT_PROCESS, ctypes.c_void_p)
