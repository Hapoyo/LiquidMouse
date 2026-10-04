"""Cambio di indirizzo di rete e ordine di avvio, con finti (nessun socket).

- il keepalive rivaluta l'IP LAN e, se cambia, rifà certificato, mapping UPnP e GUI;
- il touchpad in LAN parte prima di certificato e UPnP.
"""

import asyncio
import ssl

import pytest

pytest.importorskip("websockets")

import liquidmouse.net.server as server_mod
from liquidmouse.net.server import NetworkServices


class _Tls:
    def __init__(self, ctx=None, eventi=None):
        self.ctx = ctx if ctx is not None else object()
        self.chiamate = []
        self.eventi = eventi

    def context_for(self, local_ip):
        self.chiamate.append(local_ip)
        if self.eventi is not None:
            self.eventi.append(("tls", local_ip))
        return self.ctx


class _Upnp:
    def __init__(self, eventi=None, ext_ip="203.0.113.5"):
        self.ext_ip = ext_ip
        self.external_ip = None
        self.external_port = 8443
        self.last_error = None
        self.setup_ips = []
        self.eventi = eventi

    async def setup(self, local_ip):
        self.setup_ips.append(local_ip)
        if self.eventi is not None:
            self.eventi.append(("upnp", local_ip))
        self.external_ip = self.ext_ip
        return self.ext_ip

    def cleanup(self):
        pass


def _services(*, ip="192.168.1.10", nuovo=None, tls=None, upnp=None, **kw):
    corrente = {"ip": nuovo or ip}
    s = NetworkServices(
        config={}, auth_guard=None, trusted_peer=None, sessions=None, static=None,
        tls=tls or _Tls(), upnp=upnp or _Upnp(), local_ip=ip,
        ip_provider=lambda: corrente["ip"], **kw)
    s._ssl_ctx = object()
    s._corrente = corrente
    return s


class TestRivalutaIp:
    def test_ip_invariato_non_fa_nulla(self):
        s = _services()
        assert asyncio.run(s._refresh_local_ip()) is False
        assert s.tls.chiamate == []

    def test_senza_provider_non_controlla(self):
        s = NetworkServices(config={}, auth_guard=None, trusted_peer=None, sessions=None,
                            static=None, tls=_Tls(), upnp=_Upnp(), local_ip="192.168.1.10")
        assert asyncio.run(s._refresh_local_ip()) is False

    def test_cambio_aggiorna_ip_certificato_e_gui(self):
        visti = []
        s = _services(nuovo="10.0.0.7", on_local_ip_change=visti.append)
        assert asyncio.run(s._refresh_local_ip()) is True
        assert s.local_ip == "10.0.0.7"
        assert s.tls.chiamate == ["10.0.0.7"]      # SAN del nuovo indirizzo
        assert visti == ["10.0.0.7"]               # QR e indirizzo in finestra

    @pytest.mark.parametrize("assente", ["127.0.0.1", "", None])
    def test_rete_assente_non_sostituisce_l_ip_con_il_loopback(self, assente):
        s = _services(nuovo=assente)
        s._corrente["ip"] = assente
        assert asyncio.run(s._refresh_local_ip()) is False
        assert s.local_ip == "192.168.1.10"
        assert s.tls.chiamate == []

    def test_senza_tls_all_avvio_non_ne_crea_uno_dopo(self):
        # I server HTTPS non esistono: un contesto nuovo farebbe dichiarare il
        # remoto UPnP attivo su una porta chiusa.
        s = _services(nuovo="10.0.0.7")
        s._ssl_ctx = None
        asyncio.run(s._refresh_local_ip())
        assert s.tls.chiamate == [] and s._ssl_ctx is None

    def test_tls_non_rigenerato_tiene_il_vecchio_contesto(self):
        vecchio = object()
        s = _services(nuovo="10.0.0.7", tls=_Tls(ctx=None))
        s.tls.ctx = None
        s._ssl_ctx = vecchio
        asyncio.run(s._refresh_local_ip())
        assert s._ssl_ctx is vecchio

    def test_un_errore_nella_gui_non_blocca_il_resto(self):
        def rotto(ip):
            raise RuntimeError("finestra chiusa")

        s = _services(nuovo="10.0.0.7", on_local_ip_change=rotto)
        assert asyncio.run(s._refresh_local_ip()) is True
        assert s.local_ip == "10.0.0.7"


class TestKeepaliveConIp:
    def _esegui(self, s, durata=0.3):
        async def prova():
            try:
                await asyncio.wait_for(s._remote_keepalive(), timeout=durata)
            except asyncio.TimeoutError:
                pass
        asyncio.run(prova())

    def test_cambio_ip_rifa_subito_il_mapping_upnp(self, monkeypatch):
        # Rinnovo UPnP lontano (600 s) ma controllo IP frequente.
        monkeypatch.setattr(server_mod, "IP_CHECK_SECS", 0.01)
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 600)
        s = _services(nuovo="10.0.0.7")
        self._esegui(s)
        assert s.upnp.setup_ips[:1] == ["10.0.0.7"]    # mapping verso il nuovo IP
        assert len(s.upnp.setup_ips) == 1               # una volta sola: poi l'IP è stabile

    def test_senza_cambio_il_mapping_si_rinnova_solo_alla_scadenza(self, monkeypatch):
        monkeypatch.setattr(server_mod, "IP_CHECK_SECS", 0.01)
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 600)
        s = _services()
        self._esegui(s, 0.15)
        assert s.upnp.setup_ips == []

    def test_rinnovo_periodico_invariato(self, monkeypatch):
        monkeypatch.setattr(server_mod, "IP_CHECK_SECS", 0.01)
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 0.05)
        s = _services()
        self._esegui(s, 0.3)
        assert len(s.upnp.setup_ips) >= 2

    def test_errore_del_controllo_ip_non_ferma_il_ciclo(self, monkeypatch):
        monkeypatch.setattr(server_mod, "IP_CHECK_SECS", 0.01)
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 0.05)
        s = _services()
        chiamate = []

        def rotto():
            chiamate.append(1)
            raise OSError("scheda assente")

        s._ip_provider = rotto
        self._esegui(s, 0.3)
        assert len(chiamate) >= 3
        assert len(s.upnp.setup_ips) >= 2

    def test_cambio_ip_poi_stabile_ri_mappa_con_il_nuovo_indirizzo(self, monkeypatch):
        monkeypatch.setattr(server_mod, "IP_CHECK_SECS", 0.01)
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 600)
        s = _services()

        async def prova():
            task = asyncio.get_running_loop().create_task(s._remote_keepalive())
            await asyncio.sleep(0.05)
            s._corrente["ip"] = "172.16.5.9"
            await asyncio.sleep(0.1)
            task.cancel()

        asyncio.run(prova())
        assert s.upnp.setup_ips == ["172.16.5.9"]
        assert s.tls.chiamate == ["172.16.5.9"]


class _Serve:
    """Sostituisce websockets.serve registrando l'ordine di apertura."""

    def __init__(self, eventi):
        self.eventi = eventi

    def __call__(self, handler, host, port, **kw):
        eventi, porta = self.eventi, port

        class _Ctx:
            async def __aenter__(self_inner):
                eventi.append(("serve", porta))
                return self_inner

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()


class TestAvvioLanPrima:
    def test_le_porte_lan_si_aprono_prima_di_tls_e_upnp(self, monkeypatch):
        from liquidmouse.ports import HTTPS_PORT, PORT, WSS_PORT
        eventi = []
        monkeypatch.setattr(server_mod.websockets, "serve", _Serve(eventi))
        s = NetworkServices(config={}, auth_guard=None, trusted_peer=None, sessions=None,
                            static=None, tls=_Tls(eventi=eventi), upnp=_Upnp(eventi),
                            local_ip="192.168.1.10")

        async def prova():
            try:
                await asyncio.wait_for(s.start_websocket_server(), 0.3)
            except asyncio.TimeoutError:
                pass

        asyncio.run(prova())
        ordine = [e for e in eventi]
        assert ordine[0] == ("serve", PORT)            # il touchpad LAN per primo
        assert ordine.index(("serve", PORT)) < ordine.index(("tls", "192.168.1.10"))
        assert ordine.index(("tls", "192.168.1.10")) < ordine.index(("serve", HTTPS_PORT))
        assert ordine.index(("serve", WSS_PORT)) < ordine.index(("upnp", "192.168.1.10"))
        assert s.remote_mode == "upnp"

    def test_senza_server_avviati_non_parte_il_remoto(self, monkeypatch):
        eventi = []

        class _Occupata:
            def __call__(self, *a, **k):
                class _Ctx:
                    async def __aenter__(self_inner):
                        raise OSError("porta occupata")

                    async def __aexit__(self_inner, *x):
                        return False
                return _Ctx()

        monkeypatch.setattr(server_mod.websockets, "serve", _Occupata())
        s = NetworkServices(config={}, auth_guard=None, trusted_peer=None, sessions=None,
                            static=None, tls=_Tls(ctx=None, eventi=eventi),
                            upnp=_Upnp(eventi), local_ip="192.168.1.10")
        s.tls.ctx = None
        asyncio.run(s.start_websocket_server())
        assert ("upnp", "192.168.1.10") not in eventi


class TestTlsStessoContesto:
    def test_il_cambio_di_ip_ricarica_il_certificato_nello_stesso_contesto(self):
        pytest.importorskip("cryptography")
        from liquidmouse.security.tls import SelfSignedCert

        class Cfg(dict):
            def save(self):
                pass

        tls = SelfSignedCert(Cfg())
        primo = tls.context_for("192.168.1.10")
        cert_a = tls._config["ssl_cert"]
        secondo = tls.context_for("10.0.0.7")
        assert isinstance(primo, ssl.SSLContext)
        # I server in ascolto tengono l'oggetto: deve essere lo stesso.
        assert secondo is primo
        assert tls._config["ssl_cert"] != cert_a
        assert tls._config["ssl_ip"] == "10.0.0.7"
        # Stesso IP: nessuna rigenerazione.
        cert_b = tls._config["ssl_cert"]
        tls.context_for("10.0.0.7")
        assert tls._config["ssl_cert"] == cert_b
