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
    await asyncio.sleep(0.05)       # i task di invio consegnano l'ultimo frame
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


class TestChiusuraDallElenco:
    """La × dell'elenco chiude una sessione a cui il client non è agganciato."""

    def test_term_kill_da_un_client_non_agganciato(self, monkeypatch):
        from liquidmouse.net.protocol import ClientConnection, dispatch

        finto = FintoPty([])
        finto.isalive = lambda: True
        finto.read = lambda size: (_ for _ in ()).throw(EOFError("attesa")) if finto.closed else b""
        monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: finto)
        monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])

        async def scenario():
            manager = SessionManager()
            session = manager.create("cmd.exe")
            ws = FintoWs()                      # mai agganciato a `session`
            ctx = ClientConnection(ws, "192.168.1.30", manager)
            await dispatch(ctx, '{"type": "term_kill", "id": "%s"}' % session.id)
            await asyncio.sleep(0.05)
            return manager, session, ws

        manager, session, ws = asyncio.run(scenario())
        assert not session.alive
        assert manager.get(session.id) is None
        assert finto.closed >= 1
        # Il client riceve l'elenco aggiornato, senza la sessione chiusa.
        assert any('"term_sessions"' in p and session.id not in p for p in ws.inviati if isinstance(p, str))


class _PtyViva(FintoPty):
    """PTY che resta in vita (nessun output) finché non viene chiuso."""

    def __init__(self):
        super().__init__([])

    def read(self, size):
        if self.closed:
            raise EOFError("chiuso")
        return b""

    def isalive(self):
        return not self.closed


class TestTettoSessioni:
    def test_oltre_il_massimo_create_rifiuta(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: _PtyViva())
        monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])

        async def scenario():
            manager = SessionManager()
            for _ in range(sessions_mod.MAX_SESSIONS):
                manager.create("cmd.exe")
            with pytest.raises(RuntimeError, match="troppe sessioni"):
                manager.create("cmd.exe")
            n = len(manager.list_sessions())
            for s in manager.list_sessions():
                manager.kill(s["id"])
            return n

        assert asyncio.run(scenario()) == sessions_mod.MAX_SESSIONS

    def test_chiusa_una_sessione_se_ne_puo_creare_un_altra(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: _PtyViva())
        monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])

        async def scenario():
            manager = SessionManager()
            create = [manager.create("cmd.exe") for _ in range(sessions_mod.MAX_SESSIONS)]
            manager.kill(create[0].id)
            manager.create("cmd.exe")      # non solleva
            n = len(manager.list_sessions())
            for s in manager.list_sessions():
                manager.kill(s["id"])
            return n

        assert asyncio.run(scenario()) == sessions_mod.MAX_SESSIONS

    def test_term_create_riporta_l_errore_al_client(self, monkeypatch):
        from liquidmouse.net.protocol import ClientConnection, dispatch
        monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: _PtyViva())
        monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])

        async def scenario():
            manager = SessionManager()
            for _ in range(sessions_mod.MAX_SESSIONS):
                manager.create("cmd.exe")
            ws = FintoWs()
            await dispatch(ClientConnection(ws, "192.168.1.30", manager), '{"type":"term_create"}')
            for s in manager.list_sessions():
                manager.kill(s["id"])
            return ws

        ws = asyncio.run(scenario())
        assert any('"term_error"' in p and "troppe sessioni" in p for p in ws.inviati)


class _WsLento(FintoWs):
    """ws la cui prima send resta sospesa finché il test non la sblocca."""

    def __init__(self):
        super().__init__()
        self.sblocca = asyncio.Event()
        self.in_invio = asyncio.Event()
        self._prima = True

    async def send(self, payload):
        if self._prima:
            self._prima = False
            self.in_invio.set()
            await self.sblocca.wait()
        await super().send(payload)


def _payload_output(ws):
    from liquidmouse.net.frames import decode_term_output
    return b"".join(decode_term_output(p)[1] for p in ws.inviati if isinstance(p, bytes))


class TestAttachSenzaRace:
    def _manager_con_sessione(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "make_pty", lambda argv, cwd: _PtyViva())
        monkeypatch.setattr(sessions_mod, "resolve_argv", lambda cmd: [cmd])
        manager = SessionManager()
        return manager, manager.create("cmd.exe")

    def test_output_durante_lo_snapshot_non_si_perde_ne_si_duplica(self, monkeypatch):
        async def scenario():
            manager, session = self._manager_con_sessione(monkeypatch)
            session.output.append(b"vecchio ")
            ws = _WsLento()
            task = asyncio.create_task(manager.attach(session.id, ws))
            await ws.in_invio.wait()
            # Output arrivato mentre lo snapshot e' ancora in volo.
            session.output.append(b"nuovo1 ")
            await manager._broadcast_output(session, b"nuovo1 ")
            ws.sblocca.set()
            await task
            # Dopo l'attach l'output live passa normalmente.
            session.output.append(b"live")
            await manager._broadcast_output(session, b"live")
            await asyncio.sleep(0.02)        # il task di invio del viewer smaltisce la coda
            manager.kill(session.id)
            return ws

        ws = asyncio.run(scenario())
        assert _payload_output(ws) == b"vecchio nuovo1 live"

    def test_client_lento_non_blocca_l_attach_degli_altri(self, monkeypatch):
        async def scenario():
            manager, session = self._manager_con_sessione(monkeypatch)
            session.output.append(b"x")
            lento = _WsLento()
            veloce = FintoWs()
            t1 = asyncio.create_task(manager.attach(session.id, lento))
            await lento.in_invio.wait()
            await asyncio.wait_for(manager.attach(session.id, veloce), 1)
            lento.sblocca.set()
            await t1
            manager.kill(session.id)
            return veloce

        veloce = asyncio.run(scenario())
        assert _payload_output(veloce) == b"x"
