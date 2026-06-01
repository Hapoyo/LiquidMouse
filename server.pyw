"""
LIQUID MOUSE - Server Application
Author: Hapone
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
import base64
import uuid
import shutil
import secrets
import hashlib
import pathlib
import ssl
import ipaddress
import tempfile
import atexit
import contextlib
from dataclasses import dataclass, field

try:
    import winpty as _winpty_mod
    WINPTY_AVAILABLE = True
except Exception:
    _winpty_mod = None
    WINPTY_AVAILABLE = False

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

VERSION = "2.1.2"

# --- CONFIGURAZIONE PERSISTENTE ---
_config: dict = {}
_ssl_context: ssl.SSLContext | None = None
_ssl_temp_files: list = []
_ssl_atexit_registered: bool = False

def get_config_path() -> pathlib.Path:
    appdata = os.environ.get('APPDATA', str(pathlib.Path.home()))
    return pathlib.Path(appdata) / 'LiquidMouse' / 'config.json'

def load_config() -> dict:
    global _config
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config_loaded = False
    if path.exists():
        try:
            with open(path, encoding='utf-8') as f:
                _config = json.load(f)
                config_loaded = True
        except Exception:
            _config = {}
    else:
        _config = {}
    # Genera PIN solo se config completamente mancante o malformata,
    # non se manca solo la key (evita rigenerazione su upgrade)
    if not config_loaded or 'pin_hash' not in _config:
        pin = secrets.token_urlsafe(8)
        _config['pin_plain'] = pin
        _config['pin_hash'] = hashlib.sha256(pin.encode()).hexdigest()
        _save_config()
    return _config

def _save_config() -> None:
    try:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(_config, f, indent=2)
    except Exception:
        pass

# --- SICUREZZA AUTH REMOTA ---
_auth_failures: dict[str, tuple[int, float]] = {}
AUTH_MAX_FAILS   = 5
AUTH_BLOCK_SECS  = 1800  # 30 minuti

def _is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False

def _check_auth_blocked(ip: str) -> bool:
    entry = _auth_failures.get(ip)
    if not entry:
        return False
    count, last_t = entry
    now = time.time()
    if count >= AUTH_MAX_FAILS:
        if (now - last_t) < AUTH_BLOCK_SECS:
            return True
        _auth_failures.pop(ip, None)
    elif (now - last_t) >= AUTH_BLOCK_SECS:
        _auth_failures.pop(ip, None)
    return False

def _record_auth_fail(ip: str) -> None:
    prev = _auth_failures.get(ip, (0, 0.0))
    _auth_failures[ip] = (prev[0] + 1, time.time())

def _clear_auth_fail(ip: str) -> None:
    _auth_failures.pop(ip, None)

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
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"LiquidMouse")])
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
            _save_config()

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
            atexit.register(lambda: [os.unlink(p) for p in _ssl_temp_files if os.path.exists(p)])
            _ssl_atexit_registered = True

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cf.name, kf.name)
        _ssl_context = ctx
        return ctx
    except Exception as e:
        return None

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
PORT       = 8765   # WS locale
HTTP_PORT  = 8000   # HTTP locale
HTTPS_PORT = 8443   # HTTPS remoto (con TLS)
WSS_PORT   = 8766   # WSS remoto (con TLS)
RELAY_URL  = "wss://relay.liquidmouse.app"
_PONG      = '{"type":"pong"}'

# --- COLORI (Claude Code palette) ---
COLOR_BG          = "#0D0D0D"
COLOR_SURFACE     = "#161616"
COLOR_TEXT         = "#E8E4E0"
COLOR_ACCENT       = "#DA7756"
COLOR_MUTED        = "#5A5868"
COLOR_BORDER       = "#232323"
COLOR_ERROR        = "#E55B5B"
COLOR_OK           = "#5BA878"
COLOR_TRANSPARENT  = "#FF00FF"

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

# Buffer riutilizzabili per i path a 60Hz (move/scroll): mutati in place a ogni
# evento per evitare di allocare una INPUT + array a ogni movimento del cursore.
_move_arr   = (INPUT * 1)(_mi(MOUSEEVENTF_MOVE))
_scroll_arr = (INPUT * 1)(_mi(MOUSEEVENTF_WHEEL))

def mouse_move(dx, dy):
    if dx == 0 and dy == 0: return
    mi = _move_arr[0].value.mi
    mi.dx = dx
    mi.dy = dy
    _user32.SendInput(1, _move_arr, _INPUT_SIZE)

def mouse_scroll(amount):
    _scroll_arr[0].value.mi.mouseData = ctypes.c_ulong(ctypes.c_long(amount * WHEEL_DELTA).value).value
    _user32.SendInput(1, _scroll_arr, _INPUT_SIZE)

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
    'media_next': 0xB0, 'media_prev': 0xB1, 'media_stop': 0xB2, 'media_play_pause': 0xB3,
}

def key_press(key):
    key = key.lower()
    if key in VK_MAP:
        vk = VK_MAP[key]
        _send(_ki(vk=vk), _ki(vk=vk, flags=KEYEVENTF_KEYUP))
    elif len(key) == 1:
        key_text(key)

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
    vks = []
    for k in keys:
        k_lower = k.lower()
        if k_lower in VK_MAP:
            vks.append(VK_MAP[k_lower])
        elif len(k) == 1 and k.isalpha():
            vks.append(ord(k.upper()))   # es. 'c' → 0x43, 'v' → 0x56
        elif len(k) == 1 and k.isdigit():
            vks.append(ord(k))           # es. '1' → 0x31
    downs = [_ki(vk=vk) for vk in vks]
    ups   = [_ki(vk=vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vks)]
    _send(*downs, *ups)

# --- TERMINAL MODE: ConPTY nativo via ctypes ---
import ctypes.wintypes as _wt
import subprocess as _subprocess

_k32 = ctypes.windll.kernel32

class _COORD(ctypes.Structure):
    _fields_ = [("X", _wt.SHORT), ("Y", _wt.SHORT)]

class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb",              _wt.DWORD),
        ("lpReserved",      _wt.LPWSTR),
        ("lpDesktop",       _wt.LPWSTR),
        ("lpTitle",         _wt.LPWSTR),
        ("dwX",             _wt.DWORD),
        ("dwY",             _wt.DWORD),
        ("dwXSize",         _wt.DWORD),
        ("dwYSize",         _wt.DWORD),
        ("dwXCountChars",   _wt.DWORD),
        ("dwYCountChars",   _wt.DWORD),
        ("dwFillAttribute", _wt.DWORD),
        ("dwFlags",         _wt.DWORD),
        ("wShowWindow",     _wt.WORD),
        ("cbReserved2",     _wt.WORD),
        ("lpReserved2",     ctypes.c_char_p),
        ("hStdInput",       _wt.HANDLE),
        ("hStdOutput",      _wt.HANDLE),
        ("hStdError",       _wt.HANDLE),
    ]

class _STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]

class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess",    _wt.HANDLE),
        ("hThread",     _wt.HANDLE),
        ("dwProcessId", _wt.DWORD),
        ("dwThreadId",  _wt.DWORD),
    ]

_EXTENDED_STARTUPINFO_PRESENT        = 0x00080000
_CREATE_NO_WINDOW                    = 0x08000000
_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_STILL_ACTIVE = 259

class _ConPTY:
    """ConPTY diretto via ctypes — nessuna dipendenza esterna."""

    def __init__(self, argv: list, cwd: str, cols: int = 120, rows: int = 40):
        self._hproc = self._hpc = self._stdin_w = self._stdout_r = None
        h_sin_r, h_sin_w, h_sout_r, h_sout_w = (_wt.HANDLE() for _ in range(4))

        if not _k32.CreatePipe(ctypes.byref(h_sin_r), ctypes.byref(h_sin_w), None, 0):
            raise OSError(f"CreatePipe(stdin) err {_k32.GetLastError()}")
        if not _k32.CreatePipe(ctypes.byref(h_sout_r), ctypes.byref(h_sout_w), None, 0):
            _k32.CloseHandle(h_sin_r); _k32.CloseHandle(h_sin_w)
            raise OSError(f"CreatePipe(stdout) err {_k32.GetLastError()}")

        hpc = _wt.HANDLE()
        hr = _k32.CreatePseudoConsole(_COORD(cols, rows), h_sin_r, h_sout_w, 0, ctypes.byref(hpc))
        _k32.CloseHandle(h_sin_r); _k32.CloseHandle(h_sout_w)
        if hr != 0:
            _k32.CloseHandle(h_sin_w); _k32.CloseHandle(h_sout_r)
            raise OSError(f"CreatePseudoConsole hr={hr:#010x}")

        self._hpc, self._stdin_w, self._stdout_r = hpc, h_sin_w, h_sout_r

        attr_sz = ctypes.c_size_t(0)
        _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_sz))
        attr_buf = (ctypes.c_byte * attr_sz.value)()
        attr_ptr = ctypes.cast(attr_buf, ctypes.c_void_p)
        _k32.InitializeProcThreadAttributeList(attr_ptr, 1, 0, ctypes.byref(attr_sz))
        _k32.UpdateProcThreadAttribute(attr_ptr, 0,
            _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, hpc, ctypes.sizeof(hpc), None, None)

        si = _STARTUPINFOEX()
        ctypes.memset(ctypes.byref(si), 0, ctypes.sizeof(si))
        si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEX)
        si.lpAttributeList = attr_ptr

        pi = _PROCESS_INFORMATION()
        cmd_str = _subprocess.list2cmdline(argv) if isinstance(argv, list) else argv
        ok = _k32.CreateProcessW(None, cmd_str, None, None, False,
            _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW,
            None, cwd, ctypes.byref(si), ctypes.byref(pi))
        _k32.DeleteProcThreadAttributeList(attr_ptr)
        if not ok:
            err = _k32.GetLastError()
            self._cleanup()
            raise OSError(f"CreateProcessW err={err} cmd={cmd_str!r}")
        self._hproc = pi.hProcess
        _k32.CloseHandle(pi.hThread)

    def read(self, size: int = 4096) -> bytes:
        buf = (ctypes.c_char * size)()
        n = _wt.DWORD(0)
        ok = _k32.ReadFile(self._stdout_r, buf, size, ctypes.byref(n), None)
        if not ok or n.value == 0:
            raise EOFError("ConPTY EOF")
        return bytes(buf[:n.value])

    def write(self, data) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        n = _wt.DWORD(0)
        _k32.WriteFile(self._stdin_w, data, len(data), ctypes.byref(n), None)

    def isalive(self) -> bool:
        if not self._hproc: return False
        ec = _wt.DWORD(); _k32.GetExitCodeProcess(self._hproc, ctypes.byref(ec))
        return ec.value == _STILL_ACTIVE

    @property
    def exitstatus(self) -> int:
        if not self._hproc: return 0
        ec = _wt.DWORD(); _k32.GetExitCodeProcess(self._hproc, ctypes.byref(ec))
        return 0 if ec.value == _STILL_ACTIVE else ec.value

    def set_size(self, rows: int, cols: int) -> None:
        if self._hpc:
            try: _k32.ResizePseudoConsole(self._hpc, _COORD(cols, rows))
            except Exception: pass

    def close(self) -> None:
        if self._hproc:
            try: _k32.TerminateProcess(self._hproc, 0)
            except Exception: pass
        self._cleanup()

    def _cleanup(self):
        for h in [self._hproc, self._stdin_w, self._stdout_r]:
            if h:
                try: _k32.CloseHandle(h)
                except Exception: pass
        if self._hpc:
            try: _k32.ClosePseudoConsole(self._hpc)
            except Exception: pass
        self._hproc = self._hpc = self._stdin_w = self._stdout_r = None


class _PyWinPTY:
    """Wrapper pywinpty con stessa interfaccia bytes di _ConPTY."""

    def __init__(self, argv: list, cwd: str, cols: int = 120, rows: int = 40):
        self._p = _winpty_mod.PtyProcess.spawn(argv, dimensions=(rows, cols), cwd=cwd)

    def read(self, size: int = 4096) -> bytes:
        s = self._p.read(size)
        if s is None or s == "":
            if not self._p.isalive():
                raise EOFError("PtyProcess EOF")
            return b""
        return s.encode("utf-8", errors="replace") if isinstance(s, str) else s

    def write(self, data) -> None:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        self._p.write(data)

    def isalive(self) -> bool:
        try: return self._p.isalive()
        except Exception: return False

    @property
    def exitstatus(self) -> int:
        try: return self._p.exitstatus or 0
        except Exception: return 0

    def set_size(self, rows: int, cols: int) -> None:
        try: self._p.setwinsize(rows, cols)
        except Exception: pass

    def close(self) -> None:
        try: self._p.close(force=True)
        except Exception: pass


def _make_pty(argv: list, cwd: str, cols: int = 120, rows: int = 40):
    """Sceglie backend PTY: pywinpty quando disponibile, ConPTY ctypes fallback."""
    if WINPTY_AVAILABLE:
        try:
            return _PyWinPTY(argv, cwd, cols, rows)
        except Exception as e:
            log_message(f"pywinpty fallita ({e}), fallback ConPTY", color=COLOR_MUTED)
    return _ConPTY(argv, cwd, cols, rows)


def _resolve_argv(cmd: str) -> list:
    if os.path.isabs(cmd) and os.path.exists(cmd):
        return [cmd]
    exe = shutil.which(cmd)
    if exe and exe.lower().endswith(('.cmd', '.bat')):
        return ["cmd.exe", "/c", exe]
    return [exe] if exe else [cmd]


def _append_ring(buf: bytearray, data: bytes, maxsize: int = 65536):
    buf += data
    if len(buf) > maxsize:
        del buf[:len(buf) - maxsize]


@dataclass
class PTYSession:
    id: str
    cmd: str
    pty: object
    output_buffer: bytearray = field(default_factory=bytearray)
    ws: object = None
    created_at: float = 0.0
    alive: bool = True


class SessionManager:
    def __init__(self):
        self._sessions: dict = {}
        self._attach_lock = asyncio.Lock()

    def create(self, cmd: str = "cmd.exe") -> "PTYSession":
        sid = uuid.uuid4().hex[:8]
        argv = _resolve_argv(cmd)
        home = os.path.expanduser("~")
        backend = "pywinpty" if WINPTY_AVAILABLE else "ConPTY-ctypes"
        log_message(f"Terminal: spawn {argv} via {backend}", color=COLOR_ACCENT)
        try:
            pty = _make_pty(argv, cwd=home)
        except (OSError, Exception) as e:
            raise RuntimeError(f"Errore PTY: {e}")
        session = PTYSession(id=sid, cmd=cmd, pty=pty, created_at=time.time(), alive=True)
        self._sessions[sid] = session
        asyncio.get_running_loop().create_task(self._read_loop(session))
        return session

    async def attach(self, sid: str, ws) -> None:
        async with self._attach_lock:
            session = self._sessions.get(sid)
            if not session:
                raise RuntimeError("sessione non trovata")
            if session.ws is not None:
                raise RuntimeError("sessione già in uso da altro client")
            session.ws = ws
        buf = bytes(session.output_buffer)
        for i in range(0, max(len(buf), 1), 4096):
            chunk = buf[i:i + 4096]
            if chunk:
                await ws.send(json.dumps({
                    "type": "term_output", "id": sid,
                    "data": base64.b64encode(chunk).decode()
                }))

    def detach(self, sid: str) -> None:
        s = self._sessions.get(sid)
        if s: s.ws = None

    def send(self, sid: str, data: str) -> None:
        s = self._sessions.get(sid)
        if not s or not s.alive:
            raise RuntimeError("sessione non disponibile")
        s.pty.write(data)

    def resize(self, sid: str, cols: int, rows: int) -> None:
        s = self._sessions.get(sid)
        if s and s.alive:
            try: s.pty.set_size(rows, cols)
            except Exception: pass

    def kill(self, sid: str) -> None:
        s = self._sessions.get(sid)
        if s:
            s.alive = False
            try: s.pty.close()
            except Exception: pass
            self._sessions.pop(sid, None)

    def list_sessions(self) -> list:
        return [{"id": s.id, "cmd": s.cmd, "alive": s.alive, "created_at": s.created_at}
                for s in self._sessions.values()]

    async def _read_loop(self, session: "PTYSession") -> None:
        loop = asyncio.get_running_loop()
        exit_code = 0
        while session.alive:
            try:
                raw = await loop.run_in_executor(None, session.pty.read, 4096)
                if not session.alive:
                    # kill() invocato durante la read in executor: esci subito
                    break
                if not raw:
                    if not session.pty.isalive():
                        exit_code = session.pty.exitstatus
                        break
                    await asyncio.sleep(0.01)
                    continue
                _append_ring(session.output_buffer, raw)
                if session.ws:
                    try:
                        await session.ws.send(json.dumps({
                            "type": "term_output", "id": session.id,
                            "data": base64.b64encode(raw).decode()
                        }))
                    except Exception:
                        session.ws = None
            except EOFError:
                exit_code = session.pty.exitstatus if session.alive else 0
                break
            except Exception as e:
                if session.alive:
                    log_message(f"Terminal errore [{session.id}]: {e}", color=COLOR_ERROR)
                break
        session.alive = False
        log_message(f"Terminal: {session.cmd} terminato (exit {exit_code})", color=COLOR_ACCENT)
        if session.ws:
            try:
                await session.ws.send(json.dumps({
                    "type": "term_closed", "id": session.id, "exit_code": exit_code
                }))
            except Exception:
                pass


_session_manager = SessionManager()

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

# --- STATO CONNESSIONE REMOTA ---
_remote_mode    = "none"   # "upnp" | "relay" | "none"
_external_ip    = None
_relay_code     = None
_upnp_obj       = None
_upnp_ports     = []

# --- RELAY SOCKET ADAPTER ---
class _RelaySocket:
    """Adatta il canale relay all'interfaccia websockets per handler()."""
    def __init__(self, relay_ws, client_ip: str = "relay"):
        self._relay  = relay_ws
        self._queue  = asyncio.Queue()
        self.remote_address = (client_ip, 0)
        self.local_address  = ("relay", WSS_PORT)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            msg = await self._queue.get()
            if msg is None:
                raise StopAsyncIteration
            return msg
        except asyncio.CancelledError:
            raise StopAsyncIteration

    async def send(self, msg: str) -> None:
        if not self.closed:
            try:
                await self._relay.send(msg)
            except Exception:
                pass

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(None)

    def push(self, msg: str) -> None:
        if not self.closed:
            self._queue.put_nowait(msg)

# --- BACKEND (WebSocket & HTTP) ---
async def handler(websocket):
    global TRUSTED_IP
    client_ip  = websocket.remote_address[0]
    is_remote  = not _is_private_ip(client_ip)

    if is_remote:
        # Connessione remota: autenticazione PIN obbligatoria
        if _check_auth_blocked(client_ip):
            await websocket.send(json.dumps({"type": "auth_blocked"}))
            await websocket.close()
            log_message(f"Bloccato (brute force): {client_ip}", color=COLOR_ERROR)
            return
        try:
            auth_raw  = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_data = json.loads(auth_raw)
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            await websocket.close()
            return
        if auth_data.get('type') != 'auth':
            await websocket.close()
            return
        pin_hash = hashlib.sha256(auth_data.get('pin', '').encode()).hexdigest()
        if pin_hash != _config.get('pin_hash', ''):
            _record_auth_fail(client_ip)
            fails = _auth_failures.get(client_ip, (0, 0))[0]
            await websocket.send(json.dumps({
                "type": "auth_fail",
                "remaining": max(0, AUTH_MAX_FAILS - fails)
            }))
            await websocket.close()
            log_message(f"Auth fallita ({fails}/{AUTH_MAX_FAILS}) da {client_ip}", color=COLOR_ERROR)
            return
        _clear_auth_fail(client_ip)
        await websocket.send(json.dumps({"type": "auth_ok"}))
        log_message(f"Connessione remota autorizzata: {client_ip}", color=COLOR_ACCENT)
        # Segnale sonoro per notificare l'accesso remoto
        try:
            ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
        except Exception:
            pass
    else:
        # Connessione locale: whitelist IP (comportamento originale)
        if TRUSTED_IP is None:
            TRUSTED_IP = client_ip
            log_message(f"Autorizzato: {client_ip}", color=COLOR_ACCENT)
        elif client_ip != TRUSTED_IP:
            log_message(f"Rifiutato: {client_ip}", color=COLOR_ERROR)
            await websocket.close()
            return
        log_message(f"Sessione attiva: {client_ip}", color=COLOR_ACCENT)

    last_backspace_time = 0
    last_ping_time = 0.0
    held_keys = set()
    TERM_INPUT_MAX = 8192

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', '')

                if msg_type == 'move':
                    x = max(-200, min(200, int(float(data.get('x', 0)))))
                    y = max(-200, min(200, int(float(data.get('y', 0)))))
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

                elif msg_type == 'ping':
                    now_t = time.time()
                    # Rate limit ping: max 1 ogni 100ms
                    if now_t - last_ping_time < 0.1:
                        continue
                    last_ping_time = now_t
                    await websocket.send(_PONG)

                elif msg_type == 'term_list':
                    await websocket.send(json.dumps({
                        "type": "term_sessions",
                        "sessions": _session_manager.list_sessions()
                    }))

                elif msg_type == 'term_create':
                    cmd = data.get('cmd', 'cmd.exe')
                    try:
                        session = _session_manager.create(cmd)
                        await websocket.send(json.dumps({
                            "type": "term_created", "id": session.id
                        }))
                    except RuntimeError as e:
                        await websocket.send(json.dumps({
                            "type": "term_error", "id": "", "msg": str(e)
                        }))

                elif msg_type == 'term_attach':
                    sid = data.get('id', '')
                    try:
                        await _session_manager.attach(sid, websocket)
                    except RuntimeError as e:
                        await websocket.send(json.dumps({
                            "type": "term_error", "id": sid, "msg": str(e)
                        }))

                elif msg_type == 'term_detach':
                    sid = data.get('id', '')
                    _session_manager.detach(sid)

                elif msg_type == 'term_input':
                    sid = data.get('id', '')
                    input_data = data.get('data', '')
                    if len(input_data) > TERM_INPUT_MAX:
                        input_data = input_data[:TERM_INPUT_MAX]
                    try:
                        _session_manager.send(sid, input_data)
                    except RuntimeError as e:
                        await websocket.send(json.dumps({
                            "type": "term_error", "id": sid, "msg": str(e)
                        }))

                elif msg_type == 'term_resize':
                    sid = data.get('id', '')
                    _session_manager.resize(
                        sid,
                        int(data.get('cols', 120)),
                        int(data.get('rows', 40))
                    )

                elif msg_type == 'term_kill':
                    sid = data.get('id', '')
                    _session_manager.kill(sid)
                    await websocket.send(json.dumps({
                        "type": "term_sessions",
                        "sessions": _session_manager.list_sessions()
                    }))

            except (ValueError, KeyError, TypeError) as e:
                log_message(f"Cmd ignorato: {e}", color=COLOR_MUTED)
            except Exception as e:
                log_message(f"Errore handler: {e}", color=COLOR_ERROR)

    except websockets.exceptions.ConnectionClosed:
        log_message("In attesa di connessione...", color=COLOR_MUTED)
    finally:
        mouse_button('up')
        for key in list(held_keys):
            key_up(key)
        held_keys.clear()

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

def start_https_server(ssl_ctx: ssl.SSLContext):
    httpd = None
    try:
        httpd = HTTPServer(("0.0.0.0", HTTPS_PORT), _QuietHTTPHandler)
        try:
            httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
        except ssl.SSLError as e:
            log_message(f"HTTPS SSL setup fallito: {e}", color=COLOR_ERROR)
            httpd.server_close()
            return
        httpd.serve_forever()
    except OSError:
        log_message(f"Errore: Porta HTTPS {HTTPS_PORT} occupata!", color=COLOR_ERROR)
    except Exception as e:
        log_message(f"HTTPS Server crash: {e}", color=COLOR_ERROR)
    finally:
        if httpd:
            try: httpd.server_close()
            except Exception: pass

# --- UPNP ---
def _cleanup_upnp():
    global _upnp_obj
    if _upnp_obj:
        for port in _upnp_ports:
            try: _upnp_obj.deleteportmapping(port, 'TCP')
            except Exception: pass

def _setup_upnp_sync() -> str | None:
    """Blocking UPnP discovery — run via executor to avoid blocking event loop."""
    global _upnp_obj, _external_ip
    try:
        import miniupnpc
        u = miniupnpc.UPnP()
        u.discoverdelay = 300
        if u.discover() == 0:
            return None
        u.selectigd()
        ext_ip = u.externalipaddress()
        if not ext_ip or ext_ip == '0.0.0.0':
            return None
        for port in [HTTPS_PORT, WSS_PORT]:
            try:
                u.addportmapping(port, 'TCP', LOCAL_IP, port, 'LiquidMouse', '')
                _upnp_ports.append(port)
            except Exception:
                pass
        _upnp_obj = u
        _external_ip = ext_ip
        atexit.register(_cleanup_upnp)
        return ext_ip
    except ImportError:
        return None
    except Exception:
        return None

async def setup_upnp() -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _setup_upnp_sync)

# --- RELAY ---
async def run_relay_client() -> None:
    global _remote_mode, _relay_code
    try:
        async with websockets.connect(
            f"{RELAY_URL}/register",
            ping_interval=30, ping_timeout=10, open_timeout=10
        ) as relay_ws:
            await relay_ws.send(json.dumps({"type": "register", "version": VERSION}))
            resp = json.loads(await asyncio.wait_for(relay_ws.recv(), timeout=10))
            if resp.get('type') != 'session':
                return
            _relay_code  = resp['code']
            _remote_mode = 'relay'
            log_message(f"Relay attivo: {_relay_code}", color=COLOR_ACCENT)
            _update_remote_ui()

            relay_socket: _RelaySocket | None = None

            async for raw in relay_ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get('type')
                if mtype == 'client_connected':
                    relay_socket = _RelaySocket(relay_ws, msg.get('ip', 'relay'))
                    asyncio.get_running_loop().create_task(handler(relay_socket))
                elif mtype == 'client_message' and relay_socket:
                    relay_socket.push(msg.get('data', ''))
                elif mtype == 'client_disconnected' and relay_socket:
                    await relay_socket.close()
                    relay_socket = None
    except Exception as e:
        log_message(f"Relay: disconnesso ({type(e).__name__})", color=COLOR_MUTED)
    finally:
        if _remote_mode == 'relay':
            _remote_mode = 'none'
            _relay_code  = None

def _update_remote_ui():
    """Aggiorna label remoto nella GUI (chiamare dal thread asyncio o via root.after)."""
    if _remote_status_var:
        if _remote_mode == 'upnp':
            root.after(0, lambda: _remote_status_var.set(
                f"UPnP  {_external_ip}:{HTTPS_PORT}   PIN: {_config.get('pin_plain','')}"
            ))
        elif _remote_mode == 'relay':
            root.after(0, lambda: _remote_status_var.set(
                f"Relay  {_relay_code}   PIN: {_config.get('pin_plain','')}"
            ))
        else:
            root.after(0, lambda: _remote_status_var.set("Remoto non disponibile"))

async def start_websocket_server():
    global _remote_mode
    log_message("Protocolli di comunicazione inizializzati.", color=COLOR_MUTED)
    ssl_ctx = ensure_ssl_cert(LOCAL_IP)

    # 1. Prova UPnP
    ext_ip = await setup_upnp()
    if ext_ip:
        _remote_mode = 'upnp'
        log_message(f"UPnP attivo: {ext_ip}", color=COLOR_OK)
        _update_remote_ui()
    else:
        # 2. Fallback relay (task separato, non blocca il server WS)
        asyncio.get_running_loop().create_task(run_relay_client())

    servers = [
        websockets.serve(handler, "0.0.0.0", PORT, ping_interval=20, ping_timeout=10),
    ]
    if ssl_ctx:
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

def run_services():
    threading.Thread(target=start_http_server, daemon=True).start()
    ssl_ctx = ensure_ssl_cert(LOCAL_IP)
    if ssl_ctx:
        threading.Thread(target=start_https_server, args=(ssl_ctx,), daemon=True).start()
    asyncio.run(start_websocket_server())

# --- GUI & SYSTEM TRAY ---
root                = tk.Tk()
ip_label_var        = None
status_var          = None
status_label        = None
_main_canvas        = None
_remote_status_var  = None

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
    if _remote_mode == 'upnp':
        return f'Remoto: UPnP  {_external_ip}:{HTTPS_PORT}'
    elif _remote_mode == 'relay':
        return f'Remoto: Relay  {_relay_code}'
    return 'Remoto: non disponibile'

def run_tray_service():
    menu = (
        pystray.MenuItem('Apri', restore_window, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: _get_remote_tray_label(), None, enabled=False),
        pystray.MenuItem('Reset connessione locale', lambda icon, item: reset_trusted_ip()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Esci', terminate_application),
    )
    pystray.Icon("LiquidMouse", create_tray_icon(), "Liquid Mouse", menu).run()

def setup_gui():
    global ip_label_var, status_var, status_label, _main_canvas, _remote_status_var

    root.title("Liquid Mouse")
    w, h = 560, 420
    sx = (root.winfo_screenwidth()  - w) // 2
    sy = (root.winfo_screenheight() - h) // 2
    root.geometry(f'{w}x{h}+{sx}+{sy}')

    root.overrideredirect(True)
    root.attributes('-alpha', 0.0)
    root.wm_attributes("-transparentcolor", COLOR_TRANSPARENT)
    root.configure(bg=COLOR_TRANSPARENT)

    try: root.iconbitmap(ICON_PATH)
    except Exception: pass

    canvas = tk.Canvas(root, bg=COLOR_TRANSPARENT, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    _main_canvas = canvas

    # --- Forma finestra: rettangolo arrotondato con bordo sottile ---
    def rounded_rect(c, x1, y1, x2, y2, r, **kw):
        pts = (x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r,
               x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2,
               x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r,
               x1, y1+r, x1, y1)
        return c.create_polygon(pts, smooth=True, **kw)

    PAD = 8
    rounded_rect(canvas, PAD, PAD, w-PAD, h-PAD, 22, fill=COLOR_BG, outline=COLOR_BORDER, width=1)

    # Linea separatore dopo titolo
    sep_y = 70
    canvas.create_line(PAD+30, sep_y, w-PAD-30, sep_y, fill=COLOR_BORDER, width=1)

    # Linea separatore prima sezione remota
    sep_y_remote = 215
    canvas.create_line(PAD+30, sep_y_remote, w-PAD-30, sep_y_remote, fill=COLOR_BORDER, width=1)

    # Linea separatore sopra lo status
    sep_y2 = h - 75
    canvas.create_line(PAD+30, sep_y2, w-PAD-30, sep_y2, fill=COLOR_BORDER, width=1)

    # --- Dragging finestra ---
    def get_pos(e):
        root.x_offset = e.x
        root.y_offset = e.y
    def move_window(e):
        root.geometry(f'+{e.x_root - root.x_offset}+{e.y_root - root.y_offset}')
    canvas.bind("<Button-1>", get_pos)
    canvas.bind("<B1-Motion>", move_window)

    # --- Titolo con accento colorato ---
    title_prefix = tk.Label(root, text="", font=("Consolas", 15, "bold"), bg=COLOR_BG, fg=COLOR_ACCENT)
    title_prefix.place(x=36, y=32)
    title_main = tk.Label(root, text="", font=("Consolas", 15, "bold"), bg=COLOR_BG, fg=COLOR_TEXT)
    title_main.place(x=66, y=32)

    # Badge versione (angolo in alto a destra, prima del close button)
    tk.Label(root, text=f"v{VERSION}", font=("Consolas", 8), bg=COLOR_BG, fg=COLOR_MUTED).place(x=w-100, y=38)

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
    lbl_ip_header = tk.Label(root, text="", font=("Consolas", 8), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_ip_header.place(x=36, y=88)

    ip_label_var = tk.StringVar(value="")
    tk.Label(root, textvariable=ip_label_var, font=("Consolas", 18), bg=COLOR_BG, fg=COLOR_TEXT).place(x=36, y=112)

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
        bg_img = Image.new("RGBA", (qr_w + pad_qr*2, qr_h + pad_qr*2), COLOR_SURFACE)
        mask = Image.new("L", bg_img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bg_img.size[0], bg_img.size[1]), radius=10, fill=255)
        bg_img.putalpha(mask)
        bg_img.paste(qr_raw, (pad_qr, pad_qr), qr_raw.split()[3])
        root.qr_photo = ImageTk.PhotoImage(bg_img)
        tk.Label(root, image=root.qr_photo, bg=COLOR_BG, bd=0).place(x=w-150, y=85)
    except Exception as e:
        log_message(f"QR Error: {e}", color=COLOR_ERROR)

    # Etichetta sotto QR
    tk.Label(root, text="SCANSIONA", font=("Consolas", 7), bg=COLOR_BG, fg=COLOR_MUTED).place(x=w-138, y=195)

    # --- Sezione Accesso Remoto ---
    tk.Label(root, text="ACCESSO REMOTO", font=("Consolas", 8), bg=COLOR_BG, fg=COLOR_MUTED).place(x=36, y=225)
    _remote_status_var = tk.StringVar(value="Inizializzazione...")
    tk.Label(root, textvariable=_remote_status_var,
             font=("Consolas", 9), bg=COLOR_BG, fg=COLOR_ACCENT,
             wraplength=480, justify="left").place(x=36, y=245)

    tk.Label(root, text="PIN", font=("Consolas", 8), bg=COLOR_BG, fg=COLOR_MUTED).place(x=36, y=272)
    pin_val = _config.get('pin_plain', '—')
    tk.Label(root, text=pin_val, font=("Consolas", 14, "bold"),
             bg=COLOR_BG, fg=COLOR_TEXT).place(x=36, y=288)

    # --- Sezione stato ---
    lbl_status_header = tk.Label(root, text="", font=("Consolas", 8), bg=COLOR_BG, fg=COLOR_MUTED)
    lbl_status_header.place(x=36, y=h-65)

    # Indicatore pallino stato
    root._status_dot = canvas.create_oval(36, h-42, 44, h-34, fill=COLOR_MUTED, outline="")

    status_var = tk.StringVar(value="")
    status_label = tk.Label(root, textvariable=status_var, font=("Consolas", 9), bg=COLOR_BG, fg=COLOR_MUTED)
    status_label.place(x=52, y=h-46)

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
        (title_main,        " Liquid Mouse",            25),
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
    threading.Thread(target=run_services, daemon=True).start()
    root.after(500, lambda: threading.Thread(target=run_tray_service, daemon=True).start())

_DOT_MAP = {COLOR_OK: COLOR_OK, COLOR_ACCENT: COLOR_OK, COLOR_ERROR: COLOR_ERROR}

def log_message(message, color=None):
    if color is None: color = COLOR_MUTED
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

if __name__ == "__main__":
    load_config()
    setup_gui()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
