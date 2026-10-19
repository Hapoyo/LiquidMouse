"""Controllo di Origin e Host nell'handshake WebSocket.

Un browser manda sempre l'Origin della pagina che apre il socket: senza filtro,
una pagina qualunque aperta sul telefono o sul PC (anche su internet) potrebbe
collegarsi a ws://<ip>:8765 e, dal loopback o dalla LAN, essere trattata come
client fidato. Una regex statica sugli IPv4 numerici era troppo larga (qualunque
IP estraneo, qualunque *.trycloudflare.com), quindi qui l'insieme degli host
ammessi dipende da chi si connette e da quale porta, ed è letto a ogni
handshake: l'IP LAN e il tunnel cambiano nel tempo.

Anche l'header Host deve appartenere all'insieme: con il DNS rebinding l'Origin
è il nome dell'attaccante ma l'indirizzo risolto è il nostro, e l'Host tradisce
la pagina. `Origin` assente = client non browser (tools/test_server.py), che
non è un vettore di attacco da pagina web: passa sempre.
"""

from urllib.parse import urlsplit

from liquidmouse.net.addresses import is_loopback

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Tipi di porta: LAN (8765 in chiaro), REMOTE (8443 TLS), TUNNEL (origine del tunnel).
LAN, REMOTE, TUNNEL = "lan", "remote", "tunnel"


def origin_host(origin: str) -> str | None:
    """Host di un Origin `http(s)://host[:porta]`; None se la forma non è
    quella di un browser (percorso, credenziali, schema diverso, "null")."""
    try:
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        if parts.path or parts.query or parts.fragment or "@" in parts.netloc:
            return None
        parts.port   # solleva ValueError se la porta non è valida
        return parts.hostname.lower()
    except ValueError:
        return None


def header_host(host: str) -> str | None:
    """Host di un header Host `nome[:porta]` (anche `[::1]:8765`)."""
    try:
        parts = urlsplit("//" + host)
        if not parts.hostname or parts.path or "@" in parts.netloc:
            return None
        parts.port
        return parts.hostname.lower()
    except ValueError:
        return None


def allowed_hosts(kind: str, peer_ip: str, *, local_ips=(), external_ip=None,
                  tunnel_host=None) -> set[str]:
    """Host ammessi per questa connessione.

    - tunnel: solo l'indirizzo del tunnel corrente (e il loopback nell'Host,
      nel caso cloudflared lo riscrivesse verso l'origine);
    - peer in loopback (finestra terminale sul PC): solo localhost/127.0.0.1;
    - LAN: l'IP locale attuale (più l'indirizzo a cui il peer si è collegato);
    - 8443: l'IP esterno e il tunnel corrente, non qualunque altro indirizzo.
    """
    if kind == TUNNEL:
        return {h for h in (tunnel_host,) if h} | LOOPBACK_HOSTS
    if is_loopback(peer_ip):
        return set(LOOPBACK_HOSTS)
    if kind == LAN:
        return {h for h in local_ips if h}
    return {h for h in (external_ip, tunnel_host) if h}


def origin_allowed(kind: str, peer_ip: str, origin: str | None, host: str | None,
                   **contesto) -> bool:
    """True se l'handshake può proseguire. `contesto`: vedi `allowed_hosts`."""
    if origin is None:
        return True
    ammessi = allowed_hosts(kind, peer_ip, **contesto)
    if kind == TUNNEL:
        # Per l'Origin conta solo il tunnel: il loopback vale per l'Host.
        ammessi_origin = ammessi - LOOPBACK_HOSTS
    else:
        ammessi_origin = ammessi
    o = origin_host(origin)
    h = header_host(host) if host else None
    return o is not None and h is not None and o in ammessi_origin and h in ammessi
