"""File manager SFTP: profili, validazione dei percorsi, operazioni.

L'host è un finto in memoria (tests/sftpfakes.py): niente rete né paramiko.
"""

import pytest

from liquidmouse.net.sftp import (
    SftpError, SftpManager, join_path, validate_name, validate_path,
)
from tests.sftpfakes import FakeConfig, FakeProtector, FakeSftpClient, make_connector


@pytest.fixture
def client():
    return FakeSftpClient()


@pytest.fixture
def config():
    return FakeConfig()


@pytest.fixture
def log():
    return []


@pytest.fixture
def mgr(config, client, log):
    m = SftpManager(config, connector=make_connector(client, log=log), protector=FakeProtector())
    m.save_profile("pc", "127.0.0.1", 22, "jack", "segreto")
    return m


class TestValidazione:
    @pytest.mark.parametrize("nome", ["", ".", "..", "a/b", "a\\b", "a\x00b", "x" * 300, None, 5])
    def test_nomi_non_validi(self, nome):
        with pytest.raises(SftpError):
            validate_name(nome)

    def test_nome_valido(self):
        assert validate_name("relazione finale.txt") == "relazione finale.txt"

    @pytest.mark.parametrize("p", ["", "a\x00", "x" * 2000, None])
    def test_percorsi_non_validi(self, p):
        with pytest.raises(SftpError):
            validate_path(p)

    def test_normalizza_e_rende_assoluto(self):
        assert validate_path("home//jack/") == "/home/jack"
        assert validate_path("/a/b/../c") == "/a/c"
        assert validate_path("\\C:\\Users") == "/C:/Users"

    def test_join_rifiuta_nomi_che_escono_dalla_cartella(self):
        assert join_path("/home", "a.txt") == "/home/a.txt"
        with pytest.raises(SftpError):
            join_path("/home", "../etc")


class TestProfili:
    def test_la_vista_pubblica_non_contiene_il_segreto(self, mgr):
        (p,) = mgr.list_profiles()
        assert p == {"name": "pc", "host": "127.0.0.1", "port": 22,
                     "user": "jack", "has_password": True}

    def test_la_password_e_salvata_cifrata(self, mgr, config):
        salvato = config.data["sftp_profiles"][0]
        assert "segreto" not in str(config.data)
        assert salvato["secret"] == FakeProtector().protect("segreto")

    def test_password_vuota_conserva_quella_salvata(self, mgr, config):
        prima = config.data["sftp_profiles"][0]["secret"]
        mgr.save_profile("pc", "127.0.0.1", 22, "jack", "")
        assert config.data["sftp_profiles"][0]["secret"] == prima

    @pytest.mark.parametrize("host, porta, utente", [
        ("10.0.0.5", 22, "jack"), ("127.0.0.1", 2222, "jack"), ("127.0.0.1", 22, "altro"),
    ])
    def test_cambiando_destinazione_senza_password_il_segreto_si_azzera(
            self, mgr, config, host, porta, utente):
        # Altrimenti la password salvata per un host verrebbe presentata a un
        # altro (un client potrebbe farla recapitare a un server che controlla).
        mgr.save_profile("pc", host, porta, utente, "")
        assert config.data["sftp_profiles"][0]["secret"] == ""
        assert mgr.list_profiles()[0]["has_password"] is False

    def test_cambiando_destinazione_con_nuova_password_la_salva(self, mgr, config):
        mgr.save_profile("pc", "10.0.0.5", 22, "jack", "nuova")
        assert config.data["sftp_profiles"][0]["secret"] == FakeProtector().protect("nuova")

    def test_senza_cifratura_rifiuta_di_salvare_una_password(self, config):
        m = SftpManager(config, protector=None)
        with pytest.raises(SftpError, match="cifratura"):
            m.save_profile("pc", "h", 22, "u", "pw")
        assert "sftp_profiles" not in config.data

    @pytest.mark.parametrize("args", [
        ("", "h", 22, "u", ""), ("n", "", 22, "u", ""), ("n", "h", 0, "u", ""),
        ("n", "h", 70000, "u", ""), ("n", "h", "22", "u", ""), ("n", "h", 22, "u", 5),
    ])
    def test_campi_non_validi(self, mgr, args):
        with pytest.raises(SftpError):
            mgr.save_profile(*args)

    def test_elimina(self, mgr):
        mgr.delete_profile("pc")
        assert mgr.list_profiles() == []

    def test_limite_di_profili(self, mgr):
        for i in range(30):
            try:
                mgr.save_profile(f"p{i}", "h", 22, "u", "")
            except SftpError:
                break
        assert len(mgr.list_profiles()) <= 20


class TestConnessione:
    def test_connette_con_la_password_decifrata(self, mgr, log):
        assert mgr.connect(1, "pc") == "/home"
        assert log == [("127.0.0.1", 22, "jack", "segreto", None)]

    def test_profilo_inesistente(self, mgr):
        with pytest.raises(SftpError, match="inesistente"):
            mgr.connect(1, "boh")

    def test_prima_connessione_registra_l_impronta(self, mgr, config):
        mgr.connect(1, "pc")
        assert config.data["sftp_profiles"][0]["hostkey"] == "SHA256:abc"

    def test_impronta_nota_viene_passata_e_una_diversa_rifiutata(self, config, client, log):
        m = SftpManager(config, connector=make_connector(client, fp="SHA256:altra", log=log),
                        protector=FakeProtector())
        m.save_profile("pc", "h", 22, "u", "")
        config.data["sftp_profiles"][0]["hostkey"] = "SHA256:abc"
        with pytest.raises(SftpError) as e:
            m.connect(1, "pc")
        assert e.value.code == "hostkey"
        assert log[-1][4] == "SHA256:abc"

    def test_cambiando_host_l_impronta_si_azzera(self, mgr, config):
        mgr.connect(1, "pc")
        mgr.save_profile("pc", "10.0.0.5", 22, "jack", "")
        assert "hostkey" not in config.data["sftp_profiles"][0] or \
            not config.data["sftp_profiles"][0]["hostkey"]

    def test_senza_connessione_le_operazioni_falliscono(self, mgr):
        with pytest.raises(SftpError) as e:
            mgr.list_dir(99, "/home")
        assert e.value.code == "disconnected"

    def test_una_connessione_per_client_e_chiusura(self, mgr, client):
        mgr.connect(1, "pc")
        mgr.connect(2, "pc")
        mgr.close_owner(1)
        with pytest.raises(SftpError):
            mgr.list_dir(1, "/home")
        assert mgr.list_dir(2, "/home")
        mgr.close_all()
        assert client.closed


class TestOperazioni:
    @pytest.fixture(autouse=True)
    def _connesso(self, mgr):
        mgr.connect(1, "pc")

    def test_elenco_con_cartelle_prima(self, mgr, client):
        client.dirs.add("/home/zeta")
        client.files["/home/b.txt"] = b"xx"
        r = mgr.list_dir(1, "/home")
        assert [(v["name"], v["dir"]) for v in r["entries"]] == [
            ("zeta", True), ("a.txt", False), ("b.txt", False)]
        assert r["entries"][1]["size"] == 4

    def test_cartella_inesistente(self, mgr):
        with pytest.raises(SftpError, match="cartella"):
            mgr.list_dir(1, "/nulla")

    def test_mkdir_rename_delete(self, mgr, client):
        mgr.mkdir(1, "/home", "nuova")
        assert "/home/nuova" in client.dirs
        mgr.rename(1, "/home", "a.txt", "c.txt")
        assert "/home/c.txt" in client.files
        mgr.delete(1, "/home", "c.txt", False)
        assert "/home/c.txt" not in client.files
        mgr.delete(1, "/home", "nuova", True)
        assert "/home/nuova" not in client.dirs

    def test_rename_non_sovrascrive(self, mgr, client):
        client.files["/home/b.txt"] = b"x"
        with pytest.raises(SftpError) as e:
            mgr.rename(1, "/home", "a.txt", "b.txt")
        assert e.value.code == "exists"
        assert client.files["/home/b.txt"] == b"x"

    def test_nomi_con_separatori_rifiutati(self, mgr, client):
        for op in (lambda: mgr.mkdir(1, "/home", "../x"),
                   lambda: mgr.rename(1, "/home", "a.txt", "a/b"),
                   lambda: mgr.delete(1, "/home", "..", True)):
            with pytest.raises(SftpError):
                op()

    def test_lettura_a_blocchi(self, mgr):
        fh, size = mgr.open_read(1, "/home/a.txt")
        assert size == 4 and fh.read() == b"ciao"

    def test_download_di_una_cartella_rifiutato(self, mgr):
        with pytest.raises(SftpError, match="cartella"):
            mgr.file_size(1, "/home")

    def test_scrittura(self, mgr, client):
        fh = mgr.open_write(1, "/home/nuovo.bin")
        fh.write(b"12345")
        fh.close()
        assert client.files["/home/nuovo.bin"] == b"12345"
        assert mgr.exists(1, "/home/nuovo.bin")
        assert not mgr.exists(1, "/home/no")
