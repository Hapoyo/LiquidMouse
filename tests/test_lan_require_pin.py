"""Opzione `lan_require_pin`: il PIN anche dalla LAN, come dal remoto.

Di default (opzione assente o False) la LAN resta com'era: nessun PIN, whitelist
"primo arrivato". Il loopback (finestra terminale sul PC) è sempre fidato.
"""

import asyncio
import json

import pytest

pytest.importorskip("websockets")

from liquidmouse.net.addresses import TrustedPeer
from liquidmouse.net.server import NetworkServices
from liquidmouse.security.auth import AuthGuard, hash_pin


class _Ws:
    def __init__(self, messaggi):
        self._messaggi = list(messaggi)
        self.inviati = []
        self.chiuso = False

    async def recv(self):
        if not self._messaggi:
            await asyncio.Event().wait()          # il client tace
        return self._messaggi.pop(0)

    async def send(self, m):
        self.inviati.append(json.loads(m))

    async def close(self):
        self.chiuso = True


def _auth(pin):
    return json.dumps({"type": "auth", "pin": pin})


def _services(config=None, **kw):
    cfg = {"pin_hash": hash_pin("1234")}
    cfg.update(config or {})
    return NetworkServices(
        config=cfg, auth_guard=AuthGuard(), trusted_peer=TrustedPeer(), sessions=None,
        static=None, tls=None, upnp=None, local_ip="192.168.1.10", **kw)


def _autorizza(services, ws, ip):
    return asyncio.run(services.authorize(ws, ip))


class TestDefaultInvariato:
    def test_senza_opzione_la_lan_entra_senza_pin_e_senza_messaggi(self):
        ws = _Ws([])
        assert _autorizza(_services(), ws, "192.168.1.30")
        assert ws.inviati == []             # nessun handshake nuovo sul default

    def test_opzione_false_come_assente(self):
        ws = _Ws([])
        assert _autorizza(_services({"lan_require_pin": False}), ws, "192.168.1.30")
        assert ws.inviati == []

    def test_la_whitelist_primo_arrivato_resta(self):
        s = _services()
        assert _autorizza(s, _Ws([]), "192.168.1.30")
        altro = _Ws([])
        assert not _autorizza(s, altro, "192.168.1.31")
        assert altro.chiuso


class TestPinInLan:
    def _s(self, **kw):
        return _services({"lan_require_pin": True}, **kw)

    def test_pin_giusto_entra_e_riceve_auth_ok(self):
        ws = _Ws([_auth("1234")])
        assert _autorizza(self._s(), ws, "192.168.1.30")
        assert [m["type"] for m in ws.inviati] == ["auth_required", "auth_ok"]

    def test_pin_sbagliato_e_rifiutato_e_contato(self):
        s = self._s()
        ws = _Ws([_auth("0000")])
        assert not _autorizza(s, ws, "192.168.1.30")
        assert ws.chiuso
        assert ws.inviati[-1]["type"] == "auth_fail"
        assert s.auth_guard.remaining("192.168.1.30") < 5

    def test_anti_brute_force_come_dal_remoto(self):
        s = self._s()
        for _ in range(5):
            _autorizza(s, _Ws([_auth("0000")]), "192.168.1.30")
        ws = _Ws([_auth("1234")])
        assert not _autorizza(s, ws, "192.168.1.30")
        assert ws.inviati[0]["type"] == "auth_blocked"

    def test_non_usa_la_whitelist_primo_arrivato(self):
        # Il PIN sostituisce lo slot: due telefoni con il PIN giusto entrano.
        s = self._s()
        assert _autorizza(s, _Ws([_auth("1234")]), "192.168.1.30")
        assert _autorizza(s, _Ws([_auth("1234")]), "192.168.1.31")
        assert s.trusted_peer.ip is None

    def test_messaggi_prima_dell_auth_sono_scartati_non_eseguiti(self):
        # Il client chiama _onAuthenticated all'apertura e può mandare richieste
        # prima di rispondere ad auth_required: non devono chiudere il socket né
        # contare come autenticate.
        ws = _Ws([json.dumps({"type": "sftp_profiles"}), json.dumps({"type": "term_list"}),
                  _auth("1234")])
        assert _autorizza(self._s(), ws, "192.168.1.30")

    def test_troppi_messaggi_prima_dell_auth_chiudono(self):
        ws = _Ws([json.dumps({"type": "ping"})] * 200 + [_auth("1234")])
        assert not _autorizza(self._s(), ws, "192.168.1.30")
        assert ws.chiuso

    def test_client_che_tace_va_in_timeout(self, monkeypatch):
        import liquidmouse.net.server as server_mod
        monkeypatch.setattr(server_mod, "AUTH_TIMEOUT_SECS", 0.05)
        ws = _Ws([])
        assert not _autorizza(self._s(), ws, "192.168.1.30")
        assert ws.chiuso

    def test_il_loopback_resta_fidato_senza_pin(self):
        ws = _Ws([])
        assert _autorizza(self._s(), ws, "127.0.0.1")
        assert ws.inviati == []

    def test_l_opzione_si_legge_a_ogni_connessione(self):
        # L'interruttore della GUI vale dalla connessione successiva, senza riavvio.
        s = _services()
        assert _autorizza(s, _Ws([]), "192.168.1.30")
        s.config["lan_require_pin"] = True
        ws = _Ws([_auth("1234")])
        assert _autorizza(s, ws, "192.168.1.31")
        assert ws.inviati[0]["type"] == "auth_required"
        s.config["lan_require_pin"] = False
        s.trusted_peer.reset()
        ws2 = _Ws([])
        assert _autorizza(s, ws2, "192.168.1.32")
        assert ws2.inviati == []

    def test_il_remoto_non_riceve_auth_required(self):
        # Il remoto resta com'era: il client manda subito l'auth.
        ws = _Ws([_auth("1234")])
        assert _autorizza(self._s(), ws, "8.8.4.4")
        assert [m["type"] for m in ws.inviati] == ["auth_ok"]
