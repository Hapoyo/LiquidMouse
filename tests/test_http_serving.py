"""Serving HTTP degli asset, con richieste reali.

Questi test non hanno più bisogno di caricare server.pyw né di stubbare la GUI:
dopo l'estrazione l'handler si costruisce con `make_http_handler(static)` e si
avvia da solo. È la ragione pratica per cui il codice di rete è stato separato
dalla finestra.
"""

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from liquidmouse.net.server import make_http_handler
from liquidmouse.net.static import StaticFiles

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_url():
    static = StaticFiles(str(ROOT))
    mancanti = static.load()
    assert not mancanti, f"asset mancanti nel repo: {mancanti}"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(static))
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


class TestAsset:
    def test_la_radice_serve_il_client(self, base_url):
        stato, _, corpo = _get(base_url, "/")
        assert stato == 200
        assert b"<html" in corpo[:200].lower()

    def test_xterm_js_e_servito_intero(self, base_url):
        stato, headers, corpo = _get(base_url, "/xterm.js")
        assert stato == 200
        assert len(corpo) > 100_000
        assert "javascript" in headers.get("Content-Type", "")

    def test_content_length_coerente(self, base_url):
        _, headers, corpo = _get(base_url, "/xterm.css")
        assert int(headers["Content-Length"]) == len(corpo)

    def test_app_js_e_servito(self, base_url):
        # Dopo lo split di index.html il client non funziona senza questo:
        # un asset non elencato in STATIC_ROUTES darebbe 404 solo a runtime.
        stato, headers, corpo = _get(base_url, "/app.js")
        assert stato == 200
        assert b"function" in corpo
        assert "javascript" in headers.get("Content-Type", "")

    def test_app_css_e_servito(self, base_url):
        stato, headers, corpo = _get(base_url, "/app.css")
        assert stato == 200
        assert b"{" in corpo
        assert "text/css" in headers.get("Content-Type", "")

    def test_la_pagina_non_contiene_piu_il_client(self, base_url):
        # Il markup è ~170 righe: se tornasse a contenere CSS e JS inline,
        # sarebbe il segno che lo split è stato annullato.
        _, _, corpo = _get(base_url, "/")
        assert b"<style>" not in corpo
        assert b"<script>" not in corpo

    def test_head_non_manda_il_corpo(self, base_url):
        req = urllib.request.Request(base_url + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
            assert r.read() == b""

    def test_la_query_string_non_impedisce_di_servire(self, base_url):
        # Il client usa ?term=<id> e ?pin=<pin> sulla radice.
        assert _get(base_url, "/?term=abc123")[0] == 200

    def test_path_sconosciuto_da_404(self, base_url):
        assert _get(base_url, "/inesistente")[0] == 404


class TestRivalidazioneConEtag:
    def test_la_risposta_porta_un_etag(self, base_url):
        _, headers, _ = _get(base_url, "/")
        assert headers.get("ETag")

    def test_if_none_match_ottiene_304_senza_corpo(self, base_url):
        _, headers, _ = _get(base_url, "/")
        stato, _, corpo = _get(base_url, "/", {"If-None-Match": headers["ETag"]})
        # Senza questo, ogni reload ritrasferisce 283 KB di xterm.js.
        assert stato == 304
        assert corpo == b""

    def test_etag_diverso_non_da_304(self, base_url):
        stato, _, corpo = _get(base_url, "/", {"If-None-Match": '"altro"'})
        assert stato == 200
        assert corpo


class TestNonEspostiPiu:
    @pytest.mark.parametrize("path", [
        "/server.pyw", "/config.json", "/build.py", "/liquidmouse/config.py",
        "/../server.pyw", "/CLAUDE.md",
    ])
    def test_i_sorgenti_non_sono_scaricabili(self, base_url, path):
        # Prima il percorso LAN serviva l'intera directory su 0.0.0.0 senza
        # autenticazione: server.pyw e il config.json col PIN inclusi.
        assert _get(base_url, path)[0] == 404
