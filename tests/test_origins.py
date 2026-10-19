"""Controllo di Origin e Host per tipo di connessione (net/origins.py e
NetworkServices._guarded)."""

import asyncio
from types import SimpleNamespace

import pytest

from liquidmouse.net.origins import (LAN, REMOTE, TUNNEL, header_host, origin_allowed,
                                     origin_host)

CTX = dict(local_ips=("192.168.1.10",), external_ip="203.0.113.5",
           tunnel_host="a-b-c.trycloudflare.com")


def ok(kind, peer, origin, host, **over):
    return origin_allowed(kind, peer, origin, host, **{**CTX, **over})


class TestParsing:
    @pytest.mark.parametrize("origin,atteso", [
        ("http://192.168.1.10:8000", "192.168.1.10"),
        ("HTTPS://Localhost", "localhost"),
        ("http://[::1]:8000", "::1"),
        ("null", None),
        ("ftp://127.0.0.1", None),
        ("https://evil.com/.trycloudflare.com", None),
        ("https://user@evil.com", None),
        ("http://127.0.0.1:99999", None),
        ("", None),
    ])
    def test_origin_host(self, origin, atteso):
        assert origin_host(origin) == atteso

    @pytest.mark.parametrize("host,atteso", [
        ("192.168.1.10:8765", "192.168.1.10"),
        ("[::1]:8765", "::1"),
        ("localhost", "localhost"),
        ("a@b", None),
        ("a/b", None),
        ("", None),
    ])
    def test_header_host(self, host, atteso):
        assert header_host(host) == atteso


class TestLoopback:
    """Finestra terminale sul PC: solo localhost/127.0.0.1."""

    def test_ammessi(self):
        assert ok(LAN, "127.0.0.1", "http://127.0.0.1:8000", "127.0.0.1:8765")
        assert ok(LAN, "127.0.0.1", "http://localhost:8000", "localhost:8765")
        assert ok(LAN, "::1", "http://[::1]:8000", "[::1]:8765")
        assert ok(REMOTE, "127.0.0.1", "https://127.0.0.1:8443", "127.0.0.1:8443")

    def test_origin_assente_passa_sempre(self):
        # tools/test_server.py non manda Origin.
        for kind in (LAN, REMOTE, TUNNEL):
            assert ok(kind, "127.0.0.1", None, None)

    @pytest.mark.parametrize("origin", [
        "http://192.168.1.10:8000", "http://203.0.113.99:8000",
        "https://a-b-c.trycloudflare.com", "http://localhost.evil.com:8000",
    ])
    def test_rifiutati(self, origin):
        assert not ok(LAN, "127.0.0.1", origin, "127.0.0.1:8765")

    def test_rebinding_host_estraneo(self):
        # Origin dichiarato localhost ma l'Host tradisce il nome dell'attaccante.
        assert not ok(LAN, "127.0.0.1", "http://localhost:8000", "evil.com:8765")
        assert not ok(LAN, "127.0.0.1", "http://localhost:8000", None)


class TestLan:
    def test_solo_il_local_ip_corrente(self):
        assert ok(LAN, "192.168.1.20", "http://192.168.1.10:8000", "192.168.1.10:8765")

    def test_ip_numerico_estraneo_rifiutato(self):
        assert not ok(LAN, "192.168.1.20", "http://203.0.113.99:8000", "192.168.1.10:8765")
        assert not ok(LAN, "192.168.1.20", "http://192.168.1.77", "192.168.1.10:8765")

    def test_tunnel_estraneo_rifiutato(self):
        assert not ok(LAN, "192.168.1.20", "https://x-y-z.trycloudflare.com",
                      "192.168.1.10:8765")
        # nemmeno quello corrente: sulla LAN non è la nostra pagina
        assert not ok(LAN, "192.168.1.20", "https://a-b-c.trycloudflare.com",
                      "192.168.1.10:8765")

    def test_host_diverso_dall_origin_rifiutato(self):
        assert not ok(LAN, "192.168.1.20", "http://192.168.1.10:8000", "evil.com:8765")

    def test_local_ip_letto_dinamicamente(self):
        assert not ok(LAN, "192.168.1.20", "http://10.0.0.5:8000", "10.0.0.5:8765")
        assert ok(LAN, "192.168.1.20", "http://10.0.0.5:8000", "10.0.0.5:8765",
                  local_ips=("10.0.0.5",))


class TestRemoto8443:
    def test_ip_esterno_e_tunnel_corrente(self):
        assert ok(REMOTE, "198.51.100.7", "https://203.0.113.5:8443", "203.0.113.5:8443")
        assert ok(REMOTE, "198.51.100.7", "https://a-b-c.trycloudflare.com",
                  "a-b-c.trycloudflare.com")

    def test_rifiuta_altro(self):
        assert not ok(REMOTE, "198.51.100.7", "https://203.0.113.99:8443", "203.0.113.5:8443")
        assert not ok(REMOTE, "198.51.100.7", "https://x-y-z.trycloudflare.com",
                      "x-y-z.trycloudflare.com")
        assert not ok(REMOTE, "198.51.100.7", "https://192.168.1.10:8443", "203.0.113.5:8443")

    def test_senza_ip_esterno_o_tunnel_non_ammette_nulla(self):
        assert not ok(REMOTE, "198.51.100.7", "https://203.0.113.5:8443", "203.0.113.5:8443",
                      external_ip=None, tunnel_host=None)


class TestTunnel:
    def test_solo_il_tunnel_corrente(self):
        assert ok(TUNNEL, "127.0.0.1", "https://a-b-c.trycloudflare.com",
                  "a-b-c.trycloudflare.com")
        assert not ok(TUNNEL, "127.0.0.1", "https://x-y-z.trycloudflare.com",
                      "x-y-z.trycloudflare.com")

    def test_dal_tunnel_il_loopback_non_vale_come_origin(self):
        # Peer sempre 127.0.0.1: una pagina su http://localhost non è del tunnel.
        assert not ok(TUNNEL, "127.0.0.1", "http://localhost:8000", "localhost:8767")

    def test_host_riscritto_verso_l_origine_tollerato(self):
        assert ok(TUNNEL, "127.0.0.1", "https://a-b-c.trycloudflare.com", "127.0.0.1:8767")

    def test_senza_tunnel_rifiuta(self):
        assert not ok(TUNNEL, "127.0.0.1", "https://a-b-c.trycloudflare.com",
                      "a-b-c.trycloudflare.com", tunnel_host=None)


# --- _guarded: legge lo stato corrente a ogni handshake ---------------------

from liquidmouse.net.server import NetworkServices


class _Upnp:
    external_ip = "203.0.113.5"
    last_error = None


def _services(tunnel=None):
    return NetworkServices(config={}, auth_guard=None, trusted_peer=None,
                           sessions=None, static=None, tls=None, upnp=_Upnp(),
                           local_ip="192.168.1.10", tunnel=tunnel)


class _Conn:
    def __init__(self, peer, locale=("192.168.1.10", 8765)):
        self.remote_address = (peer, 50000)
        self.local_address = locale
        self.risposte = []

    def respond(self, status, text):
        self.risposte.append(int(status))
        return ("risposta", int(status))


def _req(origin, host, upgrade="websocket"):
    h = {"Host": host}
    if origin is not None:
        h["Origin"] = origin
    if upgrade:
        h["Upgrade"] = upgrade
    return SimpleNamespace(headers=h, path="/")


def _gate(services, kind, conn, req, inner=None):
    return asyncio.run(services._guarded(kind, inner)(conn, req))


class TestGuarded:
    def test_lan_ok_e_rifiuto(self):
        s = _services()
        assert _gate(s, "lan", _Conn("192.168.1.20"),
                     _req("http://192.168.1.10:8000", "192.168.1.10:8765")) is None
        r = _gate(s, "lan", _Conn("192.168.1.20"),
                  _req("http://203.0.113.99:8000", "192.168.1.10:8765"))
        assert r == ("risposta", 403)

    def test_lan_segue_il_cambio_di_ip(self):
        s = _services()
        conn = _Conn("192.168.1.20", locale=("192.168.1.10", 8765))
        s.local_ip = "10.0.0.5"
        # il vecchio IP resta valido solo perché è quello a cui il peer si è collegato
        assert _gate(s, "lan", conn, _req("http://10.0.0.5:8000", "10.0.0.5:8765")) is None
        conn2 = _Conn("192.168.1.20", locale=("10.0.0.5", 8765))
        assert _gate(s, "lan", conn2,
                     _req("http://192.168.1.10:8000", "192.168.1.10:8765")) == ("risposta", 403)

    def test_interfaccia_secondaria_del_pc(self):
        s = _services()
        conn = _Conn("172.20.10.2", locale=("172.20.10.1", 8765))
        assert _gate(s, "lan", conn, _req("http://172.20.10.1:8000", "172.20.10.1:8765")) is None

    def test_tunnel_corrente_dinamico(self):
        class T:
            url = "https://a-b-c.trycloudflare.com"
            running = True
            status = None
            on_change = None
        t = T()
        s = _services(tunnel=t)
        req = ("https://a-b-c.trycloudflare.com", "a-b-c.trycloudflare.com")
        assert _gate(s, "tunnel", _Conn("127.0.0.1"), _req(*req)) is None
        t.url = "https://x-y-z.trycloudflare.com"   # il tunnel è ripartito
        assert _gate(s, "tunnel", _Conn("127.0.0.1"), _req(*req)) == ("risposta", 403)

    def test_le_pagine_vanno_a_inner_senza_controllo(self):
        s = _services()

        async def inner(conn, req):
            return "pagina"
        req = _req("https://evil.example", "203.0.113.5:8443", upgrade=None)
        assert _gate(s, "remote", _Conn("198.51.100.7"), req, inner) == "pagina"

    def test_upgrade_ammesso_prosegue_con_l_handshake(self):
        s = _services()

        async def inner(conn, req):
            raise AssertionError("inner non va chiamato per gli upgrade")
        req = _req("https://203.0.113.5:8443", "203.0.113.5:8443")
        assert _gate(s, "remote", _Conn("198.51.100.7"), req, inner) is None
