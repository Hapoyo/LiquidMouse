"""Protocollo dei messaggi client → server e dispatch.

Era una catena di `if/elif` da 17 rami dentro una funzione di 193 righe. Qui
ogni tipo di messaggio è una funzione registrata in una tabella: aggiungerne uno
significa scrivere una funzione con il suo decoratore, non allungare la catena.

Tutti i valori in arrivo sono esterni e non fidati, quindi ogni handler passa da
`clamp_int` invece di fidarsi del JSON.
"""

import json
import time
from collections.abc import Awaitable, Callable

from liquidmouse.events import log_message
from liquidmouse.input.win32 import (
    hotkey, key_down, key_press, key_text, key_up,
    mouse_button, mouse_click, mouse_move, mouse_scroll,
)
from liquidmouse.theme import COLOR_ERROR, COLOR_MUTED

# --- limiti del protocollo ---------------------------------------------------
# Un client compromesso non deve poter spostare il cursore di 10^9 pixel né
# riempire la memoria con un singolo messaggio.
MOVE_CLAMP = 200
SCROLL_CLAMP = 100
TERM_INPUT_MAX = 8192
TERM_COLS_MIN, TERM_COLS_MAX = 20, 240
TERM_ROWS_MIN, TERM_ROWS_MAX = 5, 60

# Il client ripete il backspace a raffica quando il tasto resta premuto: senza
# freno, una pressione lunga cancella l'intera riga in pochi millisecondi.
BACKSPACE_MIN_INTERVAL = 0.08
# Ripetizioni massime per un singolo messaggio 'key'. Il client manda il
# conteggio dei caratteri cancellati in una volta sola; il tetto evita che un
# client compromesso chieda un milione di pressioni.
KEY_REPEAT_MAX = 100
# Il ping del client arriva ogni 5 s, ma un client difettoso potrebbe inondare.
PING_MIN_INTERVAL = 0.1

PONG = '{"type":"pong"}'


def clamp_int(value, lo: int, hi: int, default: int = 0) -> int:
    """Interpreta `value` come intero e lo limita a [lo, hi].

    Accetta anche float e stringhe numeriche (il client manda entrambi). Su
    valore non interpretabile ritorna `default` invece di sollevare: un
    messaggio malformato deve essere ignorato, non chiudere la connessione.
    """
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


# --- registro degli handler --------------------------------------------------

Handler = Callable[["ClientConnection", dict], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}


def handles(msg_type: str):
    """Registra una funzione come handler del tipo di messaggio indicato."""
    def deco(fn: Handler) -> Handler:
        if msg_type in _HANDLERS:
            raise ValueError(f"handler duplicato per {msg_type!r}")
        _HANDLERS[msg_type] = fn
        return fn
    return deco


def known_types() -> set[str]:
    return set(_HANDLERS)


class ClientConnection:
    """Stato per singola connessione, con il ciclo di vita del client.

    I tasti tenuti premuti vanno tracciati: se il client si disconnette con
    Ctrl giù, quel modificatore resterebbe premuto sul PC per sempre.
    """

    def __init__(self, websocket, client_ip: str, sessions, on_session_created=None):
        self.ws = websocket
        self.client_ip = client_ip
        self.sessions = sessions
        self.on_session_created = on_session_created
        self.held_keys: set[str] = set()
        self._last_backspace = 0.0
        self._last_ping = 0.0

    async def send_json(self, payload: dict) -> None:
        await self.ws.send(json.dumps(payload))

    async def send_term_error(self, sid: str, msg: str) -> None:
        await self.send_json({"type": "term_error", "id": sid, "msg": msg})

    async def send_session_list(self) -> None:
        await self.send_json({
            "type": "term_sessions",
            "sessions": self.sessions.list_sessions(),
        })

    def release_all(self) -> None:
        """Rilascia mouse e tasti rimasti premuti alla disconnessione."""
        mouse_button('up')
        for key in list(self.held_keys):
            key_up(key)
        self.held_keys.clear()
        self.sessions.detach_ws(self.ws)


# --- input -------------------------------------------------------------------

@handles('move')
async def _move(ctx: ClientConnection, data: dict) -> None:
    mouse_move(clamp_int(data.get('x'), -MOVE_CLAMP, MOVE_CLAMP),
               clamp_int(data.get('y'), -MOVE_CLAMP, MOVE_CLAMP))


@handles('scroll')
async def _scroll(ctx: ClientConnection, data: dict) -> None:
    amt = clamp_int(data.get('amount'), -SCROLL_CLAMP, SCROLL_CLAMP)
    if amt:
        mouse_scroll(amt)


@handles('click')
async def _click(ctx: ClientConnection, data: dict) -> None:
    mouse_click(data.get('btn', 'left'))


@handles('drag')
async def _drag(ctx: ClientConnection, data: dict) -> None:
    mouse_button(data.get('state', 'up'))


@handles('text')
async def _text(ctx: ClientConnection, data: dict) -> None:
    char = data.get('char', '')
    if char:
        key_text(char)


@handles('key')
async def _key(ctx: ClientConnection, data: dict) -> None:
    key = data.get('key', '')
    if not key:
        return
    count = clamp_int(data.get('count', 1), 1, KEY_REPEAT_MAX, 1)
    if key == 'backspace' and count == 1:
        # Il debounce protegge dall'autorepeat della tastiera del telefono, che
        # altrimenti svuota la riga in pochi millisecondi. Non si applica al
        # caso con conteggio: quello è un batch deliberato, calcolato dal client
        # sulla differenza effettiva del campo di testo.
        now = time.time()
        if now - ctx._last_backspace <= BACKSPACE_MIN_INTERVAL:
            return
        ctx._last_backspace = now
    for _ in range(count):
        key_press(key)


@handles('key_toggle')
async def _key_toggle(ctx: ClientConnection, data: dict) -> None:
    key = data.get('key', '')
    state = data.get('state', '')
    if not key or not state:
        return
    if state == 'down':
        key_down(key)
        ctx.held_keys.add(key)
    else:
        key_up(key)
        ctx.held_keys.discard(key)


@handles('hotkey')
async def _hotkey(ctx: ClientConnection, data: dict) -> None:
    keys = data.get('keys', [])
    if isinstance(keys, list):
        hotkey(*keys)


@handles('ping')
async def _ping(ctx: ClientConnection, data: dict) -> None:
    now = time.time()
    if now - ctx._last_ping < PING_MIN_INTERVAL:
        return
    ctx._last_ping = now
    await ctx.ws.send(PONG)


# --- terminale ---------------------------------------------------------------

@handles('term_list')
async def _term_list(ctx: ClientConnection, data: dict) -> None:
    await ctx.send_session_list()


@handles('term_create')
async def _term_create(ctx: ClientConnection, data: dict) -> None:
    try:
        session = ctx.sessions.create(data.get('cmd', 'cmd.exe'))
    except (RuntimeError, ValueError) as e:
        await ctx.send_term_error("", str(e))
        return
    await ctx.send_json({"type": "term_created", "id": session.id})
    if ctx.on_session_created:
        ctx.on_session_created(session.id, ctx.client_ip)


@handles('term_attach')
async def _term_attach(ctx: ClientConnection, data: dict) -> None:
    sid = data.get('id', '')
    try:
        await ctx.sessions.attach(sid, ctx.ws)
    except RuntimeError as e:
        await ctx.send_term_error(sid, str(e))


@handles('term_detach')
async def _term_detach(ctx: ClientConnection, data: dict) -> None:
    ctx.sessions.detach(data.get('id', ''), ctx.ws)


@handles('term_input')
async def _term_input(ctx: ClientConnection, data: dict) -> None:
    sid = data.get('id', '')
    payload = data.get('data', '')
    if not isinstance(payload, str):
        return
    try:
        ctx.sessions.send(sid, payload[:TERM_INPUT_MAX], ws=ctx.ws)
    except RuntimeError as e:
        await ctx.send_term_error(sid, str(e))


@handles('term_resize')
async def _term_resize(ctx: ClientConnection, data: dict) -> None:
    ctx.sessions.resize(
        data.get('id', ''),
        clamp_int(data.get('cols'), TERM_COLS_MIN, TERM_COLS_MAX, 120),
        clamp_int(data.get('rows'), TERM_ROWS_MIN, TERM_ROWS_MAX, 40),
        ws=ctx.ws,
    )


@handles('term_kill')
async def _term_kill(ctx: ClientConnection, data: dict) -> None:
    ctx.sessions.kill(data.get('id', ''), ws=ctx.ws)
    await ctx.send_session_list()


# --- dispatch ----------------------------------------------------------------

async def dispatch(ctx: ClientConnection, raw: str | bytes) -> None:
    """Instrada un messaggio grezzo. Non solleva: un client che manda
    spazzatura non deve far cadere la connessione né la GUI."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        handler = _HANDLERS.get(data.get('type', ''))
        if handler is None:
            return
        await handler(ctx, data)
    except (ValueError, KeyError, TypeError) as e:
        log_message(f"Cmd ignorato: {e}", color=COLOR_MUTED)
    except Exception as e:
        log_message(f"Errore handler: {e}", color=COLOR_ERROR)
