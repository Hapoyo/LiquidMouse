"""Finestra principale, tray e pannello sessioni.

Unico modulo che disegna: raccoglie lo stato dei widget, l'icona nella tray e il
pannello delle sessioni terminale.

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
from liquidmouse.gui.effects import apply_dwm_style
from liquidmouse.paths import ICON_PATH
from liquidmouse.ports import HTTP_PORT, HTTPS_PORT
from liquidmouse.terminal.launcher import open_pc_terminal
from liquidmouse.theme import (
    COLOR_ACCENT, COLOR_BG, COLOR_BORDER, COLOR_ERROR,
    COLOR_GLASS, COLOR_MUTED, COLOR_OK, COLOR_SURFACE, COLOR_TEXT,
    COLOR_TRANSPARENT,
)
from liquidmouse.version import VERSION


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


_deps: GuiDeps | None = None


# --- STATO DEI WIDGET ---
# root e' creato in build(), non qui: importare questo modulo non deve aprire
# una finestra.
root                = None
ip_label_var        = None
status_var          = None
status_label        = None
_main_canvas        = None
_remote_status_var  = None
_remote_status_label = None
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

# --- ACCESSO REMOTO: ETICHETTA E QR ---
# L'unica strada remota è UPnP: il router apre la 8443 e il QR ci punta con il
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
    pin = _deps.config.get('pin_plain', '')
    return (f"UPnP  {external_ip}:{HTTPS_PORT}",
            f"https://{external_ip}:{HTTPS_PORT}/?pin={pin}")


def _get_remote_tray_label():
    endpoint = _remote_endpoint()
    return f'Remoto: {endpoint[0]}' if endpoint else 'Remoto: non disponibile'


# Il pannello "ACCESSO REMOTO" ha uno spazio verticale fisso fino alla sezione
# PIN sottostante: un motivo di errore lungo (es. il testo di un'eccezione dal
# mapping UPnP) andrebbe su piu' righe e la sovrapporrebbe. Il log tiene il
# messaggio integrale; qui va troncato.
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
        return
    etichetta, url = endpoint
    root.after(0, lambda et=etichetta: _set_remote_label(et, COLOR_OK))
    root.after(0, lambda: _set_remote_qr(url))


def _set_remote_label(testo: str, colore: str) -> None:
    """Aggiorna testo e colore del pannello remoto (eseguire sul thread Tk).

    Prima il colore era fisso a COLOR_ACCENT: uno stato di attesa e uno
    attivo erano visivamente identici.
    """
    _remote_status_var.set(testo)
    if _remote_status_label is not None:
        _remote_status_label.config(fg=colore)


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
                sessions = _deps.sessions.list_sessions()
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
        pystray.MenuItem('Reset connessione locale', lambda icon, item: _deps.reset_trusted()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci', terminate_application),
    )
    pystray.Icon("LiquidControl", create_tray_icon(), "Liquid Control", menu).run()

def setup_gui():
    global ip_label_var, status_var, status_label, _main_canvas
    global _remote_status_var, _remote_status_label

    root.title("Liquid Control")
    w, h = 560, 460
    sx = (root.winfo_screenwidth()  - w) // 2
    sy = (root.winfo_screenheight() - h) // 2
    root.geometry(f'{w}x{h}+{sx}+{sy}')

    root.overrideredirect(True)
    root.attributes('-alpha', 0.0)
    # Niente "-transparentcolor": finestra opaca, angoli arrotondati da DWM
    # (vedi apply_dwm_style). La trasparenza keyed lasciava puntini bianchi
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
    # Angoli smussati quanto i pannelli del terminale web (8-10px), non i 22px
    # da "card glass": stesso linguaggio visivo, non un blob arrotondato.
    CORNER_R = 10
    # Card piatta: bordo netto invece del bordo glow, niente riflesso.
    rounded_rect(canvas, PAD, PAD, w-PAD, h-PAD, CORNER_R,
                 fill=COLOR_GLASS, outline=COLOR_BORDER, width=1)

    # Linea separatore dopo titolo
    sep_y = 70
    canvas.create_line(PAD+30, sep_y,        w-PAD-30, sep_y,        fill=COLOR_BORDER, width=1)

    # Linea separatore prima sezione remota
    sep_y_remote = 215
    canvas.create_line(PAD+30, sep_y_remote, w-PAD-30, sep_y_remote, fill=COLOR_BORDER, width=1)

    # Linea separatore sopra lo status
    sep_y2 = h - 75
    canvas.create_line(PAD+30, sep_y2,       w-PAD-30, sep_y2,       fill=COLOR_BORDER, width=1)

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
    qr_url = f"http://{_deps.local_ip}:{HTTP_PORT}/?v={int(time.time())}"
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
    _remote_status_label = tk.Label(
        root, textvariable=_remote_status_var,
        font=("Consolas", 9), bg=COLOR_TRANSPARENT, fg=COLOR_ACCENT,
        wraplength=380, justify="left")
    _remote_status_label.place(x=36, y=245)

    tk.Label(root, text="PIN", font=("Consolas", 8), bg=COLOR_TRANSPARENT, fg=COLOR_MUTED).place(x=36, y=318)
    pin_val = _deps.config.get('pin_plain', '—')
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
        (ip_label_var,      f"{_deps.local_ip}:{HTTP_PORT}",  18),
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
        apply_dwm_style(hwnd)
    root.after(200, _dwm_later)

_DOT_MAP = {COLOR_OK: COLOR_OK, COLOR_ACCENT: COLOR_OK, COLOR_ERROR: COLOR_ERROR}

def gui_log_sink(message, color=None):
    """Sink Tk per liquidmouse.events: mostra il messaggio nella status bar.

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
        dot_color = _DOT_MAP.get(color, COLOR_MUTED)
        if _main_canvas and hasattr(root, '_status_dot'):
            try:
                _main_canvas.itemconfig(root._status_dot, fill=dot_color)
            except AttributeError:
                pass
    root.after(0, _update)


def build(deps: GuiDeps):
    """Crea la finestra e registra il sink di log. Ritorna `root`."""
    global _deps, root
    _deps = deps
    root = tk.Tk()
    setup_gui()
    return root
