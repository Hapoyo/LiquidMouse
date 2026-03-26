"""
LIQUID MOUSE - Server Application
"""

import asyncio
import websockets
import json
import ctypes
import socket
import threading
import tkinter as tk
from tkinter import messagebox
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import sys
import time

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

VERSION = "1.8.1"

# --- FIX ICONA TASKBAR WINDOWS ---
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'liquidmouse.server.{VERSION}')
except Exception:
    pass

# --- FIX DPI SCALING ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# --- CONFIGURAZIONE ---
PORT      = 8765
HTTP_PORT = 8000

# --- COLORI ---
COLOR_BG          = "#0F0F0F"
COLOR_TEXT        = "#FFFFFF"
COLOR_ACCENT      = "#00FF00"
COLOR_MUTED       = "#666666"
COLOR_ERROR       = "#FF4444"
COLOR_TRANSPARENT = "#FF00FF"

# --- PERCORSO FILE ---
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE_DIR, "icon.ico")

# --- INPUT ENGINE (Win32/ctypes nativo, zero overhead) ---
_user32 = ctypes.windll.user32

INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE      = 0x0001
MOUSEEVENTF_LEFTDOWN  = 0x0002
MOUSEEVENTF_LEFTUP    = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP   = 0x0010
MOUSEEVENTF_WHEEL     = 0x0800

KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
WHEEL_DELTA       = 120

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )

class _INPUT_UNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT))

class INPUT(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong), ("value", _INPUT_UNION))

_INPUT_SIZE = ctypes.sizeof(INPUT)

def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), arr, _INPUT_SIZE)

def _mi(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.value.mi.dx = dx
    i.value.mi.dy = dy
    i.value.mi.mouseData = ctypes.c_ulong(ctypes.c_long(data).value).value
    i.value.mi.dwFlags = flags
    return i

def _ki(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.value.ki.wVk = vk
    i.value.ki.wScan = scan
    i.value.ki.dwFlags = flags
    return i

def mouse_move(dx, dy):
    if dx == 0 and dy == 0: return
    _send(_mi(MOUSEEVENTF_MOVE, dx=dx, dy=dy))

def mouse_scroll(amount):
    _send(_mi(MOUSEEVENTF_WHEEL, data=amount * WHEEL_DELTA))

def mouse_click(button='left'):
    if button == 'left':
        _send(_mi(MOUSEEVENTF_LEFTDOWN), _mi(MOUSEEVENTF_LEFTUP))
    else:
        _send(_mi(MOUSEEVENTF_RIGHTDOWN), _mi(MOUSEEVENTF_RIGHTUP))

def mouse_button(state, button='left'):
    if button == 'left':
        flag = MOUSEEVENTF_LEFTDOWN if state == 'down' else MOUSEEVENTF_LEFTUP
    else:
        flag = MOUSEEVENTF_RIGHTDOWN if state == 'down' else MOUSEEVENTF_RIGHTUP
    _send(_mi(flag))

VK_MAP = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D,
    'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12,
    'capslock': 0x14, 'esc': 0x1B, 'escape': 0x1B,
    'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'insert': 0x2D, 'delete': 0x2E,
    'win': 0x5B, 'lwin': 0x5B, 'rwin': 0x5C,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72,  'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76,  'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'numlock': 0x90, 'scrolllock': 0x91, 'printscreen': 0x2C,
    'volumemute': 0xAD, 'volumedown': 0xAE, 'volumeup': 0xAF,
}

def key_press(key):
    key = key.lower()
    if key in VK_MAP:
        vk = VK_MAP[key]
        _send(_ki(vk=vk), _ki(vk=vk, flags=KEYEVENTF_KEYUP))
    elif len(key) == 1:
        _send_unicode_char(key)

def _send_vk(key, flags=0):
    vk = VK_MAP.get(key.lower())
    if vk: _send(_ki(vk=vk, flags=flags))

def key_down(key): _send_vk(key)
def key_up(key):   _send_vk(key, KEYEVENTF_KEYUP)

def key_text(text):
    replacements = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2026': '...'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    inputs = []
    for c in text:
        sc = ord(c)
        inputs += [_ki(scan=sc, flags=KEYEVENTF_UNICODE), _ki(scan=sc, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    if inputs:
        _send(*inputs)

def hotkey(*keys):
    vks = [VK_MAP[k.lower()] for k in keys if k.lower() in VK_MAP]
    downs = [_ki(vk=vk) for vk in vks]
    ups   = [_ki(vk=vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vks)]
    _send(*downs, *ups)

# --- SICUREZZA: WHITELIST IP ---
TRUSTED_IP = None

def reset_trusted_ip():
    global TRUSTED_IP
    TRUSTED_IP = None
    log_message("Whitelist resettata. In attesa...", color=COLOR_ACCENT)

# --- UTILITIES DI RETE ---
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

# --- BACKEND (WebSocket & HTTP) ---
async def handler(websocket):
    global TRUSTED_IP
    client_ip = websocket.remote_address[0]

    if TRUSTED_IP is None:
        TRUSTED_IP = client_ip
        log_message(f"Autorizzato: {client_ip}", color=COLOR_ACCENT)
    elif client_ip != TRUSTED_IP:
        log_message(f"Rifiutato: {client_ip}", color=COLOR_ERROR)
        await websocket.close()
        return

    log_message(f"Sessione attiva: {client_ip}", color=COLOR_ACCENT)
    last_backspace_time = 0
    held_keys = set()

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', '')

                if msg_type == 'move':
                    x = int(float(data.get('x', 0)))
                    y = int(float(data.get('y', 0)))
                    mouse_move(x, y)

                elif msg_type == 'scroll':
                    amt = int(data.get('amount', 0))
                    if amt != 0: mouse_scroll(amt)

                elif msg_type == 'click':
                    mouse_click(data.get('btn', 'left'))

                elif msg_type == 'text':
                    char = data.get('char', '')
                    if char: key_text(char)

                elif msg_type == 'key':
                    key = data.get('key', '')
                    if key:
                        if key == 'backspace':
                            now = time.time()
                            if now - last_backspace_time < 0.08: continue
                            last_backspace_time = now
                        key_press(key)

                elif msg_type == 'key_toggle':
                    key   = data.get('key', '')
                    state = data.get('state', '')
                    if key and state:
                        if state == 'down':
                            key_down(key)
                            held_keys.add(key)
                        else:
                            key_up(key)
                            held_keys.discard(key)

                elif msg_type == 'drag':
                    mouse_button(data.get('state', 'up'))

                elif msg_type == 'hotkey':
                    hotkey(*data.get('keys', []))

            except (ValueError, KeyError, TypeError) as e:
                log_message(f"Cmd ignorato: {e}", color=COLOR_MUTED)
            except Exception as e:
                log_message(f"Errore handler: {e}", color=COLOR_ERROR)

    except websockets.exceptions.ConnectionClosed:
        log_message("In attesa di connessione...", color="#aaaaaa")
    finally:
        mouse_button('up')
        for key in held_keys:
            key_up(key)
        held_keys.clear()

class _QuietHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

def start_http_server():
    try:
        os.chdir(BASE_DIR)
        httpd = HTTPServer(("0.0.0.0", HTTP_PORT), _QuietHTTPHandler)
        httpd.serve_forever()
    except OSError:
        log_message(f"Errore: Porta {HTTP_PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"HTTP Server crash: {e}", color=COLOR_ERROR)

async def start_websocket_server():
    log_message("Protocolli di comunicazione inizializzati.", color="#aaaaaa")
    try:
        async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=20, ping_timeout=10):
            await asyncio.Future()
    except OSError:
        log_message(f"ERRORE CRITICO: Porta {PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"WebSocket Server crash: {e}", color=COLOR_ERROR)

def run_services():
    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.run(start_websocket_server())

# --- GUI & SYSTEM TRAY ---
root         = tk.Tk()
ip_label_var = None
status_var   = None
status_label = None

def create_tray_icon():
    if os.path.exists(ICON_PATH):
        try: return Image.open(ICON_PATH)
        except Exception: pass
    image = Image.new('RGB', (64, 64), COLOR_BG)
    dc = ImageDraw.Draw(image)
    dc.ellipse((10, 10, 54, 54), fill=COLOR_BG, outline=COLOR_ACCENT, width=3)
    dc.ellipse((24, 24, 40, 40), fill=COLOR_ACCENT)
    return image

def minimize_to_tray():
    root.withdraw()

def restore_window(icon=None, item=None):
    root.deiconify()
    root.lift()

def terminate_application(icon=None, item=None):
    if icon: icon.stop()
    root.after(100, root.destroy)

def run_tray_service():
    menu = (
        pystray.MenuItem('Apri', restore_window, default=True),
        pystray.MenuItem('Reset connessione', lambda icon, item: reset_trusted_ip()),
        pystray.MenuItem('Esci', terminate_application),
    )
    pystray.Icon("LiquidMouse", create_tray_icon(), "Liquid Mouse", menu).run()

def setup_gui():
    global ip_label_var, status_var, status_label

    root.title("Liquid Mouse")
    w, h = 520, 260
    ws_screen = root.winfo_screenwidth()
    hs_screen = root.winfo_screenheight()
    x = (ws_screen / 2) - (w / 2)
    y = (hs_screen / 2) - (h / 2)
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    root.overrideredirect(True)
    root.attributes('-alpha', 0.0)
    root.wm_attributes("-transparentcolor", COLOR_TRANSPARENT)
    root.configure(bg=COLOR_TRANSPARENT)

    try: root.iconbitmap(ICON_PATH)
    except Exception: pass

    canvas = tk.Canvas(root, bg=COLOR_TRANSPARENT, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    def create_rounded_rect(c, x1, y1, x2, y2, r, **kwargs):
        points = (x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r,
                  x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2,
                  x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r,
                  x1, y1+r, x1, y1)
        return c.create_polygon(points, smooth=True, **kwargs)

    create_rounded_rect(canvas, 10, 10, w-10, h-10, 20, fill=COLOR_BG, outline="#333333", width=1)

    def get_pos(event):
        root.x_offset = event.x
        root.y_offset = event.y
    def move_window(event):
        root.geometry(f'+{event.x_root - root.x_offset}+{event.y_root - root.y_offset}')

    canvas.bind("<Button-1>", get_pos)
    canvas.bind("<B1-Motion>", move_window)

    title_lbl = tk.Label(root, text="", font=("Consolas", 14, "bold"), bg=COLOR_BG, fg=COLOR_TEXT)
    title_lbl.place(x=40, y=40)

    def type_sequence(widgets_data, index=0):
        if index >= len(widgets_data): return
        target, text, speed = widgets_data[index]
        def type_char(current_idx=0):
            cursor = "\u2588" if current_idx < len(text) else ""
            display = text[:current_idx] + cursor
            if isinstance(target, tk.StringVar): target.set(display)
            else: target.config(text=display)
            if current_idx < len(text):
                root.after(speed, lambda: type_char(current_idx + 1))
            else:
                if isinstance(target, tk.StringVar): target.set(text)
                else: target.config(text=text)
                type_sequence(widgets_data, index + 1)
        type_char()

    cx, cy, cr = w-35, 35, 12
    close_bg = canvas.create_oval(cx-cr, cy-cr, cx+cr, cy+cr, fill="#FF5555", outline="#FF5555")
    close_fg = canvas.create_text(cx, cy, text="\u00d7", font=("Arial", 13, "bold"), fill="white")
    for item in (close_bg, close_fg):
        canvas.tag_bind(item, "<Button-1>", lambda e: minimize_to_tray())
        canvas.tag_bind(item, "<Enter>", lambda e: canvas.config(cursor="hand2"))
        canvas.tag_bind(item, "<Leave>", lambda e: canvas.config(cursor=""))

    lbl_ip_header = tk.Label(root, text="", font=("Consolas", 8, "bold"), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_ip_header.place(x=40, y=90)

    ip_label_var = tk.StringVar(value="")
    tk.Label(root, textvariable=ip_label_var, font=("Consolas", 16), bg=COLOR_BG, fg=COLOR_TEXT).place(x=40, y=110)

    qr_url = f"http://{LOCAL_IP}:{HTTP_PORT}/?v={int(time.time())}"
    try:
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        root.qr_photo = ImageTk.PhotoImage(img)
        tk.Label(root, image=root.qr_photo, bg=COLOR_BG).place(x=400, y=90)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)

    lbl_status_header = tk.Label(root, text="", font=("Consolas", 8, "bold"), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_status_header.place(x=40, y=170)

    status_var = tk.StringVar(value="")
    status_label = tk.Label(root, textvariable=status_var, font=("Consolas", 9), bg=COLOR_BG, fg=COLOR_MUTED)
    status_label.place(x=40, y=190)

    anim_sequence = [
        (title_lbl,        ">_ Liquid Mouse",        30),
        (lbl_ip_header,    "INDIRIZZO IP HOST",       10),
        (ip_label_var,     f"{LOCAL_IP}:{HTTP_PORT}", 20),
        (lbl_status_header,"STATO DEL SISTEMA",       10),
        (status_var,       "Inizializzazione...",     20),
    ]
    root.after(300, lambda: type_sequence(anim_sequence))

    def fade_in(alpha=0):
        alpha += 0.04
        if alpha < 1.0:
            root.attributes('-alpha', alpha)
            root.after(15, lambda: fade_in(alpha))
        else:
            root.attributes('-alpha', 1.0)

    root.after(100, fade_in)
    threading.Thread(target=run_services, daemon=True).start()
    root.after(500, lambda: threading.Thread(target=run_tray_service, daemon=True).start())

def log_message(message, color="#aaaaaa"):
    def _update():
        if status_var:
            status_var.set(message)
            if status_label: status_label.config(fg=color)
    root.after(0, _update)

if __name__ == "__main__":
    setup_gui()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
