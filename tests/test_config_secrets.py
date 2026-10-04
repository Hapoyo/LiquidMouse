"""PIN in chiaro e chiave privata TLS: su disco solo cifrati (DPAPI), con
migrazione delle config vecchie che li avevano in chiaro."""

import json
import sys

import pytest

from liquidmouse.config import Config
from liquidmouse.security.auth import pin_matches

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "tests")
from sftpfakes import FakeProtector  # noqa: E402


class _Rotto:
    """Protettore che non sa decifrare (config copiata su un altro utente/PC)."""

    def protect(self, text):
        return "x"

    def unprotect(self, blob):
        raise OSError("non decifrabile")


def _su_disco(cfg: Config) -> dict:
    return json.loads(cfg.path.read_text(encoding="utf-8"))


def _cfg(tmp_path, protector=FakeProtector()):
    return Config(path=tmp_path / "LiquidMouse" / "config.json", protector=protector)


class TestCifratura:
    def test_pin_e_chiave_non_stanno_in_chiaro_su_disco(self, tmp_path):
        cfg = _cfg(tmp_path)
        pin = cfg.load()["pin_plain"]
        cfg["ssl_key"] = "-----BEGIN RSA PRIVATE KEY-----"
        cfg.save()
        grezzo = cfg.path.read_text(encoding="utf-8")
        assert pin not in grezzo
        assert "BEGIN RSA" not in grezzo
        disco = _su_disco(cfg)
        assert "pin_plain" not in disco and "ssl_key" not in disco
        assert disco["pin_secret"] and disco["ssl_key_secret"]

    def test_in_memoria_restano_in_chiaro(self, tmp_path):
        # GUI e TLS leggono config.get("pin_plain") / ["ssl_key"]: il resto del
        # codice non deve sapere della cifratura.
        cfg = _cfg(tmp_path)
        pin = cfg.load()["pin_plain"]
        assert cfg.get("pin_plain") == pin

    def test_riavvio_ridecifra_lo_stesso_pin(self, tmp_path):
        pin = _cfg(tmp_path).load()["pin_plain"]
        di_nuovo = _cfg(tmp_path)
        data = di_nuovo.load()
        assert data["pin_plain"] == pin
        assert pin_matches(pin, data["pin_hash"])

    def test_l_hash_resta_su_disco_per_il_confronto(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg.load()
        assert _su_disco(cfg)["pin_hash"] == cfg["pin_hash"]

    def test_set_pin_cifra_il_nuovo_pin(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg.load()
        cfg.set_pin("nuovissimo")
        assert "nuovissimo" not in cfg.path.read_text(encoding="utf-8")
        assert _cfg(tmp_path).load()["pin_plain"] == "nuovissimo"

    def test_save_non_altera_i_dati_in_memoria(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg.load()
        cfg["ssl_key"] = "k"
        cfg.save()
        assert cfg["ssl_key"] == "k" and "ssl_key_secret" not in cfg.data


class TestMigrazione:
    def _vecchia(self, tmp_path):
        percorso = tmp_path / "LiquidMouse" / "config.json"
        percorso.parent.mkdir()
        from liquidmouse.security.auth import hash_pin
        percorso.write_text(json.dumps({
            "pin_plain": "pinvecchio", "pin_hash": hash_pin("pinvecchio"),
            "ssl_cert": "CERT", "ssl_key": "CHIAVE", "ssl_ip": "192.168.1.5",
            "sftp_profiles": [{"name": "pc"}],
        }), encoding="utf-8")
        return percorso

    def test_config_vecchia_viene_letta_e_riscritta_cifrata(self, tmp_path):
        percorso = self._vecchia(tmp_path)
        cfg = _cfg(tmp_path)
        data = cfg.load()
        # Il PIN non cambia (i telefoni configurati) e il certificato resta.
        assert data["pin_plain"] == "pinvecchio"
        assert pin_matches("pinvecchio", data["pin_hash"])
        assert (data["ssl_cert"], data["ssl_key"], data["ssl_ip"]) == (
            "CERT", "CHIAVE", "192.168.1.5")
        grezzo = percorso.read_text(encoding="utf-8")
        assert "pinvecchio" not in grezzo and "CHIAVE" not in grezzo
        # Il certificato (pubblico) e il resto non si toccano.
        disco = json.loads(grezzo)
        assert disco["ssl_cert"] == "CERT" and disco["sftp_profiles"] == [{"name": "pc"}]

    def test_dopo_la_migrazione_il_riavvio_da_lo_stesso_pin(self, tmp_path):
        self._vecchia(tmp_path)
        _cfg(tmp_path).load()
        assert _cfg(tmp_path).load()["pin_plain"] == "pinvecchio"

    def test_senza_protettore_non_riscrive(self, tmp_path):
        # Linux/test: comportamento invariato, il file resta com'e'.
        percorso = self._vecchia(tmp_path)
        prima = percorso.read_text(encoding="utf-8")
        cfg = _cfg(tmp_path, protector=None)
        assert cfg.load()["pin_plain"] == "pinvecchio"
        assert percorso.read_text(encoding="utf-8") == prima

    def test_senza_protettore_scrive_in_chiaro_come_prima(self, tmp_path):
        cfg = _cfg(tmp_path, protector=None)
        pin = cfg.load()["pin_plain"]
        assert _su_disco(cfg)["pin_plain"] == pin


class TestNonDecifrabile:
    def test_pin_non_decifrabile_ne_genera_uno_nuovo(self, tmp_path):
        _cfg(tmp_path).load()
        cfg = _cfg(tmp_path, protector=_Rotto())
        data = cfg.load()
        # Avvio possibile, PIN coerente con l'hash: l'utente rifa' il QR.
        assert data["pin_plain"] and pin_matches(data["pin_plain"], data["pin_hash"])

    def test_chiave_non_decifrabile_si_rigenera_con_il_certificato(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg.load()
        cfg["ssl_cert"], cfg["ssl_key"], cfg["ssl_ip"] = "C", "K", "1.2.3.4"
        cfg.save()
        rotto = _cfg(tmp_path, protector=_Rotto())
        data = rotto.load()
        assert not any(k in data for k in ("ssl_cert", "ssl_key", "ssl_ip"))

    def test_senza_protettore_un_segreto_cifrato_non_e_leggibile(self, tmp_path):
        cfg = _cfg(tmp_path)
        pin = cfg.load()["pin_plain"]
        altro = _cfg(tmp_path, protector=None)
        data = altro.load()
        assert data["pin_plain"] != pin and "pin_secret" not in data

    def test_protect_che_fallisce_ripiega_sul_chiaro(self, tmp_path):
        # Meglio un PIN in chiaro come prima che perderlo: il telefono resta valido.
        class Fallisce(FakeProtector):
            def protect(self, text):
                raise OSError("no")
        cfg = _cfg(tmp_path, protector=Fallisce())
        pin = cfg.load()["pin_plain"]
        assert _su_disco(cfg)["pin_plain"] == pin


def test_certificato_tls_resta_valido_dopo_la_migrazione(tmp_path):
    """Config vecchia con chiave in chiaro: il contesto TLS si costruisce con
    lo stesso certificato (quello che i browser hanno gia' accettato)."""
    pytest.importorskip("cryptography")
    from liquidmouse.security.tls import SelfSignedCert

    vecchia = Config(path=tmp_path / "c.json")  # senza protettore: in chiaro
    vecchia.load()
    tls = SelfSignedCert(vecchia)
    assert tls.context_for("192.168.1.9") is not None
    cert = vecchia["ssl_cert"]

    migrata = Config(path=tmp_path / "c.json", protector=FakeProtector())
    migrata.load()
    assert "PRIVATE KEY" not in (tmp_path / "c.json").read_text(encoding="utf-8")
    ctx = SelfSignedCert(migrata).context_for("192.168.1.9")
    assert ctx is not None
    assert migrata["ssl_cert"] == cert
    tls._cleanup_temps()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI esiste solo su Windows")
def test_dpapi_vera_andata_e_ritorno():
    from liquidmouse.security.dpapi import DpapiProtector

    p = DpapiProtector()
    blob = p.protect("segreto è ✓")
    assert "segreto" not in blob
    assert p.unprotect(blob) == "segreto è ✓"


def test_default_protector_assente_fuori_da_windows(monkeypatch):
    from liquidmouse.security import dpapi

    monkeypatch.setattr(dpapi.sys, "platform", "linux")
    assert dpapi.default_protector() is None
