"""Contropressione del terminale: coda limitata per viewer, scritture fuori dal loop.

Un viewer lento non deve fermare né la lettura del PTY né gli altri viewer; chi
supera la soglia viene chiuso. Le scritture nel PTY non bloccano l'event loop.
"""

import asyncio
import threading

import pytest

from liquidmouse.net.frames import decode_term_output
from liquidmouse.terminal import sessions as sessions_mod
from liquidmouse.terminal.sessions import SessionManager


class PtyViva:
    """PTY senza output che resta in vita finché non viene chiuso."""

    def __init__(self):
        self.closed = 0
        self.exitstatus = 0

    def read(self, size):
        if self.closed:
            raise EOFError("chiuso")
        return b""

    def isalive(self):
        return not self.closed

    def write(self, data):
        pass

    def set_size(self, rows, cols):
        pass

    def close(self):
        self.closed += 1


class Ws:
    def __init__(self):
        self.inviati = []

    async def send(self, payload):
        self.inviati.append(payload)


class WsBloccato(Ws):
    """ws che non smaltisce mai: ogni send resta sospesa."""

    def __init__(self):
        super().__init__()
        self.chiuso = None

    async def send(self, payload):
        await asyncio.Event().wait()

    async def close(self, code=1000, reason=""):
        self.chiuso = (code, reason)


def output(ws):
    return b"".join(decode_term_output(p)[1] for p in ws.inviati if isinstance(p, bytes))


def _manager(monkeypatch, pty=None):
    monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: pty or PtyViva())
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])
    manager = SessionManager()
    return manager, manager.create("cmd.exe")


class TestViewerLento:
    def test_un_viewer_bloccato_non_ferma_gli_altri_ne_il_broadcast(self, monkeypatch):
        async def scenario():
            manager, session = _manager(monkeypatch)
            lento, veloce = WsBloccato(), Ws()
            session.subscribers.update({lento, veloce})
            # Il broadcast non deve mai attendere l'invio del viewer bloccato.
            for _ in range(5):
                await asyncio.wait_for(manager._broadcast_output(session, b"abc"), 0.5)
            await asyncio.sleep(0.02)
            manager.kill(session.id)
            return veloce

        assert output(asyncio.run(scenario())) == b"abc" * 5

    def test_oltre_la_soglia_il_viewer_viene_tolto_e_chiuso(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "MAX_QUEUED_BYTES", 1000)

        async def scenario():
            manager, session = _manager(monkeypatch)
            lento, veloce = WsBloccato(), Ws()
            session.subscribers.update({lento, veloce})
            for _ in range(20):
                await manager._broadcast_output(session, b"x" * 200)
                await asyncio.sleep(0)
            await asyncio.sleep(0.02)
            presente = lento in session.subscribers
            manager.kill(session.id)
            return lento, veloce, presente

        lento, veloce, presente = asyncio.run(scenario())
        assert not presente
        assert lento.chiuso is not None
        # Gli altri viewer non perdono nulla.
        assert output(veloce) == b"x" * 200 * 20

    def test_la_coda_non_supera_la_soglia(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "MAX_QUEUED_BYTES", 1000)

        async def scenario():
            manager, session = _manager(monkeypatch)
            lento = WsBloccato()
            session.subscribers.add(lento)
            massimo = 0
            for _ in range(50):
                await manager._broadcast_output(session, b"y" * 300)
                pump = session.pumps.get(lento)
                if pump:
                    massimo = max(massimo, pump.queued)
                await asyncio.sleep(0)
            manager.kill(session.id)
            return massimo

        assert asyncio.run(scenario()) <= 1000

    def test_uscita_con_viewer_bloccato_non_resta_appesa(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "FLUSH_TIMEOUT_SECS", 0.05)

        async def scenario():
            manager, session = _manager(monkeypatch)
            lento = WsBloccato()
            session.subscribers.add(lento)
            await manager._broadcast_output(session, b"z")
            await asyncio.sleep(0.01)
            manager.kill(session.id)
            await asyncio.sleep(0.3)
            return session

        assert asyncio.run(scenario()).pumps == {}

    def test_detach_ferma_il_task_di_invio(self, monkeypatch):
        async def scenario():
            manager, session = _manager(monkeypatch)
            ws = Ws()
            session.subscribers.add(ws)
            await manager._broadcast_output(session, b"a")
            task = session.pumps[ws].task
            manager.detach(session.id, ws)
            await asyncio.sleep(0.01)
            manager.kill(session.id)
            return task, session

        task, session = asyncio.run(scenario())
        assert task.done()
        assert session.pumps == {}


class TestScritturaPty:
    def test_la_write_gira_fuori_dall_event_loop_e_in_ordine(self, monkeypatch):
        thread_loop = threading.get_ident()
        visti = []

        class PtyScrive(PtyViva):
            def write(self, data):
                visti.append((threading.get_ident(), data))

        async def scenario():
            manager, session = _manager(monkeypatch, PtyScrive())
            ws = Ws()
            session.subscribers.add(ws)
            manager.send(session.id, "ab", ws=ws)
            manager.send(session.id, "cd", ws=ws)
            await asyncio.sleep(0.05)
            manager.kill(session.id)

        asyncio.run(scenario())
        assert "".join(d for _, d in visti) == "abcd"
        assert all(t != thread_loop for t, _ in visti)

    def test_una_write_bloccata_non_ferma_il_loop(self, monkeypatch):
        sblocca = threading.Event()

        class PtyPieno(PtyViva):
            def write(self, data):
                sblocca.wait(2)

        async def scenario():
            manager, session = _manager(monkeypatch, PtyPieno())
            ws, altro = Ws(), Ws()
            session.subscribers.update({ws, altro})
            manager.send(session.id, "x", ws=ws)
            # Il loop resta libero: l'altro viewer riceve output nel frattempo.
            await manager._broadcast_output(session, b"vivo")
            await asyncio.sleep(0.02)
            sblocca.set()
            manager.kill(session.id)
            return altro

        assert output(asyncio.run(scenario())) == b"vivo"

    def test_input_in_coda_oltre_il_tetto_viene_rifiutato(self, monkeypatch):
        sblocca = threading.Event()
        monkeypatch.setattr(sessions_mod, "MAX_PENDING_WRITE", 10)

        class PtyPieno(PtyViva):
            def write(self, data):
                sblocca.wait(2)

        async def scenario():
            manager, session = _manager(monkeypatch, PtyPieno())
            ws = Ws()
            session.subscribers.add(ws)
            manager.send(session.id, "12345", ws=ws)
            await asyncio.sleep(0.01)            # il writer prende "12345" e si blocca
            manager.send(session.id, "123456789", ws=ws)
            try:
                with pytest.raises(RuntimeError, match="occupato"):
                    manager.send(session.id, "ab", ws=ws)
            finally:
                sblocca.set()
                manager.kill(session.id)

        asyncio.run(scenario())

    def test_senza_event_loop_la_write_e_sincrona(self):
        scritti = []

        class P(PtyViva):
            def write(self, data):
                scritti.append(data)

        manager = SessionManager()
        manager._sessions["a"] = sessions_mod.PTYSession(id="a", cmd="cmd.exe", pty=P())
        manager.send("a", "ls")
        assert scritti == ["ls"]


class TestBackoffEExecutor:
    def test_il_ritardo_cresce_fino_al_massimo(self):
        d = sessions_mod.IDLE_POLL_SECS
        visti = []
        for _ in range(6):
            visti.append(d)
            d = sessions_mod.next_idle_delay(d)
        assert visti[0] == 0.01
        assert visti == sorted(visti)
        assert d == sessions_mod.IDLE_POLL_MAX_SECS == 0.05

    def test_executor_dedicati_coprono_tutte_le_sessioni(self):
        from liquidmouse import executors
        assert executors.PTY_READ_WORKERS >= sessions_mod.MAX_SESSIONS
        assert executors.PTY_WRITE_WORKERS >= sessions_mod.MAX_SESSIONS

    def test_nessun_run_in_executor_sul_pool_condiviso(self):
        # Il pool di default non deve tornare: affamerebbe SFTP e UPnP.
        import pathlib
        radice = pathlib.Path(sessions_mod.__file__).resolve().parents[1]
        for f in radice.rglob("*.py"):
            if f.name == "executors.py":     # lo cita nel docstring
                continue
            assert "run_in_executor(None" not in f.read_text(encoding="utf-8"), f
