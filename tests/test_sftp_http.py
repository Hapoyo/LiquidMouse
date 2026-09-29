"""Trasferimenti HTTP con biglietto: /sftp/dl e /sftp/up, con richieste reali
sulla porta di pagina e con la strada remota (process_request di websockets)."""

import asyncio
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

pytest.importorskip("websockets")

from liquidmouse.net.server import NetworkServices, download_headers, make_http_handler
from liquidmouse.net.sftp import SftpManager
from liquidmouse.net.transfers import DOWNLOAD, UPLOAD, TransferRegistry
from tests.sftpfakes import FakeConfig, FakeProtector, FakeSftpClient, make_connector


@pytest.fixture
def client():
    c = FakeSftpClient()
    c.files["/home/grande.bin"] = bytes(range(256)) * 1000    # più di un blocco
    c.files["/home/è \"strano\".txt"] = b"x"
    return c


@pytest.fixture
def sftp(client):
    m = SftpManager(FakeConfig(), connector=make_connector(client), protector=FakeProtector())
    m.save_profile("pc", "h", 22, "u", "pw")
    m.connect(1, "pc")
    return m


@pytest.fixture
def transfers():
    return TransferRegistry()


@pytest.fixture
def base(sftp, transfers):
    static = SimpleNamespace(get=lambda path: None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_http_handler(static, sftp, transfers))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _req(url, data=None, method=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class TestDownload:
    def test_scarica_il_file_intero(self, base, transfers, client):
        t = transfers.issue(1, DOWNLOAD, "/home/grande.bin")
        stato, h, corpo = _req(f"{base}/sftp/dl?t={t}")
        assert stato == 200
        assert corpo == client.files["/home/grande.bin"]
        assert int(h["Content-Length"]) == len(corpo)
        assert h["Content-Disposition"] == "attachment; filename*=UTF-8''grande.bin"

    def test_il_biglietto_non_si_riusa(self, base, transfers):
        t = transfers.issue(1, DOWNLOAD, "/home/a.txt")
        assert _req(f"{base}/sftp/dl?t={t}")[0] == 200
        assert _req(f"{base}/sftp/dl?t={t}")[0] == 403

    @pytest.mark.parametrize("q", ["", "?t=", "?t=inventato", "?x=1"])
    def test_senza_biglietto_valido_403(self, base, q):
        assert _req(f"{base}/sftp/dl{q}")[0] == 403

    def test_biglietto_di_upload_non_scarica(self, base, transfers):
        t = transfers.issue(1, UPLOAD, "/home/a.txt")
        assert _req(f"{base}/sftp/dl?t={t}")[0] == 403

    def test_connessione_chiusa_nel_frattempo(self, base, transfers, sftp):
        t = transfers.issue(1, DOWNLOAD, "/home/a.txt")
        sftp.close_owner(1)
        assert _req(f"{base}/sftp/dl?t={t}")[0] == 410

    def test_nome_con_virgolette_non_rompe_l_header(self):
        h = dict(download_headers('a"\r\nX: y.txt', 1))
        assert "\r" not in h["Content-Disposition"] and '"' not in h["Content-Disposition"]


class TestUpload:
    def test_carica_il_file(self, base, transfers, client):
        dati = bytes(range(256)) * 700
        t = transfers.issue(1, UPLOAD, "/home/nuovo.bin")
        stato, _, corpo = _req(f"{base}/sftp/up?t={t}", data=dati, method="POST")
        assert stato == 200 and b"ok" in corpo
        assert client.files["/home/nuovo.bin"] == dati

    def test_senza_biglietto_403_e_nulla_scritto(self, base, client):
        stato, _, _ = _req(f"{base}/sftp/up?t=x", data=b"abc", method="POST")
        assert stato == 403
        assert "/home/x" not in client.files

    def test_biglietto_di_download_non_scrive(self, base, transfers, client):
        t = transfers.issue(1, DOWNLOAD, "/home/a.txt")
        assert _req(f"{base}/sftp/up?t={t}", data=b"zz", method="POST")[0] == 403
        assert client.files["/home/a.txt"] == b"ciao"

    def test_altri_post_sono_404(self, base):
        assert _req(f"{base}/altro", data=b"x", method="POST")[0] == 404

    def test_get_sull_upload_e_404(self, base, transfers):
        t = transfers.issue(1, UPLOAD, "/home/n")
        assert _req(f"{base}/sftp/up?t={t}")[0] == 404


class _Conn:
    def respond(self, status, text):
        return SimpleNamespace(status_code=int(status), body=text.encode())


def _request(path, upgrade=""):
    return SimpleNamespace(path=path, headers={"Upgrade": upgrade} if upgrade else {})


@pytest.fixture
def services(sftp, transfers):
    return NetworkServices(
        config={}, auth_guard=None, trusted_peer=None, sessions=None,
        static=SimpleNamespace(get=lambda p: None), tls=None, upnp=None,
        local_ip="127.0.0.1", sftp=sftp, transfers=transfers)


def _run(services, path):
    return asyncio.run(services.https_process_request(_Conn(), _request(path)))


class TestStradaRemota:
    def test_websocket_prosegue_l_handshake(self, services):
        assert asyncio.run(services.https_process_request(
            _Conn(), _request("/", upgrade="websocket"))) is None

    def test_download_con_biglietto(self, services, transfers):
        t = transfers.issue(1, DOWNLOAD, "/home/a.txt")
        r = _run(services, f"/sftp/dl?t={t}")
        assert r.status_code == 200 and r.body == b"ciao"
        assert r.headers["Content-Length"] == "4"

    def test_senza_biglietto_403(self, services):
        assert _run(services, "/sftp/dl?t=boh").status_code == 403

    def test_oltre_il_tetto_410(self, services, transfers, monkeypatch):
        monkeypatch.setattr("liquidmouse.net.server.REMOTE_DOWNLOAD_MAX", 2)
        t = transfers.issue(1, DOWNLOAD, "/home/a.txt")
        assert _run(services, f"/sftp/dl?t={t}").status_code == 410

    def test_gli_asset_restano_serviti(self, services):
        assert _run(services, "/nonesiste").status_code == 404
