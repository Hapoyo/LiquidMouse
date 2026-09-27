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
import os
import time
import tkinter as tk

import pystray
import qrcode
from PIL import Image, ImageDraw, ImageTk

from liquidmouse.events import log_message
from liquidmouse.gui.effects import apply_dwm_style, load_private_fonts
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

    def __init__(self, *, config, sessions, services, local_ip, reset_trusted):
        self.config = config
        self.sessions = sessions
        self.services = services
        self.local_ip = local_ip
        self.reset_trusted = reset_trusted


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
_remote_qr_item     = None
_remote_qr_box      = None   # (x, y, lato) dell'area del QR remoto
_sessions_win       = None

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
# L'unica strada remota è UPnP: il router apre una porta pubblica (la 8443 o, se
# il modem la rifiuta, una di riserva) verso la 8443 del PC e il QR ci punta con il
# PIN già in query string, così dal telefono basta scansionare. Il certificato è
# self-signed, quindi al primo accesso il browser mostra l'avviso una volta.

def _remote_endpoint() -> tuple[str, str] | None:
    """(etichetta, url del QR) per l'accesso remoto, None se non disponibile.

    Unico punto in cui si costruisce l'endpoint remoto: prima la stessa logica
    era scritta due volte, nel pannello e nell'etichetta del tray, e le due
    potevano divergere.
    """
    servizi = _deps.services()
    if servizi is None or servizi.remote_mode != 'upnp':
        return None
    external_ip = servizi.external_ip
    porta = servizi.external_port
    pin = _deps.config.get('pin_plain', '')
    return (f"UPnP  {external_ip}:{porta}",
            f"https://{external_ip}:{porta}/?pin={pin}")


def _get_remote_tray_label():
    endpoint = _remote_endpoint()
    return f'Remoto: {endpoint[0]}' if endpoint else 'Remoto: non disponibile'


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
    if not _remote_status_var:
        return
    endpoint = _remote_endpoint()
    if endpoint is None:
        servizi = _deps.services()
        motivo = servizi.upnp.last_error if servizi else None
        etichetta = (f"Remoto non disponibile: {_troncato(motivo)}" if motivo
                     else "Remoto non disponibile")
        # COLOR_MUTED, non COLOR_ERROR: UPnP non ancora riuscito e' uno stato
        # di attesa normale (il keepalive riprova ogni 10 minuti), non un
        # guasto da segnalare in rosso.
        root.after(0, lambda et=etichetta: _set_remote_label(et, COLOR_MUTED))
        # Un QR rimasto da un mapping perso manderebbe il telefono su una
        # porta ormai chiusa.
        root.after(0, _clear_remote_qr)
        return
    etichetta, url = endpoint
    root.after(0, lambda et=etichetta: _set_remote_label(et, COLOR_OK))
    root.after(0, lambda: _set_remote_qr(url))


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
        else:
            _main_canvas.itemconfig(_remote_qr_item, image=photo, state="normal")
    except Exception as e:
        log_message(f"QR remoto error: {e}", color=COLOR_ERROR)


def _clear_remote_qr() -> None:
    if _main_canvas is not None and _remote_qr_item is not None:
        _main_canvas.itemconfig(_remote_qr_item, state="hidden")


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


def setup_gui():
    global ip_label_var, status_var, status_label, _main_canvas, _status_dot
    global _remote_status_var, _remote_status_label, _remote_qr_box, _scale

    root.title("Liquid Mouse")
    try:
        _scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:
        _scale = 1.0
    _scegli_font()
    P = _px

    w, h = P(560), P(460)
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

    c = tk.Canvas(root, bg=COLOR_BG, highlightthickness=0, width=w, height=h)
    c.pack(fill="both", expand=True)
    _main_canvas = c

    # --- Schedario: linguetta aperta + cartella ---
    M = P(8)                 # bordo della finestra
    TAB_H = P(24)            # altezza delle linguette
    top = M + TAB_H          # bordo superiore della cartella
    tab_r = P(270)           # fine della linguetta aperta
    _smooth_poly(c, [(M, M), (tab_r, M), (tab_r, top), (w - M, top),
                     (w - M, h - M), (M, h - M)],
                 [P(8), P(8), P(4), P(10), P(10), P(10)],
                 fill=COLOR_PANEL, outline=COLOR_CREAM, width=P(1))
    tab_mid = M + TAB_H // 2
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

    # --- Dragging finestra ---
    def get_pos(e):
        root.x_offset = e.x
        root.y_offset = e.y
    def move_window(e):
        root.geometry(f'+{e.x_root - root.x_offset}+{e.y_root - root.y_offset}')
    c.bind("<Button-1>", get_pos)
    c.bind("<B1-Motion>", move_window)

    L, R = P(24), w - P(24)          # margini interni della cartella
    GAP = P(10)

    # --- Host LAN: etichetta, indirizzo grande, QR su pannello crema ---
    y0 = top + P(14)
    lbl_host = _text(c, L, y0, "", _f_label(12), COLOR_MUTED)
    _text(c, R - P(130), y0, f"v{VERSION} «{CODENAME.lower()}»", _f_label(11), COLOR_MUTED, "ne")

    qr_side = P(116)
    qx1, qy1 = R - qr_side, y0 + P(24)
    _panel(c, qx1, qy1, R, qy1 + qr_side + P(16), COLOR_CREAM)
    qr_url = f"http://{_deps.local_ip}:{HTTP_PORT}/?v={int(time.time())}"
    try:
        lato = qr_side - P(16)
        root.qr_photo = ImageTk.PhotoImage(_qr_image(qr_url, lato, COLOR_INK, COLOR_CREAM))
        c.create_image(qx1 + qr_side // 2, qy1 + P(8) + lato // 2, image=root.qr_photo)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)
    c.create_text(qx1 + qr_side // 2, qy1 + qr_side + P(6), text="scan lan",
                  font=_f_label(11), fill=COLOR_INK)

    ip_testo = f"{_deps.local_ip}:{HTTP_PORT}"
    ip_label_var = _text(c, L - P(2), y0 + P(78), "",
                         _fit_num(ip_testo, qx1 - L - GAP * 2, 44, 20), COLOR_TEXT, "sw")
    _text(c, L, y0 + P(90), "apri dal telefono sulla stessa wi-fi",
          _f_label(11), COLOR_MUTED)
    # Barra arancio come la barra della giornata di PiDash: separa l'host
    # dalla fila dei pannelli.
    bar_y = y0 + P(122)
    _panel(c, L, bar_y, qx1 - GAP * 2, bar_y + P(6), COLOR_ORANGE, r=3)

    # --- Fila dei pannelli: remoto (scuro) e PIN (arancio) ---
    ry1 = qy1 + qr_side + P(16) + GAP * 2
    ry2 = ry1 + P(128)
    pin_l = R - P(150)
    _panel(c, L, ry1, pin_l - GAP, ry2, COLOR_BG, COLOR_BORDER)
    _text(c, L + P(12), ry1 + P(10), "remoto // upnp", _f_label(12), COLOR_MUTED)
    rqr = P(88)
    _remote_qr_box = (pin_l - GAP - P(12) - rqr, ry1 + (ry2 - ry1 - rqr) // 2, rqr)
    # Crema come il QR LAN; finché UPnP non risponde mostra "qr in attesa".
    _panel(c, _remote_qr_box[0] - P(6), _remote_qr_box[1] - P(6),
           _remote_qr_box[0] + rqr + P(6), _remote_qr_box[1] + rqr + P(6),
           COLOR_CREAM, r=8)
    c.create_text(_remote_qr_box[0] + rqr // 2, _remote_qr_box[1] + rqr // 2,
                  text="qr\nin attesa", justify="center", font=_f_label(11), fill=COLOR_INK)
    _remote_status_var = _text(
        c, L + P(12), ry1 + P(34), "Inizializzazione...", _f_label(12), COLOR_MUTED,
        width=_remote_qr_box[0] - L - P(30))
    _remote_status_label = _remote_status_var

    _panel(c, pin_l, ry1, R, ry2, COLOR_ORANGE)
    _text(c, pin_l + P(12), ry1 + P(10), "pin", _f_label(12), COLOR_INK)
    pin_val = _deps.config.get('pin_plain', '—')
    _text(c, pin_l + P(10), ry1 + P(78), pin_val,
          _fit_num(pin_val, R - pin_l - P(22), 30, 12), COLOR_INK, "sw")
    _text(c, pin_l + P(12), ry2 - P(10), "nel qr remoto", _f_label(11), COLOR_INK, "sw")

    # --- Stato ---
    sy1, sy2 = ry2 + GAP, h - M - P(16)
    _panel(c, L, sy1, R, sy2, COLOR_BG, COLOR_BORDER)
    lbl_status_header = _text(c, L + P(12), sy1 + P(10), "", _f_label(12), COLOR_MUTED)
    dot_y = sy1 + P(42)
    _status_dot = c.create_oval(L + P(12), dot_y - P(5), L + P(22), dot_y + P(5),
                                fill=COLOR_MUTED, outline="")
    status_var = _text(c, L + P(32), dot_y, "", _f_label(12), COLOR_MUTED, "w",
                       width=R - L - P(48))
    status_label = status_var

    # --- Animazione typewriter con cursore a blocco (come il client web) ---
    def type_sequence(widgets_data, idx=0):
        if idx >= len(widgets_data): return
        target, text, speed = widgets_data[idx]
        def _type(ci=0):
            if ci < len(text):
                target.set(text[:ci] + "█")
                root.after(speed, lambda: _type(ci + 1))
            else:
                target.set(text)
                root.after(80, lambda: type_sequence(widgets_data, idx + 1))
        _type()

    anim_data = [
        (tab_num,           "001",                           40),
        (tab_title,         "liquid mouse",                  25),
        (lbl_host,          "host // lan",                   15),
        (ip_label_var,      ip_testo,                        18),
        (lbl_status_header, "stato",                         15),
        (status_var,        "Inizializzazione...",           18),
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
        apply_dwm_style(hwnd)
    root.after(200, _dwm_later)

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
            status_var.set(message)
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
