"""SessionManager: ciclo di vita di una sessione PTY, senza Windows.

Il PTY è sostituito da un finto backend con la stessa interfaccia a byte.
"""

import asyncio

import pytest

from liquidmouse.terminal import sessions as sessions_mod
from liquidmouse.terminal.sessions import SessionManager


class FintoPty:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = 0
        self.exitstatus = 0

    def read(self, size):
        if self._chunks:
            return self._chunks.pop(0)
        raise EOFError("fine")

    def isalive(self):
        return bool(self._chunks)

    def write(self, data):
        pass

    def set_size(self, rows, cols):
        pass

    def close(self):
        self.closed += 1


class FintoWs:
    def __init__(self):
        self.inviati = []

    async def send(self, payload):
        self.inviati.append(payload)


@pytest.fixture
def pty(monkeypatch):
    finto = FintoPty([b"ciao"])
    monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: finto)
    monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])
    return finto


async def _esegui_fino_all_uscita(manager, ws):
    session = manager.create("cmd.exe")
    session.subscribers.add(ws)
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not session.alive:
            break
    return session


class TestUscitaNaturale:
    def test_la_sessione_uscita_libera_il_pty(self, pty):
        async def scenario():
            manager = SessionManager()
            ws = FintoWs()
            session = await _esegui_fino_all_uscita(manager, ws)
            return manager, session, ws

        manager, session, ws = asyncio.run(scenario())
        assert not session.alive
        assert pty.closed == 1
        assert manager.get(session.id) is None
        assert manager.list_sessions() == []

    def test_i_viewer_ricevono_output_e_chiusura(self, pty):
        async def scenario():
            manager = SessionManager()
            ws = FintoWs()
            await _esegui_fino_all_uscita(manager, ws)
            return ws

        ws = asyncio.run(scenario())
        assert any(isinstance(p, bytes) and p.endswith(b"ciao") for p in ws.inviati)
        assert any(isinstance(p, str) and '"term_closed"' in p for p in ws.inviati)

    def test_kill_poi_uscita_non_chiude_due_volte_con_errore(self, pty):
        async def scenario():
            manager = SessionManager()
            session = manager.create("cmd.exe")
            manager.kill(session.id)
            await asyncio.sleep(0.05)
            return manager, session

        manager, session = asyncio.run(scenario())
        assert manager.get(session.id) is None
        assert pty.closed >= 1
