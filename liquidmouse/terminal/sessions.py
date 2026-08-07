"""Sessioni PTY condivise fra i client collegati.

Una sessione sopravvive alla disconnessione del client: il telefono può
riagganciarsi e ritrovare la schermata grazie al ring buffer, e la stessa
sessione può avere più viewer contemporanei (il telefono e la finestra aperta
sul PC).
"""

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from liquidmouse.events import log_message
from liquidmouse.net.frames import encode_term_output
from liquidmouse.terminal.commands import resolve_argv
from liquidmouse.terminal.conpty import READ_SIZE, WINPTY_AVAILABLE, make_pty
from liquidmouse.terminal.ringbuffer import RingBuffer
from liquidmouse.theme import COLOR_ACCENT, COLOR_ERROR, COLOR_MUTED

# Attesa quando il PTY non ha dati ma il processo è vivo. Riguarda solo il
# backend pywinpty, che ritorna b"" invece di bloccare.
IDLE_POLL_SECS = 0.01


@dataclass
class PTYSession:
    id: str
    cmd: str
    pty: object
    output: RingBuffer = field(default_factory=RingBuffer)
    subscribers: set = field(default_factory=set)   # ws attivi (telefono + finestra PC)
    created_at: float = 0.0
    alive: bool = True


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, PTYSession] = {}
        self._attach_lock = asyncio.Lock()
        # _sessions è mutato dal loop asyncio e letto dal thread Tk (pannello
        # sessioni e menu tray). Prima la race era solo mitigata con un list().
        self._dict_lock = threading.Lock()

    def create(self, cmd: str = "cmd.exe") -> PTYSession:
        """Avvia una sessione. Richiede un event loop attivo: il read loop viene
        agganciato subito come task."""
        loop = asyncio.get_running_loop()
        sid = uuid.uuid4().hex[:8]
        argv = resolve_argv(cmd)
        home = os.path.expanduser("~")
        backend = "pywinpty" if WINPTY_AVAILABLE else "ConPTY-ctypes"
        log_message(f"Terminal: spawn {argv} via {backend}", color=COLOR_ACCENT)
        try:
            pty = make_pty(argv, cwd=home)
        except Exception as e:
            raise RuntimeError(f"Errore PTY: {e}")
        session = PTYSession(id=sid, cmd=cmd, pty=pty, created_at=time.time(), alive=True)
        with self._dict_lock:
            self._sessions[sid] = session
        loop.create_task(self._read_loop(session))
        return session

    def get(self, sid: str) -> PTYSession | None:
        with self._dict_lock:
            return self._sessions.get(sid)

    async def attach(self, sid: str, ws) -> None:
        """Aggancia `ws` e gli rimanda la schermata conservata."""
        async with self._attach_lock:
            session = self.get(sid)
            if not session:
                raise RuntimeError("sessione non trovata")
            buf = session.output.snapshot()
            if buf:
                # Un solo frame invece di uno ogni 4 KB: il replay di un buffer
                # pieno costava fino a 16 invii separati, ognuno con un await, e
                # il terminale si ridisegnava a scatti.
                await ws.send(encode_term_output(sid, buf))
            session.subscribers.add(ws)

    def detach(self, sid: str, ws) -> None:
        s = self.get(sid)
        if s:
            s.subscribers.discard(ws)

    def detach_ws(self, ws) -> None:
        """Sgancia questo ws da ogni sessione (su disconnessione del client)."""
        with self._dict_lock:
            sessioni = list(self._sessions.values())
        for s in sessioni:
            s.subscribers.discard(ws)

    def send(self, sid: str, data: str, ws=None) -> None:
        s = self.get(sid)
        if not s or not s.alive:
            raise RuntimeError("sessione non disponibile")
        if ws is not None and ws not in s.subscribers:
            raise RuntimeError("non collegato alla sessione")
        s.pty.write(data)

    def resize(self, sid: str, cols: int, rows: int, ws=None) -> None:
        s = self.get(sid)
        if ws is not None and s and ws not in s.subscribers:
            return
        if s and s.alive:
            try:
                s.pty.set_size(rows, cols)
            except Exception as e:
                log_message(f"Terminal resize [{sid}] {cols}x{rows}: {e}", color=COLOR_MUTED)

    def kill(self, sid: str, ws=None) -> None:
        s = self.get(sid)
        if ws is not None and s and ws not in s.subscribers:
            return
        if s:
            s.alive = False
            try:
                s.pty.close()
            except Exception:
                pass
            with self._dict_lock:
                self._sessions.pop(sid, None)

    def list_sessions(self) -> list:
        with self._dict_lock:
            sessioni = list(self._sessions.values())
        return [{"id": s.id, "cmd": s.cmd, "alive": s.alive,
                 "created_at": s.created_at, "viewers": len(s.subscribers)}
                for s in sessioni]

    async def _broadcast(self, session: PTYSession, msg: dict) -> None:
        """Invia un messaggio JSON a tutti i viewer; rimuove quelli morti."""
        await self._send_all(session, json.dumps(msg))

    async def _broadcast_output(self, session: PTYSession, raw: bytes) -> None:
        """Invia output del PTY come frame binario.

        Non passa da JSON+base64: erano ~33% di banda in più e una codifica per
        ogni chunk, con la decodifica corrispondente sul telefono.
        """
        await self._send_all(session, encode_term_output(session.id, raw))

    async def _send_all(self, session: PTYSession, payload) -> None:
        if not session.subscribers:
            return
        dead = []
        for sub in list(session.subscribers):
            try:
                await sub.send(payload)
            except Exception:
                dead.append(sub)
        for d in dead:
            session.subscribers.discard(d)

    async def _read_loop(self, session: PTYSession) -> None:
        loop = asyncio.get_running_loop()
        exit_code = 0
        while session.alive:
            try:
                raw = await loop.run_in_executor(None, session.pty.read, READ_SIZE)
                if not session.alive:
                    # kill() invocato durante la read in executor: esci subito
                    break
                if not raw:
                    if not session.pty.isalive():
                        exit_code = session.pty.exitstatus
                        break
                    await asyncio.sleep(IDLE_POLL_SECS)
                    continue
                session.output.append(raw)
                await self._broadcast_output(session, raw)
            except EOFError:
                exit_code = session.pty.exitstatus if session.alive else 0
                break
            except Exception as e:
                if session.alive:
                    log_message(f"Terminal errore [{session.id}]: {e}", color=COLOR_ERROR)
                break
        session.alive = False
        log_message(f"Terminal: {session.cmd} terminato (exit {exit_code})", color=COLOR_ACCENT)
        await self._broadcast(session, {
            "type": "term_closed", "id": session.id, "exit_code": exit_code
        })
