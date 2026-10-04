"""Cache in memoria degli asset statici del client.

Prima gli asset venivano riletti da disco a ogni richiesta, e sul percorso
remoto quella lettura avveniva **dentro l'event loop asyncio**: servire i 283 KB
di xterm.js bloccava tutti i WebSocket attivi, quindi mouse e terminale si
inchiodavano mentre la pagina caricava. E con `Cache-Control: no-cache` il
browser li riscaricava a ogni reload.

Gli asset sono immutabili per l'intera vita del processo (nel bundle PyInstaller
sono estratti una volta sola), quindi si caricano all'avvio e si tengono in
memoria — sono poche centinaia di KB — con un ETag che permette al browser di
farsi rispondere 304 invece di ritrasferirli.

In più: la versione gzip si calcola una volta sola al caricamento (xterm.js passa
da 283 KB a circa 70, ed è ciò che pesa sul 4G), index.html referenzia gli asset con
`?v=VERSION` così che gli altri file possano essere `immutable` per un anno, e ogni
risposta porta gli header di sicurezza (`SECURITY_HEADERS`).
"""

import gzip
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

# URL pubblico → (nome del file su disco, content type)
# È una whitelist: qualunque path non elencato riceve 404. Il percorso LAN
# serviva invece l'intera BASE_DIR, quindi esponeva anche server.pyw e la
# config a chiunque fosse sulla rete.
# Le chiavi (URL pubblici) non cambiano mai per riorganizzazioni interne: solo
# il nome su disco (secondo elemento) riflette dove il file vive nel repo.
STATIC_ROUTES: dict[str, tuple[str, str]] = {
    "/":           ("static/index.html", "text/html; charset=utf-8"),
    "/index.html": ("static/index.html", "text/html; charset=utf-8"),
    "/app.css":    ("static/app.css",    "text/css; charset=utf-8"),
    "/app.js":     ("static/app.js",     "application/javascript; charset=utf-8"),
    "/xterm.js":   ("static/vendor/xterm.js",  "application/javascript; charset=utf-8"),
    "/xterm.css":  ("static/vendor/xterm.css", "text/css; charset=utf-8"),
    # Motion (motion.dev), build UMD che espone il global `Motion`: locale e
    # non da CDN, perché il client gira anche in una LAN senza internet.
    "/motion.js":  ("static/vendor/motion.js", "application/javascript; charset=utf-8"),
    "/LICENSE-motion.txt": ("static/vendor/LICENSE-motion.txt", "text/plain; charset=utf-8"),
    "/icon.ico":   ("static/icon.ico",   "image/x-icon"),
    # Tema cyber: gli stessi TTF sono caricati anche da Tk (gui/effects.py).
    "/fonts/SpaceGrotesk-Medium.ttf": ("static/fonts/SpaceGrotesk-Medium.ttf", "font/ttf"),
    "/fonts/SpaceMono-Regular.ttf":   ("static/fonts/SpaceMono-Regular.ttf",   "font/ttf"),
    "/fonts/SpaceMono-Bold.ttf":      ("static/fonts/SpaceMono-Bold.ttf",      "font/ttf"),
    # La licenza OFL deve accompagnare i font ovunque vengano distribuiti.
    "/fonts/OFL-SpaceGrotesk.txt": ("static/fonts/OFL-SpaceGrotesk.txt", "text/plain; charset=utf-8"),
    "/fonts/OFL-SpaceMono.txt":    ("static/fonts/OFL-SpaceMono.txt",    "text/plain; charset=utf-8"),
}


# Pagina di ingresso: l'unica che il browser deve rivalidare a ogni apertura,
# perché è lei a dire quali versioni degli altri file usare.
INDEX_URLS = ("/", "/index.html")
IMMUTABLE = "max-age=31536000, immutable"
# Gli asset non cambiano mentre il processo gira, ma fra una versione e l'altra sì:
# l'URL versionato (?v=) rende sicuro tenerli un anno nella cache del browser.
# I font hanno il nome del file come identità e non si aggiornano mai.
_VERSIONED_PREFIXES = ("/fonts/",)

# CSP: script solo dal nostro server (niente handler inline, vedi app.js).
# style-src tiene 'unsafe-inline' perché xterm.js inserisce elementi <style> e
# la pagina ha qualche style="": passare a nonce/hash è un passo successivo.
# connect-src elenca ws:/wss: perché 'self' non copre il WebSocket su un'altra
# porta (8765/8443) in tutti i browser.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self' ws: wss:; img-src 'self' data:; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS: list[tuple[str, str]] = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy", CSP),
]

# Tipi per cui gzip ha senso; il resto si serve com'è. L'asset comprime solo se
# il risultato è davvero più piccolo.
_COMPRIMIBILI = ("text/", "application/javascript", "font/ttf", "image/x-icon")
# Riferimenti locali di index.html (src/href) a cui aggiungere ?v=VERSION.
_RIF_LOCALE = re.compile(r'(\b(?:src|href)=")([^"#?:]+)(")')


class StaticAsset:
    __slots__ = ("body", "content_type", "etag", "gzip_body", "gzip_etag")

    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.content_type = content_type
        self.etag = '"%s"' % hashlib.sha256(body).hexdigest()[:16]
        self.gzip_body: bytes | None = None
        self.gzip_etag: str | None = None
        if content_type.startswith(_COMPRIMIBILI):
            # mtime=0: stesso input → stessi byte, quindi ETag stabile fra riavvii.
            compresso = gzip.compress(body, compresslevel=9, mtime=0)
            if len(compresso) < len(body):
                self.gzip_body = compresso
                # Rappresentazione diversa = validatore diverso (RFC 9110).
                self.gzip_etag = self.etag[:-1] + '-gz"'


@dataclass
class Served:
    """Risposta pronta: stato, header (senza quelli di sicurezza) e corpo."""
    status: int
    headers: list[tuple[str, str]]
    body: bytes


def accepts_gzip(header_value: str | None) -> bool:
    """True se `Accept-Encoding` ammette gzip (q=0 lo esclude)."""
    if not header_value:
        return False
    for voce in header_value.split(","):
        nome, _, params = voce.strip().partition(";")
        if nome.strip().lower() not in ("gzip", "x-gzip", "*"):
            continue
        q = re.search(r"q\s*=\s*([0-9.]+)", params)
        try:
            return float(q.group(1)) > 0 if q else True
        except ValueError:
            return False
    return False


class StaticFiles:
    """Asset statici precaricati, indicizzati per URL."""

    def __init__(self, base_dir: str, routes: dict | None = None,
                 version: str | None = None) -> None:
        self.base_dir = base_dir
        self.routes = routes if routes is not None else STATIC_ROUTES
        # Senza versione (test, anteprime) index.html resta com'è sul disco.
        self.version = version
        self._assets: dict[str, StaticAsset] = {}

    def load(self) -> list[str]:
        """Carica in memoria gli asset. Ritorna i nomi dei file mancanti.

        Un file mancante non è fatale — l'app parte comunque — ma va segnalato:
        il sintomo altrimenti è un 404 che si manifesta solo da remoto.
        """
        self._assets.clear()
        cache: dict[str, StaticAsset] = {}
        mancanti = []
        for url, (fname, ctype) in self.routes.items():
            if fname in cache:
                self._assets[url] = cache[fname]
                continue
            try:
                with open(os.path.join(self.base_dir, fname), "rb") as fh:
                    body = fh.read()
                if url in INDEX_URLS and self.version:
                    body = self._versioned_index(body)
                asset = StaticAsset(body, ctype)
            except OSError:
                if fname not in mancanti:
                    mancanti.append(fname)
                continue
            cache[fname] = asset
            self._assets[url] = asset
        return mancanti

    def _versioned_index(self, html: bytes) -> bytes:
        """Aggiunge `?v=VERSION` ai riferimenti locali di index.html che sono
        rotte note: a ogni release gli URL cambiano e la cache di un anno è sicura."""
        testo = html.decode("utf-8")

        def aggiungi(m: re.Match) -> str:
            if "/" + m.group(2).lstrip("/") not in self.routes:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}?v={self.version}{m.group(3)}"

        return _RIF_LOCALE.sub(aggiungi, testo).encode("utf-8")

    def cache_control(self, raw_path: str) -> str:
        """`immutable` solo per ciò che ha l'URL versionato (o è un font);
        index.html e gli URL senza ?v= restano da rivalidare."""
        path, _, query = raw_path.partition("?")
        if path in INDEX_URLS:
            return "no-cache"
        if path.startswith(_VERSIONED_PREFIXES) or parse_qs(query).get("v"):
            return IMMUTABLE
        return "no-cache"

    def serve(self, raw_path: str, accept_encoding: str | None = None,
              if_none_match: str | None = None) -> Served | None:
        """Risposta completa per un GET, o None se il path non è in whitelist.

        Sceglie la rappresentazione (gzip o no) dall'Accept-Encoding e risponde
        304 se l'ETag di quella rappresentazione coincide.
        """
        asset = self.get(raw_path)
        if asset is None:
            return None
        gz = asset.gzip_body is not None and accepts_gzip(accept_encoding)
        etag = asset.gzip_etag if gz else asset.etag
        headers = [("ETag", etag), ("Cache-Control", self.cache_control(raw_path))]
        if asset.gzip_body is not None:
            headers.append(("Vary", "Accept-Encoding"))
        if etag_matches(if_none_match, etag):
            return Served(304, headers, b"")
        body = asset.gzip_body if gz else asset.body
        headers = [("Content-Type", asset.content_type),
                   ("Content-Length", str(len(body)))] + headers
        if gz:
            headers.append(("Content-Encoding", "gzip"))
        return Served(200, headers, body)

    def get(self, path: str) -> StaticAsset | None:
        """Asset per un path di richiesta, query string esclusa."""
        return self._assets.get(path.split("?", 1)[0])

    def __len__(self) -> int:
        return len(self._assets)


def etag_matches(header_value: str | None, etag: str) -> bool:
    """True se l'If-None-Match del client copre `etag` (allora basta un 304)."""
    if not header_value:
        return False
    if header_value.strip() == "*":
        return True
    for candidato in header_value.split(","):
        candidato = candidato.strip()
        if candidato.startswith("W/"):
            candidato = candidato[2:]
        if candidato == etag:
            return True
    return False
