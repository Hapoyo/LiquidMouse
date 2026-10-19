"""Job Object con KILL_ON_JOB_CLOSE e pulizia dei cloudflared orfani.

La logica gira con un'API finta (anche su Linux). Le prove con kernel32 vero
girano solo su Windows (CI Windows e PC dell'utente) e usano un processo reale
innocuo (`ping -t`, copiato con il nome di cloudflared.exe).
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time

import pytest

from liquidmouse.net import procguard
from liquidmouse.net.procguard import KillOnCloseJob, terminate_stale


class _FintaApi:
    def __init__(self, *, kill_on_close_ok=True, assign_ok=True, processi=()):
        self.kill_on_close_ok = kill_on_close_ok
        self.assign_ok = assign_ok
        self.processi = list(processi)       # [(pid, percorso)]
        self.eventi = []

    def create_job(self):
        self.eventi.append("create")
        return 111

    def set_kill_on_close(self, job):
        self.eventi.append(("kill_on_close", job))
        return self.kill_on_close_ok

    def assign(self, job, pid):
        self.eventi.append(("assign", job, pid))
        return self.assign_ok

    def close(self, handle):
        self.eventi.append(("close", handle))

    def find_processes(self, name):
        self.eventi.append(("find", name))
        return list(self.processi)

    def terminate(self, pid):
        self.eventi.append(("terminate", pid))
        return True


class TestKillOnCloseJob:
    def test_crea_il_job_una_volta_e_assegna_i_processi(self):
        api = _FintaApi()
        job = KillOnCloseJob(api)
        assert job.assign(10) and job.assign(11)
        assert api.eventi == ["create", ("kill_on_close", 111),
                              ("assign", 111, 10), ("assign", 111, 11)]

    def test_il_job_non_si_chiude_da_solo(self):
        # Chiuderlo a mano ucciderebbe cloudflared: lo chiude il sistema
        # alla morte del processo.
        api = _FintaApi()
        job = KillOnCloseJob(api)
        job.assign(10)
        assert not any(e[0] == "close" for e in api.eventi if isinstance(e, tuple))

    def test_se_non_si_imposta_kill_on_close_il_job_non_si_usa(self):
        api = _FintaApi(kill_on_close_ok=False)
        job = KillOnCloseJob(api)
        assert job.assign(10) is False
        assert ("close", 111) in api.eventi        # handle di un job inutile
        assert job.available is False
        assert job.assign(11) is False             # non ritenta a ogni avvio
        assert api.eventi.count("create") == 1

    def test_assegnazione_rifiutata(self):
        assert KillOnCloseJob(_FintaApi(assign_ok=False)).assign(10) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="su Windows l'API esiste")
    def test_senza_api_e_inerte(self):
        job = KillOnCloseJob()
        assert job.available is False
        assert job.assign(10) is False


class TestTerminateStale:
    def test_chiude_solo_i_processi_del_nostro_binario(self, tmp_path):
        nostro = tmp_path / "bin" / "cloudflared.exe"
        altro = tmp_path / "altrove" / "cloudflared.exe"
        api = _FintaApi(processi=[(1, str(nostro)), (2, str(altro))])
        assert terminate_stale(nostro, api) == 1
        assert ("terminate", 1) in api.eventi and ("terminate", 2) not in api.eventi

    def test_non_tocca_nulla_se_nessuno_corrisponde(self, tmp_path):
        api = _FintaApi(processi=[(2, str(tmp_path / "x" / "cloudflared.exe"))])
        assert terminate_stale(tmp_path / "bin" / "cloudflared.exe", api) == 0
        assert not any(e[0] == "terminate" for e in api.eventi if isinstance(e, tuple))

    def test_cerca_per_nome_file(self, tmp_path):
        api = _FintaApi()
        terminate_stale(tmp_path / "cloudflared.exe", api)
        assert ("find", "cloudflared.exe") in api.eventi

    def test_un_errore_dell_api_non_solleva(self, tmp_path):
        class Rotta(_FintaApi):
            def find_processes(self, name):
                raise OSError("snapshot")
        assert terminate_stale(tmp_path / "cloudflared.exe", Rotta()) == 0

    @pytest.mark.skipif(sys.platform == "win32", reason="su Windows l'API esiste")
    def test_senza_api_non_fa_nulla(self, tmp_path):
        assert terminate_stale(tmp_path / "cloudflared.exe") == 0


# --- kernel32 vero (solo Windows) -------------------------------------------

solo_windows = pytest.mark.skipif(sys.platform != "win32", reason="serve kernel32")
PING = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")


def test_dimensione_della_struttura_del_job():
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: 144 byte a 64 bit, 112 a 32 bit.
    atteso = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
    assert ctypes.sizeof(procguard._ExtendedLimits) == atteso


def _vivo(proc) -> bool:
    return proc.poll() is None


def _aspetta_morte(proc, secondi=5.0) -> bool:
    fine = time.time() + secondi
    while time.time() < fine:
        if not _vivo(proc):
            return True
        time.sleep(0.05)
    return False


def _lancia_ping(exe):
    return subprocess.Popen([str(exe), "-t", "127.0.0.1"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


@solo_windows
@pytest.mark.skipif(not os.path.exists(PING), reason="ping.exe assente")
class TestKernel32Vero:
    def test_chiudere_il_job_termina_il_processo(self):
        api = procguard.default_api()
        assert api is not None
        job = KillOnCloseJob(api)
        proc = _lancia_ping(PING)
        try:
            assert job.assign(proc.pid) is True
            assert _vivo(proc)
            # La morte del nostro processo chiude l'handle del job: qui lo si simula.
            api.close(job._job)
            assert _aspetta_morte(proc), "il processo del job doveva terminare"
        finally:
            if _vivo(proc):
                proc.kill()

    def test_terminate_stale_chiude_solo_il_nostro_percorso(self, tmp_path):
        nostro = tmp_path / "bin" / "cloudflared.exe"
        altro = tmp_path / "altrove" / "cloudflared.exe"
        for p in (nostro, altro):
            p.parent.mkdir()
            shutil.copy2(PING, p)
        p_nostro, p_altro = _lancia_ping(nostro), _lancia_ping(altro)
        try:
            time.sleep(0.5)
            assert terminate_stale(nostro) == 1
            assert _aspetta_morte(p_nostro)
            assert _vivo(p_altro), "un cloudflared altrui non va toccato"
        finally:
            for p in (p_nostro, p_altro):
                if _vivo(p):
                    p.kill()
