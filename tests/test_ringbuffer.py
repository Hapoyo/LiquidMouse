"""Ring buffer dell'output PTY: contenuto corretto e costo ammortizzato."""

import pytest

from liquidmouse.terminal.ringbuffer import RingBuffer


def _naive(chunks, maxsize):
    """Implementazione di riferimento (quella precedente), per confronto."""
    buf = bytearray()
    for c in chunks:
        buf += c
        if len(buf) > maxsize:
            del buf[:len(buf) - maxsize]
    return bytes(buf)


class TestContenuto:
    def test_vuoto(self):
        assert RingBuffer().snapshot() == b""
        assert len(RingBuffer()) == 0

    def test_sotto_soglia_conserva_tutto(self):
        rb = RingBuffer(maxsize=100)
        rb.append(b"ciao ")
        rb.append(b"mondo")
        assert rb.snapshot() == b"ciao mondo"
        assert len(rb) == 10

    def test_scarta_i_piu_vecchi(self):
        rb = RingBuffer(maxsize=5)
        rb.append(b"abcdefgh")
        assert rb.snapshot() == b"defgh"
        assert len(rb) == 5

    def test_chunk_singolo_piu_grande_del_ring(self):
        rb = RingBuffer(maxsize=4)
        rb.append(b"0123456789")
        assert rb.snapshot() == b"6789"

    def test_append_vuoto_e_innocuo(self):
        rb = RingBuffer(maxsize=10)
        rb.append(b"abc")
        rb.append(b"")
        assert rb.snapshot() == b"abc"

    def test_clear(self):
        rb = RingBuffer(maxsize=10)
        rb.append(b"abc")
        rb.clear()
        assert rb.snapshot() == b""
        assert len(rb) == 0

    def test_maxsize_non_positivo(self):
        with pytest.raises(ValueError):
            RingBuffer(maxsize=0)


class TestEquivalenzaConLaVersionePrecedente:
    """Il contenuto osservabile non deve essere cambiato: solo il costo."""

    @pytest.mark.parametrize("maxsize", [1, 4, 7, 64, 1000])
    def test_stessi_risultati(self, maxsize):
        chunks = [bytes([i % 256]) * (i % 13 + 1) for i in range(200)]
        rb = RingBuffer(maxsize=maxsize)
        for c in chunks:
            rb.append(c)
        assert rb.snapshot() == _naive(chunks, maxsize)

    def test_snapshot_intermedi_coincidono(self):
        chunks = [b"riga %d\n" % i for i in range(50)]
        rb = RingBuffer(maxsize=30)
        for i, c in enumerate(chunks):
            rb.append(c)
            assert rb.snapshot() == _naive(chunks[: i + 1], 30)


class TestCostoAmmortizzato:
    def test_non_compatta_a_ogni_chunk(self):
        # Il punto dell'ottimizzazione: con la versione precedente ogni append
        # oltre la soglia faceva un memmove dell'intero buffer. Qui il buffer
        # sottostante cresce e viene compattato di rado, quindi resta limitato
        # ma non viene riallineato a ogni scrittura.
        rb = RingBuffer(maxsize=1024)
        for _ in range(1000):
            rb.append(b"x" * 512)
        assert len(rb) == 1024
        # Il buffer interno non deve crescere senza controllo.
        assert len(rb._buf) <= 3 * rb.maxsize
