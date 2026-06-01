"""
LiquidMouse Relay Server
Deploy on a VPS with a valid TLS certificate (e.g. via Caddy or nginx).
Usage: python relay_server.py [--host 0.0.0.0] [--port 8080]

Protocol:
  Server registers:  WS  /register  → sends {type:"register", version:"x.x.x"}
                     Relay responds  {type:"session", code:"XXXX-YYYY"}
  Client connects:   WS  /ws/{code}
  Server→relay→client: server sends {type:"server_msg", data:"<json>"}
  Client→relay→server: relay wraps as {type:"client_message", data:"<json>"}
"""

import asyncio
import secrets
import json
import logging
import argparse
import os
from http.server import SimpleHTTPRequestHandler
from http import HTTPStatus

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("relay")

_sessions: dict[str, dict] = {}  # code -> {server_ws, client_ws|None}


async def _handle_server(websocket: websockets.WebSocketServerProtocol) -> None:
    """Handles a server.pyw registration on /register."""
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") != "register":
            return
    except Exception:
        return

    code = secrets.token_urlsafe(8)
    _sessions[code] = {"server": websocket, "client": None}
    await websocket.send(json.dumps({"type": "session", "code": code}))
    log.info(f"Server registered  code={code}  ip={websocket.remote_address[0]}")

    try:
        async for raw in websocket:
            session = _sessions.get(code)
            if session and session["client"]:
                try:
                    await session["client"].send(raw)
                except Exception:
                    pass
    finally:
        _sessions.pop(code, None)
        log.info(f"Server disconnected  code={code}")


async def _handle_client(websocket: websockets.WebSocketServerProtocol, code: str) -> None:
    """Handles a browser client connecting to /ws/{code}."""
    session = _sessions.get(code)
    if not session:
        await websocket.close(1008, "session not found")
        return
    if session.get("client") is not None:
        await websocket.close(1008, "session already in use")
        return

    client_ip = websocket.remote_address[0]
    log.info(f"Client connected  code={code}  ip={client_ip}")

    try:
        await session["server"].send(json.dumps({
            "type": "client_connected", "ip": client_ip
        }))
    except Exception:
        return
    # Assign only after successful handshake to avoid dangling pointer
    session["client"] = websocket

    try:
        async for raw in websocket:
            if session.get("server"):
                try:
                    await session["server"].send(json.dumps({
                        "type": "client_message", "data": raw
                    }))
                except Exception:
                    break
    finally:
        session["client"] = None
        try:
            await session["server"].send(json.dumps({"type": "client_disconnected"}))
        except Exception:
            pass
        log.info(f"Client disconnected  code={code}")


_INDEX_HTML: bytes | None = None

def _load_index_html() -> bytes:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "index.html")
        with open(path, "rb") as f:
            _INDEX_HTML = f.read()
    return _INDEX_HTML


async def _ws_handler(websocket: websockets.WebSocketServerProtocol) -> None:
    path = websocket.request.path if hasattr(websocket, 'request') else getattr(websocket, 'path', '/')
    if path == "/register":
        await _handle_server(websocket)
    elif path.startswith("/ws/"):
        code = path[4:].split("?")[0]
        await _handle_client(websocket, code)
    else:
        await websocket.close(1008, "unknown path")


_STATIC_WHITELIST = {"/xterm.js", "/xterm.css", "/favicon.ico"}
_STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

class _RelayHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=_STATIC_DIR, **kwargs)

    def do_GET(self):
        raw_path = self.path.split("?")[0]
        # Path traversal protection: canonicalize and reject any ../ escape
        if ".." in raw_path:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        path = raw_path.rstrip("/")
        # Static asset whitelist
        if path in _STATIC_WHITELIST:
            super().do_GET()
            return
        # Relay session URL (/CODE) or root → serve index.html
        if path == "" or (len(path) > 1 and "/" not in path[1:]):
            body = _load_index_html()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, *args):
        pass


async def main(host: str, port: int) -> None:
    from http.server import HTTPServer
    import threading

    http_port = port + 1
    httpd = HTTPServer((host, http_port), _RelayHTTPHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info(f"HTTP  listening on {host}:{http_port}")

    async with websockets.serve(_ws_handler, host, port):
        log.info(f"Relay listening on {host}:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LiquidMouse relay server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
