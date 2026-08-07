"""Anti-bruteforce: soglia, finestra di blocco e scadenza del contatore."""

import pytest

from liquidmouse.security.auth import (
    AUTH_BLOCK_SECS,
    AUTH_MAX_FAILS,
    AuthGuard,
    hash_pin,
    pin_matches,
)


class _Clock:
    """Orologio manuale, per non far dipendere i test da sleep reali."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, secs: float) -> None:
        self.now += secs


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def guard(clock):
    return AuthGuard(clock=clock)


class TestPinHashing:
    def test_matching_pin(self):
        assert pin_matches("segreto", hash_pin("segreto"))

    def test_wrong_pin(self):
        assert not pin_matches("sbagliato", hash_pin("segreto"))

    def test_hash_is_not_the_pin(self):
        assert hash_pin("segreto") != "segreto"
        assert len(hash_pin("segreto")) == 64


class TestBlocking:
    def test_unknown_ip_is_not_blocked(self, guard):
        assert not guard.is_blocked("1.2.3.4")

    def test_below_threshold_is_not_blocked(self, guard):
        for _ in range(AUTH_MAX_FAILS - 1):
            guard.record_fail("1.2.3.4")
        assert not guard.is_blocked("1.2.3.4")

    def test_threshold_blocks(self, guard):
        for _ in range(AUTH_MAX_FAILS):
            guard.record_fail("1.2.3.4")
        assert guard.is_blocked("1.2.3.4")

    def test_block_expires(self, guard, clock):
        for _ in range(AUTH_MAX_FAILS):
            guard.record_fail("1.2.3.4")
        clock.advance(AUTH_BLOCK_SECS + 1)
        assert not guard.is_blocked("1.2.3.4")

    def test_block_holds_just_before_expiry(self, guard, clock):
        for _ in range(AUTH_MAX_FAILS):
            guard.record_fail("1.2.3.4")
        clock.advance(AUTH_BLOCK_SECS - 1)
        assert guard.is_blocked("1.2.3.4")

    def test_stale_partial_failures_are_forgotten(self, guard, clock):
        # Due tentativi oggi e tre fra un mese non devono sommarsi a cinque.
        guard.record_fail("1.2.3.4")
        guard.record_fail("1.2.3.4")
        clock.advance(AUTH_BLOCK_SECS + 1)
        assert not guard.is_blocked("1.2.3.4")
        assert guard.remaining("1.2.3.4") == AUTH_MAX_FAILS

    def test_blocks_are_per_ip(self, guard):
        for _ in range(AUTH_MAX_FAILS):
            guard.record_fail("1.2.3.4")
        assert guard.is_blocked("1.2.3.4")
        assert not guard.is_blocked("5.6.7.8")

    def test_success_clears_the_counter(self, guard):
        guard.record_fail("1.2.3.4")
        guard.record_fail("1.2.3.4")
        guard.clear("1.2.3.4")
        assert guard.remaining("1.2.3.4") == AUTH_MAX_FAILS


class TestRemaining:
    def test_counts_down(self, guard):
        assert guard.remaining("1.2.3.4") == AUTH_MAX_FAILS
        guard.record_fail("1.2.3.4")
        assert guard.remaining("1.2.3.4") == AUTH_MAX_FAILS - 1

    def test_never_negative(self, guard):
        for _ in range(AUTH_MAX_FAILS + 10):
            guard.record_fail("1.2.3.4")
        assert guard.remaining("1.2.3.4") == 0


class TestConcurrentHandshakes:
    def test_second_parallel_attempt_is_refused(self, guard):
        # Senza questo, N connessioni parallele proverebbero N PIN prima che il
        # contatore dei fallimenti raggiunga la soglia.
        assert guard.begin("1.2.3.4")
        assert not guard.begin("1.2.3.4")

    def test_slot_is_released(self, guard):
        guard.begin("1.2.3.4")
        guard.end("1.2.3.4")
        assert guard.begin("1.2.3.4")

    def test_different_ips_do_not_interfere(self, guard):
        assert guard.begin("1.2.3.4")
        assert guard.begin("5.6.7.8")
