"""Frame binari per l'output del terminale.

L'output del PTY viaggiava come JSON con il payload in base64: ~33% di banda in
più, una codifica base64 per ogni chunk lato server e una decodifica byte a byte
lato client. Su output abbondante (una build, un `dir /s`) era il costo
dominante del terminale.

Qui il payload va sul filo grezzo, dentro un frame WebSocket binario:

    [0x01][len_id: 1 byte][id: len_id byte ASCII][payload: byte grezzi]

La lunghezza dell'id è esplicita per non dipendere dal fatto che oggi
`uuid4().hex[:8]` sia sempre di 8 caratteri.

Gli altri messaggi del terminale (`term_created`, `term_closed`, `term_error`,
`term_sessions`) restano JSON: sono rari e strutturati, il binario non darebbe
nulla. Il client distingue i due casi dal tipo del dato ricevuto.

Il decoder qui serve ai test e a un eventuale client Python; il client reale è
il JavaScript in `index.html`, che deve restare allineato a questo formato.
"""

FRAME_TERM_OUTPUT = 0x01

# L'id sta in un solo byte di lunghezza.
MAX_ID_LEN = 255


def encode_term_output(session_id: str, payload: bytes) -> bytes:
    """Costruisce un frame di output. Solleva ValueError su id non valido."""
    try:
        raw_id = session_id.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError(f"id di sessione non ASCII: {session_id!r}")
    if not raw_id or len(raw_id) > MAX_ID_LEN:
        raise ValueError(f"lunghezza id non valida: {len(raw_id)}")
    return bytes((FRAME_TERM_OUTPUT, len(raw_id))) + raw_id + payload


def decode_term_output(frame: bytes) -> tuple[str, bytes] | None:
    """Estrae (id, payload) da un frame. None se il frame non è valido.

    Non solleva: i frame arrivano dalla rete e un frame malformato va ignorato,
    non deve chiudere la connessione.
    """
    if len(frame) < 2 or frame[0] != FRAME_TERM_OUTPUT:
        return None
    id_len = frame[1]
    if id_len == 0 or len(frame) < 2 + id_len:
        return None
    try:
        session_id = frame[2:2 + id_len].decode("ascii")
    except UnicodeDecodeError:
        return None
    return session_id, frame[2 + id_len:]
