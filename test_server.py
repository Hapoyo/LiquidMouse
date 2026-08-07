"""
🧪 LiquidControl — smoke test del server
Da eseguire con il server avviato (py -3.13 server.pyw oppure EXE/LiquidControl.exe):

    py -3.13 test_server.py

Verifica: porte in ascolto, pagina servita (HTTP e HTTPS porta unica),
canale comandi WS/WSS (ping→pong), assenza dell'errore JS che uccideva
il client (regressione v2.2.x: `break` illegale → "In attesa..." perenne).
"""
import asyncio
import json
import os
import re
import socket
import ssl
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "127.0.0.1"
HTTP_PORT, HTTPS_PORT, WS_PORT, WSS_PORT = 8000, 8443, 8765, 8766

_ssl_noverify = ssl.create_default_context()
_ssl_noverify.check_hostname = False
_ssl_noverify.verify_mode = ssl.CERT_NONE

passed, failed = [], []

def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))

def test_ports():
    print("\n[1/4] Porte in ascolto")
    for port in (HTTP_PORT, HTTPS_PORT, WS_PORT, WSS_PORT):
        s = socket.socket()
        s.settimeout(3)
        try:
            s.connect((HOST, port))
            check(f"porta {port}", True)
        except OSError as e:
            check(f"porta {port}", False, str(e))
        finally:
            s.close()

def test_static():
    print("\n[2/4] Client statico (HTTP 8000 + porta unica HTTPS 8443)")
    for url, label in ((f"http://{HOST}:{HTTP_PORT}/", "HTTP /"),
                       (f"https://{HOST}:{HTTPS_PORT}/", "HTTPS / (porta unica)"),
                       (f"https://{HOST}:{HTTPS_PORT}/xterm.js", "HTTPS /xterm.js")):
        try:
            r = urllib.request.urlopen(url, context=_ssl_noverify, timeout=10)
            body = r.read()
            check(label, r.status == 200 and len(body) > 1000, f"{r.status}, {len(body)} byte")
            if label == "HTTP /":
                test_client_js(body.decode("utf-8", errors="replace"))
        except Exception as e:
            check(label, False, str(e))

def test_client_js(html):
    # Regressione v2.2.x: un `break` in una catena if/else = SyntaxError che
    # uccide l'intero script → client congelato su "In attesa...".
    # Un `break` legale sta sempre dentro for/while/switch: qui verifichiamo
    # che ogni `break;` nel sorgente sia racchiuso in uno di quei costrutti
    # con una euristica di prossimità (nessun loop/switch → sospetto).
    suspects = []
    for m in re.finditer(r"\bbreak\s*;", html):
        window = html[max(0, m.start() - 600):m.start()]
        if not re.search(r"\b(for|while|switch)\b", window):
            line = html.count("\n", 0, m.start()) + 1
            suspects.append(line)
    check("nessun `break` sospetto nel client JS", not suspects,
          f"righe: {suspects}" if suspects else "")

async def _ws_ping(url, ssl_ctx=None):
    import websockets
    async with websockets.connect(url, ssl=ssl_ctx) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        return resp.get("type") == "pong"

def test_ws():
    print("\n[3/4] Canale comandi (ping→pong)")
    for url, ctx, label in ((f"ws://{HOST}:{WS_PORT}", None, "WS 8765"),
                            (f"wss://{HOST}:{HTTPS_PORT}", _ssl_noverify, "WSS 8443 (porta unica)"),
                            (f"wss://{HOST}:{WSS_PORT}", _ssl_noverify, "WSS 8766 (legacy)")):
        try:
            check(label, asyncio.run(_ws_ping(url, ctx)))
        except Exception as e:
            check(label, False, str(e))

def test_version():
    print("\n[4/4] Versione dichiarata")
    try:
        src = open(os.path.join("liquidmouse", "version.py"), encoding="utf-8").read()
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
        check("VERSION presente in liquidmouse/version.py", bool(m), m.group(1) if m else "")
    except OSError as e:
        check("VERSION presente in liquidmouse/version.py", False, str(e))

if __name__ == "__main__":
    print("=" * 50)
    print("   🧪 LIQUIDCONTROL — SMOKE TEST SERVER")
    print("=" * 50)
    test_ports()
    test_static()
    test_ws()
    test_version()
    print("\n" + "=" * 50)
    print(f"   Esito: {len(passed)} OK, {len(failed)} FALLITI")
    if failed:
        print("   Falliti: " + ", ".join(failed))
    print("=" * 50)
    sys.exit(1 if failed else 0)
