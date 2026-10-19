"""UpnpMapper: motivo del fallimento riportato per ogni punto di uscita.

Prima ogni causa (libreria assente, nessun router, IP esterno non valido,
mapping rifiutato, eccezione qualsiasi) finiva nello stesso "non riuscito" nel
log, rendendo impossibile diagnosticare senza leggere il codice sorgente.
"""

import asyncio
import builtins
import sys
import types

from liquidmouse.net.upnp import EXTERNAL_PORTS, LEASE_SECS, MAPPING_DESC, UpnpMapper


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
        self.leases: list[int] = []               # lease di ogni addportmapping riuscito
        self.tentativi: list[int] = []            # lease di ogni chiamata, anche fallita
        self.solo_permanenti = False              # router che risponde 725 a lease != 0
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

    def addportmapping(self, ext_port, proto, local_ip, int_port, desc, remote_host,
                       lease=0):
        # Firma di miniupnpc 2.2.8/2.3.3: leaseDuration è il 7º argomento, opzionale.
        self.tentativi.append(lease)
        if self.solo_permanenti and lease != 0:
            raise Exception("OnlyPermanentLeasesSupported")
        if self._mapping_error:
            raise self._mapping_error
        if ext_port in self._rifiutate:
            raise self._rifiutate[ext_port]
        if ext_port in self.esistenti:
            raise Exception("ConflictInMappingEntry")
        self.mapped.append((ext_port, int_port))
        self.leases.append(lease)

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
        assert "doppio nat" in mapper.last_error
        assert "192.168.1.254" in mapper.last_error
        assert fake.mapped == []

    def test_ip_esterno_cgnat(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(external_ip="100.72.1.9"))
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert "cgnat" in mapper.last_error
        # Il pannello remoto tronca a 55 caratteri: la causa deve starci.
        assert len(mapper.last_error) < 55

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


class TestLeaseFinita:
    def test_chiede_una_lease_finita(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        UpnpMapper().setup_sync("192.168.1.10")
        assert fake.leases == [LEASE_SECS] and LEASE_SECS > 0

    def test_la_lease_regge_piu_rinnovi_del_keepalive(self):
        from liquidmouse.net.server import UPNP_KEEPALIVE_SECS
        assert LEASE_SECS >= 2 * UPNP_KEEPALIVE_SECS

    def test_il_keepalive_rinnova_la_lease_a_ogni_giro(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        mapper.setup_sync("192.168.1.10")      # rinnovo del keepalive
        assert fake.leases == [LEASE_SECS, LEASE_SECS]

    def test_725_ripiega_sulla_lease_zero(self, monkeypatch):
        fake = _FakeUPnP()
        fake.solo_permanenti = True
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert fake.tentativi == [LEASE_SECS, 0]
        assert fake.leases == [0]
        assert mapper.external_port == 8443

    def test_dopo_il_725_i_rinnovi_non_riprovano_la_lease_finita(self, monkeypatch):
        fake = _FakeUPnP()
        fake.solo_permanenti = True
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        mapper.setup_sync("192.168.1.10")
        assert fake.tentativi == [LEASE_SECS, 0, 0]

    def test_altri_errori_non_attivano_il_ripiego(self, monkeypatch):
        fake = _FakeUPnP(mapping_error=Exception("NotAuthorized"))
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") is None
        assert 0 not in fake.tentativi
        assert mapper._solo_permanenti is False


class TestResiduiEForwardAltrui:
    def test_all_avvio_toglie_il_residuo_nostro_anche_su_un_altra_porta(self, monkeypatch):
        # Residuo di un avvio precedente sulla 9443, mentre ora la 8443 è libera:
        # non darebbe mai conflitto, ma resterebbe aperto.
        fake = _FakeUPnP(esistenti={9443: ("192.168.1.7", 8443, MAPPING_DESC)})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        assert fake.deleted_ports == [9443]
        assert mapper.external_port == 8443

    def test_i_residui_si_cercano_una_volta_sola(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        fake2 = _FakeUPnP(esistenti={9443: ("192.168.1.7", 8443, MAPPING_DESC)})
        _install_fake_miniupnpc(monkeypatch, fake2)
        mapper.setup_sync("192.168.1.10")       # rinnovo: niente scansione
        assert fake2.deleted_ports == []

    def test_non_tocca_i_forward_di_altre_app_nemmeno_sullo_stesso_pc(self, monkeypatch):
        # Stesso IP del PC, ma un'altra descrizione: prima il confronto
        # sull'host faceva cancellare questo forward.
        fake = _FakeUPnP(esistenti={8443: ("192.168.1.10", 443, "AltraApp")})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert fake.deleted_ports == []
        assert fake.esistenti[8443][2] == "AltraApp"
        assert mapper.external_port == EXTERNAL_PORTS[1]

    def test_un_nostro_residuo_con_altro_host_si_libera(self, monkeypatch):
        fake = _FakeUPnP(esistenti={8443: ("192.168.1.99", 8443, MAPPING_DESC)})
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper()
        mapper.setup_sync("192.168.1.10")
        assert fake.deleted_ports == [8443]
        assert fake.mapped == [(8443, 8443)]

    def test_errore_nella_scansione_non_blocca_il_mapping(self, monkeypatch):
        fake = _FakeUPnP()

        def rotto(*a):
            raise Exception("SOAP")
        fake.getspecificportmapping = rotto
        _install_fake_miniupnpc(monkeypatch, fake)
        assert UpnpMapper().setup_sync("192.168.1.10") == "203.0.113.5"
