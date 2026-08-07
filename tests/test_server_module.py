"""Carica davvero server.pyw e prova il server HTTP statico.

È l'unico test che tocca l'entrypoint. Serve a intercettare gli errori che
l'analisi statica non vede — un simbolo rimasto indietro dopo un'estrazione, un
side-effect reintrodotto a import time — senza richiedere Windows né uno schermo:
tkinter, pystray, PIL, qrcode e ctypes.windll sono sostituiti da stub.

Se questo test inizia a fallire con un ImportError su una libreria GUI, quasi
certamente il core ha ripreso a dipendere dalla GUI.
"""

import ctypes
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _Qualunque:
    """Stub permissivo: accetta qualsiasi chiamata e attributo."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, nome):
        return _Qualunque()

    def __call__(self, *a, **k):
        return _Qualunque()


def _installa_stub(monkeypatch):
    def modulo(nome, **attrs):
        m = types.ModuleType(nome)
        for k, v in attrs.items():
            setattr(m, k, v)
        monkeypatch.setitem(sys.modules, nome, m)
        return m

    tk = modulo(
        "tkinter", Tk=_Qualunque, Canvas=_Qualunque, Label=_Qualunque,
        Frame=_Qualunque, Entry=_Qualunque, Button=_Qualunque,
        StringVar=_Qualunque, Toplevel=_Qualunque, Text=_Qualunque,
        Scale=_Qualunque, PhotoImage=_Qualunque,
        HORIZONTAL="h", END="end", BOTH="both", LEFT="left",
    )
    tk.messagebox = modulo("tkinter.messagebox", showerror=lambda *a, **k: None)
    modulo("pystray", Icon=_Qualunque, Menu=_Qualunque, MenuItem=_Qualunque)
    modulo("PIL", Image=_Qualunque(), ImageDraw=_Qualunque(), ImageTk=_Qualunque())
    modulo("qrcode", QRCode=_Qualunque, make=lambda *a, **k: _Qualunque())
    if not hasattr(ctypes, "windll"):
        monkeypatch.setattr(ctypes, "windll", _Qualunque(), raising=False)


@pytest.fixture
def server_module(monkeypatch):
    pytest.importorskip("websockets")
    _installa_stub(monkeypatch)
    monkeypatch.syspath_prepend(str(ROOT))
    mod = types.ModuleType("server_pyw")
    mod.__file__ = str(ROOT / "server.pyw")
    codice = (ROOT / "server.pyw").read_text(encoding="utf-8")
    exec(compile(codice, "server.pyw", "exec"), mod.__dict__)
    return mod


class TestCaricamento:
    def test_il_modulo_si_carica(self, server_module):
        assert server_module is not None

    @pytest.mark.parametrize("nome", [
        "main", "handler", "_authorize", "setup_gui", "run_services",
        "start_http_server", "start_websocket_server", "_https_process_request",
        "_gui_log_sink", "start_background_services", "init_process",
        "reset_trusted_ip", "load_config", "ensure_ssl_cert",
        "create_tray_icon", "run_tray_service", "_on_session_created",
    ])
    def test_i_simboli_attesi_esistono(self, server_module, nome):
        assert hasattr(server_module, nome), f"{nome} non definito"

    def test_il_log_non_solleva_prima_che_la_gui_esista(self, server_module):
        # _gui_log_sink viene registrato in main() prima di setup_gui(): i
        # messaggi emessi nel frattempo non devono far cadere l'avvio.
        server_module._gui_log_sink("prova", color="#ffffff")


@pytest.fixture
def http_server(server_module):
    mancanti = server_module._static.load()
    assert not mancanti, f"asset mancanti nel repo: {mancanti}"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_module._StaticHTTPHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class TestServingStatico:
    def test_la_radice_serve_il_client(self, http_server):
        stato, _, corpo = _get(http_server, "/")
        assert stato == 200
        assert b"<html" in corpo[:200].lower()

    def test_xterm_js_e_servito_intero(self, http_server):
        stato, headers, corpo = _get(http_server, "/xterm.js")
        assert stato == 200
        assert len(corpo) > 100_000
        assert "javascript" in headers.get("Content-Type", "")

    def test_la_query_string_non_impedisce_di_servire(self, http_server):
        # Il client usa ?term=<id> e ?pin=<pin> sulla radice.
        assert _get(http_server, "/?term=abc123")[0] == 200

    def test_path_sconosciuto_da_404(self, http_server):
        assert _get(http_server, "/inesistente")[0] == 404


class TestRivalidazioneConEtag:
    def test_la_risposta_porta_un_etag(self, http_server):
        _, headers, _ = _get(http_server, "/")
        assert headers.get("ETag")

    def test_if_none_match_ottiene_304_senza_corpo(self, http_server):
        _, headers, _ = _get(http_server, "/")
        etag = headers.get("ETag")
        stato, _, corpo = _get(http_server, "/", {"If-None-Match": etag})
        # Senza questo, ogni reload della pagina ritrasferisce 283 KB.
        assert stato == 304
        assert corpo == b""


class TestNonEspostiPiu:
    @pytest.mark.parametrize("path", [
        "/server.pyw", "/config.json", "/build.py", "/liquidmouse/config.py",
    ])
    def test_i_sorgenti_non_sono_scaricabili(self, http_server, path):
        # Prima il percorso LAN serviva l'intera directory su 0.0.0.0 senza
        # autenticazione: server.pyw incluso.
        assert _get(http_server, path)[0] == 404
