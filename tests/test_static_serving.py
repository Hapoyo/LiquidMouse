"""Servizio degli asset: gzip precalcolato, URL versionati, cache immutabile,
header di sicurezza. Sia sulla porta HTTP (LAN) sia sulla strada remota."""

import asyncio
import gzip
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from liquidmouse.net.static import (
    CSP, IMMUTABLE, SECURITY_HEADERS, STATIC_ROUTES, StaticFiles, accepts_gzip,
)
from liquidmouse.version import VERSION

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sito():
    sf = StaticFiles(str(ROOT), version=VERSION)
    assert not sf.load()
    return sf


class TestAcceptEncoding:
    @pytest.mark.parametrize("valore", ["gzip", "gzip, deflate, br", "br;q=1, gzip;q=0.5",
                                        "*", "GZIP", "x-gzip"])
    def test_ammesso(self, valore):
        assert accepts_gzip(valore)

    @pytest.mark.parametrize("valore", [None, "", "identity", "br", "gzip;q=0", "gzip; q=0.0"])
    def test_non_ammesso(self, valore):
        assert not accepts_gzip(valore)


class TestGzip:
    def test_i_file_di_testo_hanno_la_versione_gzip(self, sito):
        for url in ("/app.js", "/app.css", "/xterm.js", "/", "/motion.js"):
            asset = sito.get(url)
            assert asset.gzip_body is not None, url
            assert len(asset.gzip_body) < len(asset.body)
            assert gzip.decompress(asset.gzip_body) == asset.body

    def test_il_gzip_e_deterministico(self, sito):
        again = StaticFiles(str(ROOT), version=VERSION)
        again.load()
        assert again.get("/app.js").gzip_body == sito.get("/app.js").gzip_body
        assert again.get("/app.js").gzip_etag == sito.get("/app.js").gzip_etag

    def test_etag_diversi_per_le_due_rappresentazioni(self, sito):
        a = sito.get("/app.js")
        assert a.etag != a.gzip_etag
        assert a.gzip_etag.startswith('"') and a.gzip_etag.endswith('"')

    def test_serve_gzip_solo_se_richiesto(self, sito):
        con = sito.serve("/app.js", "gzip, br")
        senza = sito.serve("/app.js", None)
        h = dict(con.headers)
        assert h["Content-Encoding"] == "gzip"
        assert h["Vary"] == "Accept-Encoding"
        assert int(h["Content-Length"]) == len(con.body)
        assert gzip.decompress(con.body) == senza.body
        assert "Content-Encoding" not in dict(senza.headers)
        assert dict(senza.headers)["Vary"] == "Accept-Encoding"

    def test_304_per_l_etag_della_rappresentazione_giusta(self, sito):
        gz = dict(sito.serve("/app.js", "gzip").headers)["ETag"]
        plain = dict(sito.serve("/app.js", None).headers)["ETag"]
        assert sito.serve("/app.js", "gzip", gz).status == 304
        assert sito.serve("/app.js", None, plain).status == 304
        # L'ETag dell'altra rappresentazione non vale.
        assert sito.serve("/app.js", "gzip", plain).status == 200
        assert sito.serve("/app.js", None, gz).status == 200

    def test_il_304_non_ha_corpo_e_porta_cache_control(self, sito):
        etag = dict(sito.serve("/xterm.js", None).headers)["ETag"]
        r = sito.serve("/xterm.js?v=1", None, etag)
        assert r.status == 304 and r.body == b""
        assert dict(r.headers)["Cache-Control"] == IMMUTABLE

    def test_un_asset_non_comprimibile_non_ha_vary(self, tmp_path):
        (tmp_path / "x.bin").write_bytes(bytes(range(256)))
        sf = StaticFiles(str(tmp_path), {"/x": ("x.bin", "application/octet-stream")})
        sf.load()
        r = sf.serve("/x", "gzip")
        assert "Vary" not in dict(r.headers) and "Content-Encoding" not in dict(r.headers)

    def test_non_comprime_se_non_conviene(self, tmp_path):
        # Byte quasi casuali: gzip li ingrandirebbe.
        import os
        (tmp_path / "r.js").write_bytes(os.urandom(64))
        sf = StaticFiles(str(tmp_path), {"/r.js": ("r.js", "application/javascript")})
        sf.load()
        assert sf.get("/r.js").gzip_body is None


class TestUrlVersionati:
    def test_index_referenzia_gli_asset_con_la_versione(self, sito):
        html = sito.get("/").body.decode()
        for nome in ("app.js", "app.css", "xterm.js", "xterm.css", "motion.js", "icon.ico"):
            assert f'"{nome}?v={VERSION}"' in html, nome

    def test_ogni_riferimento_locale_e_versionato_e_servito(self, sito):
        html = sito.get("/").body.decode()
        rif = re.findall(r'(?:src|href)="([^"#]+)"', html)
        assert rif
        for r in rif:
            path, _, query = r.partition("?")
            assert query == f"v={VERSION}", r
            assert sito.get("/" + path) is not None, r

    def test_senza_versione_index_resta_com_e(self):
        sf = StaticFiles(str(ROOT))
        sf.load()
        assert b"?v=" not in sf.get("/").body

    def test_il_sorgente_su_disco_non_e_toccato(self):
        assert b"?v=" not in (ROOT / "static" / "index.html").read_bytes()

    def test_la_query_non_cambia_l_asset_servito(self, sito):
        assert sito.get(f"/app.js?v={VERSION}") is sito.get("/app.js")


class TestCacheControl:
    def test_index_si_rivalida_sempre(self, sito):
        for p in ("/", "/index.html", "/?term=abc", f"/index.html?v={VERSION}"):
            assert dict(sito.serve(p).headers)["Cache-Control"] == "no-cache", p

    def test_asset_versionati_sono_immutabili_per_un_anno(self, sito):
        for nome in ("app.js", "app.css", "xterm.js", "xterm.css", "motion.js", "icon.ico"):
            cc = dict(sito.serve(f"/{nome}?v={VERSION}").headers)["Cache-Control"]
            assert cc == "max-age=31536000, immutable", nome

    def test_senza_versione_resta_no_cache(self, sito):
        # Un URL senza ?v= non cambia con la release: cacheato un anno resterebbe
        # vecchio dopo un aggiornamento.
        assert dict(sito.serve("/app.js").headers)["Cache-Control"] == "no-cache"

    def test_i_font_sono_immutabili(self, sito):
        cc = dict(sito.serve("/fonts/SpaceMono-Regular.ttf").headers)["Cache-Control"]
        assert cc == IMMUTABLE

    def test_path_fuori_whitelist(self, sito):
        assert sito.serve("/server.pyw") is None


class TestSicurezza:
    def test_header_richiesti(self):
        d = dict(SECURITY_HEADERS)
        assert d["X-Content-Type-Options"] == "nosniff"
        assert d["Referrer-Policy"] == "no-referrer"
        assert d["X-Frame-Options"] == "DENY"
        assert d["Content-Security-Policy"] == CSP

    def test_csp_non_ammette_script_inline_ne_origini_esterne(self):
        script = re.search(r"script-src ([^;]+)", CSP).group(1)
        assert script == "'self'"
        assert "unsafe-eval" not in CSP
        assert "frame-ancestors 'none'" in CSP
        assert "ws:" in CSP and "wss:" in CSP      # il WebSocket è su un'altra porta
        assert "http" not in CSP.replace("https", "")   # nessuna origine esterna

    def test_il_client_non_usa_cio_che_la_csp_blocca(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        for vietato in ("eval(", "new Function(", "javascript:", "document.write("):
            assert vietato not in js, vietato


@pytest.fixture
def base_url(sito):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(sito))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _handler(static):
    from liquidmouse.net.server import make_http_handler
    return make_http_handler(static)


def _get(base, path, headers=None, method="GET"):
    req = urllib.request.Request(base + path, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class TestPortaLan:
    def test_gzip_con_accept_encoding(self, base_url):
        stato, h, corpo = _get(base_url, f"/xterm.js?v={VERSION}", {"Accept-Encoding": "gzip"})
        assert stato == 200 and h["Content-Encoding"] == "gzip"
        assert h["Vary"] == "Accept-Encoding"
        assert int(h["Content-Length"]) == len(corpo)
        assert len(corpo) < 120_000          # xterm.js intero sono ~283 KB
        assert gzip.decompress(corpo).startswith((b"!function", b"/*", b"(function", b"var"))

    def test_senza_accept_encoding_e_identita(self, base_url):
        stato, h, corpo = _get(base_url, "/app.js", {"Accept-Encoding": "identity"})
        assert stato == 200 and "Content-Encoding" not in h
        assert b"function" in corpo

    def test_head_con_gzip_non_manda_corpo_ma_la_lunghezza(self, base_url):
        stato, h, corpo = _get(base_url, "/app.js", {"Accept-Encoding": "gzip"}, "HEAD")
        assert stato == 200 and corpo == b"" and int(h["Content-Length"]) > 0

    def test_304_con_etag_gzip(self, base_url):
        _, h, _ = _get(base_url, "/app.js", {"Accept-Encoding": "gzip"})
        stato, h2, corpo = _get(base_url, "/app.js",
                                {"Accept-Encoding": "gzip", "If-None-Match": h["ETag"]})
        assert stato == 304 and corpo == b""

    @pytest.mark.parametrize("path", ["/", "/app.js", "/inesistente", "/server.pyw",
                                      "/fonts/SpaceMono-Regular.ttf"])
    def test_header_di_sicurezza_su_ogni_risposta(self, base_url, path):
        _, h, _ = _get(base_url, path)
        for nome, valore in SECURITY_HEADERS:
            assert h[nome] == valore, (path, nome)

    def test_cache_control_per_pagina_e_asset(self, base_url):
        assert _get(base_url, "/")[1]["Cache-Control"] == "no-cache"
        _, h, corpo = _get(base_url, "/")
        # La pagina servita punta davvero a URL che il server serve immutabili.
        for m in re.findall(rb'src="(app\.js\?v=[^"]+)"', corpo):
            assert _get(base_url, "/" + m.decode())[1]["Cache-Control"] == IMMUTABLE


class _Conn:
    def respond(self, status, text):
        from websockets.datastructures import Headers
        return SimpleNamespace(status_code=int(status), body=text.encode(), headers=Headers())


def _services(static):
    pytest.importorskip("websockets")
    from liquidmouse.net.server import NetworkServices
    return NetworkServices(config={}, auth_guard=None, trusted_peer=None, sessions=None,
                           static=static, tls=None, upnp=None, local_ip="127.0.0.1")


def _remote(services, path, headers=None):
    req = SimpleNamespace(path=path, headers=headers or {})
    return asyncio.run(services.https_process_request(_Conn(), req))


class TestStradaRemota:
    def test_gzip_cache_e_sicurezza(self, sito):
        r = _remote(_services(sito), f"/app.js?v={VERSION}", {"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers["Content-Encoding"] == "gzip"
        assert r.headers["Cache-Control"] == IMMUTABLE
        assert gzip.decompress(r.body) == sito.get("/app.js").body
        for nome, valore in SECURITY_HEADERS:
            assert r.headers[nome] == valore

    def test_304_remoto(self, sito):
        s = _services(sito)
        etag = _remote(s, "/", {"Accept-Encoding": "gzip"}).headers["ETag"]
        r = _remote(s, "/", {"Accept-Encoding": "gzip", "If-None-Match": etag})
        assert r.status_code == 304 and r.body == b""
        assert r.headers["Cache-Control"] == "no-cache"

    def test_404_porta_gli_header_di_sicurezza(self, sito):
        r = _remote(_services(sito), "/nonesiste")
        assert r.status_code == 404
        assert r.headers["X-Frame-Options"] == "DENY"
