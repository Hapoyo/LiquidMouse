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
"""

import hashlib
import os

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
    "/icon.ico":   ("static/icon.ico",   "image/x-icon"),
}


class StaticAsset:
    __slots__ = ("body", "content_type", "etag")

    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.content_type = content_type
        self.etag = '"%s"' % hashlib.sha256(body).hexdigest()[:16]


class StaticFiles:
    """Asset statici precaricati, indicizzati per URL."""

    def __init__(self, base_dir: str, routes: dict | None = None) -> None:
        self.base_dir = base_dir
        self.routes = routes if routes is not None else STATIC_ROUTES
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
                    asset = StaticAsset(fh.read(), ctype)
            except OSError:
                if fname not in mancanti:
                    mancanti.append(fname)
                continue
            cache[fname] = asset
            self._assets[url] = asset
        return mancanti

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
