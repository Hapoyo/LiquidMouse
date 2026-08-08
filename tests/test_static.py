"""Cache degli asset statici: whitelist, ETag e assenza di letture da disco."""

import pytest

from liquidmouse.net.static import (
    STATIC_ROUTES,
    StaticFiles,
    etag_matches,
)


@pytest.fixture
def sito(tmp_path):
    static_dir = tmp_path / "static"
    vendor_dir = static_dir / "vendor"
    vendor_dir.mkdir(parents=True)
    (static_dir / "index.html").write_bytes(b"<html>ciao</html>")
    (static_dir / "app.css").write_bytes(b"body{}")
    (static_dir / "app.js").write_bytes(b"// app")
    (vendor_dir / "xterm.js").write_bytes(b"// xterm")
    (vendor_dir / "xterm.css").write_bytes(b".x{}")
    (static_dir / "icon.ico").write_bytes(b"\x00icon")
    # Resta alla radice, fuori da static/: verifica che i sorgenti restino
    # irraggiungibili anche dopo la riorganizzazione.
    (tmp_path / "server.pyw").write_bytes(b"segreti")
    sf = StaticFiles(str(tmp_path))
    sf.load()
    return sf


class TestCaricamento:
    def test_carica_tutte_le_rotte(self, sito):
        assert len(sito) == len(STATIC_ROUTES)

    def test_radice_e_index_condividono_l_asset(self, sito):
        # Stesso file: deve essere caricato una volta sola in memoria.
        assert sito.get("/") is sito.get("/index.html")

    def test_riporta_i_file_mancanti(self, tmp_path):
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_bytes(b"x")
        sf = StaticFiles(str(tmp_path))
        mancanti = sf.load()
        assert "static/vendor/xterm.js" in mancanti
        assert "static/index.html" not in mancanti

    def test_un_file_mancante_non_impedisce_gli_altri(self, tmp_path):
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_bytes(b"x")
        sf = StaticFiles(str(tmp_path))
        sf.load()
        assert sf.get("/") is not None
        assert sf.get("/xterm.js") is None


class TestWhitelist:
    def test_i_file_non_elencati_non_sono_serviti(self, sito):
        # Il percorso LAN serviva l'intera directory: chiunque sulla rete
        # poteva scaricare server.pyw e la config.
        assert sito.get("/server.pyw") is None
        assert sito.get("/config.json") is None

    def test_path_traversal_respinto(self, sito):
        assert sito.get("/../server.pyw") is None
        assert sito.get("/..%2Fserver.pyw") is None
        assert sito.get("//etc/passwd") is None

    def test_path_sconosciuto(self, sito):
        assert sito.get("/inesistente") is None


class TestQueryString:
    def test_la_query_string_e_ignorata(self, sito):
        # Il client usa ?term=<id> e ?pin=<pin> sulla radice.
        assert sito.get("/?term=abc123") is sito.get("/")
        assert sito.get("/index.html?pin=xyz") is sito.get("/index.html")


class TestContenutoEHeader:
    def test_corpo_e_content_type(self, sito):
        asset = sito.get("/")
        assert asset.body == b"<html>ciao</html>"
        assert asset.content_type == "text/html; charset=utf-8"

    def test_content_type_del_javascript(self, sito):
        assert sito.get("/xterm.js").content_type.startswith("application/javascript")
        assert sito.get("/app.js").content_type.startswith("application/javascript")

    def test_content_type_del_css(self, sito):
        assert sito.get("/app.css").content_type.startswith("text/css")

    def test_etag_stabile_per_lo_stesso_contenuto(self, sito):
        assert sito.get("/").etag == sito.get("/index.html").etag

    def test_etag_diverso_per_contenuti_diversi(self, sito):
        assert sito.get("/").etag != sito.get("/xterm.js").etag

    def test_etag_e_quotato(self, sito):
        etag = sito.get("/").etag
        assert etag.startswith('"') and etag.endswith('"')


class TestEtagMatches:
    def test_corrispondenza_esatta(self):
        assert etag_matches('"abc"', '"abc"')

    def test_nessun_header(self):
        assert not etag_matches(None, '"abc"')
        assert not etag_matches("", '"abc"')

    def test_valore_diverso(self):
        assert not etag_matches('"altro"', '"abc"')

    def test_asterisco_copre_tutto(self):
        assert etag_matches("*", '"abc"')

    def test_lista_di_candidati(self):
        assert etag_matches('"x", "abc", "y"', '"abc"')

    def test_etag_debole(self):
        assert etag_matches('W/"abc"', '"abc"')
