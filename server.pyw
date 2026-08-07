"""
LIQUID CONTROL - Server Application
Author: Hapone
"""

import asyncio
import websockets
import json
import ctypes
import ipaddress
import threading
import tkinter as tk
from tkinter import messagebox
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import sys
import time
import ssl
import tempfile
import atexit
import contextlib
from http import HTTPStatus
from websockets.http11 import Response
from websockets.datastructures import Headers

from liquidmouse import events
from liquidmouse.config import Config
from liquidmouse.events import log_message
from liquidmouse.net.addresses import (
    TrustedPeer, get_local_ip, get_tailscale_ip, is_loopback,
    is_private_ip, is_tailscale_conn,
)
from liquidmouse.net.protocol import ClientConnection, dispatch
from liquidmouse.paths import BASE_DIR, ICON_PATH
from liquidmouse.ports import HTTP_PORT, HTTPS_PORT, PORT, WSS_PORT
from liquidmouse.security.auth import AUTH_MAX_FAILS, AuthGuard, pin_matches
from liquidmouse.terminal.launcher import open_pc_terminal
from liquidmouse.terminal.sessions import SessionManager
from liquidmouse.theme import (
    COLOR_ACCENT, COLOR_BG, COLOR_BORDER_GLOW, COLOR_ERROR,
    COLOR_GLASS, COLOR_MUTED, COLOR_OK, COLOR_SURFACE, COLOR_TEXT,
    COLOR_TRANSPARENT,
)
from liquidmouse.version import VERSION

# --- GESTIONE DEI MODULI E DELLE DIPENDENZE ---
try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
    import qrcode
except ImportError:
    temp_root = tk.Tk()
    temp_root.withdraw()
    messagebox.showerror("Errore Librerie", "Mancano le librerie. Esegui nel terminale:\npip install pystray Pillow qrcode")
    sys.exit(1)

# --- STATO GLOBALE ---
_config = Config()
_auth_guard = AuthGuard()
_trusted_peer = TrustedPeer()
_session_manager = SessionManager()

_ssl_context: ssl.SSLContext | None = None
_ssl_temp_files: list = []
_ssl_atexit_registered: bool = False

def load_config() -> dict:
    return _config.load()

# --- CERTIFICATO TLS AUTO-FIRMATO ---
def ensure_ssl_cert(local_ip: str) -> ssl.SSLContext | None:
    global _ssl_context, _ssl_temp_files
    if _ssl_context and _config.get('ssl_ip') == local_ip:
        return _ssl_context
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        if (_config.get('ssl_cert') and _config.get('ssl_key')
                and _config.get('ssl_ip') == local_ip):
            cert_pem = _config['ssl_cert'].encode()
            key_pem  = _config['ssl_key'].encode()
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"LiquidControl")])
            try:
                san = x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(local_ip))])
            except ValueError:
                san = x509.SubjectAlternativeName([x509.DNSName(local_ip)])
            cert = (
                x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
                .add_extension(san, critical=False)
                .sign(key, hashes.SHA256())
            )
            cert_pem = cert.public_bytes(serialization.Encoding.PEM)
            key_pem  = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()
            )
            _config['ssl_cert'] = cert_pem.decode()
            _config['ssl_key']  = key_pem.decode()
            _config['ssl_ip']   = local_ip
            _config.save()

        # Cleanup eventuali file temp residui da una precedente generazione (IP changed)
        for old_path in _ssl_temp_files:
            try:
                if os.path.exists(old_path): os.unlink(old_path)
            except Exception: pass

        cf = tempfile.NamedTemporaryFile(delete=False, suffix='.crt', mode='wb')
        cf.write(cert_pem); cf.close()
        kf = tempfile.NamedTemporaryFile(delete=False, suffix='.key', mode='wb')
        kf.write(key_pem); kf.close()
        _ssl_temp_files = [cf.name, kf.name]
        global _ssl_atexit_registered
        if not _ssl_atexit_registered:
            def _cleanup_ssl_temps():
                for p in _ssl_temp_files:
                    try:
                        if os.path.exists(p):
                            os.unlink(p)
                    except OSError:
                        pass
            atexit.register(_cleanup_ssl_temps)
            _ssl_atexit_registered = True

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cf.name, kf.name)
        _ssl_context = ctx
        return ctx
    except ImportError:
        # cryptography assente: niente TLS, quindi niente 8443/8766. L'app
        # resta usabile in LAN, ma il remoto non parte — va detto, altrimenti
        # il sintomo e' solo un "IN ATTESA" senza spiegazione.
        log_message("TLS non disponibile: manca 'cryptography'", color=COLOR_ERROR)
        return None
    except Exception as e:
        log_message(f"Certificato TLS non generato: {e}", color=COLOR_ERROR)
        return None

def init_process() -> None:
    """Impostazioni di processo Windows. Chiamata da main(), non a import time:
    importare un modulo non deve modificare lo stato del processo."""
    # Icona corretta nella taskbar (senza, Windows raggruppa sotto python.exe)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f'liquidmouse.server.{VERSION}')
    except Exception:
        pass
    # DPI scaling: senza, su schermi HiDPI la finestra esce sfocata
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def _apply_dwm_acrylic(hwnd: int) -> bool:
    """Applica DWM Acrylic/Mica backdrop su Windows 11 (build 22000+).
    Ritorna True se riuscito, False su fallback (Win10 o errore)."""
    try:
        import ctypes.wintypes
        # La finestra va marcata dark-mode PRIMA del backdrop: senza questo
        # flag DWM compone il Mica nella variante chiara (anche a tema di
        # sistema scuro) e le aree transparentcolor diventano bande bianche
        # illeggibili dietro i testi.
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # build 19041+; 19 su build precedenti
        dark = ctypes.c_int(1)
        res_dark = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))
        if res_dark != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        # Angoli arrotondati reali (Win11): sostituiscono il vecchio rounding
        # finto via transparentcolor che lasciava puntini di anti-aliasing.
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        corner = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2  # Mica (finestra principale, Win11 22H2+ build 22621)
        value = ctypes.c_int(DWMSBT_MAINWINDOW)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        return res == 0
    except Exception:
        return False

# --- SICUREZZA: WHITELIST IP ---
def reset_trusted_ip():
    _trusted_peer.reset()
    log_message("Whitelist resettata. In attesa...", color=COLOR_ACCENT)

# IP LAN: risolto una volta sola in main(). Restava una connessione UDP
# eseguita a import time, che rendeva il modulo non importabile a costo zero.
LOCAL_IP = "127.0.0.1"

# --- STATO CONNESSIONE REMOTA ---
_remote_mode    = "none"   # "upnp" | "none"
_external_ip    = None
_upnp_obj       = None
_upnp_ports     = []
_upnp_atexit_registered = False

# --- BACKEND (WebSocket & HTTP) ---
async def _authorize(websocket, client_ip: str) -> bool:
    """Applica il modello di autorizzazione. False = connessione già chiusa.

    Tre percorsi: remoto → PIN obbligatorio; loopback → sempre fidato (serve
    alla finestra terminale aperta sul PC stesso); LAN → whitelist primo
    arrivato. Tailscale conta come LAN: il tailnet è già autenticato e cifrato.
    """
    is_remote = not (is_private_ip(client_ip) or is_tailscale_conn(websocket))

    if not is_remote:
        if is_loopback(client_ip):
            log_message(f"Sessione locale: {client_ip}", color=COLOR_ACCENT)
            return True
        if not _trusted_peer.claim(client_ip):
            log_message(f"Rifiutato: {client_ip}", color=COLOR_ERROR)
            await websocket.close()
            return False
        log_message(f"Sessione attiva: {client_ip}", color=COLOR_ACCENT)
        return True

    # --- percorso remoto: autenticazione con PIN ---
    if _auth_guard.is_blocked(client_ip) or not _auth_guard.begin(client_ip):
        await websocket.send(json.dumps({"type": "auth_blocked"}))
        await websocket.close()
        log_message(f"Bloccato (brute force): {client_ip}", color=COLOR_ERROR)
        return False
    try:
        try:
            auth_raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_data = json.loads(auth_raw)
        except Exception:
            await websocket.close()
            return False
        if auth_data.get('type') != 'auth':
            await websocket.close()
            return False
        if not pin_matches(auth_data.get('pin', ''), _config.get('pin_hash', '')):
            _auth_guard.record_fail(client_ip)
            remaining = _auth_guard.remaining(client_ip)
            await websocket.send(json.dumps({
                "type": "auth_fail", "remaining": remaining
            }))
            await websocket.close()
            log_message(
                f"Auth fallita ({AUTH_MAX_FAILS - remaining}/{AUTH_MAX_FAILS}) da {client_ip}",
                color=COLOR_ERROR)
            return False
    finally:
        _auth_guard.end(client_ip)

    _auth_guard.clear(client_ip)
    await websocket.send(json.dumps({"type": "auth_ok"}))
    log_message(f"Connessione remota autorizzata: {client_ip}", color=COLOR_ACCENT)
    return True


async def handler(websocket):
    """Ciclo di vita di una connessione client."""
    client_ip = websocket.remote_address[0]
    if not await _authorize(websocket, client_ip):
        return

    ctx = ClientConnection(
        websocket, client_ip, _session_manager,
        on_session_created=_on_session_created,
    )
    try:
        async for message in websocket:
            await dispatch(ctx, message)
    except websockets.exceptions.ConnectionClosed:
        log_message("In attesa di connessione...", color=COLOR_MUTED)
    finally:
        # Senza questo, un client che si disconnette con Ctrl premuto lascia il
        # modificatore giu' sul PC. Sgancia anche le sessioni terminal, cosi'
        # una riconnessione puo' riagganciarle.
        ctx.release_all()


def _on_session_created(sid: str, client_ip: str) -> None:
    """Sessione avviata da telefono/LAN/remoto: apri la finestra reale sul PC.
    Non per il loopback, che *e'* gia' quella finestra."""
    if not is_loopback(client_ip):
        open_pc_terminal(sid)


class _QuietHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)
    def log_message(self, *args): pass

def start_http_server():
    try:
        httpd = HTTPServer(("0.0.0.0", HTTP_PORT), _QuietHTTPHandler)
        httpd.serve_forever()
    except OSError:
        log_message(f"Errore: Porta {HTTP_PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"HTTP Server crash: {e}", color=COLOR_ERROR)

# --- PORTA UNICA REMOTA (HTTPS + WSS su HTTPS_PORT) ---
# La 8443 serve sia il client statico sia il canale comandi WSS. Motivo
# (lug 2026): molti router/ISP FWA lasciano passare 8443 ma filtrano porte
# inusuali come 8766 → il client restava "IN ATTESA" con la pagina carica.
# Porta unica = un solo port-forward e un solo certificato da accettare
# (il browser NON mostra l'avviso certificato per un wss:// su porta
# diversa: fallisce in silenzio).
_STATIC_FILES = {
    "/":           ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/xterm.js":   ("xterm.js",   "application/javascript; charset=utf-8"),
    "/xterm.css":  ("xterm.css",  "text/css; charset=utf-8"),
    "/icon.ico":   ("icon.ico",   "image/x-icon"),
}

def _https_process_request(connection, request):
    """process_request del server WSS su HTTPS_PORT: le richieste senza
    Upgrade (browser che chiede la pagina) ricevono i file statici; quelle
    WebSocket proseguono con l'handshake (return None)."""
    if request.headers.get("Upgrade", ""):
        return None
    path = request.path.split("?", 1)[0]
    entry = _STATIC_FILES.get(path)
    if entry is None:
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
    fname, ctype = entry
    try:
        with open(os.path.join(BASE_DIR, fname), "rb") as fh:
            body = fh.read()
    except OSError:
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
    headers = Headers([
        ("Content-Type", ctype),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache"),
        ("Connection", "close"),
    ])
    return Response(200, "OK", headers, body)

# --- UPNP ---
def _cleanup_upnp():
    if _upnp_obj:
        for port in _upnp_ports:
            try:
                _upnp_obj.deleteportmapping(port, 'TCP')
            except Exception as e:
                try:
                    log_message(f"UPnP cleanup porta {port}: {e}", color=COLOR_MUTED)
                except Exception:
                    pass

def _setup_upnp_sync() -> str | None:
    """Blocking UPnP discovery — run via executor to avoid blocking event loop.
    Richiamabile più volte (keepalive): ricrea sempre un oggetto UPnP fresco,
    perché i router FWA possono perdere i pinhole NAT pur continuando a
    elencare i mapping (visto sul Home&Life SuperWiFi, lug 2026)."""
    global _upnp_obj, _external_ip, _upnp_atexit_registered
    try:
        import miniupnpc
        u = miniupnpc.UPnP()
        # 300ms perdeva l'IGD sui router FWA lenti a rispondere a SSDP:
        # la discovery girava "a vuoto" e il remoto risultava non disponibile
        # anche con UPnP abilitato. Gira in executor, non blocca l'avvio.
        u.discoverdelay = 2000
        if u.discover() == 0:
            return None
        u.selectigd()
        ext_ip = u.externalipaddress()
        if not ext_ip or ext_ip == '0.0.0.0':
            return None
        mapped = []
        # Porta unica remota: serve solo HTTPS_PORT (pagina + WSS insieme)
        for port in [HTTPS_PORT]:
            try:
                u.addportmapping(port, 'TCP', LOCAL_IP, port, 'LiquidControl', '')
                mapped.append(port)
            except Exception:
                pass
        if not mapped:
            # Nessuna porta aperta: dichiarare il remoto attivo sarebbe un falso positivo
            return None
        _upnp_ports[:] = mapped
        _upnp_obj = u
        _external_ip = ext_ip
        if not _upnp_atexit_registered:
            atexit.register(_cleanup_upnp)
            _upnp_atexit_registered = True
        return ext_ip
    except ImportError:
        return None
    except Exception:
        return None

async def setup_upnp() -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _setup_upnp_sync)

# --- AGGIORNAMENTO UI REMOTO ---
def _update_remote_ui():
    """Aggiorna label + QR remoto nella GUI (thread-safe via root.after).
    Priorità: Tailscale (funziona ovunque, non dipende da router/ISP) > UPnP."""
    if not _remote_status_var:
        return
    ts_ip = get_tailscale_ip()
    if ts_ip:
        label = f"VPN  {ts_ip}:{HTTP_PORT}"
        if _remote_mode == 'upnp':
            label += f"   ·   UPnP {_external_ip}:{HTTPS_PORT}"
        root.after(0, lambda: _remote_status_var.set(label))
        # Via tailnet la connessione è già cifrata/autenticata: HTTP+WS, niente
        # certificato da accettare, niente PIN (il server la classifica locale).
        root.after(0, lambda: _set_remote_qr(f"http://{ts_ip}:{HTTP_PORT}/"))
    elif _remote_mode == 'upnp':
        root.after(0, lambda: _remote_status_var.set(f"UPnP  {_external_ip}:{HTTPS_PORT}"))
        pin = _config.get('pin_plain', '')
        remote_url = f"https://{_external_ip}:{HTTPS_PORT}/?pin={pin}"
        root.after(0, lambda: _set_remote_qr(remote_url))
    else:
        root.after(0, lambda: _remote_status_var.set("Remoto non disponibile (né VPN né UPnP)"))

def _set_remote_qr(url: str) -> None:
    """Crea/aggiorna il QR per l'accesso remoto (eseguire sul thread Tk)."""
    global _remote_qr_label
    try:
        qr = qrcode.QRCode(version=1, box_size=2, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color=COLOR_TEXT, back_color=COLOR_SURFACE).convert("RGBA")
        photo = ImageTk.PhotoImage(img)
        root._remote_qr_photo = photo  # tiene il riferimento (evita GC)
        if _remote_qr_label is None:
            _remote_qr_label = tk.Label(root, image=photo, bg=COLOR_TRANSPARENT, bd=0)
            _remote_qr_label.place(x=438, y=232)
            tk.Label(root, text="SCAN REMOTO", font=("Consolas", 7),
                     bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=446, y=232 + 92)
        else:
            _remote_qr_label.config(image=photo)
    except Exception as e:
        log_message(f"QR remoto error: {e}", color=COLOR_ERROR)

async def start_websocket_server():
    global _remote_mode
    log_message("Protocolli di comunicazione inizializzati.", color=COLOR_MUTED)
    ssl_ctx = _ssl_context

    # UPnP: unica strategia remota (port-forward automatico sul router).
    ext_ip = await setup_upnp()
    if ext_ip:
        _remote_mode = 'upnp'
        log_message(f"UPnP attivo: {ext_ip}", color=COLOR_OK)
    else:
        _remote_mode = 'none'
        log_message("UPnP non riuscito: remoto non disponibile", color=COLOR_MUTED)
    _update_remote_ui()

    # Keepalive: rinnova i mapping ogni 10 min. Auto-ripara il remoto dopo
    # riavvii del router (che azzerano il NAT) e recupera i casi in cui
    # l'UPnP viene abilitato sul router a server già avviato.
    async def _upnp_keepalive():
        global _remote_mode
        while True:
            await asyncio.sleep(600)
            new_ip = await setup_upnp()
            new_mode = 'upnp' if new_ip else 'none'
            if new_mode != _remote_mode or (new_ip and new_ip != _external_ip):
                _remote_mode = new_mode
                if new_ip:
                    log_message(f"UPnP rinnovato: {new_ip}", color=COLOR_OK)
                else:
                    log_message("UPnP perso: remoto non disponibile", color=COLOR_MUTED)
                _update_remote_ui()
    asyncio.get_running_loop().create_task(_upnp_keepalive())

    servers = [
        websockets.serve(handler, "0.0.0.0", PORT, ping_interval=20, ping_timeout=10),
    ]
    if ssl_ctx:
        # Porta unica remota: pagina + WSS su HTTPS_PORT (vedi _https_process_request)
        servers.append(
            websockets.serve(handler, "0.0.0.0", HTTPS_PORT, ssl=ssl_ctx,
                             ping_interval=20, ping_timeout=10,
                             process_request=_https_process_request)
        )
        # Legacy: WSS dedicato per client pre-porta-unica ancora in giro
        servers.append(
            websockets.serve(handler, "0.0.0.0", WSS_PORT, ssl=ssl_ctx,
                             ping_interval=20, ping_timeout=10)
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
        await loop.run_in_executor(None, _cleanup_upnp)

def run_services():
    threading.Thread(target=start_http_server, daemon=True).start()
    # HTTPS_PORT è gestita dal server websockets (porta unica remota):
    # niente thread HTTPS separato, il bind doppio fallirebbe.
    ensure_ssl_cert(LOCAL_IP)
    asyncio.run(start_websocket_server())

# --- GUI & SYSTEM TRAY ---
root                = tk.Tk()
ip_label_var        = None
status_var          = None
status_label        = None
_main_canvas        = None
_remote_status_var  = None
_remote_qr_label    = None
_sessions_win       = None

def create_tray_icon():
    if os.path.exists(ICON_PATH):
        try: return Image.open(ICON_PATH)
        except Exception: pass
    image = Image.new('RGB', (64, 64), "#1A1A1A")
    dc = ImageDraw.Draw(image)
    dc.rounded_rectangle((4, 4, 60, 60), radius=12, fill="#1A1A1A", outline=COLOR_ACCENT, width=2)
    dc.ellipse((22, 22, 42, 42), fill=COLOR_ACCENT)
    return image

def minimize_to_tray():
    root.withdraw()

def restore_window(icon=None, item=None):
    root.deiconify()
    root.lift()

def terminate_application(icon=None, item=None):
    if icon: icon.stop()
    root.after(100, root.destroy)

def _get_remote_tray_label():
    ts_ip = get_tailscale_ip()
    if ts_ip:
        return f'Remoto: VPN  {ts_ip}:{HTTP_PORT}'
    if _remote_mode == 'upnp':
        return f'Remoto: UPnP  {_external_ip}:{HTTPS_PORT}'
    return 'Remoto: non disponibile'

def _open_sessions_panel(*_):
    """Pannello GUI sul PC con le sessioni terminal attive (auto-refresh 2s).
    Doppio click su una riga = (ri)apri quella sessione in una finestra sul PC."""
    global _sessions_win
    if _sessions_win is not None:
        try:
            if _sessions_win.winfo_exists():
                _sessions_win.deiconify(); _sessions_win.lift(); return
        except Exception:
            pass
    win = tk.Toplevel(root)
    win.title("Sessioni terminal")
    win.configure(bg=COLOR_GLASS)
    win.geometry("470x320")
    try: win.iconbitmap(ICON_PATH)
    except Exception: pass
    tk.Label(win, text="SESSIONI TERMINAL ATTIVE", font=("Consolas", 9, "bold"),
             bg=COLOR_GLASS, fg=COLOR_ACCENT).pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(win, text="doppio click su una sessione = aprila sul PC",
             font=("Consolas", 8), bg=COLOR_GLASS, fg=COLOR_MUTED).pack(anchor="w", padx=14, pady=(0, 6))
    txt = tk.Text(win, bg=COLOR_GLASS, fg=COLOR_TEXT, font=("Consolas", 9),
                  bd=0, highlightthickness=0, padx=10, pady=8, wrap="none", cursor="hand2")
    txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    txt.config(state="disabled")
    _sessions_win = win
    _state = {"sessions": []}

    def _refresh():
        if _sessions_win is None:
            return
        try:
            if not _sessions_win.winfo_exists():
                return
            try:
                sessions = _session_manager.list_sessions()
            except Exception:
                sessions = []
            _state["sessions"] = sessions
            txt.config(state="normal")
            txt.delete("1.0", "end")
            if not sessions:
                txt.insert("end", "(nessuna sessione attiva)\n")
            else:
                now = time.time()
                for s in sessions:
                    age = int((now - s['created_at']) / 60)
                    state = "● attiva" if s['alive'] else "○ chiusa"
                    txt.insert("end",
                        f"{state}   {s['cmd']:<16} id {s['id']}   {age}m   {s['viewers']} viewer\n")
            txt.config(state="disabled")
        except Exception:
            pass
        win.after(2000, _refresh)

    def _on_dblclick(e):
        try:
            idx = int(txt.index(f"@{e.x},{e.y}").split('.')[0]) - 1
            sessions = _state["sessions"]
            if 0 <= idx < len(sessions) and sessions[idx]['alive']:
                open_pc_terminal(sessions[idx]['id'])
        except Exception:
            pass
    txt.bind("<Double-Button-1>", _on_dblclick)

    def _on_close():
        global _sessions_win
        _sessions_win = None
        try: win.destroy()
        except Exception: pass

    win.protocol("WM_DELETE_WINDOW", _on_close)
    _refresh()

def run_tray_service():
    menu = (
        pystray.MenuItem('Apri', restore_window, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: _get_remote_tray_label(), None, enabled=False),
        pystray.MenuItem('Sessioni terminal', lambda icon, item: root.after(0, _open_sessions_panel)),
        pystray.MenuItem('Reset connessione locale', lambda icon, item: reset_trusted_ip()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci', terminate_application),
    )
    pystray.Icon("LiquidControl", create_tray_icon(), "Liquid Control", menu).run()

def setup_gui():
    global ip_label_var, status_var, status_label, _main_canvas, _remote_status_var

    root.title("Liquid Control")
    w, h = 560, 460
    sx = (root.winfo_screenwidth()  - w) // 2
    sy = (root.winfo_screenheight() - h) // 2
    root.geometry(f'{w}x{h}+{sx}+{sy}')

    root.overrideredirect(True)
    root.attributes('-alpha', 0.0)
    # Niente "-transparentcolor": finestra opaca, angoli arrotondati da DWM
    # (vedi _apply_dwm_acrylic). La trasparenza keyed lasciava puntini bianchi
    # sui bordi e "bucava" gli angoli.
    root.configure(bg=COLOR_TRANSPARENT)

    try: root.iconbitmap(ICON_PATH)
    except Exception: pass

    canvas = tk.Canvas(root, bg=COLOR_TRANSPARENT, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    _main_canvas = canvas

    # --- Forma finestra: rettangolo arrotondato ---
    def rounded_rect(c, x1, y1, x2, y2, r, **kw):
        pts = (x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r,
               x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2,
               x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r,
               x1, y1+r, x1, y1)
        return c.create_polygon(pts, smooth=True, **kw)

    PAD = 8
    # Sfondo glass: bordo glow sottile invece del bordo piatto
    rounded_rect(canvas, PAD, PAD, w-PAD, h-PAD, 22,
                 fill=COLOR_GLASS, outline=COLOR_BORDER_GLOW, width=1)
    # Striscia riflesso superiore (simulazione highlight glass)
    rounded_rect(canvas, PAD, PAD, w-PAD, PAD+3, 3,
                 fill="#FFFFFF", outline="", stipple="gray12")

    # Linea separatore dopo titolo
    sep_y = 70
    canvas.create_line(PAD+30, sep_y,        w-PAD-30, sep_y,        fill=COLOR_BORDER_GLOW, width=1)

    # Linea separatore prima sezione remota
    sep_y_remote = 215
    canvas.create_line(PAD+30, sep_y_remote, w-PAD-30, sep_y_remote, fill=COLOR_BORDER_GLOW, width=1)

    # Linea separatore sopra lo status
    sep_y2 = h - 75
    canvas.create_line(PAD+30, sep_y2,       w-PAD-30, sep_y2,       fill=COLOR_BORDER_GLOW, width=1)

    # --- Dragging finestra ---
    def get_pos(e):
        root.x_offset = e.x
        root.y_offset = e.y
    def move_window(e):
        root.geometry(f'+{e.x_root - root.x_offset}+{e.y_root - root.y_offset}')
    canvas.bind("<Button-1>", get_pos)
    canvas.bind("<B1-Motion>", move_window)

    # --- Titolo con accento colorato ---
    title_prefix = tk.Label(root, text="", font=("Consolas", 15, "bold"), bg=COLOR_TRANSPARENT, fg=COLOR_ACCENT)
    title_prefix.place(x=36, y=32)
    title_main = tk.Label(root, text="", font=("Consolas", 15, "bold"), bg=COLOR_TRANSPARENT, fg=COLOR_TEXT)
    title_main.place(x=66, y=32)

    # Badge versione (angolo in alto a destra, prima del close button)
    tk.Label(root, text=f"v{VERSION}", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=w-100, y=38)

    # --- Bottone chiudi: stile minimale con hover ---
    cx, cy = w - 36, 36
    close_bg = canvas.create_text(cx, cy, text="\u2715", font=("Consolas", 12), fill=COLOR_MUTED)
    def _close_enter(e):
        canvas.itemconfig(close_bg, fill=COLOR_ERROR)
        canvas.config(cursor="hand2")
    def _close_leave(e):
        canvas.itemconfig(close_bg, fill=COLOR_MUTED)
        canvas.config(cursor="")
    canvas.tag_bind(close_bg, "<Button-1>", lambda e: minimize_to_tray())
    canvas.tag_bind(close_bg, "<Enter>", _close_enter)
    canvas.tag_bind(close_bg, "<Leave>", _close_leave)

    # --- Sezione IP ---
    lbl_ip_header = tk.Label(root, text="", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED)
    lbl_ip_header.place(x=36, y=88)

    ip_label_var = tk.StringVar(value="")
    tk.Label(root, textvariable=ip_label_var, font=("Consolas", 18), bg=COLOR_TRANSPARENT, fg=COLOR_TEXT).place(x=36, y=112)

    # --- QR Code con sfondo arrotondato ---
    qr_url = f"http://{LOCAL_IP}:{HTTP_PORT}/?v={int(time.time())}"
    try:
        qr = qrcode.QRCode(version=1, box_size=3, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        qr_raw = qr.make_image(fill_color=COLOR_TEXT, back_color=COLOR_BG).convert("RGBA")
        # Sfondo arrotondato per il QR
        qr_w, qr_h = qr_raw.size
        pad_qr = 8
        bg_img = Image.new("RGBA", (qr_w + pad_qr*2, qr_h + pad_qr*2), COLOR_GLASS)
        mask = Image.new("L", bg_img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bg_img.size[0], bg_img.size[1]), radius=10, fill=255)
        bg_img.putalpha(mask)
        bg_img.paste(qr_raw, (pad_qr, pad_qr), qr_raw.split()[3])
        root.qr_photo = ImageTk.PhotoImage(bg_img)
        tk.Label(root, image=root.qr_photo, bg=COLOR_TRANSPARENT, bd=0).place(x=w-150, y=85)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)

    # Etichetta sotto QR
    tk.Label(root, text="SCANSIONA", font=("Consolas", 7), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=w-138, y=195)

    # --- Sezione Accesso Remoto ---
    tk.Label(root, text="ACCESSO REMOTO", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=36, y=225)
    _remote_status_var = tk.StringVar(value="Inizializzazione...")
    tk.Label(root, textvariable=_remote_status_var,
             font=("Consolas", 9), bg=COLOR_TRANSPARENT, fg=COLOR_ACCENT,
             wraplength=380, justify="left").place(x=36, y=245)

    tk.Label(root, text="PIN", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=36, y=318)
    pin_val = _config.get('pin_plain', '—')
    tk.Label(root, text=pin_val, font=("Consolas", 14, "bold"),
             bg=COLOR_TRANSPARENT, fg=COLOR_TEXT).place(x=36, y=334)

    # --- Sezione stato ---
    lbl_status_header = tk.Label(root, text="", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED)
    lbl_status_header.place(x=36, y=h-65)

    # Indicatore pallino stato
    root._status_dot = canvas.create_oval(36, h-42, 44, h-34, fill=COLOR_MUTED, outline="")

    status_var = tk.StringVar(value="")
    status_label = tk.Label(root, textvariable=status_var, font=("Consolas", 9), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED)
    status_label.place(x=52, y=h-46)

    # Bottone "Sessioni terminal" (apre il pannello GUI con le sessioni attive)
    sess_btn = canvas.create_text(w-118, h-42, text="▤ SESSIONI", anchor="w",
                                  font=("Consolas", 8), fill=COLOR_MUTED)
    def _sess_enter(e):
        canvas.itemconfig(sess_btn, fill=COLOR_ACCENT); canvas.config(cursor="hand2")
    def _sess_leave(e):
        canvas.itemconfig(sess_btn, fill=COLOR_MUTED); canvas.config(cursor="")
    canvas.tag_bind(sess_btn, "<Button-1>", lambda e: _open_sessions_panel())
    canvas.tag_bind(sess_btn, "<Enter>", _sess_enter)
    canvas.tag_bind(sess_btn, "<Leave>", _sess_leave)

    # --- Animazione typewriter ---
    def type_sequence(widgets_data, idx=0):
        if idx >= len(widgets_data): return
        target, text, speed = widgets_data[idx]
        def _type(ci=0):
            cursor = "\u2588" if ci < len(text) else ""
            display = text[:ci] + cursor
            if isinstance(target, tk.StringVar): target.set(display)
            else: target.config(text=display)
            if ci < len(text):
                root.after(speed, lambda: _type(ci + 1))
            else:
                if isinstance(target, tk.StringVar): target.set(text)
                else: target.config(text=text)
                root.after(80, lambda: type_sequence(widgets_data, idx + 1))
        _type()

    anim_data = [
        (title_prefix,      ">_",                      40),
        (title_main,        " Liquid Control",           25),
        (lbl_ip_header,     "HOST",                     15),
        (ip_label_var,      f"{LOCAL_IP}:{HTTP_PORT}",  18),
        (lbl_status_header, "STATO",                    15),
        (status_var,        "Inizializzazione...",      18),
    ]
    root.after(400, lambda: type_sequence(anim_data))

    # --- Fade-in con easing cubico (~60fps) ---
    FADE_STEPS = 45
    def ease_out_cubic(t):
        return 1.0 - (1.0 - t) ** 3

    def fade_in(step=0):
        if step <= FADE_STEPS:
            alpha = ease_out_cubic(step / FADE_STEPS)
            root.attributes('-alpha', min(alpha, 1.0))
            root.after(16, lambda: fade_in(step + 1))

    root.after(80, fade_in)
    # Applica dark-mode + angoli arrotondati DWM su Win11 (non-blocking).
    # La finestra è opaca: se DWM fallisce (Win10) resta rettangolare ma
    # perfettamente leggibile.
    def _dwm_later():
        try:
            hwnd = int(root.wm_frame(), 16)
        except Exception:
            try:
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            except Exception:
                return
        _apply_dwm_acrylic(hwnd)
    root.after(200, _dwm_later)

_DOT_MAP = {COLOR_OK: COLOR_OK, COLOR_ACCENT: COLOR_OK, COLOR_ERROR: COLOR_ERROR}

def _gui_log_sink(message, color=None):
    """Sink Tk per liquidmouse.events: mostra il messaggio nella status bar.

    Registrato in main(). Il core non conosce questa funzione, pubblica e basta;
    prima invece scriveva sui widget direttamente e legava a Tk anche i moduli
    di rete e di terminale.
    """
    if color is None:
        color = COLOR_MUTED
    def _update():
        if status_var:
            status_var.set(message)
            if status_label: status_label.config(fg=color)
        dot_color = _DOT_MAP.get(color, COLOR_MUTED)
        if _main_canvas and hasattr(root, '_status_dot'):
            try:
                _main_canvas.itemconfig(root._status_dot, fill=dot_color)
            except AttributeError:
                pass
    root.after(0, _update)


def start_background_services() -> None:
    """Avvia rete e tray. Separata da setup_gui(): finché le due cose erano
    nella stessa funzione non esisteva modo di disegnare la GUI senza aprire
    socket, né di far partire i servizi senza GUI."""
    threading.Thread(target=run_services, daemon=True).start()
    root.after(500, lambda: threading.Thread(target=run_tray_service, daemon=True).start())


def main() -> int:
    global LOCAL_IP
    init_process()
    events.subscribe(_gui_log_sink)
    LOCAL_IP = get_local_ip()
    load_config()
    setup_gui()
    start_background_services()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
