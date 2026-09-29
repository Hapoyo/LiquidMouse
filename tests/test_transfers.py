"""Biglietti monouso dei trasferimenti: l'unica autenticazione dell'HTTP."""

import pytest

from liquidmouse.net.transfers import (
    DOWNLOAD, TICKET_TTL_SECS, TICKETS_MAX, UPLOAD, TransferRegistry,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def reg(clock):
    return TransferRegistry(clock)


def test_il_biglietto_vale_una_volta_sola(reg):
    t = reg.issue(1, DOWNLOAD, "/a")
    assert reg.redeem(t, DOWNLOAD).path == "/a"
    assert reg.redeem(t, DOWNLOAD) is None


def test_token_sconosciuto(reg):
    assert reg.redeem("boh", DOWNLOAD) is None
    assert reg.redeem("", DOWNLOAD) is None


def test_scade(reg, clock):
    t = reg.issue(1, DOWNLOAD, "/a")
    clock.t += TICKET_TTL_SECS + 1
    assert reg.redeem(t, DOWNLOAD) is None


def test_direzione_sbagliata_brucia_il_biglietto(reg):
    t = reg.issue(1, UPLOAD, "/a")
    assert reg.redeem(t, DOWNLOAD) is None
    assert reg.redeem(t, UPLOAD) is None


def test_revoca_dei_biglietti_di_un_client(reg):
    mio, altro = reg.issue(1, DOWNLOAD, "/a"), reg.issue(2, DOWNLOAD, "/b")
    reg.revoke_owner(1)
    assert reg.redeem(mio, DOWNLOAD) is None
    assert reg.redeem(altro, DOWNLOAD).owner == 2


def test_tetto_sui_biglietti_aperti(reg):
    for _ in range(TICKETS_MAX):
        reg.issue(1, DOWNLOAD, "/a")
    with pytest.raises(RuntimeError):
        reg.issue(1, DOWNLOAD, "/a")


def test_i_scaduti_liberano_posto(reg, clock):
    for _ in range(TICKETS_MAX):
        reg.issue(1, DOWNLOAD, "/a")
    clock.t += TICKET_TTL_SECS + 1
    reg.issue(1, DOWNLOAD, "/a")


def test_direzione_non_valida(reg):
    with pytest.raises(ValueError):
        reg.issue(1, "x", "/a")


def test_i_token_non_sono_prevedibili(reg):
    assert len({reg.issue(1, DOWNLOAD, "/a") for _ in range(50)}) == 50
