"""Ciclo di vita dei servizi di rete: HTTP locale, WebSocket, TLS, UPnP.

Tutto quello che serve arriva dal costruttore invece che da variabili globali:
è ciò che permette di far girare i servizi senza GUI e di sostituire i pezzi
nei test.

Le porte in gioco sono quattro (vedi `liquidmouse/ports.py`); la 8443 è la
"porta unica" remota e serve sia la pagina sia il canale comandi.
"""

import asyncio
import contextlib
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

from liquidmouse.events import log_message
from liquidmouse.net.addresses import is_loopback, is_private_ip
from liquidmouse.net.protocol import ClientConnection, dispatch
from liquidmouse.net.static import etag_matches
from liquidmouse.ports import HTTP_PORT, HTTPS_PORT, PORT, WSS_PORT
from liquidmouse.security.auth import AUTH_MAX_FAILS, pin_matches
from liquidmouse.theme import COLOR_ACCENT, COLOR_ERROR, COLOR_MUTED, COLOR_OK

AUTH_TIMEOUT_SECS = 10.0
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 10
# Rinnovo dei mapping UPnP. Auto-ripara il remoto dopo un riavvio del router
# (che azzera il NAT) e recupera i casi in cui l'UPnP viene abilitato a server
# già avviato.
UPNP_KEEPALIVE_SECS = 600


def make_http_handler(static):
    """Handler HTTP che serve `static` dalla cache in memoria.

    Sostituisce SimpleHTTPRequestHandler(directory=BASE_DIR), che serviva
    l'intera directory: chiunque sulla LAN poteva scaricare server.pyw e la
    config col PIN. Qui vale la whitelist di `static`.
    """

    class _StaticHTTPHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._serve(con_corpo=True)

        def do_HEAD(self):
            self._serve(con_corpo=False)

        def _serve(self, con_corpo: bool):
            asset = static.get(self.path)
            if asset is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            if etag_matches(self.headers.get("If-None-Match"), asset.etag):
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", asset.etag)
                self.end_headers()
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", asset.content_type)
            self.send_header("Content-Length", str(len(asset.body)))
            self.send_header("ETag", asset.etag)
            # no-cache = rivalida sempre, ma con l'ETag la rivalidazione costa
            # un 304 vuoto invece di ritrasferire 283 KB di xterm.js.
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if con_corpo:
                self.wfile.write(asset.body)

        def log_message(self, *args):
            pass

    return _StaticHTTPHandler


class NetworkServices:
    def __init__(self, *, config, auth_guard, trusted_peer, sessions, static,
                 tls, upnp, local_ip: str,
                 on_remote_change=None, on_session_created=None) -> None:
        self.config = config
        self.auth_guard = auth_guard
        self.trusted_peer = trusted_peer
        self.sessions = sessions
        self.static = static
        self.tls = tls
        self.upnp = upnp
        self.local_ip = local_ip
        self.on_remote_change = on_remote_change
        self.on_session_created = on_session_created
        self.remote_mode = "none"   # "upnp" | "none"

    @property
    def external_ip(self) -> str | None:
        return self.upnp.external_ip

    # --- autorizzazione ---------------------------------------------------

    async def authorize(self, websocket, client_ip: str) -> bool:
        """Applica il modello di autorizzazione. False = connessione già chiusa.

        Tre percorsi: remoto → PIN obbligatorio; loopback → sempre fidato (serve
        alla finestra terminale aperta sul PC stesso); LAN → whitelist primo
        arrivato.

        Nota: `is_private_ip` esclude il range CGNAT 100.64/10, quindi un client
        dietro il NAT condiviso dell'ISP conta come remoto e deve dare il PIN.
        """
        is_remote = not is_private_ip(client_ip)

        if not is_remote:
            if is_loopback(client_ip):
                log_message(f"Sessione locale: {client_ip}", color=COLOR_ACCENT)
                return True
            if not self.trusted_peer.claim(client_ip):
                log_message(f"Rifiutato: {client_ip}", color=COLOR_ERROR)
                await websocket.close()
                return False
            log_message(f"Sessione attiva: {client_ip}", color=COLOR_ACCENT)
            return True

        return await self._authorize_remote(websocket, client_ip)

    async def _authorize_remote(self, websocket, client_ip: str) -> bool:
        guard = self.auth_guard
        # begin() impedisce N handshake paralleli dallo stesso IP, che
        # proverebbero N PIN prima che il contatore raggiunga la soglia.
        if guard.is_blocked(client_ip) or not guard.begin(client_ip):
            await websocket.send(json.dumps({"type": "auth_blocked"}))
            await websocket.close()
            log_message(f"Bloccato (brute force): {client_ip}", color=COLOR_ERROR)
            return False
        try:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=AUTH_TIMEOUT_SECS)
                data = json.loads(raw)
            except Exception:
                await websocket.close()
                return False
            if data.get('type') != 'auth':
                await websocket.close()
                return False
            if not pin_matches(data.get('pin', ''), self.config.get('pin_hash', '')):
                guard.record_fail(client_ip)
                rimasti = guard.remaining(client_ip)
                await websocket.send(json.dumps({
                    "type": "auth_fail", "remaining": rimasti
                }))
                await websocket.close()
                log_message(
                    f"Auth fallita ({AUTH_MAX_FAILS - rimasti}/{AUTH_MAX_FAILS}) da {client_ip}",
                    color=COLOR_ERROR)
                return False
        finally:
            # Senza il finally, un'eccezione fuori dai rami previsti lasciava
            # l'IP occupato per sempre, bloccandolo in modo permanente.
            guard.end(client_ip)

        guard.clear(client_ip)
        await websocket.send(json.dumps({"type": "auth_ok"}))
        log_message(f"Connessione remota autorizzata: {client_ip}", color=COLOR_ACCENT)
        return True

    # --- WebSocket --------------------------------------------------------

    async def handler(self, websocket):
        """Ciclo di vita di una connessione client."""
        client_ip = websocket.remote_address[0]
        if not await self.authorize(websocket, client_ip):
            return

        ctx = ClientConnection(websocket, client_ip, self.sessions,
                               on_session_created=self.on_session_created)
        try:
            async for message in websocket:
                await dispatch(ctx, message)
        except websockets.exceptions.ConnectionClosed:
            log_message("In attesa di connessione...", color=COLOR_MUTED)
        finally:
            # Senza questo, un client che si disconnette con Ctrl premuto lascia
            # il modificatore giù sul PC. Sgancia anche le sessioni terminal,
            # così una riconnessione può riagganciarle.
            ctx.release_all()

    # --- HTTP -------------------------------------------------------------

    def start_http_server(self) -> None:
        try:
            # ThreadingHTTPServer: con quello sequenziale una richiesta lenta
            # bloccava tutte le altre, e la pagina carica quattro asset.
            httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT),
                                        make_http_handler(self.static))
            httpd.serve_forever()
        except OSError:
            log_message(f"Errore: Porta {HTTP_PORT} occupata!", color=COLOR_ERROR)
        except Exception as e:
            log_message(f"HTTP Server crash: {e}", color=COLOR_ERROR)

    def https_process_request(self, connection, request):
        """Le richieste senza Upgrade (browser che chiede la pagina) ricevono i
        file statici; quelle WebSocket proseguono con l'handshake (return None).

        Legge dalla cache in memoria: qui siamo dentro l'event loop asyncio, e
        una lettura da disco bloccherebbe tutti i WebSocket attivi.
        """
        if request.headers.get("Upgrade", ""):
            return None
        asset = self.static.get(request.path)
        if asset is None:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        if etag_matches(request.headers.get("If-None-Match"), asset.etag):
            return Response(304, "Not Modified", Headers([
                ("ETag", asset.etag),
                ("Connection", "close"),
            ]), b"")
        return Response(200, "OK", Headers([
            ("Content-Type", asset.content_type),
            ("Content-Length", str(len(asset.body))),
            ("ETag", asset.etag),
            ("Cache-Control", "no-cache"),
            ("Connection", "close"),
        ]), asset.body)

    # --- avvio ------------------------------------------------------------

    def _set_remote_mode(self, mode: str) -> None:
        self.remote_mode = mode
        if self.on_remote_change:
            self.on_remote_change()

    async def _upnp_keepalive(self) -> None:
        while True:
            await asyncio.sleep(UPNP_KEEPALIVE_SECS)
            precedente = self.external_ip
            nuovo_ip = await self.upnp.setup(self.local_ip)
            nuovo_mode = 'upnp' if nuovo_ip else 'none'
            if nuovo_mode != self.remote_mode or (nuovo_ip and nuovo_ip != precedente):
                if nuovo_ip:
                    log_message(f"UPnP rinnovato: {nuovo_ip}", color=COLOR_OK)
                else:
                    log_message("UPnP perso: remoto non disponibile", color=COLOR_MUTED)
                self._set_remote_mode(nuovo_mode)

    async def start_websocket_server(self) -> None:
        log_message("Protocolli di comunicazione inizializzati.", color=COLOR_MUTED)
        ssl_ctx = self.tls.context_for(self.local_ip)

        ext_ip = await self.upnp.setup(self.local_ip)
        if ext_ip:
            log_message(f"UPnP attivo: {ext_ip}", color=COLOR_OK)
        else:
            log_message("UPnP non riuscito: remoto non disponibile", color=COLOR_MUTED)
        self._set_remote_mode('upnp' if ext_ip else 'none')

        asyncio.get_running_loop().create_task(self._upnp_keepalive())

        servers = [
            websockets.serve(self.handler, "0.0.0.0", PORT,
                             ping_interval=WS_PING_INTERVAL,
                             ping_timeout=WS_PING_TIMEOUT),
        ]
        if ssl_ctx:
            # Porta unica remota: pagina + WSS su HTTPS_PORT.
            servers.append(
                websockets.serve(self.handler, "0.0.0.0", HTTPS_PORT, ssl=ssl_ctx,
                                 ping_interval=WS_PING_INTERVAL,
                                 ping_timeout=WS_PING_TIMEOUT,
                                 process_request=self.https_process_request)
            )
            # Legacy: WSS dedicato per client pre-porta-unica ancora in giro.
            servers.append(
                websockets.serve(self.handler, "0.0.0.0", WSS_PORT, ssl=ssl_ctx,
                                 ping_interval=WS_PING_INTERVAL,
                                 ping_timeout=WS_PING_TIMEOUT)
            )

        try:
            async with contextlib.AsyncExitStack() as stack:
                for srv in servers:
                    await stack.enter_async_context(srv)
                await asyncio.Future()
        except OSError:
            log_message(f"ERRORE CRITICO: Porta {PORT} occupata!", color=COLOR_ERROR)
        except Exception as e:
            log_message(f"WebSocket Server crash: {e}", color=COLOR_ERROR)
        finally:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.upnp.cleanup)

    def run(self) -> None:
        """Punto di ingresso del thread dei servizi."""
        threading.Thread(target=self.start_http_server, daemon=True).start()
        # HTTPS_PORT è gestita dal server websockets (porta unica remota):
        # niente thread HTTPS separato, il bind doppio fallirebbe.
        asyncio.run(self.start_websocket_server())
