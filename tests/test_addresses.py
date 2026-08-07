"""Classificazione degli indirizzi: è ciò che decide se serve il PIN."""

from liquidmouse.net.addresses import (
    TrustedPeer,
    is_loopback,
    is_private_ip,
    is_tailscale_conn,
)


class TestIsPrivateIp:
    def test_lan_ranges_are_private(self):
        assert is_private_ip("192.168.1.10")
        assert is_private_ip("10.0.0.5")
        assert is_private_ip("172.16.0.1")

    def test_link_local_is_private(self):
        assert is_private_ip("169.254.1.1")

    def test_public_is_not_private(self):
        assert not is_private_ip("8.8.8.8")
        assert not is_private_ip("93.184.216.34")

    def test_cgnat_is_not_private(self):
        # Il punto chiave: un altro cliente dello stesso ISP in CGNAT non deve
        # passare per "LAN", altrimenti salta l'autenticazione con PIN.
        assert not is_private_ip("100.64.0.1")
        assert not is_private_ip("100.100.100.100")
        assert not is_private_ip("100.127.255.254")

    def test_just_outside_cgnat_follows_normal_rules(self):
        assert not is_private_ip("100.63.255.255")  # pubblico
        assert not is_private_ip("100.128.0.0")     # pubblico

    def test_garbage_is_not_private(self):
        assert not is_private_ip("")
        assert not is_private_ip("non-un-ip")
        assert not is_private_ip("999.999.999.999")


class TestIsLoopback:
    def test_ipv4_and_ipv6_loopback(self):
        assert is_loopback("127.0.0.1")
        assert is_loopback("127.1.2.3")
        assert is_loopback("::1")

    def test_non_loopback(self):
        assert not is_loopback("192.168.1.10")
        assert not is_loopback("spazzatura")


class _FakeWebSocket:
    def __init__(self, remote, local):
        self.remote_address = (remote, 12345)
        self.local_address = (local, 8443)


class TestIsTailscaleConn:
    def test_both_ends_in_cgnat(self):
        assert is_tailscale_conn(_FakeWebSocket("100.101.1.1", "100.102.2.2"))

    def test_source_cgnat_but_arrives_on_lan_ip_is_rejected(self):
        # Scenario che il controllo sulla destinazione esiste per bloccare: un
        # vicino di CGNAT dell'ISP che arriva sulla porta UPnP-mappata.
        assert not is_tailscale_conn(_FakeWebSocket("100.101.1.1", "192.168.1.5"))

    def test_lan_source_is_not_tailscale(self):
        assert not is_tailscale_conn(_FakeWebSocket("192.168.1.9", "100.101.1.1"))

    def test_malformed_address_is_rejected(self):
        assert not is_tailscale_conn(_FakeWebSocket("nope", "100.101.1.1"))


class TestTrustedPeer:
    def test_starts_empty(self):
        assert TrustedPeer().ip is None

    def test_first_claim_wins(self):
        peer = TrustedPeer()
        assert peer.claim("192.168.1.10")
        assert peer.ip == "192.168.1.10"

    def test_same_ip_can_reclaim(self):
        peer = TrustedPeer()
        peer.claim("192.168.1.10")
        assert peer.claim("192.168.1.10")

    def test_second_ip_is_refused(self):
        peer = TrustedPeer()
        peer.claim("192.168.1.10")
        assert not peer.claim("192.168.1.99")
        assert peer.ip == "192.168.1.10"

    def test_reset_frees_the_slot(self):
        peer = TrustedPeer()
        peer.claim("192.168.1.10")
        peer.reset()
        assert peer.ip is None
        assert peer.claim("192.168.1.99")
