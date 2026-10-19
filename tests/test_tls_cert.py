"""Certificato auto-firmato: CN generico, SAN con l'IP LAN, rigenerazione
una tantum dei certificati con il vecchio CN."""

import pytest

pytest.importorskip("cryptography")

from cryptography import x509
from cryptography.x509.oid import NameOID

from liquidmouse.security.tls import CERT_CN, SelfSignedCert


class _Cfg(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.salvataggi = 0

    def save(self):
        self.salvataggi += 1


def _cert(cfg) -> x509.Certificate:
    return x509.load_pem_x509_certificate(cfg["ssl_cert"].encode())


class TestCertificato:
    def test_cn_generico_e_non_il_nome_del_programma(self):
        cfg = _Cfg()
        assert SelfSignedCert(cfg).context_for("192.168.1.10") is not None
        cn = _cert(cfg).subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == CERT_CN == "localhost"
        assert "liquid" not in cn.lower()

    def test_san_con_l_ip_lan(self):
        cfg = _Cfg()
        SelfSignedCert(cfg).context_for("192.168.1.10")
        san = _cert(cfg).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert [str(i) for i in san.get_values_for_type(x509.IPAddress)] == ["192.168.1.10"]

    def test_il_cn_nuovo_e_salvato(self):
        cfg = _Cfg()
        SelfSignedCert(cfg).context_for("192.168.1.10")
        assert cfg["ssl_cn"] == CERT_CN and cfg.salvataggi == 1

    def test_il_certificato_si_riusa_senza_rigenerare(self):
        cfg = _Cfg()
        SelfSignedCert(cfg).context_for("192.168.1.10")
        primo = cfg["ssl_cert"]
        SelfSignedCert(cfg).context_for("192.168.1.10")      # riavvio
        assert cfg["ssl_cert"] == primo and cfg.salvataggi == 1

    def test_un_certificato_col_vecchio_cn_si_rigenera_una_volta(self):
        cfg = _Cfg()
        SelfSignedCert(cfg).context_for("192.168.1.10")
        cfg.pop("ssl_cn")                    # come scritto dalle versioni precedenti
        vecchio = cfg["ssl_cert"]
        SelfSignedCert(cfg).context_for("192.168.1.10")
        assert cfg["ssl_cert"] != vecchio and cfg["ssl_cn"] == CERT_CN
        nuovo = cfg["ssl_cert"]
        SelfSignedCert(cfg).context_for("192.168.1.10")
        assert cfg["ssl_cert"] == nuovo
