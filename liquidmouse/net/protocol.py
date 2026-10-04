"""Protocollo dei messaggi client → server e dispatch.

Era una catena di `if/elif` da 17 rami dentro una funzione di 193 righe. Qui
ogni tipo di messaggio è una funzione registrata in una tabella: aggiungerne uno
significa scrivere una funzione con il suo decoratore, non allungare la catena.

Tutti i valori in arrivo sono esterni e non fidati, quindi ogni handler passa da
`clamp_int` invece di fidarsi del JSON.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

from liquidmouse.events import log_message
from liquidmouse.executors import SFTP
from liquidmouse.input.win32 import (
    hotkey, key_down, key_press, key_text, key_up,
    mouse_button, mouse_click, mouse_move, mouse_scroll,
)
from liquidmouse.net.sftp import SftpError, join_path, validate_name
from liquidmouse.net.transfers import DOWNLOAD, REMOTE_DOWNLOAD_MAX, UPLOAD
from liquidmouse.theme import COLOR_ERROR, COLOR_MUTED

# --- limiti del protocollo ---------------------------------------------------
# Un client compromesso non deve poter spostare il cursore di 10^9 pixel né
# riempire la memoria con un singolo messaggio.
MOVE_CLAMP = 200
SCROLL_CLAMP = 100
TERM_INPUT_MAX = 8192
TERM_COLS_MIN, TERM_COLS_MAX = 20, 240
TERM_ROWS_MIN, TERM_ROWS_MAX = 5, 60
SFTP_TEXT_MAX = 1024
# Testo di un singolo messaggio 'text' (una digitazione, un incolla) e tasti di
# una combinazione: oltre questi tetti un client compromesso potrebbe battere
# megabyte di testo o premere decine di tasti in un colpo solo.
KEY_TEXT_MAX = 1024
HOTKEY_KEYS_MAX = 6

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

    def __init__(self, websocket, client_ip: str, sessions, on_session_created=None,
                 sftp=None, transfers=None, remote: bool = False):
        self.ws = websocket
        self.client_ip = client_ip
        self.sessions = sessions
        self.on_session_created = on_session_created
        self.sftp = sftp
        self.transfers = transfers
        # Client arrivato da 8443/tunnel: i trasferimenti hanno limiti propri.
        self.remote = remote
        # Chiave dei biglietti e delle connessioni SFTP di questo client.
        self.owner = id(websocket)
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
        if self.sftp is not None:
            self.sftp.close_owner(self.owner)
        if self.transfers is not None:
            self.transfers.revoke_owner(self.owner)


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
    if char and isinstance(char, str):
        key_text(char[:KEY_TEXT_MAX])


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
        # Prima si scartano i token non stringa, poi si applica il tetto: così
        # la spazzatura non consuma i posti dei tasti veri.
        hotkey(*[k for k in keys if isinstance(k, str)][:HOTKEY_KEYS_MAX])


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
    # Senza ws: la × arriva dall'elenco delle sessioni, dove il client non è
    # agganciato. Il controllo sull'aggancio non proteggeva nulla, perché un
    # client autenticato può sempre agganciarsi con term_attach; bloccava
    # solo la chiusura, e le sessioni restavano aperte per sempre.
    ctx.sessions.kill(data.get('id', ''))
    await ctx.send_session_list()


# --- file manager (SFTP) -----------------------------------------------------

def _campo(data: dict, key: str) -> str:
    """Campo testuale del messaggio, mai un non-stringa e con lunghezza limitata."""
    v = data.get(key, '')
    return v[:SFTP_TEXT_MAX] if isinstance(v, str) else ''


async def _sftp(ctx: ClientConnection, fn, *args):
    """Esegue `fn` (bloccante) fuori dall'event loop. Su errore avvisa il client
    e ritorna None: un elenco lento o un host giù non deve fermare il resto."""
    if ctx.sftp is None:
        await ctx.send_json({"type": "sftp_error", "msg": "file manager non disponibile"})
        return None
    try:
        return await asyncio.get_running_loop().run_in_executor(SFTP, fn, *args)
    except SftpError as e:
        await ctx.send_json({"type": "sftp_error", "msg": str(e), "code": e.code})
    return None


async def _send_profiles(ctx: ClientConnection) -> None:
    await ctx.send_json({"type": "sftp_profiles",
                         "profiles": ctx.sftp.list_profiles() if ctx.sftp else []})


@handles('sftp_profiles')
async def _sftp_profiles(ctx: ClientConnection, data: dict) -> None:
    await _send_profiles(ctx)


@handles('sftp_profile_save')
async def _sftp_profile_save(ctx: ClientConnection, data: dict) -> None:
    if await _sftp(ctx, lambda: ctx.sftp.save_profile(
            _campo(data, 'name'), _campo(data, 'host'),
            clamp_int(data.get('port'), 1, 65535, 22),
            _campo(data, 'user'), _campo(data, 'password')) or True):
        await _send_profiles(ctx)


@handles('sftp_profile_delete')
async def _sftp_profile_delete(ctx: ClientConnection, data: dict) -> None:
    if await _sftp(ctx, lambda: ctx.sftp.delete_profile(_campo(data, 'name')) or True):
        await _send_profiles(ctx)


@handles('sftp_connect')
async def _sftp_connect(ctx: ClientConnection, data: dict) -> None:
    name = _campo(data, 'name')
    path = await _sftp(ctx, ctx.sftp.connect if ctx.sftp else None, ctx.owner, name)
    if path is not None:
        await ctx.send_json({"type": "sftp_connected", "name": name, "path": path})


@handles('sftp_disconnect')
async def _sftp_disconnect(ctx: ClientConnection, data: dict) -> None:
    if ctx.sftp is not None:
        ctx.sftp.close_owner(ctx.owner)
    await ctx.send_json({"type": "sftp_disconnected"})


@handles('sftp_list')
async def _sftp_list(ctx: ClientConnection, data: dict) -> None:
    listing = await _sftp(ctx, ctx.sftp.list_dir if ctx.sftp else None,
                          ctx.owner, _campo(data, 'path'))
    if listing is not None:
        await ctx.send_json({"type": "sftp_listing", **listing})


async def _sftp_done(ctx: ClientConnection, op: str, path: str, fn, *args) -> None:
    """Esegue un'operazione che modifica la cartella e conferma con `sftp_ok`
    (il client ricarica l'elenco)."""
    if await _sftp(ctx, lambda: fn(*args) or True):
        await ctx.send_json({"type": "sftp_ok", "op": op, "path": path})


@handles('sftp_mkdir')
async def _sftp_mkdir(ctx: ClientConnection, data: dict) -> None:
    if ctx.sftp:
        await _sftp_done(ctx, 'mkdir', _campo(data, 'path'), ctx.sftp.mkdir,
                         ctx.owner, _campo(data, 'path'), _campo(data, 'name'))


@handles('sftp_rename')
async def _sftp_rename(ctx: ClientConnection, data: dict) -> None:
    if ctx.sftp:
        await _sftp_done(ctx, 'rename', _campo(data, 'path'), ctx.sftp.rename,
                         ctx.owner, _campo(data, 'path'), _campo(data, 'old'), _campo(data, 'new'))


@handles('sftp_delete')
async def _sftp_delete(ctx: ClientConnection, data: dict) -> None:
    if ctx.sftp:
        await _sftp_done(ctx, 'delete', _campo(data, 'path'), ctx.sftp.delete,
                         ctx.owner, _campo(data, 'path'), _campo(data, 'name'),
                         data.get('dir') is True)


def _issue_ticket(ctx: ClientConnection, data: dict) -> dict:
    """Prepara un biglietto di trasferimento (bloccante: interroga l'host)."""
    direction = data.get('direction')
    if ctx.transfers is None or direction not in (DOWNLOAD, UPLOAD):
        raise SftpError("trasferimento non disponibile")
    if direction == DOWNLOAD:
        path = join_path(_campo(data, 'path'), _campo(data, 'name'))
        size = ctx.sftp.file_size(ctx.owner, path)
        if ctx.remote and size > REMOTE_DOWNLOAD_MAX:
            raise SftpError(
                f"da remoto il download è limitato a {REMOTE_DOWNLOAD_MAX >> 20} MB", code="too_big")
    else:
        if ctx.remote:
            raise SftpError("l'upload non è disponibile da remoto: usa la rete locale",
                            code="remote_upload")
        path = join_path(_campo(data, 'path'), _campo(data, 'name'))
        size = 0
        if data.get('overwrite') is not True and ctx.sftp.exists(ctx.owner, path):
            raise SftpError("esiste già un file con quel nome", code="exists")
    ctx.sftp._get(ctx.owner)  # senza connessione il biglietto non servirebbe
    try:
        token = ctx.transfers.issue(ctx.owner, direction, path)
    except RuntimeError as e:
        raise SftpError(str(e)) from e
    return {"type": "sftp_ticket", "direction": direction, "token": token,
            "name": validate_name(_campo(data, 'name')), "size": size}


@handles('sftp_ticket')
async def _sftp_ticket(ctx: ClientConnection, data: dict) -> None:
    reply = await _sftp(ctx, _issue_ticket, ctx, data)
    if reply is not None:
        await ctx.send_json(reply)


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
