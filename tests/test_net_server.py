"""NetworkServices.start_websocket_server: coerenza fra TLS e UPnP nella
decisione del remote_mode.

UPnP e TLS sono indipendenti (vengono risolti da due oggetti diversi, iniettati
separatamente): se UPnP apre la porta ma il certificato non è disponibile
(manca `cryptography`, o la generazione fallisce), i server HTTPS_PORT/WSS_PORT
non vengono nemmeno aggiunti alla lista `servers` più sotto. Dichiarare
comunque il remoto attivo sarebbe un falso positivo — un QR che punta a una
porta chiusa, il rovescio del sintomo "remoto non disponibile".

Nessun bind reale: `websockets.serve` è sostituito da un context manager
finto, così il test non apre socket e gira anche in CI senza permessi di rete.
"""

import asyncio

import pytest

pytest.importorskip("websockets")

import liquidmouse.net.server as server_mod
from liquidmouse.net.server import NetworkServices


class _FakeServeCtx:
    """Sostituisce l'oggetto ritornato da websockets.serve: nessun bind reale."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeTls:
    def __init__(self, ctx):
        self._ctx = ctx

    def context_for(self, local_ip):
        return self._ctx


class _FakeUpnp:
    def __init__(self, ext_ip):
        self._ext_ip = ext_ip
        self.external_ip = None
        self.last_error = None

    async def setup(self, local_ip):
        self.external_ip = self._ext_ip
        return self._ext_ip

    def cleanup(self):
        pass


def _build_services(monkeypatch, *, ssl_ctx, ext_ip):
    monkeypatch.setattr(server_mod.websockets, "serve", lambda *a, **k: _FakeServeCtx())
    return NetworkServices(
        config={}, auth_guard=None, trusted_peer=None, sessions=None,
        static=None, tls=_FakeTls(ssl_ctx), upnp=_FakeUpnp(ext_ip),
        local_ip="192.168.1.10",
    )


async def _avvia_e_ferma(services, timeout=0.2):
    """`start_websocket_server` non ritorna mai finché il processo vive
    (`await asyncio.Future()`): la decisione su remote_mode è già presa prima
    di quel punto, quindi basta lasciarla girare un istante e interromperla."""
    try:
        await asyncio.wait_for(services.start_websocket_server(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


class TestModalitaRemotaCoerenteConTls:
    def test_upnp_ok_ma_niente_tls_non_dichiara_remoto_attivo(self, monkeypatch):
        services = _build_services(monkeypatch, ssl_ctx=None, ext_ip="203.0.113.5")
        asyncio.run(_avvia_e_ferma(services))
        assert services.remote_mode == "none"
        assert services.upnp.last_error is not None
        assert "TLS" in services.upnp.last_error

    def test_upnp_e_tls_ok_dichiara_remoto_attivo(self, monkeypatch):
        services = _build_services(monkeypatch, ssl_ctx=object(), ext_ip="203.0.113.5")
        asyncio.run(_avvia_e_ferma(services))
        assert services.remote_mode == "upnp"

    def test_upnp_fallito_resta_none_a_prescindere_dal_tls(self, monkeypatch):
        services = _build_services(monkeypatch, ssl_ctx=object(), ext_ip=None)
        asyncio.run(_avvia_e_ferma(services))
        assert services.remote_mode == "none"


# --- tunnel Cloudflare -----------------------------------------------------

import json

from liquidmouse.net.server import TUNNEL_GUARD_KEY, tunnel_client_ip
from liquidmouse.security.auth import AuthGuard, hash_pin


class _FakeTunnel:
    def __init__(self, url="https://a-b-c.trycloudflare.com"):
        self._url = url
        self.url = None
        self.status = None
        self.running = False
        self.on_change = None
        self.avvii = 0
        self.fermate = 0

    def start(self):
        self.avvii += 1
        self.running = True
        self.url = self._url

    def stop(self):
        self.fermate += 1
        self.running = False
        self.url = None


def _build_con_tunnel(monkeypatch, *, ext_ip, tunnel):
    monkeypatch.setattr(server_mod.websockets, "serve", lambda *a, **k: _FakeServeCtx())
    return NetworkServices(
        config={}, auth_guard=None, trusted_peer=None, sessions=None,
        static=None, tls=_FakeTls(object()), upnp=_FakeUpnp(ext_ip),
        local_ip="192.168.1.10", tunnel=tunnel,
    )


class TestSceltaDelTunnel:
    def test_upnp_fallito_avvia_il_tunnel(self, monkeypatch):
        tunnel = _FakeTunnel()
        services = _build_con_tunnel(monkeypatch, ext_ip=None, tunnel=tunnel)
        asyncio.run(_avvia_e_ferma(services))
        assert tunnel.avvii == 1
        assert services.remote_mode == "tunnel"
        # All'uscita del server il tunnel va chiuso con lui.
        assert tunnel.fermate == 1

    def test_upnp_riuscito_non_avvia_il_tunnel(self, monkeypatch):
        tunnel = _FakeTunnel()
        services = _build_con_tunnel(monkeypatch, ext_ip="203.0.113.5", tunnel=tunnel)
        asyncio.run(_avvia_e_ferma(services))
        assert tunnel.avvii == 0
        assert services.remote_mode == "upnp"

    def test_tunnel_senza_indirizzo_resta_none_poi_diventa_tunnel(self, monkeypatch):
        # L'indirizzo arriva dopo qualche secondo, dal thread del tunnel.
        tunnel = _FakeTunnel(url=None)
        services = _build_con_tunnel(monkeypatch, ext_ip=None, tunnel=tunnel)
        asyncio.run(_avvia_e_ferma(services))
        assert services.remote_mode == "none"
        tunnel.url = "https://a-b-c.trycloudflare.com"
        tunnel.on_change()
        assert services.remote_mode == "tunnel"

    def test_upnp_tornato_ferma_il_tunnel(self, monkeypatch):
        tunnel = _FakeTunnel()
        services = _build_con_tunnel(monkeypatch, ext_ip=None, tunnel=tunnel)
        services._ssl_ctx = object()
        asyncio.run(services._refresh_remote(primo=True))
        assert services.remote_mode == "tunnel"
        services.upnp._ext_ip = "203.0.113.5"
        asyncio.run(services._refresh_remote())
        assert services.remote_mode == "upnp"
        assert tunnel.fermate == 1

    def test_motivo_mostrato_e_quello_del_tunnel(self, monkeypatch):
        tunnel = _FakeTunnel(url=None)
        services = _build_con_tunnel(monkeypatch, ext_ip=None, tunnel=tunnel)
        services.upnp.last_error = "cgnat dell'operatore (100.107.62.102)"
        tunnel.running = True
        tunnel.status = "download di cloudflared…"
        assert "download" in services.remote_problem


class TestIpDietroIlTunnel:
    def test_usa_l_header_di_cloudflare(self):
        assert tunnel_client_ip({"CF-Connecting-IP": "198.51.100.7"}) == "198.51.100.7"

    def test_header_assente_o_falso(self):
        assert tunnel_client_ip({}) == TUNNEL_GUARD_KEY
        assert tunnel_client_ip({"CF-Connecting-IP": "non-un-ip"}) == TUNNEL_GUARD_KEY
        assert tunnel_client_ip(None) == TUNNEL_GUARD_KEY


class _FakeWs:
    def __init__(self, messaggi):
        self._messaggi = list(messaggi)
        self.inviati = []
        self.chiuso = False

    async def recv(self):
        return self._messaggi.pop(0)

    async def send(self, m):
        self.inviati.append(json.loads(m))

    async def close(self):
        self.chiuso = True


class TestPinSulTunnel:
    """Dal tunnel ogni client arriva da 127.0.0.1: senza il ramo dedicato il
    loopback lo farebbe entrare senza PIN."""

    def _services(self):
        return NetworkServices(
            config={"pin_hash": hash_pin("1234")}, auth_guard=AuthGuard(),
            trusted_peer=None, sessions=None, static=None, tls=None,
            upnp=_FakeUpnp(None), local_ip="192.168.1.10",
        )

    def test_senza_pin_rifiuta_anche_da_loopback(self):
        ws = _FakeWs([json.dumps({"type": "auth", "pin": "sbagliato"})])
        ok = asyncio.run(self._services().authorize(ws, "127.0.0.1", via_tunnel=True))
        assert not ok
        assert ws.inviati[0]["type"] == "auth_fail"

    def test_pin_giusto_entra(self):
        ws = _FakeWs([json.dumps({"type": "auth", "pin": "1234"})])
        ok = asyncio.run(self._services().authorize(ws, "198.51.100.7", via_tunnel=True))
        assert ok
        assert ws.inviati[-1]["type"] == "auth_ok"

    def test_loopback_diretto_resta_fidato(self):
        # La finestra terminale sul PC continua a entrare senza PIN.
        ws = _FakeWs([])
        assert asyncio.run(self._services().authorize(ws, "127.0.0.1"))
