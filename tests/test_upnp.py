"""UpnpMapper: motivo del fallimento riportato per ogni punto di uscita.

Prima ogni causa (libreria assente, nessun router, IP esterno non valido,
mapping rifiutato, eccezione qualsiasi) finiva nello stesso "non riuscito" nel
log, rendendo impossibile diagnosticare senza leggere il codice sorgente.
"""

import asyncio
import builtins
import sys
import types

from liquidmouse.net.upnp import EXTERNAL_PORTS, UpnpMapper


class _FakeUPnP:
    """Sostituisce miniupnpc.UPnP() per i test.

    `rifiutate`: porta esterna → eccezione sollevata da addportmapping.
    `esistenti`: porta esterna → (host, porta interna, descrizione) già mappata.
    """

    def __init__(self, discover_result=1, external_ip="203.0.113.5",
                 mapping_error: Exception | None = None,
                 rifiutate: dict[int, Exception] | None = None,
                 esistenti: dict[int, tuple] | None = None):
        self.discoverdelay = None
        self._discover_result = discover_result
        self._external_ip = external_ip
        self._mapping_error = mapping_error
        self._rifiutate = dict(rifiutate or {})
        self.esistenti = dict(esistenti or {})
        self.mapped: list[tuple[int, int]] = []   # (esterna, interna)
        self.deleted_ports: list[int] = []

    @property
    def mapped_ports(self) -> list[int]:
        return [est for est, _int in self.mapped]

    def discover(self):
        return self._discover_result

    def selectigd(self):
        pass

    def externalipaddress(self):
        return self._external_ip

    def addportmapping(self, ext_port, proto, local_ip, int_port, desc, remote_host):
        if self._mapping_error:
            raise self._mapping_error
        if ext_port in self._rifiutate:
            raise self._rifiutate[ext_port]
        if ext_port in self.esistenti:
            raise Exception("ConflictInMappingEntry")
        self.mapped.append((ext_port, int_port))

    def getspecificportmapping(self, ext_port, proto):
        voce = self.esistenti.get(ext_port)
        return None if voce is None else (*voce, True, 0)

    def deleteportmapping(self, port, proto):
        self.deleted_ports.append(port)
        self.esistenti.pop(port, None)


def _install_fake_miniupnpc(monkeypatch, fake_upnp: _FakeUPnP):
    modulo = types.ModuleType("miniupnpc")
    modulo.UPnP = lambda: fake_upnp
    monkeypatch.setitem(sys.modules, "miniupnpc", modulo)


class TestSuccesso:
    def test_ritorna_l_ip_esterno(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP())
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert mapper.external_ip == "203.0.113.5"
        assert mapper.external_port == 8443
        assert mapper.last_error is None

    def test_mappa_la_8443_sulla_8443_interna(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        UpnpMapper().setup_sync("192.168.1.10")
        assert fake.mapped == [(8443, 8443)]

    def test_applica_il_ritardo_di_discovery(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        UpnpMapper().setup_sync("192.168.1.10")
        assert fake.discoverdelay == 2000


class TestMotiviDiFallimento:
    def test_libreria_assente(self, monkeypatch):
        # sys.modules[nome] = None e' il modo standard per far fallire un
        # `import nome` successivo con ImportError, senza toccare i builtin.
        monkeypatch.setitem(sys.modules, "miniupnpc", None)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "miniupnpc" in mapper.last_error

    def test_libreria_rompe_l_import_con_errore_diverso_da_import_error(self, monkeypatch):
        # Caso limite reale: un'estensione nativa compilata male (DLL
        # incompatibili in un EXE PyInstaller) puo' far fallire `import
        # miniupnpc` con un errore diverso da ImportError. Prima del fix
        # quell'eccezione si propagava non gestita fuori da setup_sync,
        # lasciando last_error a None: lo stesso sintomo di "remoto non
        # disponibile" ma senza alcun dettaglio diagnostico nel log.
        monkeypatch.delitem(sys.modules, "miniupnpc", raising=False)
        vero_import = builtins.__import__

        def import_che_rompe(name, *args, **kwargs):
            if name == "miniupnpc":
                raise OSError("impossibile caricare miniupnpc.dll")
            return vero_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_che_rompe)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert mapper.last_error is not None
        assert "miniupnpc" in mapper.last_error

    def test_nessun_router_trovato(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(discover_result=0))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "discovery" in mapper.last_error

    def test_ip_esterno_non_valido(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(external_ip="0.0.0.0"))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "doppio NAT" in mapper.last_error

    def test_ip_esterno_assente(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(external_ip=""))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None

    def test_ip_esterno_privato_e_doppio_nat(self, monkeypatch):
        # Router proprio dietro il modem dell'operatore: il mapping
        # riuscirebbe, ma aprirebbe la porta solo verso il modem.
        fake = _FakeUPnP(external_ip="192.168.1.254")
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "doppio NAT" in mapper.last_error
        assert fake.mapped == []

    def test_ip_esterno_cgnat(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(external_ip="100.72.1.9"))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "CGNAT" in mapper.last_error

    def test_mapping_rifiutato_su_tutte_le_porte(self, monkeypatch):
        errore = RuntimeError("porta gia' in uso")
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(mapping_error=errore))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert mapper.external_port is None
        for porta in EXTERNAL_PORTS:
            assert str(porta) in mapper.last_error
        assert "porta gia' in uso" in mapper.last_error


class TestPorteDiRiserva:
    def test_8443_rifiutata_usa_la_successiva(self, monkeypatch):
        # Caso reale: il modem dell'operatore tiene la 8443 per sé e rifiuta
        # il mapping. Prima il remoto restava chiuso; ora si passa alla 9443
        # esterna, sempre inoltrata alla 8443 del PC.
        fake = _FakeUPnP(rifiutate={8443: Exception("NotAuthorized")})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert mapper.external_port == EXTERNAL_PORTS[1]
        assert fake.mapped == [(EXTERNAL_PORTS[1], 8443)]

    def test_mapping_nostro_residuo_si_autorisolve(self, monkeypatch):
        # "ConflictInMappingEntry" per un mapping residuo di un avvio
        # precedente (crash, kill, IP locale cambiato): si libera e si rimappa.
        fake = _FakeUPnP(esistenti={8443: ("192.168.1.7", 8443, "LiquidMouse")})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert mapper.external_port == 8443
        assert fake.deleted_ports == [8443]
        assert fake.mapped == [(8443, 8443)]

    def test_mapping_di_un_altro_dispositivo_non_si_tocca(self, monkeypatch):
        fake = _FakeUPnP(esistenti={8443: ("192.168.1.50", 443, "NAS")})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert fake.deleted_ports == []
        assert mapper.external_port == EXTERNAL_PORTS[1]

    def test_il_rinnovo_riprova_prima_la_porta_in_uso(self, monkeypatch):
        # Cambiare porta a ogni keepalive invaliderebbe il QR già scansionato.
        fake = _FakeUPnP(rifiutate={8443: Exception("NotAuthorized")})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")

        fake2 = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake2)
        mapper.setup_sync("192.168.1.10")
        assert mapper.external_port == EXTERNAL_PORTS[1]
        assert fake2.mapped == [(EXTERNAL_PORTS[1], 8443)]

    def test_il_rinnovo_su_un_altra_porta_chiude_la_vecchia(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")

        fake2 = _FakeUPnP(rifiutate={8443: Exception("NotAuthorized")})
        _install_fake_miniupnpc(monkeypatch, fake2)
        mapper.setup_sync("192.168.1.10")
        assert mapper.external_port == EXTERNAL_PORTS[1]
        assert fake.deleted_ports == [8443]

    def test_successo_azzera_l_errore_precedente(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(discover_result=0))
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        assert mapper.last_error is not None

        _install_fake_miniupnpc(monkeypatch, _FakeUPnP())
        mapper.setup_sync("192.168.1.10")
        assert mapper.last_error is None


class TestCleanup:
    def test_rimuove_i_mapping_creati(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        mapper.cleanup()
        assert fake.deleted_ports == [8443]

    def test_cleanup_senza_setup_non_solleva(self):
        UpnpMapper().cleanup()


def test_setup_asincrono_delega_al_sincrono(monkeypatch):
    _install_fake_miniupnpc(monkeypatch, _FakeUPnP())
    mapper = UpnpMapper()
    assert asyncio.run(mapper.setup("192.168.1.10")) == "203.0.113.5"
