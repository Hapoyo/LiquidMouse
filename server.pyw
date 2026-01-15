"""
🖱️ LIQUID MOUSE - Server Application
====================================
Versione: 1.4.0 (Smart Menu Edition)
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

# --- GESTIONE DIPENDENZE ---
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    # Crea una finestra TK nascosta per mostrare il messaggio di errore se mancano librerie
    temp_root = tk.Tk()
    temp_root.withdraw()
    messagebox.showerror("Errore Librerie", "Mancano le librerie 'pystray' o 'Pillow'.\n\nEsegui nel terminale:\npip install pystray Pillow")
    sys.exit(1)

# --- CONFIGURAZIONE SISTEMA ---
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False
SENSITIVITY = 1.8 
PORT = 8765
HTTP_PORT = 8000

# --- FIX ICONA TASKBAR WINDOWS ---
try:
    # Disaccoppia l'icona dalla shell di Python per mostrarla correttamente nella barra
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('liquidmouse.server.1.4.0')
except Exception:
    pass

# --- COLORI (Design System) ---
COLOR_BG = "#2b2e4a"
COLOR_TEXT = "#ffffff"
COLOR_ACCENT = "#88ffcc"
COLOR_MUTED = "#6c7099"
COLOR_ERROR = "#ff6b6b"
COLOR_STATUS_BAR = "#25273f"

# --- PERCORSO FILE ---
# Ottiene la cartella dove si trova lo script per caricare i file (come l'icona) in modo sicuro
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

# --- BACKEND (WebSocket & HTTP) ---
async def handler(websocket):
    log_message("Dispositivo connesso", color=COLOR_ACCENT)
    last_backspace_time = 0
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
                    # Normalizzazione caratteri speciali (smart quotes da mobile)
                    replacements = {
                        '’': "'", '‘': "'", 
                        '“': '"', '”': '"',
                        '…': '...'
                    }
                    for old, new in replacements.items():
                        char = char.replace(old, new)
                    if char: pyautogui.write(char, _pause=False)
                elif msg_type == 'key':
                    key = data.get('key', '')
                    if key:
                        # Debounce per backspace (evita cancellazioni multiple involontarie)
                        if key == 'backspace':
                            now = time.time()
                            if now - last_backspace_time < 0.08: continue
                            last_backspace_time = now
                        pyautogui.press(key, _pause=False)
                elif msg_type == 'drag':
                    if data.get('state') == 'down': pyautogui.mouseDown()
                    else: pyautogui.mouseUp()
                elif msg_type == 'hotkey':
                    pyautogui.hotkey(*data.get('keys', []))

            except Exception: pass
            
    except websockets.exceptions.ConnectionClosed:
        log_message("In attesa di connessione...", color="#aaaaaa")
    finally:
        pyautogui.mouseUp()

def start_http_server():
    try:
        # Cambia la directory di lavoro per servire index.html
        os.chdir(BASE_DIR)
        handler = SimpleHTTPRequestHandler
        handler.log_message = lambda self, format, *args: None # Silenzia log HTTP
        httpd = HTTPServer(("0.0.0.0", HTTP_PORT), handler)
        httpd.serve_forever()
    except OSError:
        log_message(f"Errore: Porta Web {HTTP_PORT} occupata!", color=COLOR_ERROR)

async def start_websocket_server():
    ip = get_local_ip()
    update_ui_info(ip)
    log_message("Server avviato. In attesa...", color="#aaaaaa")
    
    try:
        async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=None):
            await asyncio.Future()
    except OSError:
        log_message(f"ERRORE CRITICO: Porta {PORT} occupata!", color=COLOR_ERROR)
        log_message("Chiudi altri server Liquid Mouse.", color=COLOR_ERROR)

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
    """Carica l'icona personalizzata o ne crea una di fallback se manca il file."""
    if os.path.exists(ICON_PATH):
        try:
            return Image.open(ICON_PATH)
        except Exception:
             pass # Se il file è corrotto, usa il fallback

    # Fallback: crea un'icona generata se icon.ico non esiste
    image = Image.new('RGB', (64, 64), COLOR_BG)
    dc = ImageDraw.Draw(image)
    dc.ellipse((10, 10, 54, 54), fill=COLOR_BG, outline=COLOR_ACCENT, width=3)
    dc.ellipse((24, 24, 40, 40), fill=COLOR_ACCENT)
    return image

def minimize_to_tray():
    root.withdraw()
    if tray_icon: tray_icon.notify("Server attivo in background", "Liquid Mouse")

def restore_window(icon=None, item=None):
    root.deiconify()
    root.lift()

def terminate_application(icon=None, item=None):
    if icon: icon.stop()
    time.sleep(0.1)
    root.quit()
    os._exit(0)

def run_tray_service():
    global tray_icon
    menu = (pystray.MenuItem('Apri', restore_window, default=True), pystray.MenuItem('Esci', terminate_application))
    tray_icon = pystray.Icon("LiquidMouse", create_tray_icon(), "Liquid Mouse", menu)
    tray_icon.run()

def setup_gui():
    global ip_label_var, status_var, status_label
    
    root.title("Liquid Mouse")
    root.geometry("350x450")
    root.configure(bg=COLOR_BG)
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", minimize_to_tray)

    # TENTATIVO CARICAMENTO ICONA FINESTRA
    try:
        root.iconbitmap(ICON_PATH)
    except Exception:
        pass # Ignora errori se l'icona non si carica (usa quella di default di TK)

    main_frame = tk.Frame(root, bg=COLOR_BG)
    main_frame.pack(expand=True, fill='both', padx=30, pady=30)

    tk.Label(main_frame, text="🖱️", font=("Segoe UI", 48), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(20, 10))
    tk.Label(main_frame, text="Liquid Mouse", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack()

    tk.Frame(main_frame, height=30, bg=COLOR_BG).pack()

    tk.Label(main_frame, text="CONNETTITI A:", font=("Segoe UI", 8, "bold"), bg=COLOR_BG, fg=COLOR_MUTED).pack()
    
    ip_label_var = tk.StringVar(value="...")
    tk.Label(main_frame, textvariable=ip_label_var, font=("Segoe UI", 24, "bold"), bg=COLOR_BG, fg=COLOR_ACCENT).pack(pady=5)
    
    tk.Label(main_frame, text="Inserisci questo IP\nnel browser del telefono", font=("Segoe UI", 9), bg=COLOR_BG, fg=COLOR_MUTED).pack(pady=10)

    # Status Bar
    status_frame = tk.Frame(root, bg=COLOR_STATUS_BAR, height=40)
    status_frame.pack(fill='x', side='bottom')
    status_frame.pack_propagate(False)

    status_var = tk.StringVar(value="Avvio servizi...")
    status_label = tk.Label(status_frame, textvariable=status_var, font=("Consolas", 9), bg=COLOR_STATUS_BAR, fg="#aaaaaa")
    status_label.pack(expand=True)

    threading.Thread(target=run_services, daemon=True).start()
    threading.Thread(target=run_tray_service, daemon=True).start()

def log_message(message, color="#aaaaaa"):
    def _update():
        if status_var:
            status_var.set(message)
            if status_label: status_label.config(fg=color)
    root.after(0, _update)

def update_ui_info(ip):
    root.after(0, lambda: ip_label_var.set(f"{ip}:{HTTP_PORT}"))

if __name__ == "__main__":
    setup_gui()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)