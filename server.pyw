"""
🖱️ LIQUID MOUSE - Server Application
====================================
"""

import asyncio
import websockets
import json
import pyautogui
import socket
import threading
import tkinter as tk
from tkinter import messagebox
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import sys
import ctypes
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

# --- CONFIGURAZIONE SISTEMA ---
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False
SENSITIVITY = 1.8 
PORT = 8765
HTTP_PORT = 8000

# --- FIX ICONA TASKBAR WINDOWS ---
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('liquidmouse.server.1.7.0')
except Exception:
    pass

# --- FIX DPI SCALING ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# --- COLORI ---
COLOR_BG = "#0F0F0F"
COLOR_TEXT = "#FFFFFF"
COLOR_ACCENT = "#00FF00"
COLOR_MUTED = "#666666"
COLOR_ERROR = "#FF4444"
COLOR_TRANSPARENT = "#FF00FF"

# --- PERCORSO FILE ---
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE_DIR, "icon.ico")

# --- UTILITIES DI RETE ---
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# IP calcolato una sola volta all'avvio per evitare latenze e incoerenze
LOCAL_IP = get_local_ip()

# --- BACKEND (WebSocket & HTTP) ---
async def handler(websocket):
    log_message("Sessione Client Attivata", color=COLOR_ACCENT)
    last_backspace_time = 0
    held_keys = set() # Tiene traccia dei tasti bloccati (Ctrl, Shift, ecc)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', '')
                
                if msg_type == 'move':
                    x = int(float(data.get('x', 0)) * SENSITIVITY)
                    y = int(float(data.get('y', 0)) * SENSITIVITY)
                    if x != 0 or y != 0: pyautogui.moveRel(x, y, _pause=False)
                
                elif msg_type == 'scroll':
                    amt = int(data.get('amount', 0))
                    if amt != 0: pyautogui.scroll(amt, _pause=False)
                
                elif msg_type == 'click':
                    pyautogui.click(button=data.get('btn', 'left'), _pause=False)
                
                elif msg_type == 'text':
                    char = data.get('char', '')
                    replacements = {'’': "'", '‘': "'", '“': '"', '”': '"', '…': '...'}
                    for old, new in replacements.items():
                        char = char.replace(old, new)
                    if char: pyautogui.write(char, _pause=False)
                
                elif msg_type == 'key':
                    key = data.get('key', '')
                    if key:
                        if key == 'backspace':
                            now = time.time()
                            if now - last_backspace_time < 0.08: continue
                            last_backspace_time = now
                        pyautogui.press(key, _pause=False)

                elif msg_type == 'key_toggle':
                    # Gestione tasti che vengono tenuti premuti (Ctrl, Shift)
                    key = data.get('key', '')
                    state = data.get('state', '')
                    if key and state:
                        if state == 'down':
                            pyautogui.keyDown(key)
                            held_keys.add(key)
                        else:
                            pyautogui.keyUp(key)
                            held_keys.discard(key)

                elif msg_type == 'drag':
                    if data.get('state') == 'down': 
                        pyautogui.mouseDown()
                    else: 
                        pyautogui.mouseUp()
                
                elif msg_type == 'hotkey':
                    pyautogui.hotkey(*data.get('keys', []))

            except (ValueError, KeyError, TypeError) as e:
                log_message(f"Cmd ignorato: {e}", color=COLOR_MUTED)
            except Exception as e:
                log_message(f"Errore handler: {e}", color=COLOR_ERROR)
            
    except websockets.exceptions.ConnectionClosed:
        log_message("In attesa di connessione...", color="#aaaaaa")
    finally:
        # PULIZIA DI SICUREZZA: Rilascia tutto quando il client si disconnette
        pyautogui.mouseUp()
        for key in held_keys:
            pyautogui.keyUp(key)
        held_keys.clear()

def start_http_server():
    try:
        os.chdir(BASE_DIR)
        handler = SimpleHTTPRequestHandler
        handler.log_message = lambda self, format, *args: None
        httpd = HTTPServer(("0.0.0.0", HTTP_PORT), handler)
        httpd.serve_forever()
    except OSError:
        log_message(f"Errore: Porta Web {HTTP_PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"HTTP Server crash: {e}", color=COLOR_ERROR)

async def start_websocket_server():
    log_message("Protocolli di comunicazione inizializzati.", color="#aaaaaa")
    try:
        async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=None):
            await asyncio.Future()
    except OSError:
        log_message(f"ERRORE CRITICO: Porta {PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"WebSocket Server crash: {e}", color=COLOR_ERROR)

def run_services():
    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.run(start_websocket_server())

# --- GUI & SYSTEM TRAY ---
root = tk.Tk()
ip_label_var = None
status_var = None
status_label = None
tray_icon = None

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
    # Chiusura pulita tramite il mainloop: evita os._exit() che bypasserebbe i finalizer
    root.after(100, root.destroy)

def run_tray_service():
    global tray_icon
    menu = (pystray.MenuItem('Apri', restore_window, default=True), pystray.MenuItem('Esci', terminate_application))
    tray_icon = pystray.Icon("LiquidMouse", create_tray_icon(), "Liquid Mouse", menu)
    tray_icon.run()

def setup_gui():
    global ip_label_var, status_var, status_label
    
    root.title("Liquid Mouse")
    w, h = 520, 260
    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    x = (ws/2) - (w/2)
    y = (hs/2) - (h/2)
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
        points = (x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1)
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
            cursor = "█" if current_idx < len(text) else ""
            display = text[:current_idx] + cursor
            if isinstance(target, tk.StringVar): target.set(display)
            else: target.config(text=display)
            if current_idx < len(text): root.after(speed, lambda: type_char(current_idx+1))
            else:
                if isinstance(target, tk.StringVar): target.set(text)
                else: target.config(text=text)
                type_sequence(widgets_data, index+1)
        type_char()

    cx, cy, cr = w-35, 35, 12
    close_bg = canvas.create_oval(cx-cr, cy-cr, cx+cr, cy+cr, fill="#FF5555", outline="#FF5555")
    close_fg = canvas.create_text(cx, cy, text="×", font=("Arial", 13, "bold"), fill="white")
    for item in (close_bg, close_fg):
        canvas.tag_bind(item, "<Button-1>", lambda e: minimize_to_tray())
        canvas.tag_bind(item, "<Enter>", lambda e: canvas.config(cursor="hand2"))
        canvas.tag_bind(item, "<Leave>", lambda e: canvas.config(cursor=""))

    lbl_ip_header = tk.Label(root, text="", font=("Consolas", 8, "bold"), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_ip_header.place(x=40, y=90)
    
    ip_label_var = tk.StringVar(value="")
    tk.Label(root, textvariable=ip_label_var, font=("Consolas", 16), bg=COLOR_BG, fg=COLOR_TEXT).place(x=40, y=110)
    
    # -- QR CODE GENERATION --
    qr_url = f"http://{LOCAL_IP}:{HTTP_PORT}/?v={int(time.time())}"
    try:
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        root.qr_photo = ImageTk.PhotoImage(img)
        qr_label = tk.Label(root, image=root.qr_photo, bg=COLOR_BG)
        qr_label.place(x=400, y=90)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)
    

    lbl_status_header = tk.Label(root, text="", font=("Consolas", 8, "bold"), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_status_header.place(x=40, y=170)

    status_var = tk.StringVar(value="")
    status_label = tk.Label(root, textvariable=status_var, font=("Consolas", 9), bg=COLOR_BG, fg=COLOR_MUTED)
    status_label.place(x=40, y=190)

    anim_sequence = [
        (title_lbl, ">_ Liquid Mouse", 30),
        (lbl_ip_header, "INDIRIZZO IP HOST", 10),
        (ip_label_var, f"{LOCAL_IP}:{HTTP_PORT}", 20),
        (lbl_status_header, "STATO DEL SISTEMA", 10),
        (status_var, "Inizializzazione...", 20)
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
    # Avvio tray ritardato di 500ms per evitare race condition con l'inizializzazione della GUI
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