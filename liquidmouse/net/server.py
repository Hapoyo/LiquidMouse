"""Ciclo di vita dei servizi di rete: HTTP locale, WebSocket, TLS, UPnP.

Tutto quello che serve arriva dal costruttore invece che da variabili globali:
è ciò che permette di far girare i servizi senza GUI e di sostituire i pezzi
nei test.

Le porte in gioco sono cinque (vedi `liquidmouse/ports.py`); la 8443 è la
"porta unica" remota e serve sia la pagina sia il canale comandi. La 8767 è
l'origine del tunnel Cloudflare, la strada remota quando UPnP non può
funzionare (CGNAT).
"""

import asyncio
import contextlib
import ipaddress
import json
import re
import threading
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

from liquidmouse.events import log_message
from liquidmouse.executors import NET, SFTP
from liquidmouse.net.addresses import is_loopback, is_private_ip
from liquidmouse.net.protocol import ClientConnection, dispatch
from liquidmouse.net.sftp import CHUNK, SftpError
from liquidmouse.net.static import SECURITY_HEADERS
from liquidmouse.net.transfers import DOWNLOAD, REMOTE_DOWNLOAD_MAX, UPLOAD
from liquidmouse.ports import HTTP_PORT, HTTPS_PORT, PORT, TUNNEL_PORT, WSS_PORT
from liquidmouse.security.auth import AUTH_MAX_FAILS, pin_matches
from liquidmouse.theme import COLOR_ACCENT, COLOR_ERROR, COLOR_MUTED, COLOR_OK

AUTH_TIMEOUT_SECS = 10.0
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 10
# Timeout di lettura/scrittura delle connessioni HTTP sulla 8000 (aperta alla
# LAN): senza, un client che apre il socket e non finisce la richiesta (o non
# legge la risposta) terrebbe un thread per sempre (slowloris). Vale per ogni
# singola operazione sul socket, non per l'intero trasferimento.
HTTP_TIMEOUT_SECS = 30
# Rinnovo dei mapping UPnP. Auto-ripara il remoto dopo un riavvio del router
# (che azzera il NAT) e recupera i casi in cui l'UPnP viene abilitato a server
# già avviato.
UPNP_KEEPALIVE_SECS = 600
# Ogni quanto il keepalive controlla se l'IP locale è cambiato (wifi diverso,
# DHCP rinnovato con un altro indirizzo): costa una connect UDP senza traffico,
# quindi si può fare molto più spesso del rinnovo UPnP.
IP_CHECK_SECS = 30
# Chiave anti brute force per chi arriva dal tunnel senza l'header di
# Cloudflare (in pratica solo un processo locale).
TUNNEL_GUARD_KEY = "tunnel"

# Origin ammessi nell'handshake WebSocket. Un browser manda sempre l'Origin
# della pagina che apre il socket: senza filtro, una pagina qualunque aperta
# sul telefono o sul PC (anche su internet) potrebbe collegarsi a ws://<ip>:8765
# e, dal loopback o dalla LAN, essere trattata come client fidato. Valgono solo
# le pagine servite da noi: localhost/127.0.0.1 (finestra terminale sul PC), un
# IPv4 numerico (LAN e IP pubblico UPnP) e il tunnel. Hostname arbitrari no:
# sono la via del DNS rebinding. None = client non browser (nessun header, come
# test_server.py), che non è un vettore di attacco da pagina web.
_ORIGIN_HOST = (r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3}"
                r"|[a-z0-9-]+\.trycloudflare\.com)")
ALLOWED_ORIGINS = [
    None,
    re.compile(rf"https?://{_ORIGIN_HOST}(?::\d{{1,5}})?", re.IGNORECASE),
]


def tunnel_client_ip(headers) -> str:
    """IP del client dietro il tunnel, dall'header che mette Cloudflare.

    Dal tunnel tutte le connessioni arrivano da 127.0.0.1: usato come chiave
    dell'anti brute force, cinque PIN sbagliati di chiunque su internet
    avrebbero bloccato per 30 minuti anche il telefono del proprietario.
    L'header è affidabile perché la porta del tunnel ascolta solo in loopback:
    ci arriva cloudflared, e Cloudflare lo riscrive sempre.
    """
    valore = (headers.get("CF-Connecting-IP") or "").strip() if headers else ""
    try:
        return str(ipaddress.ip_address(valore))
    except ValueError:
        return TUNNEL_GUARD_KEY


SFTP_DOWNLOAD_PATH = "/sftp/dl"
SFTP_UPLOAD_PATH = "/sftp/up"


def ticket_token(raw_path: str) -> tuple[str, str]:
    """(percorso, token) da un URL di trasferimento; token vuoto se manca."""
    parts = urlsplit(raw_path)
    return parts.path, (parse_qs(parts.query).get("t") or [""])[0]


def download_headers(name: str, size: int) -> list[tuple[str, str]]:
    """Intestazioni di un download. Il nome va percent-encoded (RFC 5987): un
    nome con virgolette o a capo spezzerebbe l'header."""
    return [
        ("Content-Type", "application/octet-stream"),
        ("Content-Length", str(size)),
        ("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name, safe='')}"),
        ("Cache-Control", "no-store"),
    ]


def make_http_handler(static, sftp=None, transfers=None):
    """Handler HTTP che serve `static` dalla cache in memoria.

    Sostituisce SimpleHTTPRequestHandler(directory=BASE_DIR), che serviva
    l'intera directory: chiunque sulla LAN poteva scaricare server.pyw e la
    config col PIN. Qui vale la whitelist di `static`.

    Con `sftp` e `transfers` gestisce anche i trasferimenti (`/sftp/dl`,
    `/sftp/up`), ognuno con un biglietto monouso: vedi net/transfers.py.
    """

    class _StaticHTTPHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = HTTP_TIMEOUT_SECS

        def do_GET(self):
            if urlsplit(self.path).path == SFTP_DOWNLOAD_PATH:
                self._sftp_download()
                return
            self._serve(con_corpo=True)

        def do_POST(self):
            if urlsplit(self.path).path == SFTP_UPLOAD_PATH:
                self._sftp_upload()
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def _ticket(self, direction: str):
            """Biglietto valido o None (e in quel caso ha già risposto 403)."""
            ticket = None
            if sftp is not None and transfers is not None:
                ticket = transfers.redeem(ticket_token(self.path)[1], direction)
            if ticket is None:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return ticket

        def _sftp_download(self):
            ticket = self._ticket(DOWNLOAD)
            if ticket is None:
                return
            try:
                fh, size = sftp.open_read(ticket.owner, ticket.path)
            except SftpError as e:
                self.send_error(HTTPStatus.GONE, str(e))
                return
            try:
                self.send_response(HTTPStatus.OK)
                for k, v in download_headers(ticket.path.rsplit("/", 1)[-1], size):
                    self.send_header(k, v)
                self.end_headers()
                # A blocchi: un file da 2 GB non deve stare in memoria.
                rimasti = size
                while rimasti > 0:
                    blocco = fh.read(min(CHUNK, rimasti))
                    if not blocco:
                        break
                    self.wfile.write(blocco)
                    rimasti -= len(blocco)
                if rimasti > 0:
                    # File accorciato durante il download: chiudere, altrimenti
                    # il browser aspetta byte che non arriveranno.
                    self.close_connection = True
            except (OSError, ConnectionError):
                self.close_connection = True   # il telefono ha annullato
            finally:
                fh.close()

        def _sftp_upload(self):
            ticket = self._ticket(UPLOAD)
            if ticket is None:
                return
            try:
                totale = int(self.headers.get("Content-Length", ""))
                if totale < 0:
                    raise ValueError
            except ValueError:
                self.close_connection = True
                self.send_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
                return
            try:
                fh = sftp.open_write(ticket.owner, ticket.path)
            except SftpError as e:
                self.close_connection = True
                self.send_error(HTTPStatus.GONE, str(e))
                return
            completo = False
            try:
                rimasti = totale
                while rimasti > 0:
                    blocco = self.rfile.read(min(CHUNK, rimasti))
                    if not blocco:
                        raise ConnectionError("upload interrotto")
                    fh.write(blocco)
                    rimasti -= len(blocco)
                fh.close()   # qui il file parziale diventa quello definitivo
                completo = True
            except (OSError, ConnectionError):
                self.close_connection = True
                return
            finally:
                if not completo:
                    # Un upload interrotto non deve lasciare un file troncato
                    # al posto dell'originale: si scarta il parziale.
                    fh.abort()
            corpo = b'{"ok":true}'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_HEAD(self):
            self._serve(con_corpo=False)

        def end_headers(self):
            # Su ogni risposta (pagina, 404, download), non solo sugli asset.
            for nome, valore in SECURITY_HEADERS:
                self.send_header(nome, valore)
            super().end_headers()

        def _serve(self, con_corpo: bool):
            risposta = static.serve(self.path, self.headers.get("Accept-Encoding"),
                                    self.headers.get("If-None-Match"))
            if risposta is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            self.send_response(risposta.status)
            for nome, valore in risposta.headers:
                self.send_header(nome, valore)
            self.end_headers()
            if con_corpo and risposta.body:
                self.wfile.write(risposta.body)

        def log_message(self, *args):
            pass

    return _StaticHTTPHandler


class NetworkServices:
    def __init__(self, *, config, auth_guard, trusted_peer, sessions, static,
                 tls, upnp, local_ip: str, tunnel=None,
                 on_remote_change=None, on_session_created=None,
                 sftp=None, transfers=None,
                 ip_provider=None, on_local_ip_change=None) -> None:
        self.config = config
        self.auth_guard = auth_guard
        self.trusted_peer = trusted_peer
        self.sessions = sessions
        self.static = static
        self.tls = tls
        self.upnp = upnp
        self.tunnel = tunnel
        if tunnel is not None:
            tunnel.on_change = self._on_tunnel_change
        self.local_ip = local_ip
        # Callable senza argomenti che ritorna l'IP LAN attuale (server.pyw passa
        # get_local_ip); None = nessun controllo, come nei test. `on_local_ip_change`
        # è il sink con cui la GUI aggiorna QR e indirizzo: il core non la importa.
        self._ip_provider = ip_provider
        self.on_local_ip_change = on_local_ip_change
        self.on_remote_change = on_remote_change
        self.on_session_created = on_session_created
        self.sftp = sftp
        self.transfers = transfers
        self.remote_mode = "none"   # "upnp" | "tunnel" | "none"
        self._ssl_ctx = None

    @property
    def external_ip(self) -> str | None:
        return self.upnp.external_ip

    @property
    def external_port(self) -> int:
        """Porta pubblica del QR: il router può aver rifiutato la 8443 e
        averne concessa una di riserva (vedi net/upnp.py)."""
        return getattr(self.upnp, "external_port", None) or HTTPS_PORT

    @property
    def tunnel_url(self) -> str | None:
        return self.tunnel.url if self.tunnel is not None else None

    @property
    def remote_problem(self) -> str | None:
        """Perché il remoto non è attivo: lo stato del tunnel quando è lui la
        strada in corso, altrimenti il motivo del fallimento UPnP."""
        if self.tunnel is not None and self.tunnel.running and self.tunnel.status:
            return f"tunnel: {self.tunnel.status}"
        return self.upnp.last_error

    # --- autorizzazione ---------------------------------------------------

    async def authorize(self, websocket, client_ip: str, *, via_tunnel: bool = False) -> bool:
        """Applica il modello di autorizzazione. False = connessione già chiusa.

        Tre percorsi: remoto → PIN obbligatorio; loopback → sempre fidato (serve
        alla finestra terminale aperta sul PC stesso); LAN → whitelist primo
        arrivato.

        Nota: `is_private_ip` esclude il range CGNAT 100.64/10, quindi un client
        dietro il NAT condiviso dell'ISP conta come remoto e deve dare il PIN.
        Dal tunnel il PIN serve sempre: lì ogni client arriva da 127.0.0.1, e
        il ramo loopback lo lascerebbe entrare senza.
        """
        if via_tunnel:
            return await self._authorize_remote(websocket, client_ip)
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
            if not isinstance(data, dict):
                # Un JSON che non è un oggetto (lista, numero) non è un client
                # vero: conta come tentativo fallito invece di far cadere
                # l'handshake con un'eccezione non contata dal guard.
                pin = None
            elif data.get('type') != 'auth':
                await websocket.close()
                return False
            else:
                pin = data.get('pin', '')
            if not isinstance(pin, str) or not pin_matches(
                    pin, self.config.get('pin_hash', '')):
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

    async def handler(self, websocket, *, via_tunnel: bool = False):
        """Ciclo di vita di una connessione client."""
        if via_tunnel:
            client_ip = tunnel_client_ip(getattr(websocket.request, "headers", None))
        else:
            client_ip = websocket.remote_address[0]
        if not await self.authorize(websocket, client_ip, via_tunnel=via_tunnel):
            return

        ctx = ClientConnection(websocket, client_ip, self.sessions,
                               on_session_created=self.on_session_created,
                               sftp=self.sftp, transfers=self.transfers,
                               remote=via_tunnel or not is_private_ip(client_ip))
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
                                        make_http_handler(self.static, self.sftp,
                                                          self.transfers))
            httpd.serve_forever()
        except OSError:
            log_message(f"Errore: Porta {HTTP_PORT} occupata!", color=COLOR_ERROR)
        except Exception as e:
            log_message(f"HTTP Server crash: {e}", color=COLOR_ERROR)

    def _read_download(self, ticket) -> tuple[bytes, str]:
        """Legge un file intero per la strada remota (bloccante, tetto di
        REMOTE_DOWNLOAD_MAX: la risposta di websockets sta tutta in memoria)."""
        fh, size = self.sftp.open_read(ticket.owner, ticket.path)
        try:
            if size > REMOTE_DOWNLOAD_MAX:
                raise SftpError("file troppo grande per il download remoto")
            return fh.read(size), ticket.path.rsplit("/", 1)[-1]
        finally:
            fh.close()

    async def _remote_download(self, connection, request):
        percorso, token = ticket_token(request.path)
        ticket = None
        if self.sftp is not None and self.transfers is not None:
            ticket = self.transfers.redeem(token, DOWNLOAD)
        if percorso != SFTP_DOWNLOAD_PATH or ticket is None:
            return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
        try:
            corpo, nome = await asyncio.get_running_loop().run_in_executor(
                SFTP, self._read_download, ticket)
        except SftpError as e:
            return connection.respond(HTTPStatus.GONE, f"{e}\n")
        headers = download_headers(nome, len(corpo)) + [("Connection", "close")]
        return Response(200, "OK", Headers(headers), corpo)

    async def https_process_request(self, connection, request):
        """Le richieste senza Upgrade (browser che chiede la pagina) ricevono i
        file statici; quelle WebSocket proseguono con l'handshake (return None).

        Legge dalla cache in memoria: qui siamo dentro l'event loop asyncio, e
        una lettura da disco bloccherebbe tutti i WebSocket attivi. I download
        SFTP fanno eccezione ma girano in un executor.
        """
        if request.headers.get("Upgrade", ""):
            return None
        if request.path.startswith(SFTP_DOWNLOAD_PATH):
            risposta = await self._remote_download(connection, request)
        else:
            risposta = self._remote_static(connection, request)
        # Su ogni risposta (pagina, 404, download), non solo sugli asset.
        for nome, valore in SECURITY_HEADERS:
            risposta.headers[nome] = valore
        return risposta

    def _remote_static(self, connection, request):
        servito = self.static.serve(request.path, request.headers.get("Accept-Encoding"),
                                    request.headers.get("If-None-Match"))
        if servito is None:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        motivo = "Not Modified" if servito.status == 304 else "OK"
        return Response(servito.status, motivo,
                        Headers(servito.headers + [("Connection", "close")]), servito.body)

    # --- avvio ------------------------------------------------------------

    def _set_remote_mode(self, mode: str) -> None:
        self.remote_mode = mode
        if self.on_remote_change:
            self.on_remote_change()

    def _tunnel_mode(self) -> str:
        return 'tunnel' if self.tunnel_url else 'none'

    def _on_tunnel_change(self) -> None:
        """Il tunnel ha cambiato stato (dal suo thread). Con UPnP attivo il
        tunnel non è la strada in uso e non cambia nulla."""
        if self.remote_mode == 'upnp':
            return
        self._set_remote_mode(self._tunnel_mode())

    async def _refresh_remote(self, *, primo: bool = False) -> None:
        """Sceglie la strada remota: UPnP se apre la porta, altrimenti il tunnel.

        Unico punto di decisione, usato all'avvio e dal keepalive: prima il
        keepalive rifaceva la scelta per conto suo e saltava il controllo sul
        certificato TLS.
        """
        precedente = (self.remote_mode, self.external_ip, self.external_port)
        ext_ip = await self.upnp.setup(self.local_ip)
        if ext_ip and not self._ssl_ctx:
            # UPnP ha aperto la porta ma senza certificato TLS il server
            # HTTPS_PORT/WSS_PORT non viene nemmeno avviato: dichiarare il
            # remoto UPnP attivo sarebbe un falso positivo, un QR che punta a
            # una porta chiusa.
            self.upnp.last_error = (
                "UPnP attivo ma certificato TLS non disponibile: il percorso "
                "remoto resta chiuso (vedi log)")
            ext_ip = None
            if primo:
                log_message(self.upnp.last_error, color=COLOR_ERROR)

        if ext_ip:
            if self.tunnel is not None and self.tunnel.running:
                # Porta aperta: il tunnel non serve più, e lasciarlo su terrebbe
                # un secondo indirizzo pubblico aperto senza motivo.
                self.tunnel.stop()
            if precedente != ('upnp', ext_ip, self.external_port):
                log_message(f"UPnP attivo: {ext_ip}:{self.external_port}", color=COLOR_OK)
                self._set_remote_mode('upnp')
            return

        if primo or precedente[0] == 'upnp':
            log_message(f"UPnP non riuscito: {self.upnp.last_error}", color=COLOR_MUTED)
        if self.tunnel is not None and not self.tunnel.running:
            log_message("Accesso remoto tramite tunnel Cloudflare", color=COLOR_MUTED)
            self.tunnel.start()
        nuovo = self._tunnel_mode()
        if primo or nuovo != precedente[0]:
            self._set_remote_mode(nuovo)

    async def _refresh_local_ip(self) -> bool:
        """Rivaluta l'IP LAN; se è cambiato aggiorna certificato e GUI.

        Prima `local_ip` era calcolato una volta sola all'avvio: cambiando rete
        il QR LAN, il SAN del certificato e il mapping UPnP restavano quelli
        vecchi fino al riavvio. Ritorna True se l'IP è cambiato (il chiamante
        rifà allora la scelta remota, che riapre il mapping verso il nuovo IP).
        """
        if self._ip_provider is None:
            return False
        nuovo = self._ip_provider()
        # 127.0.0.1 = rete assente, non un indirizzo a cui passare: si resta
        # sull'ultimo noto e si riprova al prossimo giro.
        if not nuovo or nuovo == self.local_ip or is_loopback(nuovo):
            return False
        log_message(f"Indirizzo LAN cambiato: {self.local_ip} → {nuovo}", color=COLOR_ACCENT)
        self.local_ip = nuovo
        # Stesso SSLContext: i server HTTPS/WSS già in ascolto lo hanno in uso,
        # e tls.context_for ricarica il nuovo certificato dentro quell'oggetto.
        # La generazione RSA può durare secondi: fuori dall'event loop.
        # Se all'avvio il TLS non c'era, i server HTTPS non esistono: generare ora
        # un contesto farebbe dichiarare attivo un remoto su una porta chiusa.
        if self._ssl_ctx is not None:
            ctx = await asyncio.get_running_loop().run_in_executor(
                NET, self.tls.context_for, nuovo)
            if ctx is not None:
                self._ssl_ctx = ctx
            else:
                log_message("Certificato TLS non rigenerato per il nuovo IP: resta il vecchio",
                            color=COLOR_ERROR)
        if self.on_local_ip_change:
            try:
                self.on_local_ip_change(nuovo)
            except Exception as e:
                log_message(f"Aggiornamento GUI dopo il cambio IP: {e}", color=COLOR_ERROR)
        return True

    async def _remote_keepalive(self) -> None:
        trascorso = 0.0
        while True:
            # Un solo ciclo: controlla spesso l'IP, rinnova UPnP/tunnel ogni
            # UPNP_KEEPALIVE_SECS o subito se l'IP è cambiato.
            passo = min(IP_CHECK_SECS, UPNP_KEEPALIVE_SECS)
            await asyncio.sleep(passo)
            trascorso += passo
            # Un'eccezione qui (router che risponde male, tunnel che non parte)
            # ucciderebbe il task in silenzio e il remoto non si ripareriebbe
            # più fino al riavvio: si registra e si riprova al giro dopo.
            try:
                cambiato = await self._refresh_local_ip()
            except Exception as e:
                cambiato = False
                log_message(f"Controllo dell'IP locale fallito: {e}", color=COLOR_ERROR)
            if not cambiato and trascorso < UPNP_KEEPALIVE_SECS:
                continue
            trascorso = 0.0
            try:
                await self._refresh_remote()
            except Exception as e:
                log_message(f"Rinnovo accesso remoto fallito: {e}", color=COLOR_ERROR)

    async def _tunnel_handler(self, websocket):
        await self.handler(websocket, via_tunnel=True)

    async def start_websocket_server(self) -> None:
        log_message("Protocolli di comunicazione inizializzati.", color=COLOR_MUTED)
        loop = asyncio.get_running_loop()
        keepalive = None
        try:
            async with contextlib.AsyncExitStack() as stack:
                avviati = 0

                async def avvia(servers) -> int:
                    """Una porta occupata ferma solo il suo server: prima
                    l'OSError smontava anche quelli già avviati e il log
                    accusava sempre la 8765."""
                    ok = 0
                    for porta, srv in servers:
                        try:
                            await stack.enter_async_context(srv)
                        except OSError as e:
                            log_message(f"ERRORE CRITICO: Porta {porta} occupata! ({e})",
                                        color=COLOR_ERROR)
                            continue
                        ok += 1
                    return ok

                # 1. Server che non hanno bisogno di TLS né di UPnP: il touchpad
                # in LAN è disponibile subito. Prima la generazione RSA (secondi
                # al primo avvio) e la discovery UPnP (fino a 2 s) venivano
                # prima e tenevano il telefono su "in attesa".
                lan = [
                    (PORT, websockets.serve(self.handler, "0.0.0.0", PORT,
                                            ping_interval=WS_PING_INTERVAL,
                                            ping_timeout=WS_PING_TIMEOUT,
                                            origins=ALLOWED_ORIGINS)),
                ]
                if self.tunnel is not None:
                    # Origine del tunnel: solo loopback, pagina + WS insieme come
                    # la 8443. Il TLS lo termina Cloudflare, qui arriva in chiaro.
                    lan.append((TUNNEL_PORT,
                        websockets.serve(self._tunnel_handler, "127.0.0.1", TUNNEL_PORT,
                                         ping_interval=WS_PING_INTERVAL,
                                         ping_timeout=WS_PING_TIMEOUT,
                                         origins=ALLOWED_ORIGINS,
                                         process_request=self.https_process_request)))
                avviati += await avvia(lan)

                # 2. Certificato (fuori dall'event loop) e server HTTPS/WSS.
                ssl_ctx = await loop.run_in_executor(NET, self.tls.context_for, self.local_ip)
                self._ssl_ctx = ssl_ctx
                if ssl_ctx:
                    # Porta unica remota: pagina + WSS su HTTPS_PORT.
                    remoti = [(HTTPS_PORT,
                        websockets.serve(self.handler, "0.0.0.0", HTTPS_PORT, ssl=ssl_ctx,
                                         ping_interval=WS_PING_INTERVAL,
                                         ping_timeout=WS_PING_TIMEOUT,
                                         origins=ALLOWED_ORIGINS,
                                         process_request=self.https_process_request)),
                        # Legacy: WSS dedicato per client pre-porta-unica ancora in giro.
                        (WSS_PORT,
                        websockets.serve(self.handler, "0.0.0.0", WSS_PORT, ssl=ssl_ctx,
                                         ping_interval=WS_PING_INTERVAL,
                                         ping_timeout=WS_PING_TIMEOUT,
                                         origins=ALLOWED_ORIGINS))]
                    avviati += await avvia(remoti)

                if avviati:
                    # 3. Strada remota, a server già in ascolto. Un errore qui non
                    # deve impedire l'avvio: il telefono in LAN funziona comunque.
                    try:
                        await self._refresh_remote(primo=True)
                    except Exception as e:
                        log_message(f"Accesso remoto non avviato: {e}", color=COLOR_ERROR)
                    keepalive = loop.create_task(self._remote_keepalive())
                    await asyncio.Future()
        except Exception as e:
            log_message(f"WebSocket Server crash: {e}", color=COLOR_ERROR)
        finally:
            if keepalive is not None:
                keepalive.cancel()
            await loop.run_in_executor(NET, self.upnp.cleanup)
            if self.tunnel is not None:
                self.tunnel.stop()

    def run(self) -> None:
        """Punto di ingresso del thread dei servizi."""
        threading.Thread(target=self.start_http_server, daemon=True).start()
        # HTTPS_PORT è gestita dal server websockets (porta unica remota):
        # niente thread HTTPS separato, il bind doppio fallirebbe.
        asyncio.run(self.start_websocket_server())
