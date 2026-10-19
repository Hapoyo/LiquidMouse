"""
🧪 LiquidMouse — smoke test del server
Da eseguire con il server avviato (py -3.13 server.pyw oppure EXE/LiquidMouse.exe):

    py -3.13 tools/test_server.py

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
HTTP_PORT, HTTPS_PORT, WS_PORT = 8000, 8443, 8765

# Gli script del client, nell'ordine di index.html (static/app-core.js).
CLIENT_JS = ("app-core.js", "app-touchpad.js", "app-terminal.js", "app-files.js")

_ssl_noverify = ssl.create_default_context()
_ssl_noverify.check_hostname = False
_ssl_noverify.verify_mode = ssl.CERT_NONE

passed, failed = [], []

def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))

def test_ports():
    print("\n[1/4] Porte in ascolto")
    for port in (HTTP_PORT, HTTPS_PORT, WS_PORT):
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
    # Gli script del client e app.css vanno chiesti esplicitamente: dopo lo
    # split di index.html il JS non sta piu' nella pagina, e un asset non
    # elencato in STATIC_ROUTES o nel datas dello spec da' 404 solo qui.
    voci = [(f"http://{HOST}:{HTTP_PORT}/", "HTTP /"),
            (f"https://{HOST}:{HTTPS_PORT}/", "HTTPS / (porta unica)")]
    for nome in CLIENT_JS:
        voci.append((f"http://{HOST}:{HTTP_PORT}/{nome}", f"HTTP /{nome}"))
        voci.append((f"https://{HOST}:{HTTPS_PORT}/{nome}", f"HTTPS /{nome}"))
    voci += [(f"https://{HOST}:{HTTPS_PORT}/app.css", "HTTPS /app.css"),
             (f"https://{HOST}:{HTTPS_PORT}/xterm.js", "HTTPS /xterm.js")]
    for url, label in voci:
        try:
            r = urllib.request.urlopen(url, context=_ssl_noverify, timeout=10)
            body = r.read()
            check(label, r.status == 200 and len(body) > 1000, f"{r.status}, {len(body)} byte")
            if label.startswith("HTTP /app-"):
                test_client_js(body.decode("utf-8", errors="replace"), label)
        except Exception as e:
            check(label, False, str(e))

def test_client_js(js, label):
    # Regressione v2.2.x: un `break` in una catena if/else = SyntaxError che
    # uccide l'intero script → client congelato su "In attesa...".
    # Un `break` legale sta sempre dentro for/while/switch: qui verifichiamo
    # che ogni `break;` nel sorgente sia racchiuso in uno di quei costrutti
    # con una euristica di prossimità (nessun loop/switch → sospetto).
    #
    # NB: va eseguito sul corpo degli script, non su quello di /. Puntato alla
    # pagina scansionerebbe un HTML senza JS e passerebbe sempre, perdendo in
    # silenzio la copertura su questa regressione.
    if "function" not in js:
        check(f"{label}: il corpo analizzato contiene JS", False,
              "test_client_js ha ricevuto qualcosa che non e' il client")
        return
    suspects = []
    for m in re.finditer(r"\bbreak\s*;", js):
        window = js[max(0, m.start() - 600):m.start()]
        if not re.search(r"\b(for|while|switch)\b", window):
            line = js.count("\n", 0, m.start()) + 1
            suspects.append(line)
    check(f"{label}: nessun `break` sospetto", not suspects,
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
                            (f"wss://{HOST}:{HTTPS_PORT}", _ssl_noverify, "WSS 8443 (porta unica)")):
        try:
            check(label, asyncio.run(_ws_ping(url, ctx)))
        except Exception as e:
            check(label, False, str(e))

def test_version():
    print("\n[4/4] Versione dichiarata")
    try:
        # Dalla posizione del file e non dalla cartella corrente: lo script sta
        # in tools/ e si lancia da qualunque directory.
        radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(radice, "liquidmouse", "version.py"), encoding="utf-8").read()
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
        check("VERSION presente in liquidmouse/version.py", bool(m), m.group(1) if m else "")
    except OSError as e:
        check("VERSION presente in liquidmouse/version.py", False, str(e))

if __name__ == "__main__":
    print("=" * 50)
    print("   🧪 LIQUIDMOUSE — SMOKE TEST SERVER")
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
