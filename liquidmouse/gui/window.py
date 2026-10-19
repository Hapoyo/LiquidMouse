"""Finestra principale, tray e pannello sessioni — tema cyber di PiDash.

Unico modulo che disegna. La finestra è una cartella di uno schedario: la
linguetta aperta "001 liquid mouse" con il pannello sotto, la linguetta chiusa
"002 terminale" che apre il pannello delle sessioni. Dentro, pannelli
arrotondati pieni: indirizzo LAN e QR, accesso remoto, PIN, stato.

Tutto è disegnato sul canvas (testi compresi): il testo di un canvas non ha
sfondo proprio e sta sopra i pannelli colorati senza rettangoli di contorno.
Le misure sono in pixel a 96 dpi e passano da `_px`, così su uno schermo HiDPI
finestra e font crescono insieme invece di sovrapporsi.

Le dipendenze verso il core arrivano da `GuiDeps`, riempito da `build()`. Non
sono import diretti dell'entrypoint perche' sarebbe una dipendenza circolare:
server.pyw importa questo modulo, non il contrario.
"""

import ctypes
import ipaddress
import os
import re
import time
import tkinter as tk
from dataclasses import dataclass

import pystray
import qrcode
from PIL import Image, ImageDraw, ImageTk

from liquidmouse.config import LAN_REQUIRE_PIN_DEFAULT
from liquidmouse.events import log_message
from liquidmouse.gui.effects import apply_dwm_style, load_private_fonts
from liquidmouse.net.addresses import is_loopback
from liquidmouse.paths import BASE_DIR, ICON_PATH
from liquidmouse.ports import HTTP_PORT
from liquidmouse.terminal.launcher import open_pc_terminal
from liquidmouse.theme import (
    COLOR_ACCENT, COLOR_AMBER, COLOR_BG, COLOR_BORDER, COLOR_CREAM,
    COLOR_ERROR, COLOR_INK, COLOR_MUTED, COLOR_OK, COLOR_ORANGE, COLOR_PANEL,
    COLOR_TEXT, FONT_FILES, FONT_LABEL, FONT_LABEL_FALLBACK, FONT_NUM,
    FONT_NUM_FALLBACK,
)
from liquidmouse.version import CODENAME, VERSION


class GuiDeps:
    """Cio' di cui la GUI ha bisogno dal resto dell'applicazione.

    `services` e' un callable e non un oggetto perche' NetworkServices viene
    costruito dopo la GUI: al momento di disegnare non esiste ancora.
    """

    def __init__(self, *, config, sessions, services, local_ip, reset_trusted,
                 regenerate_pin=None):
        self.config = config
        self.sessions = sessions
        self.services = services
        self.local_ip = local_ip
        self.reset_trusted = reset_trusted
        # Callable senza argomenti: genera un PIN nuovo, lo salva cifrato e
        # chiude le sessioni remote. None = voce del tray che non fa nulla.
        self.regenerate_pin = regenerate_pin


class _CanvasText:
    """Testo del canvas con l'interfaccia di StringVar + Label usata qui.

    `set` come una StringVar, `config(text=, fg=)` come un Label: così il sink
    di log, l'animazione di avvio e il pannello remoto non devono sapere che
    sotto c'è un elemento del canvas.
    """

    def __init__(self, canvas, item) -> None:
        self._canvas = canvas
        self._item = item

    def set(self, text: str) -> None:
        self._canvas.itemconfig(self._item, text=text)

    def set_font(self, font) -> None:
        self._canvas.itemconfig(self._item, font=font)

    def config(self, text: str | None = None, fg: str | None = None) -> None:
        opts = {}
        if text is not None:
            opts["text"] = text
        if fg is not None:
            opts["fill"] = fg
        if opts:
            self._canvas.itemconfig(self._item, **opts)


_deps: GuiDeps | None = None


# --- STATO DEI WIDGET ---
# root e' creato in build(), non qui: importare questo modulo non deve aprire
# una finestra.
root                = None
ip_label_var        = None
status_var          = None
status_label        = None
_main_canvas        = None
_status_dot         = None
_remote_status_var  = None
_remote_status_label = None
_remote_title_var   = None   # "remoto // upnp" o "remoto // tunnel"
_remote_qr_item     = None
_remote_qr_box      = None   # (x, y, lato) dell'area del QR remoto
_lan_qr_item        = None   # immagine del QR LAN, rifatta se cambia l'IP
_lan_qr_box         = None   # (x, y, lato) dell'immagine del QR LAN
_lan_ip_max_w       = 0      # larghezza massima dell'indirizzo LAN, per il font
_lan_hint_var       = None   # riga sotto l'indirizzo LAN ("apri dal telefono...")
_sessions_win       = None
_remote_qr_hint     = None   # testo sotto il QR remoto ("in attesa" / "nascosto")
_remote_snapshot    = None   # (modo, endpoint, motivo) dell'ultimo update_remote_ui
_pin_var            = None   # valore del PIN, mascherato finché non si mostra
_pin_max_w          = 0
_pin_btn_text       = None   # etichetta del pulsante "mostra per 30 s"
_reveal_until       = 0.0    # time.monotonic() fino a cui i segreti sono in chiaro
_reveal_job         = None   # id del timer che li rimaschera

# Scala del disegno rispetto a 96 dpi e famiglie di font effettive (quelle del
# tema se caricate, altrimenti i ripieghi). Fissate in build().
_scale = 1.0
_font_num = FONT_NUM_FALLBACK
_font_label = FONT_LABEL_FALLBACK


def _px(n: float) -> int:
    """Misura in pixel a 96 dpi → pixel reali."""
    return max(1, round(n * _scale))


def _f_label(size: int = 12, bold: bool = False) -> tuple:
    # Dimensione negativa = pixel: il layout è in pixel, i font devono seguire
    # la stessa unità (in punti crescerebbero da soli con i dpi).
    return (_font_label, -_px(size), "bold") if bold else (_font_label, -_px(size))


def _f_num(size: int) -> tuple:
    return (_font_num, -_px(size))


def create_tray_icon():
    if os.path.exists(ICON_PATH):
        try: return Image.open(ICON_PATH)
        except Exception: pass
    image = Image.new('RGB', (64, 64), COLOR_BG)
    dc = ImageDraw.Draw(image)
    dc.rounded_rectangle((4, 4, 60, 60), radius=12, fill=COLOR_PANEL, outline=COLOR_CREAM, width=2)
    dc.ellipse((22, 22, 42, 42), fill=COLOR_ORANGE)
    return image

def minimize_to_tray():
    root.withdraw()

def restore_window(icon=None, item=None):
    root.deiconify()
    root.lift()

def terminate_application(icon=None, item=None):
    if icon: icon.stop()
    root.after(100, root.destroy)

# --- ACCESSO REMOTO: ETICHETTA E QR ---
# Due strade, con il PIN nel QR in entrambe. UPnP: il router apre una porta
# pubblica (la 8443 o una di riserva) verso la 8443 del PC; certificato
# self-signed, quindi al primo accesso il browser mostra l'avviso. Tunnel
# Cloudflare, quando UPnP non può funzionare (CGNAT): indirizzo
# *.trycloudflare.com con certificato valido, diverso a ogni avvio.

def _remote_endpoint() -> tuple[str, str] | None:
    """(etichetta, url del QR) per l'accesso remoto, None se non disponibile.

    Unico punto in cui si costruisce l'endpoint remoto: prima la stessa logica
    era scritta due volte, nel pannello e nell'etichetta del tray, e le due
    potevano divergere.
    """
    servizi = _deps.services()
    if servizi is None:
        return None
    pin = _deps.config.get('pin_plain', '')
    if servizi.remote_mode == 'upnp':
        external_ip = servizi.external_ip
        porta = servizi.external_port
        return (f"UPnP  {external_ip}:{porta}",
                f"https://{external_ip}:{porta}/#pin={pin}")
    if servizi.remote_mode == 'tunnel' and servizi.tunnel_url:
        url = servizi.tunnel_url
        return (f"Tunnel  {url.removeprefix('https://')}", f"{url}/#pin={pin}")
    return None


def _get_remote_tray_label():
    endpoint = _remote_endpoint()
    # Il menu del tray si legge anche con la finestra mascherata: stessa regola.
    return (f'Remoto: {_visible_text(endpoint[0])}' if endpoint
            else 'Remoto: non disponibile')


# --- SEGRETI MASCHERATI ---
# PIN, QR remoto, IP esterno e indirizzo del tunnel stanno in chiaro solo per
# SHOW_SECS dopo "mostra": la finestra si fotografa, si condivide in una call,
# si lascia aperta su un PC altrui, e un QR remoto contiene il PIN. Il QR LAN
# senza PIN non è un segreto e resta sempre visibile.
SHOW_SECS = 30
MASK_CHAR = "•"
MASK_IP = "•••.•••.•••.•••"
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TUNNEL_SUB = re.compile(r"[a-z0-9-]+(?=\.trycloudflare\.com)", re.IGNORECASE)


# Reti locali vere (RFC 1918 e link-local). Non `is_private_ip`/`is_private` di
# ipaddress: includono anche gli intervalli di documentazione (203.0.113.0/24
# ecc.), che negli esempi e nelle anteprime stanno al posto di IP pubblici.
_LAN_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"))


def _is_lan_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return is_loopback(ip) or any(addr in n for n in _LAN_NETS)


def mask_sensitive(testo: str) -> str:
    """Nasconde IP pubblici/CGNAT e il nome del tunnel in un testo.

    Gli indirizzi LAN e il loopback restano: non dicono nulla di utile a chi
    guarda lo schermo da fuori, e senza di essi il log ("Sessione attiva: ...")
    perderebbe senso. L'IP esterno e il range 100.64/10 (CGNAT) sì: identificano
    la linea dell'utente.
    """
    def _ip(m):
        ip = m.group(0)
        return ip if _is_lan_ip(ip) else MASK_IP
    return _TUNNEL_SUB.sub(MASK_CHAR * 3, _IPV4.sub(_ip, testo))


def secrets_visible() -> bool:
    return time.monotonic() < _reveal_until


def _visible_text(testo: str) -> str:
    return testo if secrets_visible() else mask_sensitive(testo)


def _set_reveal(on: bool) -> None:
    """Mostra i segreti per SHOW_SECS (o li nasconde subito) e ridisegna.

    Da eseguire sul thread Tk. Ogni "mostra" riparte da 30 s e sostituisce il
    timer precedente, altrimenti il vecchio rimaschererebbe prima del tempo.
    """
    global _reveal_until, _reveal_job
    if _reveal_job is not None:
        try:
            root.after_cancel(_reveal_job)
        except Exception:
            pass
        _reveal_job = None
    _reveal_until = time.monotonic() + SHOW_SECS if on else 0.0
    if on:
        _reveal_job = root.after(SHOW_SECS * 1000, lambda: _set_reveal(False))
    _refresh_secrets()


def toggle_reveal(*_) -> None:
    """Pulsante "mostra per 30 s" (e clic sul QR remoto): mostra o nasconde."""
    _set_reveal(not secrets_visible())


def _masked_pin(pin: str) -> str:
    return pin if secrets_visible() else MASK_CHAR * len(pin)


def _refresh_secrets() -> None:
    """Ridisegna tutto ciò che dipende dalla visibilità (thread Tk)."""
    visibile = secrets_visible()
    if _pin_var is not None and _deps is not None:
        testo = _masked_pin(_deps.config.get('pin_plain', '—'))
        _pin_var.set(testo)
        try:
            _pin_var.set_font(_fit_num(testo, _pin_max_w, 30, 12))
        except Exception:
            pass
    if _pin_btn_text is not None:
        _pin_btn_text.set("nascondi" if visibile else f"mostra per {SHOW_SECS} s")
    _render_remote()
    if root is not None and ip_label_var is not None and _deps is not None:
        _set_lan_ui(_deps.local_ip)


def regenerate_pin(icon=None, item=None) -> None:
    """Voce del tray "rigenera pin": PIN nuovo, QR nuovi, sessioni remote chiuse.

    Il lavoro vero (config, DPAPI, chiusura dei socket) è del core, passato in
    `GuiDeps.regenerate_pin`; qui si ridisegna. Il vecchio QR smette di valere
    perché porta il vecchio PIN.
    """
    if _deps is None or _deps.regenerate_pin is None:
        return
    try:
        _deps.regenerate_pin()
    except Exception as e:
        log_message(f"PIN non rigenerato: {e}", color=COLOR_ERROR)
        return
    if root is not None:
        update_remote_ui()
        root.after(0, _refresh_secrets)


# Il pannello "remoto" ha un'altezza fissa: un motivo di errore lungo (es. il
# testo di un'eccezione dal mapping UPnP) andrebbe su troppe righe e uscirebbe
# dal pannello. Il log tiene il messaggio integrale; qui va troncato.
REMOTE_LABEL_MAX = 55


def _troncato(testo: str, max_len: int = REMOTE_LABEL_MAX) -> str:
    return testo if len(testo) <= max_len else testo[:max_len - 1].rstrip() + "…"


def update_remote_ui():
    """Aggiorna etichetta, colore e QR remoto nella GUI.

    Chiamata dal thread dei servizi di rete, quindi ogni tocco ai widget passa
    da root.after.
    """
    global _remote_snapshot
    if not _remote_status_var:
        return
    servizi = _deps.services()
    modo = servizi.remote_mode if servizi is not None else 'none'
    endpoint = _remote_endpoint()
    motivo = servizi.remote_problem if servizi and endpoint is None else None
    # Fotografia dello stato di rete: la maschera si applica poi sul thread Tk,
    # in `_render_remote`, perché dipende dal "mostra" premuto in quel momento.
    _remote_snapshot = (modo, endpoint, motivo)
    root.after(0, _render_remote)


def _render_remote() -> None:
    """Disegna pannello e QR remoto dall'ultima fotografia (thread Tk)."""
    if not _remote_status_var or _remote_snapshot is None:
        return
    modo, endpoint, motivo = _remote_snapshot
    if _remote_title_var is not None:
        _remote_title_var.set("remoto // tunnel" if modo == 'tunnel' else "remoto // upnp")
    if endpoint is None:
        etichetta = (f"Remoto non disponibile: {_troncato(_visible_text(motivo))}"
                     if motivo else "Remoto non disponibile")
        # COLOR_MUTED, non COLOR_ERROR: UPnP non ancora riuscito e' uno stato
        # di attesa normale (il keepalive riprova ogni 10 minuti), non un
        # guasto da segnalare in rosso.
        _set_remote_label(etichetta, COLOR_MUTED)
        # Un QR rimasto da un mapping perso manderebbe il telefono su una
        # porta ormai chiusa.
        _clear_remote_qr(HINT_IN_ATTESA)
        return
    etichetta, url = endpoint
    _set_remote_label(_visible_text(etichetta), COLOR_OK)
    if secrets_visible():
        _set_remote_qr(url)
    else:
        # Il QR remoto contiene il PIN: nascosto finché non si preme "mostra".
        _clear_remote_qr(HINT_NASCOSTO)


def update_lan_ui(ip: str) -> None:
    """L'IP LAN è cambiato: aggiorna indirizzo e QR della finestra.

    Chiamata dal thread dei servizi di rete (sink di NetworkServices), quindi il
    disegno passa da root.after. Prima il QR LAN era calcolato una volta sola
    in setup_gui e dopo un cambio di rete puntava a un indirizzo che non c'era più.
    """
    if _deps is not None:
        _deps.local_ip = ip
    if root is None or ip_label_var is None:
        return
    root.after(0, lambda: _set_lan_ui(ip))


def _set_lan_ui(ip: str) -> None:
    """Ridisegna indirizzo, suggerimento e QR LAN (eseguire sul thread Tk)."""
    ip_testo = f"{ip}:{HTTP_PORT}"
    try:
        if _lan_hint_var is not None:
            _lan_hint_var.set(LAN_HINT_PIN if lan_require_pin() else LAN_HINT)
        ip_label_var.set(ip_testo)
        ip_label_var.set_font(_fit_num(ip_testo, _lan_ip_max_w, 44, 20))
    except Exception as e:
        log_message(f"Indirizzo LAN non aggiornato: {e}", color=COLOR_ERROR)
    if _main_canvas is None or _lan_qr_item is None or _lan_qr_box is None:
        return
    try:
        x, y, lato = _lan_qr_box
        photo = ImageTk.PhotoImage(_qr_image(_lan_qr_url(ip), lato, COLOR_INK, COLOR_CREAM))
        root.qr_photo = photo   # tiene il riferimento (evita GC)
        _main_canvas.itemconfig(_lan_qr_item, image=photo)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)


LAN_HINT = "apri dal telefono sulla stessa wi-fi"
LAN_HINT_PIN = "stessa wi-fi, serve il pin"


def lan_require_pin() -> bool:
    """True se l'opzione `lan_require_pin` della config è accesa."""
    return bool(_deps is not None
                and _deps.config.get('lan_require_pin', LAN_REQUIRE_PIN_DEFAULT))


def _lan_qr_url(ip: str) -> str:
    # Il parametro v cambia a ogni disegno: il telefono non riusa una pagina in cache.
    url = f"http://{ip}:{HTTP_PORT}/?v={int(time.time())}"
    if lan_require_pin() and secrets_visible():
        # Come il QR remoto: il client legge #pin= e lo manda all'handshake.
        # Solo mentre i segreti sono mostrati; altrimenti il QR apre la pagina
        # e il telefono chiede il PIN (che sta nel riquadro, dietro "mostra").
        url += f"#pin={_deps.config.get('pin_plain', '')}"
    return url


def toggle_lan_require_pin(icon=None, item=None) -> None:
    """Voce del tray: accende/spegne il PIN anche dalla LAN.

    Vale dalle connessioni successive (il server legge l'opzione a ogni
    handshake); chi è già dentro resta collegato fino alla disconnessione.
    Lo stato è nella config, quindi sopravvive al riavvio.
    """
    nuovo = not lan_require_pin()
    _deps.config['lan_require_pin'] = nuovo
    _deps.config.save()
    log_message("PIN richiesto anche dalla LAN" if nuovo
                else "LAN senza PIN (primo dispositivo che si collega)",
                color=COLOR_ACCENT)
    if root is not None and ip_label_var is not None:
        root.after(0, lambda: _set_lan_ui(_deps.local_ip))


def _set_remote_label(testo: str, colore: str) -> None:
    """Aggiorna testo e colore del pannello remoto (eseguire sul thread Tk)."""
    _remote_status_var.set(testo)
    if _remote_status_label is not None:
        _remote_status_label.config(fg=colore)


def _qr_image(url: str, lato: int, fill: str, back: str):
    """QR di `url` grande al massimo `lato` pixel, moduli interi (nitido).

    Bordo di un solo modulo: il QR sta su un pannello dello stesso colore del
    fondo del codice, che fa già da zona di rispetto.
    """
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    moduli = qr.modules_count + 2
    qr.box_size = max(1, lato // moduli)
    return qr.make_image(fill_color=fill, back_color=back).convert("RGB")


def _set_remote_qr(url: str) -> None:
    """Crea/aggiorna il QR per l'accesso remoto (eseguire sul thread Tk)."""
    global _remote_qr_item
    if _main_canvas is None or _remote_qr_box is None:
        return
    try:
        x, y, lato = _remote_qr_box
        photo = ImageTk.PhotoImage(_qr_image(url, lato, COLOR_INK, COLOR_CREAM))
        root._remote_qr_photo = photo  # tiene il riferimento (evita GC)
        if _remote_qr_item is None:
            _remote_qr_item = _main_canvas.create_image(
                x + lato // 2, y + lato // 2, image=photo)
            # Un clic sul QR lo rimaschera subito.
            _main_canvas.tag_bind(_remote_qr_item, "<Button-1>", toggle_reveal)
        else:
            _main_canvas.itemconfig(_remote_qr_item, image=photo, state="normal")
    except Exception as e:
        log_message(f"QR remoto error: {e}", color=COLOR_ERROR)


HINT_IN_ATTESA = "qr\nin attesa"
HINT_NASCOSTO = "qr\nnascosto"


def _clear_remote_qr(hint: str = HINT_IN_ATTESA) -> None:
    if _main_canvas is not None and _remote_qr_item is not None:
        _main_canvas.itemconfig(_remote_qr_item, state="hidden")
    if _remote_qr_hint is not None:
        _remote_qr_hint.set(hint)


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
    win.title("Liquid Mouse — sessioni terminale")
    win.configure(bg=COLOR_BG)
    win.geometry(f"{_px(500)}x{_px(320)}")
    try: win.iconbitmap(ICON_PATH)
    except Exception: pass
    tk.Label(win, text="002  sessioni terminale", font=_f_label(12, bold=True),
             bg=COLOR_BG, fg=COLOR_TEXT).pack(anchor="w", padx=_px(14), pady=(_px(12), _px(2)))
    tk.Label(win, text="doppio click su una sessione = aprila sul pc",
             font=_f_label(11), bg=COLOR_BG, fg=COLOR_MUTED).pack(anchor="w", padx=_px(14), pady=(0, _px(8)))
    txt = tk.Text(win, bg=COLOR_PANEL, fg=COLOR_TEXT, font=_f_label(12),
                  bd=0, highlightthickness=1, highlightbackground=COLOR_BORDER,
                  highlightcolor=COLOR_BORDER, padx=_px(10), pady=_px(8),
                  wrap="none", cursor="hand2", selectbackground=COLOR_AMBER,
                  selectforeground=COLOR_INK)
    txt.pack(fill="both", expand=True, padx=_px(12), pady=(0, _px(12)))
    txt.tag_configure("attiva", foreground=COLOR_OK)
    txt.tag_configure("chiusa", foreground=COLOR_MUTED)
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
                sessions = _deps.sessions.list_sessions()
            except Exception:
                sessions = []
            _state["sessions"] = sessions
            txt.config(state="normal")
            txt.delete("1.0", "end")
            if not sessions:
                txt.insert("end", "nessuna sessione attiva\n", "chiusa")
            else:
                now = time.time()
                for s in sessions:
                    age = int((now - s['created_at']) / 60)
                    if s['alive']:
                        txt.insert("end", "● attiva  ", "attiva")
                    else:
                        txt.insert("end", "○ chiusa  ", "chiusa")
                    txt.insert("end",
                        f"{s['cmd']:<16} id {s['id']}   {age}m   {s['viewers']} viewer\n")
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
        pystray.MenuItem('Reset connessione locale', lambda icon, item: _deps.reset_trusted()),
        pystray.MenuItem('PIN anche dalla LAN', toggle_lan_require_pin,
                         checked=lambda item: lan_require_pin()),
        pystray.MenuItem('Rigenera PIN', regenerate_pin),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci', terminate_application),
    )
    pystray.Icon("LiquidMouse", create_tray_icon(), "Liquid Mouse", menu).run()


# --- DISEGNO ---

def _smooth_poly(c, corners, radii, **kw):
    """Poligono con angoli arrotondati (raggio per angolo, 0 = spigolo vivo).

    Tk non ha rettangoli arrotondati: con smooth=True i vertici diventano punti
    di controllo di una spline, e un punto ripetuto obbliga la curva a passarci.
    Per ogni angolo si mettono due punti doppi a distanza r lungo i lati e
    l'angolo stesso una volta sola: lati dritti, angoli raccordati.
    """
    pts = []
    n = len(corners)
    for i, (x, y) in enumerate(corners):
        r = radii[i]
        if r <= 0:
            pts += [x, y, x, y, x, y]
            continue
        px_, py_ = corners[i - 1]
        nx, ny = corners[(i + 1) % n]

        def verso(ax, ay, r=r, x=x, y=y):
            dx, dy = ax - x, ay - y
            lung = max(1e-6, (dx * dx + dy * dy) ** 0.5)
            return x + dx / lung * r, y + dy / lung * r

        a = verso(px_, py_)
        b = verso(nx, ny)
        pts += [*a, *a, x, y, *b, *b]
    return c.create_polygon(pts, smooth=True, **kw)


def _panel(c, x1, y1, x2, y2, fill, outline=None, r=10):
    r = _px(r)
    return _smooth_poly(c, [(x1, y1), (x2, y1), (x2, y2), (x1, y2)], [r] * 4,
                        fill=fill, outline=outline or fill, width=_px(1))


def _text(c, x, y, text="", font=None, fill=COLOR_TEXT, anchor="nw", **kw) -> _CanvasText:
    item = c.create_text(x, y, text=text, font=font or _f_label(), fill=fill,
                         anchor=anchor, **kw)
    return _CanvasText(c, item)


def _fit_num(text: str, max_w: int, max_px: int, min_px: int = 12) -> tuple:
    """Font numerico più grande (in pixel a 96 dpi) con cui `text` sta in max_w."""
    for size in range(max_px, min_px - 1, -1):
        font = _f_num(size)
        if int(root.tk.call("font", "measure", font, text)) <= max_w:
            return font
    return _f_num(min_px)


def _scegli_font() -> None:
    """Famiglie effettive: quelle del tema se Tk le vede, altrimenti ripiego."""
    global _font_num, _font_label
    try:
        famiglie = set(root.tk.call("font", "families"))
    except Exception:
        famiglie = set()
    _font_num = FONT_NUM if FONT_NUM in famiglie else FONT_NUM_FALLBACK
    _font_label = FONT_LABEL if FONT_LABEL in famiglie else FONT_LABEL_FALLBACK


@dataclass(frozen=True)
class _Layout:
    """Misure della finestra in pixel reali (già passate da `_px`).

    Calcolate una volta sola e passate alle funzioni di disegno: prima erano
    variabili locali di un'unica funzione da 200 righe, e ogni pezzo dipendeva
    da quelle dei pezzi sopra.
    """
    w: int          # larghezza e altezza della finestra
    h: int
    m: int          # bordo della finestra
    top: int        # bordo superiore della cartella (sotto le linguette)
    tab_r: int      # fine della linguetta aperta
    tab_mid: int    # asse verticale del testo delle linguette
    left: int       # margini interni della cartella
    right: int
    gap: int
    y0: int         # prima riga dell'host LAN
    qr_side: int    # lato del pannello del QR LAN
    qx1: int        # angolo in alto a sinistra del pannello del QR LAN
    qy1: int
    ry1: int        # fila dei pannelli remoto / PIN
    ry2: int
    pin_l: int      # bordo sinistro del pannello del PIN
    sy1: int        # pannello di stato
    sy2: int


def _make_layout() -> _Layout:
    """Calcola le misure. Richiede `_scale` già fissata (vedi `_init_scale_and_fonts`)."""
    P = _px
    w, h = P(560), P(460)
    m, tab_h = P(8), P(24)
    left, right = P(24), w - P(24)
    gap = P(10)
    top = m + tab_h
    y0 = top + P(14)
    qr_side = P(116)
    qx1, qy1 = right - qr_side, y0 + P(24)
    ry1 = qy1 + qr_side + P(16) + gap * 2
    ry2 = ry1 + P(128)
    return _Layout(w=w, h=h, m=m, top=top, tab_r=P(270), tab_mid=m + tab_h // 2,
                   left=left, right=right, gap=gap, y0=y0, qr_side=qr_side,
                   qx1=qx1, qy1=qy1, ry1=ry1, ry2=ry2, pin_l=right - P(150),
                   sy1=ry2 + gap, sy2=h - m - P(16))


def _init_scale_and_fonts() -> None:
    global _scale
    try:
        _scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:
        _scale = 1.0
    _scegli_font()


def _configure_window(lay: _Layout) -> None:
    w, h = lay.w, lay.h
    sx = (root.winfo_screenwidth()  - w) // 2
    sy = (root.winfo_screenheight() - h) // 2
    root.geometry(f'{w}x{h}+{sx}+{sy}')

    root.overrideredirect(True)
    root.attributes('-alpha', 0.0)
    # Finestra opaca, angoli arrotondati da DWM (vedi apply_dwm_style). La
    # vecchia trasparenza keyed lasciava puntini bianchi sui bordi.
    root.configure(bg=COLOR_BG)

    try: root.iconbitmap(ICON_PATH)
    except Exception: pass


def _draw_tabs(c, lay: _Layout) -> tuple[_CanvasText, _CanvasText]:
    """Cartella dello schedario, linguette e pulsante di chiusura.

    Ritorna i due testi della linguetta aperta (numero e titolo), che
    l'animazione d'avvio scrive carattere per carattere.
    """
    P = _px
    M, top, tab_r, tab_mid, w = lay.m, lay.top, lay.tab_r, lay.tab_mid, lay.w
    _smooth_poly(c, [(M, M), (tab_r, M), (tab_r, top), (w - M, top),
                     (w - M, lay.h - M), (M, lay.h - M)],
                 [P(8), P(8), P(4), P(10), P(10), P(10)],
                 fill=COLOR_PANEL, outline=COLOR_CREAM, width=P(1))
    tab_num = _text(c, M + P(10), tab_mid, "", _f_label(12), COLOR_TEXT, "w")
    tab_title = _text(c, tab_r - P(12), tab_mid, "", _f_label(12, bold=True), COLOR_TEXT, "e")

    # Linguetta chiusa "002 terminale": crema, testo scuro, apre le sessioni.
    t2_l, t2_r = tab_r + P(6), w - P(44)
    tab2 = _smooth_poly(c, [(t2_l, M), (t2_r, M), (t2_r, top - P(3)), (t2_l, top - P(3))],
                        [P(8), P(8), 0, 0], fill=COLOR_CREAM, outline=COLOR_CREAM, width=P(1))
    tab2_num = c.create_text(t2_l + P(10), tab_mid - P(1), text="002", anchor="w",
                             font=_f_label(12), fill=COLOR_INK)
    tab2_txt = c.create_text(t2_r - P(10), tab_mid - P(1), text="terminale", anchor="e",
                             font=_f_label(12), fill=COLOR_INK)

    def _tab2_hover(on):
        colore = COLOR_AMBER if on else COLOR_CREAM
        c.itemconfig(tab2, fill=colore, outline=colore)
        c.config(cursor="hand2" if on else "")
    for item in (tab2, tab2_num, tab2_txt):
        c.tag_bind(item, "<Button-1>", lambda e: _open_sessions_panel())
        c.tag_bind(item, "<Enter>", lambda e: _tab2_hover(True))
        c.tag_bind(item, "<Leave>", lambda e: _tab2_hover(False))

    # Chiudi (riduce nella tray)
    close = c.create_text(w - P(22), tab_mid, text="×", font=_f_label(18), fill=COLOR_MUTED)
    def _close_hover(on):
        c.itemconfig(close, fill=COLOR_ERROR if on else COLOR_MUTED)
        c.config(cursor="hand2" if on else "")
    c.tag_bind(close, "<Button-1>", lambda e: minimize_to_tray())
    c.tag_bind(close, "<Enter>", lambda e: _close_hover(True))
    c.tag_bind(close, "<Leave>", lambda e: _close_hover(False))
    return tab_num, tab_title


def _bind_window_drag(c) -> None:
    """Trascinare il canvas sposta la finestra (senza barra del titolo)."""
    def get_pos(e):
        root.x_offset = e.x
        root.y_offset = e.y
    def move_window(e):
        root.geometry(f'+{e.x_root - root.x_offset}+{e.y_root - root.y_offset}')
    c.bind("<Button-1>", get_pos)
    c.bind("<B1-Motion>", move_window)


def _draw_lan_panel(c, lay: _Layout) -> tuple[_CanvasText, str]:
    """Host LAN: etichetta, indirizzo grande, QR su pannello crema.

    Ritorna l'etichetta "host" e il testo dell'indirizzo, per l'animazione.
    """
    global ip_label_var, _lan_qr_item, _lan_qr_box, _lan_ip_max_w, _lan_hint_var
    P = _px
    L, R, GAP, y0 = lay.left, lay.right, lay.gap, lay.y0
    qr_side, qx1, qy1 = lay.qr_side, lay.qx1, lay.qy1
    lbl_host = _text(c, L, y0, "", _f_label(12), COLOR_MUTED)
    _text(c, R - P(130), y0, f"v{VERSION} «{CODENAME.lower()}»", _f_label(11), COLOR_MUTED, "ne")

    _panel(c, qx1, qy1, R, qy1 + qr_side + P(16), COLOR_CREAM)
    qr_url = _lan_qr_url(_deps.local_ip)
    try:
        lato = qr_side - P(16)
        root.qr_photo = ImageTk.PhotoImage(_qr_image(qr_url, lato, COLOR_INK, COLOR_CREAM))
        _lan_qr_item = c.create_image(qx1 + qr_side // 2, qy1 + P(8) + lato // 2,
                                      image=root.qr_photo)
        _lan_qr_box = (qx1 + P(8), qy1 + P(8), lato)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)
    c.create_text(qx1 + qr_side // 2, qy1 + qr_side + P(6), text="scan lan",
                  font=_f_label(11), fill=COLOR_INK)

    ip_testo = f"{_deps.local_ip}:{HTTP_PORT}"
    _lan_ip_max_w = qx1 - L - GAP * 2
    ip_label_var = _text(c, L - P(2), y0 + P(78), "",
                         _fit_num(ip_testo, _lan_ip_max_w, 44, 20), COLOR_TEXT, "sw")
    _lan_hint_var = _text(c, L, y0 + P(90),
                          LAN_HINT_PIN if lan_require_pin() else LAN_HINT,
                          _f_label(11), COLOR_MUTED)
    # Barra arancio come la barra della giornata di PiDash: separa l'host
    # dalla fila dei pannelli.
    bar_y = y0 + P(122)
    _panel(c, L, bar_y, qx1 - GAP * 2, bar_y + P(6), COLOR_ORANGE, r=3)
    return lbl_host, ip_testo


def _draw_remote_panel(c, lay: _Layout) -> None:
    """Pannello scuro dell'accesso remoto: titolo, stato e QR in attesa."""
    global _remote_status_var, _remote_status_label, _remote_title_var, _remote_qr_box
    global _remote_qr_hint
    P = _px
    L, GAP, ry1, ry2, pin_l = lay.left, lay.gap, lay.ry1, lay.ry2, lay.pin_l
    _panel(c, L, ry1, pin_l - GAP, ry2, COLOR_BG, COLOR_BORDER)
    _remote_title_var = _text(c, L + P(12), ry1 + P(10), "remoto // upnp",
                              _f_label(12), COLOR_MUTED)
    rqr = P(88)
    _remote_qr_box = (pin_l - GAP - P(12) - rqr, ry1 + (ry2 - ry1 - rqr) // 2, rqr)
    # Crema come il QR LAN; finché UPnP non risponde mostra "qr in attesa".
    _panel(c, _remote_qr_box[0] - P(6), _remote_qr_box[1] - P(6),
           _remote_qr_box[0] + rqr + P(6), _remote_qr_box[1] + rqr + P(6),
           COLOR_CREAM, r=8)
    _remote_qr_hint = _text(c, _remote_qr_box[0] + rqr // 2, _remote_qr_box[1] + rqr // 2,
                            HINT_IN_ATTESA, _f_label(11), COLOR_INK, "center",
                            justify="center")
    # Clic sul riquadro = "mostra" (il pulsante vero sta nel pannello del PIN).
    c.tag_bind(_remote_qr_hint._item, "<Button-1>", toggle_reveal)
    _remote_status_var = _text(
        c, L + P(12), ry1 + P(34), "Inizializzazione...", _f_label(12), COLOR_MUTED,
        width=_remote_qr_box[0] - L - P(30))
    _remote_status_label = _remote_status_var


def _draw_pin_panel(c, lay: _Layout) -> None:
    """Pannello arancio con il PIN (lo stesso che va nel QR remoto).

    Il PIN è mascherato; il pulsante lo mostra, insieme a QR remoto e IP, per
    SHOW_SECS secondi.
    """
    global _pin_var, _pin_max_w, _pin_btn_text
    P = _px
    R, ry1, ry2, pin_l = lay.right, lay.ry1, lay.ry2, lay.pin_l
    _panel(c, pin_l, ry1, R, ry2, COLOR_ORANGE)
    _text(c, pin_l + P(12), ry1 + P(10), "pin", _f_label(12), COLOR_INK)
    _pin_max_w = R - pin_l - P(22)
    pin_val = _masked_pin(_deps.config.get('pin_plain', '—'))
    _pin_var = _text(c, pin_l + P(10), ry1 + P(78), pin_val,
                     _fit_num(pin_val, _pin_max_w, 30, 12), COLOR_INK, "sw")
    # Pulsante: pannello scuro con testo crema, alto quanto serve a un clic.
    bx1, bx2 = pin_l + P(12), R - P(12)
    by2 = ry2 - P(10)
    by1 = by2 - P(26)
    fondo = _panel(c, bx1, by1, bx2, by2, COLOR_INK, r=6)
    _pin_btn_text = _text(c, (bx1 + bx2) // 2, (by1 + by2) // 2, f"mostra per {SHOW_SECS} s",
                          _f_label(11), COLOR_CREAM, "center")

    def _hover(on):
        c.itemconfig(fondo, fill=COLOR_BORDER if on else COLOR_INK,
                     outline=COLOR_BORDER if on else COLOR_INK)
        c.config(cursor="hand2" if on else "")
    for item in (fondo, _pin_btn_text._item):
        c.tag_bind(item, "<Button-1>", toggle_reveal)
        c.tag_bind(item, "<Enter>", lambda e: _hover(True))
        c.tag_bind(item, "<Leave>", lambda e: _hover(False))


def _draw_status_panel(c, lay: _Layout) -> _CanvasText:
    """Pannello di stato con il pallino colorato; ritorna l'intestazione."""
    global status_var, status_label, _status_dot
    P = _px
    L, R, sy1, sy2 = lay.left, lay.right, lay.sy1, lay.sy2
    _panel(c, L, sy1, R, sy2, COLOR_BG, COLOR_BORDER)
    lbl_status_header = _text(c, L + P(12), sy1 + P(10), "", _f_label(12), COLOR_MUTED)
    dot_y = sy1 + P(42)
    _status_dot = c.create_oval(L + P(12), dot_y - P(5), L + P(22), dot_y + P(5),
                                fill=COLOR_MUTED, outline="")
    status_var = _text(c, L + P(32), dot_y, "", _f_label(12), COLOR_MUTED, "w",
                       width=R - L - P(48))
    status_label = status_var
    return lbl_status_header


# --- ANIMAZIONE D'AVVIO ---
# Tempi in un posto solo. Tk su Windows non scatta più spesso di ~16 ms: i
# vecchi intervalli di 15-40 ms per carattere diventavano comunque 16-40 e
# l'intro durava più di due secondi prima che la finestra fosse leggibile.
# Ora ogni testo si scrive in al più TYPE_MAX_TICKS passi (più caratteri per
# passo se è lungo) e la dissolvenza ha meno passi: ~1 s in tutto. Il testo
# finale è identico: l'ultimo passo scrive sempre la stringa intera.
TYPE_START_MS = 120      # prima si aspettavano 400 ms
TYPE_TICK_MS = 16        # un passo ogni frame
TYPE_MAX_TICKS = 10
TYPE_GAP_MS = 30         # pausa fra un testo e il successivo (era 80)
FADE_START_MS = 40       # era 80
FADE_STEPS = 24          # era 45
FADE_STEP_MS = 16


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _type_sequence(items, idx: int = 0) -> None:
    """Scrive i testi uno dopo l'altro, con un cursore a blocco (come il client web).

    `items` = [(widget, testo)]. Ogni testo avanza di `passo` caratteri per tick.
    """
    if idx >= len(items):
        return
    target, text = items[idx]
    passo = max(1, -(-len(text) // TYPE_MAX_TICKS))   # divisione per eccesso

    def _type(ci: int = 0) -> None:
        if ci < len(text):
            target.set(text[:ci] + "█")
            root.after(TYPE_TICK_MS, lambda: _type(ci + passo))
        else:
            target.set(text)
            root.after(TYPE_GAP_MS, lambda: _type_sequence(items, idx + 1))
    _type()


def _fade_in(step: int = 0) -> None:
    """Dissolvenza con easing cubico fino a finestra opaca."""
    if step <= FADE_STEPS:
        root.attributes('-alpha', min(_ease_out_cubic(step / FADE_STEPS), 1.0))
        root.after(FADE_STEP_MS, lambda: _fade_in(step + 1))


def _start_intro(items) -> None:
    root.after(TYPE_START_MS, lambda: _type_sequence(items))
    root.after(FADE_START_MS, _fade_in)


def _apply_dwm_later() -> None:
    """Dark-mode + angoli arrotondati DWM su Win11 (non bloccante).

    La finestra è opaca: se DWM fallisce (Win10) resta rettangolare ma
    perfettamente leggibile.
    """
    def _dwm_later():
        try:
            hwnd = int(root.wm_frame(), 16)
        except Exception:
            try:
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            except Exception:
                return
        apply_dwm_style(hwnd)
    root.after(200, _dwm_later)


def setup_gui():
    """Disegna la finestra. Ogni sezione sta nella sua funzione `_draw_*`."""
    global _main_canvas
    root.title("Liquid Mouse")
    _init_scale_and_fonts()
    lay = _make_layout()
    _configure_window(lay)

    c = tk.Canvas(root, bg=COLOR_BG, highlightthickness=0, width=lay.w, height=lay.h)
    c.pack(fill="both", expand=True)
    _main_canvas = c

    tab_num, tab_title = _draw_tabs(c, lay)
    _bind_window_drag(c)
    lbl_host, ip_testo = _draw_lan_panel(c, lay)
    _draw_remote_panel(c, lay)
    _draw_pin_panel(c, lay)
    lbl_status_header = _draw_status_panel(c, lay)

    _start_intro([
        (tab_num,           "001"),
        (tab_title,         "liquid mouse"),
        (lbl_host,          "host // lan"),
        (ip_label_var,      ip_testo),
        (lbl_status_header, "stato"),
        (status_var,        "Inizializzazione..."),
    ])
    _apply_dwm_later()

_DOT_MAP = {COLOR_OK: COLOR_OK, COLOR_ACCENT: COLOR_OK, COLOR_ERROR: COLOR_ERROR}

def gui_log_sink(message, color=None):
    """Sink Tk per liquidmouse.events: mostra il messaggio nella riga di stato.

    Registrato in main(). Il core non conosce questa funzione, pubblica e basta;
    prima invece scriveva sui widget direttamente e legava a Tk anche i moduli
    di rete e di terminale.
    """
    if root is None:
        # Registrato prima di build(): i messaggi emessi nel frattempo non
        # hanno dove andare, ma non devono far cadere l'avvio.
        return
    if color is None:
        color = COLOR_MUTED
    def _update():
        if status_var:
            # Il log dice "UPnP attivo: <ip esterno>" e "Tunnel attivo: <url>":
            # anche la riga di stato rispetta la maschera.
            status_var.set(_visible_text(message))
            if status_label: status_label.config(fg=color)
        if _main_canvas is not None and _status_dot is not None:
            _main_canvas.itemconfig(_status_dot, fill=_DOT_MAP.get(color, COLOR_MUTED))
    root.after(0, _update)


def build(deps: GuiDeps):
    """Crea la finestra e registra il sink di log. Ritorna `root`."""
    global _deps, root
    _deps = deps
    # Prima di tk.Tk(): Tk elenca i font di sistema alla prima richiesta.
    load_private_fonts([os.path.join(BASE_DIR, f) for f in FONT_FILES])
    root = tk.Tk()
    setup_gui()
    return root
