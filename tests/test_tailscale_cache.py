"""Cache della sonda Tailscale: evita di congelare la GUI a ogni interrogazione."""

from liquidmouse.net.addresses import CachedTailscaleIp


class _Sonda:
    """Sonda finta che conta quante volte viene eseguita."""

    def __init__(self, valore="100.101.1.1"):
        self.valore = valore
        self.chiamate = 0

    def __call__(self):
        self.chiamate += 1
        return self.valore


class _Orologio:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, secs):
        self.now += secs


def _cache(sonda, orologio, ttl=30.0):
    return CachedTailscaleIp(ttl=ttl, probe=sonda, clock=orologio)


class TestCache:
    def test_la_prima_chiamata_interroga(self):
        sonda, orologio = _Sonda(), _Orologio()
        assert _cache(sonda, orologio)() == "100.101.1.1"
        assert sonda.chiamate == 1

    def test_le_chiamate_successive_usano_la_cache(self):
        sonda, orologio = _Sonda(), _Orologio()
        c = _cache(sonda, orologio)
        for _ in range(50):
            c()
        # Il menu tray la interroga a ogni apertura: senza cache sarebbero 50
        # socket con timeout 1 s.
        assert sonda.chiamate == 1

    def test_scade_dopo_il_ttl(self):
        sonda, orologio = _Sonda(), _Orologio()
        c = _cache(sonda, orologio, ttl=30.0)
        c()
        orologio.advance(31)
        c()
        assert sonda.chiamate == 2

    def test_non_scade_prima_del_ttl(self):
        sonda, orologio = _Sonda(), _Orologio()
        c = _cache(sonda, orologio, ttl=30.0)
        c()
        orologio.advance(29)
        c()
        assert sonda.chiamate == 1

    def test_il_valore_none_e_memorizzato(self):
        # Il caso lento e' proprio Tailscale spento: la sonda aspetta il timeout
        # e ritorna None. Memorizzare None e' l'ottimizzazione che conta.
        sonda, orologio = _Sonda(valore=None), _Orologio()
        c = _cache(sonda, orologio)
        assert c() is None
        assert c() is None
        assert sonda.chiamate == 1

    def test_invalidate_forza_una_nuova_sonda(self):
        sonda, orologio = _Sonda(), _Orologio()
        c = _cache(sonda, orologio)
        c()
        c.invalidate()
        c()
        assert sonda.chiamate == 2

    def test_riflette_il_cambio_di_stato_dopo_la_scadenza(self):
        sonda, orologio = _Sonda(valore=None), _Orologio()
        c = _cache(sonda, orologio, ttl=10.0)
        assert c() is None
        sonda.valore = "100.99.1.1"
        orologio.advance(11)
        assert c() == "100.99.1.1"
