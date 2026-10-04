"""Sessioni PTY condivise fra i client collegati.

Una sessione sopravvive alla disconnessione del client: il telefono può
riagganciarsi e ritrovare la schermata grazie al ring buffer, e la stessa
sessione può avere più viewer contemporanei (il telefono e la finestra aperta
sul PC).

Il read loop del PTY non invia mai direttamente: accoda l'output nella coda
limitata di ogni viewer e un task per viewer lo spedisce. Così un telefono
lento non ferma la lettura della shell né gli altri viewer.
"""

import asyncio
import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from liquidmouse.events import log_message
from liquidmouse.executors import PTY_READ, PTY_WRITE
from liquidmouse.net.frames import encode_term_output
from liquidmouse.terminal.commands import resolve_argv
from liquidmouse.terminal.conpty import READ_SIZE, WINPTY_AVAILABLE, make_pty
from liquidmouse.terminal.ringbuffer import RingBuffer
from liquidmouse.theme import COLOR_ACCENT, COLOR_ERROR, COLOR_MUTED

# Attesa quando il PTY non ha dati ma il processo è vivo. Riguarda solo il
# backend pywinpty, che ritorna b"" invece di bloccare: parte da IDLE_POLL_SECS
# e cresce fino a IDLE_POLL_MAX_SECS finché non arriva output, così una shell
# ferma non costa 100 risvegli al secondo e una che scrive risponde subito.
IDLE_POLL_SECS = 0.01
IDLE_POLL_MAX_SECS = 0.05
# Tetto alle sessioni aperte: ogni sessione è un processo, un PTY e 64 KB di
# ring buffer, e `term_create` è libero per ogni client autenticato.
MAX_SESSIONS = 8
# Byte in coda per viewer prima di chiuderlo: un telefono che non legge più
# (schermo spento, rete morta) non deve far crescere la memoria del PC né,
# come prima, fermare la lettura del PTY e gli altri viewer.
MAX_QUEUED_BYTES = 1024 * 1024
# Input in attesa di essere scritto nel PTY (la shell non legge): oltre, il
# client riceve un errore invece di accumulare senza limite.
MAX_PENDING_WRITE = 64 * 1024
# Quanto aspettare, all'uscita di una sessione, che i viewer ricevano l'ultimo
# frame (term_closed) prima di abbandonarli.
FLUSH_TIMEOUT_SECS = 2.0


def next_idle_delay(current: float) -> float:
    """Prossima attesa del polling a vuoto: raddoppia fino a IDLE_POLL_MAX_SECS."""
    return min(current * 2, IDLE_POLL_MAX_SECS)


class _Pump:
    """Coda limitata e task di invio di un singolo viewer."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.queue: deque = deque()
        self.queued = 0
        self.wake = asyncio.Event()
        self.closing = False        # svuota la coda e poi termina
        self.task: asyncio.Task | None = None


@dataclass
class PTYSession:
    id: str
    cmd: str
    pty: object
    output: RingBuffer = field(default_factory=RingBuffer)
    subscribers: set = field(default_factory=set)   # ws attivi (telefono + finestra PC)
    # ws appena agganciati che stanno ricevendo lo snapshot: il broadcast li
    # salta, il delta lo manda attach() per tenere l'ordine dei byte.
    catching_up: set = field(default_factory=set)
    created_at: float = 0.0
    alive: bool = True
    # Un task di invio per viewer (ws → _Pump) e la coda delle scritture nel PTY.
    pumps: dict = field(default_factory=dict)
    pending_write: deque = field(default_factory=deque)
    pending_write_bytes: int = 0
    writer: asyncio.Task | None = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, PTYSession] = {}
        # _sessions è mutato dal loop asyncio e letto dal thread Tk (pannello
        # sessioni e menu tray). Prima la race era solo mitigata con un list().
        self._dict_lock = threading.Lock()
        # Task di servizio (chiusura dei ws lenti): tenuti qui perché l'event
        # loop ne conserva solo un riferimento debole.
        self._background: set[asyncio.Task] = set()

    def create(self, cmd: str = "cmd.exe") -> PTYSession:
        """Avvia una sessione. Richiede un event loop attivo: il read loop viene
        agganciato subito come task."""
        loop = asyncio.get_running_loop()
        with self._dict_lock:
            piene = len(self._sessions) >= MAX_SESSIONS
        if piene:
            raise RuntimeError(f"troppe sessioni (max {MAX_SESSIONS}): chiudine una")
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
        """Aggancia `ws` e gli rimanda la schermata conservata.

        Snapshot e contatore si prendono insieme e il ws entra fra i subscriber
        senza await in mezzo: l'output che arriva mentre lo snapshot e' in volo
        non va perso (prima il subscriber veniva aggiunto dopo l'await). Fino
        al raggiungimento del live il broadcast salta il ws, e qui si manda il
        delta accumulato dopo l'offset. Nessun lock tenuto durante gli invii:
        un client lento non blocca l'attach degli altri.
        """
        session = self.get(sid)
        if not session:
            raise RuntimeError("sessione non trovata")
        buf, offset = session.output.snapshot_with_offset()
        session.subscribers.add(ws)
        session.catching_up.add(ws)
        try:
            # Un solo frame invece di uno ogni 4 KB: il replay di un buffer
            # pieno costava fino a 16 invii separati, ognuno con un await, e
            # il terminale si ridisegnava a scatti.
            while True:
                if buf:
                    await ws.send(encode_term_output(sid, buf))
                # since() e total si leggono senza await in mezzo; se non c'e'
                # delta si esce nello stesso istante e il finally rimette il ws
                # nel live: nessun byte cade fra i due.
                buf = session.output.since(offset)
                if not buf:
                    break
                offset = session.output.total
        except BaseException:
            session.subscribers.discard(ws)
            self._drop_pump(session, ws)
            raise
        finally:
            session.catching_up.discard(ws)

    def detach(self, sid: str, ws) -> None:
        s = self.get(sid)
        if s:
            s.subscribers.discard(ws)
            self._drop_pump(s, ws)

    def detach_ws(self, ws) -> None:
        """Sgancia questo ws da ogni sessione (su disconnessione del client)."""
        with self._dict_lock:
            sessioni = list(self._sessions.values())
        for s in sessioni:
            s.subscribers.discard(ws)
            self._drop_pump(s, ws)

    def send(self, sid: str, data: str, ws=None) -> None:
        s = self.get(sid)
        if not s or not s.alive:
            raise RuntimeError("sessione non disponibile")
        if ws is not None and ws not in s.subscribers:
            raise RuntimeError("non collegato alla sessione")
        self._queue_write(s, data)

    def _queue_write(self, s: PTYSession, data: str) -> None:
        """Mette `data` in coda per il PTY senza bloccare l'event loop.

        La write può bloccare (pipe piena se la shell non legge) e ConPTY la
        faceva dentro il loop, fermando ogni WebSocket. Un solo task per
        sessione svuota la coda in un thread dedicato, quindi l'ordine dei
        tasti resta quello di arrivo.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            s.pty.write(data)       # fuori da un loop (script, test): sincrono
            return
        if s.pending_write_bytes + len(data) > MAX_PENDING_WRITE:
            raise RuntimeError("terminale occupato: input scartato")
        s.pending_write.append(data)
        s.pending_write_bytes += len(data)
        if s.writer is None or s.writer.done():
            s.writer = loop.create_task(self._write_loop(s))

    async def _write_loop(self, s: PTYSession) -> None:
        loop = asyncio.get_running_loop()
        while s.pending_write and s.alive:
            chunk = "".join(s.pending_write)
            s.pending_write.clear()
            s.pending_write_bytes = 0
            try:
                await loop.run_in_executor(PTY_WRITE, s.pty.write, chunk)
            except Exception as e:
                # Pipe rotta o processo uscito: il read loop chiuderà la sessione.
                if s.alive:
                    log_message(f"Terminal scrittura [{s.id}]: {e}", color=COLOR_ERROR)
                break
        s.pending_write.clear()
        s.pending_write_bytes = 0

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

    # --- invio ai viewer -----------------------------------------------------

    async def _broadcast(self, session: PTYSession, msg: dict) -> None:
        """Accoda un messaggio JSON per tutti i viewer."""
        self._fan_out(session, json.dumps(msg))

    async def _broadcast_output(self, session: PTYSession, raw: bytes) -> None:
        """Accoda output del PTY come frame binario.

        Non passa da JSON+base64: erano ~33% di banda in più e una codifica per
        ogni chunk, con la decodifica corrispondente sul telefono.
        """
        self._fan_out(session, encode_term_output(session.id, raw))

    def _fan_out(self, session: PTYSession, payload) -> None:
        """Mette il payload nella coda di ogni viewer; non attende nessuno."""
        for sub in list(session.subscribers):
            if sub in session.catching_up:
                continue
            self._enqueue(session, sub, payload)

    def _enqueue(self, session: PTYSession, ws, payload) -> None:
        pump = session.pumps.get(ws)
        if pump is None:
            pump = _Pump(ws)
            pump.task = asyncio.get_running_loop().create_task(self._pump_loop(session, pump))
            session.pumps[ws] = pump
        if pump.queued + len(payload) > MAX_QUEUED_BYTES:
            self._evict(session, ws)
            return
        pump.queue.append(payload)
        pump.queued += len(payload)
        pump.wake.set()

    async def _pump_loop(self, session: PTYSession, pump: _Pump) -> None:
        """Invia in ordine la coda di un viewer; un errore di invio lo toglie."""
        try:
            while True:
                while pump.queue:
                    payload = pump.queue.popleft()
                    pump.queued -= len(payload)
                    await pump.ws.send(payload)
                if pump.closing:
                    return
                pump.wake.clear()
                await pump.wake.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            session.subscribers.discard(pump.ws)
            if session.pumps.get(pump.ws) is pump:
                del session.pumps[pump.ws]

    def _drop_pump(self, session: PTYSession, ws) -> None:
        pump = session.pumps.pop(ws, None)
        if pump and pump.task and not pump.task.done():
            pump.task.cancel()

    def _evict(self, session: PTYSession, ws) -> None:
        """Toglie un viewer che non smaltisce l'output e ne chiude la connessione.

        Il client riconnette da solo e si riaggancia con lo snapshot del ring
        buffer: meglio di un PC che accumula megabyte per un telefono fermo.
        """
        session.subscribers.discard(ws)
        self._drop_pump(session, ws)
        log_message(f"Terminal [{session.id}]: viewer troppo lento, connessione chiusa",
                    color=COLOR_MUTED)
        close = getattr(ws, "close", None)
        if close is None:
            return
        task = asyncio.get_running_loop().create_task(self._close_ws(close))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    @staticmethod
    async def _close_ws(close) -> None:
        try:
            await close(1013, "viewer troppo lento")
        except Exception:
            pass

    async def _flush_pumps(self, session: PTYSession) -> None:
        """All'uscita della sessione: lascia ai viewer il tempo di ricevere
        l'ultimo frame, poi abbandona chi è ancora bloccato."""
        pumps = list(session.pumps.values())
        for pump in pumps:
            pump.closing = True
            pump.wake.set()
        tasks = [p.task for p in pumps if p.task]
        if tasks:
            _, pendenti = await asyncio.wait(tasks, timeout=FLUSH_TIMEOUT_SECS)
            for t in pendenti:
                t.cancel()
        session.pumps.clear()

    async def _read_loop(self, session: PTYSession) -> None:
        loop = asyncio.get_running_loop()
        exit_code = 0
        idle = IDLE_POLL_SECS
        while session.alive:
            try:
                raw = await loop.run_in_executor(PTY_READ, session.pty.read, READ_SIZE)
                if not session.alive:
                    # kill() invocato durante la read in executor: esci subito
                    break
                if not raw:
                    if not session.pty.isalive():
                        exit_code = session.pty.exitstatus
                        break
                    await asyncio.sleep(idle)
                    idle = next_idle_delay(idle)
                    continue
                idle = IDLE_POLL_SECS
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
        # Uscita naturale (exit, processo chiuso): prima la sessione restava nel
        # dizionario con PTY e ring buffer allocati per sempre, perché solo
        # kill() li liberava e il client non lo chiama mai. close() è
        # idempotente, quindi va bene anche dopo un kill().
        try:
            session.pty.close()
        except Exception:
            pass
        with self._dict_lock:
            if self._sessions.get(session.id) is session:
                del self._sessions[session.id]
        log_message(f"Terminal: {session.cmd} terminato (exit {exit_code})", color=COLOR_ACCENT)
        await self._broadcast(session, {
            "type": "term_closed", "id": session.id, "exit_code": exit_code
        })
        await self._flush_pumps(session)
