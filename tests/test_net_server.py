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

    @pytest.mark.parametrize("payload", [
        "[1, 2]", "123", "null", '{"type": "auth", "pin": 123}',
        '{"type": "auth", "pin": null}', '{"type": "auth", "pin": ["1234"]}',
    ])
    def test_payload_malformato_conta_come_tentativo_fallito(self, payload):
        # Un JSON non-dict o un PIN non stringa faceva sollevare l'handshake:
        # la connessione cadeva con traceback e il tentativo non veniva contato.
        services = self._services()
        ws = _FakeWs([payload])
        ok = asyncio.run(services.authorize(ws, "198.51.100.7", via_tunnel=True))
        assert not ok and ws.chiuso
        assert ws.inviati[0]["type"] == "auth_fail"
        assert services.auth_guard.remaining("198.51.100.7") < 5

    def test_loopback_diretto_resta_fidato(self):
        # La finestra terminale sul PC continua a entrare senza PIN.
        ws = _FakeWs([])
        assert asyncio.run(self._services().authorize(ws, "127.0.0.1"))


# --- controllo Origin sui WebSocket ----------------------------------------

import socket

from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve as serve_reale
from websockets.exceptions import InvalidStatus


class _CatturaServe:
    """Sostituisce websockets.serve registrando gli argomenti di ogni chiamata."""

    def __init__(self):
        self.chiamate = []

    def __call__(self, *a, **k):
        self.chiamate.append(k)
        return _FakeServeCtx()


class TestOriginDeiWebSocket:
    def test_tutti_e_quattro_i_serve_filtrano_l_origin(self, monkeypatch):
        cattura = _CatturaServe()
        monkeypatch.setattr(server_mod.websockets, "serve", cattura)
        services = NetworkServices(
            config={}, auth_guard=None, trusted_peer=None, sessions=None,
            static=None, tls=_FakeTls(object()), upnp=_FakeUpnp(None),
            local_ip="192.168.1.10", tunnel=_FakeTunnel())
        asyncio.run(_avvia_e_ferma(services))
        assert len(cattura.chiamate) == 4
        for k in cattura.chiamate:
            assert k["origins"] is server_mod.ALLOWED_ORIGINS

    async def _tenta(self, origin):
        """Handshake reale su loopback con l'Origin dato. Ritorna lo status
        HTTP del rifiuto, o 101 se la connessione è stata accettata."""
        async def handler(ws):
            await ws.close()

        async with serve_reale(handler, "127.0.0.1", 0,
                                    origins=server_mod.ALLOWED_ORIGINS) as srv:
            porta = srv.sockets[0].getsockname()[1]
            headers = {"Origin": origin} if origin is not None else {}
            try:
                async with ws_connect(f"ws://127.0.0.1:{porta}",
                                      additional_headers=headers):
                    return 101
            except InvalidStatus as e:
                return e.response.status_code

    @pytest.mark.parametrize("origin", [
        None,                                  # client non browser (test_server.py)
        "http://127.0.0.1:8000",               # finestra terminale sul PC
        "http://localhost:8000",
        "http://192.168.1.10:8000",            # pagina in LAN
        "https://203.0.113.5:8443",            # pagina remota via UPnP
        "https://203.0.113.5",                 # porta opzionale
        "https://a-b-c.trycloudflare.com",     # tunnel
    ])
    def test_origin_ammessi(self, origin):
        assert asyncio.run(self._tenta(origin)) == 101

    @pytest.mark.parametrize("origin", [
        "https://evil.example",
        "http://evil.example:8000",
        "http://127.0.0.1.evil.example",       # prefisso numerico, host altrui
        "https://trycloudflare.com.evil.example",
        "https://evil.com/.trycloudflare.com",
        "ftp://127.0.0.1",
        "null",
    ])
    def test_origin_rifiutati_con_403(self, origin):
        assert asyncio.run(self._tenta(origin)) == 403


# --- robustezza dell'avvio e del keepalive ---------------------------------

from liquidmouse.ports import HTTPS_PORT, PORT


class _ServeTracciato:
    """Finto websockets.serve: l'ingresso fallisce con OSError per le porte
    indicate; registra chi è entrato e chi è uscito."""

    def __init__(self, porte_occupate=()):
        self.occupate = set(porte_occupate)
        self.entrati = []
        self.usciti = []

    def __call__(self, handler, host, porta, **k):
        outer = self

        class _Ctx:
            async def __aenter__(self):
                if porta in outer.occupate:
                    raise OSError(98, "address already in use")
                outer.entrati.append(porta)
                return self

            async def __aexit__(self, *a):
                outer.usciti.append(porta)
                return False
        return _Ctx()


@pytest.fixture
def messaggi(monkeypatch):
    righe = []
    monkeypatch.setattr(server_mod, "log_message", lambda msg, color=None: righe.append(msg))
    return righe


class TestAvvioServer:
    def test_porta_occupata_e_riportata_con_il_suo_numero(self, monkeypatch, messaggi):
        serve = _ServeTracciato(porte_occupate={HTTPS_PORT})
        monkeypatch.setattr(server_mod.websockets, "serve", serve)
        services = NetworkServices(
            config={}, auth_guard=None, trusted_peer=None, sessions=None,
            static=None, tls=_FakeTls(object()), upnp=_FakeUpnp(None),
            local_ip="192.168.1.10")
        asyncio.run(_avvia_e_ferma(services))
        errori = [m for m in messaggi if "occupata" in m]
        assert any(str(HTTPS_PORT) in m for m in errori), errori
        assert not any(str(PORT) in m for m in errori), "la 8765 non c'entra"

    def test_una_porta_occupata_non_smonta_gli_altri_server(self, monkeypatch, messaggi):
        serve = _ServeTracciato(porte_occupate={HTTPS_PORT})
        monkeypatch.setattr(server_mod.websockets, "serve", serve)
        services = NetworkServices(
            config={}, auth_guard=None, trusted_peer=None, sessions=None,
            static=None, tls=_FakeTls(object()), upnp=_FakeUpnp(None),
            local_ip="192.168.1.10")
        asyncio.run(_avvia_e_ferma(services))
        # La 8765 (LAN) e la 8766 (WSS legacy) restano attive.
        assert PORT in serve.entrati
        assert len(serve.entrati) == 2
        # Nessuna è stata chiusa prima dello stop: solo allo scadere del test.
        assert sorted(serve.usciti) == sorted(serve.entrati)

    def test_primo_refresh_fallito_non_impedisce_l_avvio(self, monkeypatch, messaggi):
        serve = _ServeTracciato()
        monkeypatch.setattr(server_mod.websockets, "serve", serve)

        class _UpnpRotto(_FakeUpnp):
            async def setup(self, local_ip):
                raise RuntimeError("router muto")

        services = NetworkServices(
            config={}, auth_guard=None, trusted_peer=None, sessions=None,
            static=None, tls=_FakeTls(None), upnp=_UpnpRotto(None),
            local_ip="192.168.1.10")
        asyncio.run(_avvia_e_ferma(services))
        assert PORT in serve.entrati
        assert any("router muto" in m for m in messaggi), messaggi


class TestKeepalive:
    def test_un_errore_non_ferma_il_ciclo(self, monkeypatch, messaggi):
        monkeypatch.setattr(server_mod, "UPNP_KEEPALIVE_SECS", 0.01)
        chiamate = []

        class _UpnpInstabile(_FakeUpnp):
            async def setup(self, local_ip):
                chiamate.append(1)
                if len(chiamate) == 1:
                    raise OSError("rete assente")
                return None

        services = NetworkServices(
            config={}, auth_guard=None, trusted_peer=None, sessions=None,
            static=None, tls=None, upnp=_UpnpInstabile(None), local_ip="192.168.1.10")

        async def prova():
            try:
                await asyncio.wait_for(services._remote_keepalive(), timeout=0.2)
            except asyncio.TimeoutError:
                pass

        asyncio.run(prova())
        assert len(chiamate) >= 3, "il ciclo si è fermato al primo errore"
        assert any("rete assente" in m for m in messaggi), messaggi
