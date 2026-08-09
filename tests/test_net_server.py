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
