"""Messaggi sftp_*: superficie esposta al client, quindi non fidata."""

import asyncio
import json

import pytest

from liquidmouse.net.protocol import ClientConnection, dispatch
from liquidmouse.net.sftp import SftpManager
from liquidmouse.net.transfers import REMOTE_DOWNLOAD_MAX, TransferRegistry
from tests.sftpfakes import FakeConfig, FakeProtector, FakeSftpClient, make_connector
from tests.test_protocol import FakeSessions, FakeWebSocket


@pytest.fixture
def client():
    return FakeSftpClient()


@pytest.fixture
def parts(client):
    m = SftpManager(FakeConfig(), connector=make_connector(client), protector=FakeProtector())
    return m, TransferRegistry()


@pytest.fixture
def ws():
    return FakeWebSocket()


def make_ctx(ws, parts, remote=False):
    sftp, transfers = parts
    return ClientConnection(ws, "192.168.1.10", FakeSessions(), sftp=sftp,
                            transfers=transfers, remote=remote)


def send(ctx, **payload):
    asyncio.run(dispatch(ctx, json.dumps(payload)))
    return ctx.ws.json_sent()


def collegato(ctx):
    send(ctx, type="sftp_profile_save", name="pc", host="h", port=22, user="u", password="pw")
    send(ctx, type="sftp_connect", name="pc")


def test_senza_file_manager_risponde_con_errore(ws):
    ctx = ClientConnection(ws, "192.168.1.10", FakeSessions())
    (r,) = send(ctx, type="sftp_list", path="/")
    assert r["type"] == "sftp_error"


def test_profili_e_connessione(ws, parts):
    ctx = make_ctx(ws, parts)
    risposte = send(ctx, type="sftp_profile_save", name="pc", host="h", port="22",
                    user="u", password="pw")
    assert risposte[-1]["type"] == "sftp_profiles"
    assert "pw" not in json.dumps(risposte)
    risposte = send(ctx, type="sftp_connect", name="pc")
    assert risposte[-1] == {"type": "sftp_connected", "name": "pc", "path": "/home"}


def test_la_porta_e_limitata(ws, parts):
    ctx = make_ctx(ws, parts)
    send(ctx, type="sftp_profile_save", name="pc", host="h", port=10 ** 9, user="u", password="")
    assert parts[0].list_profiles()[0]["port"] == 65535


def test_campi_non_stringa_non_sollevano(ws, parts):
    ctx = make_ctx(ws, parts)
    r = send(ctx, type="sftp_profile_save", name=["x"], host={}, port=None, user=5, password=1)
    assert r[-1]["type"] == "sftp_error"


def test_elenco(ws, parts):
    ctx = make_ctx(ws, parts)
    collegato(ctx)
    r = send(ctx, type="sftp_list", path="/home")[-1]
    assert r["type"] == "sftp_listing" and r["entries"][0]["name"] == "a.txt"


def test_elenco_senza_connessione(ws, parts):
    ctx = make_ctx(ws, parts)
    r = send(ctx, type="sftp_list", path="/home")[-1]
    assert r["type"] == "sftp_error" and r["code"] == "disconnected"


def test_operazioni_confermano_con_ok(ws, parts, client):
    ctx = make_ctx(ws, parts)
    collegato(ctx)
    assert send(ctx, type="sftp_mkdir", path="/home", name="n")[-1]["type"] == "sftp_ok"
    assert "/home/n" in client.dirs
    assert send(ctx, type="sftp_delete", path="/home", name="n", dir=True)[-1]["type"] == "sftp_ok"
    assert "/home/n" not in client.dirs


def test_nome_con_traversal_rifiutato(ws, parts):
    ctx = make_ctx(ws, parts)
    collegato(ctx)
    assert send(ctx, type="sftp_mkdir", path="/home", name="../x")[-1]["type"] == "sftp_error"


def test_delete_dir_deve_essere_true_esplicito(ws, parts, client):
    ctx = make_ctx(ws, parts)
    collegato(ctx)
    r = send(ctx, type="sftp_delete", path="/home", name="a.txt", dir="yes")
    assert r[-1]["type"] == "sftp_ok" and "/home/a.txt" not in client.files


class TestBiglietti:
    def test_download(self, ws, parts):
        ctx = make_ctx(ws, parts)
        collegato(ctx)
        r = send(ctx, type="sftp_ticket", direction="dl", path="/home", name="a.txt")[-1]
        assert r["type"] == "sftp_ticket" and r["size"] == 4
        assert parts[1].redeem(r["token"], "dl").path == "/home/a.txt"

    def test_download_di_file_inesistente(self, ws, parts):
        ctx = make_ctx(ws, parts)
        collegato(ctx)
        assert send(ctx, type="sftp_ticket", direction="dl", path="/home",
                    name="no")[-1]["type"] == "sftp_error"

    def test_direzione_non_valida(self, ws, parts):
        ctx = make_ctx(ws, parts)
        collegato(ctx)
        assert send(ctx, type="sftp_ticket", direction="x", path="/home",
                    name="a")[-1]["type"] == "sftp_error"

    def test_senza_connessione_niente_biglietto(self, ws, parts):
        ctx = make_ctx(ws, parts)
        r = send(ctx, type="sftp_ticket", direction="up", path="/home", name="n")[-1]
        assert r["type"] == "sftp_error"

    def test_upload_su_file_esistente_chiede_conferma(self, ws, parts):
        ctx = make_ctx(ws, parts)
        collegato(ctx)
        r = send(ctx, type="sftp_ticket", direction="up", path="/home", name="a.txt")[-1]
        assert r["code"] == "exists"
        r = send(ctx, type="sftp_ticket", direction="up", path="/home", name="a.txt",
                 overwrite=True)[-1]
        assert r["type"] == "sftp_ticket"

    def test_upload_da_remoto_non_disponibile(self, ws, parts):
        ctx = make_ctx(ws, parts, remote=True)
        collegato(ctx)
        r = send(ctx, type="sftp_ticket", direction="up", path="/home", name="n")[-1]
        assert r["code"] == "remote_upload"

    def test_download_remoto_ha_un_tetto(self, ws, parts, client):
        client.files["/home/grande"] = b""
        ctx = make_ctx(ws, parts, remote=True)
        collegato(ctx)
        client.stat = lambda p, orig=client.stat: _con_size(orig(p), REMOTE_DOWNLOAD_MAX + 1)
        r = send(ctx, type="sftp_ticket", direction="dl", path="/home", name="grande")[-1]
        assert r["code"] == "too_big"

    def test_alla_disconnessione_chiude_connessione_e_biglietti(self, ws, parts, client, monkeypatch):
        monkeypatch.setattr("liquidmouse.net.protocol.mouse_button", lambda s: None)
        ctx = make_ctx(ws, parts)
        collegato(ctx)
        token = send(ctx, type="sftp_ticket", direction="dl", path="/home",
                     name="a.txt")[-1]["token"]
        ctx.release_all()
        assert client.closed
        assert parts[1].redeem(token, "dl") is None


def _con_size(attr, size):
    attr.st_size = size
    return attr
