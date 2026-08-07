"""
LIQUID CONTROL - Server Application
Author: Hapone

Entrypoint. Costruisce le dipendenze, le collega e avvia GUI e servizi.
La logica vive in `liquidmouse/`; qui c'è solo il cablaggio — vedi CLAUDE.md.
"""

import ctypes
import sys
import threading

from liquidmouse import events
from liquidmouse.config import Config
from liquidmouse.events import log_message
from liquidmouse.net.addresses import TrustedPeer, get_local_ip, is_loopback
from liquidmouse.net.server import NetworkServices
from liquidmouse.net.static import StaticFiles
from liquidmouse.net.upnp import UpnpMapper
from liquidmouse.paths import BASE_DIR
from liquidmouse.security.auth import AuthGuard
from liquidmouse.security.tls import SelfSignedCert
from liquidmouse.terminal.launcher import open_pc_terminal
from liquidmouse.terminal.sessions import SessionManager
from liquidmouse.theme import COLOR_ACCENT, COLOR_ERROR
from liquidmouse.version import VERSION

# La GUI è l'unica parte che richiede pystray/PIL/qrcode: se mancano, l'errore
# va mostrato prima di qualsiasi altra cosa.
try:
    from liquidmouse.gui import window
except ImportError:
    import tkinter as tk
    from tkinter import messagebox
    temp_root = tk.Tk()
    temp_root.withdraw()
    messagebox.showerror(
        "Errore Librerie",
        "Mancano le librerie. Esegui nel terminale:\n"
        "pip install pystray Pillow qrcode")
    sys.exit(1)

# --- DIPENDENZE ---
# Costruite qui e passate a chi le usa: nessun modulo del pacchetto tiene stato
# globale proprio, ed è ciò che li rende testabili in isolamento.
_config = Config()
_auth_guard = AuthGuard()
_trusted_peer = TrustedPeer()
_session_manager = SessionManager()
_static = StaticFiles(BASE_DIR)
_tls = SelfSignedCert(_config)
_upnp = UpnpMapper()

# Costruiti in main(), quando l'IP locale è noto e la finestra esiste.
_services: NetworkServices | None = None
_root = None

LOCAL_IP = "127.0.0.1"


def load_config() -> dict:
    return _config.load()


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


def reset_trusted_ip() -> None:
    """Voce "Reset connessione locale" del menu tray: libera lo slot LAN."""
    _trusted_peer.reset()
    log_message("Whitelist resettata. In attesa...", color=COLOR_ACCENT)


def _on_session_created(sid: str, client_ip: str) -> None:
    """Sessione avviata da telefono/LAN/remoto: apri la finestra reale sul PC.
    Non per il loopback, che *è* già quella finestra."""
    if not is_loopback(client_ip):
        open_pc_terminal(sid)


def _build_services() -> NetworkServices:
    """Gli unici due punti di contatto fra rete e GUI sono l'aggiornamento del
    pannello remoto e l'apertura della finestra terminale."""
    return NetworkServices(
        config=_config,
        auth_guard=_auth_guard,
        trusted_peer=_trusted_peer,
        sessions=_session_manager,
        static=_static,
        tls=_tls,
        upnp=_upnp,
        local_ip=LOCAL_IP,
        on_remote_change=window.update_remote_ui,
        on_session_created=_on_session_created,
    )


def _build_gui_deps() -> "window.GuiDeps":
    return window.GuiDeps(
        config=_config,
        sessions=_session_manager,
        # Callable e non oggetto: NetworkServices esiste già quando la finestra
        # viene disegnata, ma passarlo per riferimento legherebbe la GUI a
        # un'istanza specifica.
        services=lambda: _services,
        local_ip=LOCAL_IP,
        reset_trusted=reset_trusted_ip,
    )


def start_background_services() -> None:
    """Avvia rete e tray. Separata dalla costruzione della finestra: finché le
    due cose stavano nella stessa funzione non esisteva modo di disegnare la GUI
    senza aprire socket, né di far partire i servizi senza GUI."""
    threading.Thread(target=_services.run, daemon=True).start()
    _root.after(500, lambda: threading.Thread(
        target=window.run_tray_service, daemon=True).start())


def main() -> int:
    global LOCAL_IP, _services, _root
    init_process()
    events.subscribe(window.gui_log_sink)
    LOCAL_IP = get_local_ip()
    load_config()
    # Asset in memoria una volta sola: sono immutabili e nel bundle PyInstaller
    # vengono estratti all'avvio. Un file mancante non è fatale ma va detto
    # subito, altrimenti il sintomo è un 404 che compare solo da remoto.
    mancanti = _static.load()
    if mancanti:
        log_message(f"Asset mancanti: {', '.join(mancanti)}", color=COLOR_ERROR)
    _services = _build_services()
    _root = window.build(_build_gui_deps())
    start_background_services()
    try:
        _root.mainloop()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
