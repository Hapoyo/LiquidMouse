"""UpnpMapper: motivo del fallimento riportato per ogni punto di uscita.

Prima ogni causa (libreria assente, nessun router, IP esterno non valido,
mapping rifiutato, eccezione qualsiasi) finiva nello stesso "non riuscito" nel
log, rendendo impossibile diagnosticare senza leggere il codice sorgente.
"""

import asyncio
import builtins
import sys
import types

from liquidmouse.net.upnp import UpnpMapper


class _FakeUPnP:
    """Sostituisce miniupnpc.UPnP() per i test."""

    def __init__(self, discover_result=1, external_ip="203.0.113.5",
                 mapping_error: Exception | None = None):
        self.discoverdelay = None
        self._discover_result = discover_result
        self._external_ip = external_ip
        self._mapping_error = mapping_error
        self.mapped_ports: list[int] = []
        self.deleted_ports: list[int] = []

    def discover(self):
        return self._discover_result

    def selectigd(self):
        pass

    def externalipaddress(self):
        return self._external_ip

    def addportmapping(self, port, proto, local_ip, ext_port, desc, remote_host):
        if self._mapping_error:
            raise self._mapping_error
        self.mapped_ports.append(port)

    def deleteportmapping(self, port, proto):
        self.deleted_ports.append(port)


class _FakeUPnPConflictThenOk(_FakeUPnP):
    """Rifiuta il primo addportmapping su una porta (ConflictInMappingEntry),
    ma riesce dopo la deleteportmapping del self-heal."""

    def __init__(self, *a, conflict_error=None, **k):
        super().__init__(*a, **k)
        self._conflict_error = conflict_error or Exception("ConflictInMappingEntry")
        self._tentativi: dict[int, int] = {}

    def addportmapping(self, port, proto, local_ip, ext_port, desc, remote_host):
        self._tentativi[port] = self._tentativi.get(port, 0) + 1
        if self._tentativi[port] == 1:
            raise self._conflict_error
        self.mapped_ports.append(port)


def _install_fake_miniupnpc(monkeypatch, fake_upnp: _FakeUPnP):
    modulo = types.ModuleType("miniupnpc")
    modulo.UPnP = lambda: fake_upnp
    monkeypatch.setitem(sys.modules, "miniupnpc", modulo)


class TestSuccesso:
    def test_ritorna_l_ip_esterno(self, monkeypatch):
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP())
        mapper = UpnpMapper(ports=[8443])
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert mapper.external_ip == "203.0.113.5"
        assert mapper.last_error is None

    def test_mappa_tutte_le_porte_richieste(self, monkeypatch):
        fake = _FakeUPnP()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper(ports=[8443, 8766])
        mapper.setup_sync("192.168.1.10")
        assert fake.mapped_ports == [8443, 8766]

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

    def test_mapping_rifiutato(self, monkeypatch):
        errore = RuntimeError("porta gia' in uso")
        _install_fake_miniupnpc(monkeypatch, _FakeUPnP(mapping_error=errore))
        mapper = UpnpMapper(ports=[8443])
        assert mapper.setup_sync("192.168.1.10") is None
        assert "8443" in mapper.last_error
        assert "porta gia' in uso" in mapper.last_error

    def test_conflitto_di_mappatura_si_autorisolve(self, monkeypatch):
        # Caso reale osservato: "ConflictInMappingEntry" quando una mappatura
        # residua di un avvio precedente (crash, kill, o IP locale cambiato)
        # occupa gia' la porta. Il self-heal libera e rimappa in un colpo solo,
        # senza che l'utente debba intervenire sul router.
        fake = _FakeUPnPConflictThenOk()
        _install_fake_miniupnpc(monkeypatch, fake)
        mapper = UpnpMapper(ports=[8443])
        assert mapper.setup_sync("192.168.1.10") == "203.0.113.5"
        assert mapper.last_error is None
        assert fake.deleted_ports == [8443]
        assert fake.mapped_ports == [8443]

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
        mapper = UpnpMapper(ports=[8443])
        mapper.setup_sync("192.168.1.10")
        mapper.cleanup()
        assert fake.deleted_ports == [8443]

    def test_cleanup_senza_setup_non_solleva(self):
        UpnpMapper().cleanup()


def test_setup_asincrono_delega_al_sincrono(monkeypatch):
    _install_fake_miniupnpc(monkeypatch, _FakeUPnP())
    mapper = UpnpMapper()
    assert asyncio.run(mapper.setup("192.168.1.10")) == "203.0.113.5"
