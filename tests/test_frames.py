"""Frame binari dell'output terminale: round-trip e robustezza."""

import pytest

from liquidmouse.net.frames import (
    FRAME_TERM_OUTPUT,
    MAX_ID_LEN,
    decode_term_output,
    encode_term_output,
)


class TestRoundTrip:
    def test_caso_tipico(self):
        frame = encode_term_output("a1b2c3d4", b"ciao mondo\r\n")
        assert decode_term_output(frame) == ("a1b2c3d4", b"ciao mondo\r\n")

    def test_payload_vuoto(self):
        assert decode_term_output(encode_term_output("abc", b"")) == ("abc", b"")

    def test_payload_binario_non_utf8(self):
        # L'output del PTY puo' contenere sequenze non valide in UTF-8: e' il
        # motivo per cui il payload viaggia grezzo e non come stringa.
        crudo = bytes(range(256))
        assert decode_term_output(encode_term_output("id", crudo)) == ("id", crudo)

    def test_payload_grande(self):
        crudo = b"x" * 65536
        sid, payload = decode_term_output(encode_term_output("abcd1234", crudo))
        assert payload == crudo

    @pytest.mark.parametrize("sid", ["a", "ab", "a1b2c3d4", "x" * MAX_ID_LEN])
    def test_id_di_lunghezze_diverse(self, sid):
        # La lunghezza e' esplicita proprio per non dipendere dagli 8 caratteri
        # attuali di uuid4().hex[:8].
        assert decode_term_output(encode_term_output(sid, b"p")) == (sid, b"p")

    def test_payload_che_sembra_un_altro_frame(self):
        # Il payload non deve poter confondere il parser.
        interno = encode_term_output("xyz", b"finto")
        assert decode_term_output(encode_term_output("vero", interno)) == ("vero", interno)


class TestFormato:
    def test_primo_byte_e_il_tipo(self):
        assert encode_term_output("ab", b"x")[0] == FRAME_TERM_OUTPUT

    def test_secondo_byte_e_la_lunghezza_dell_id(self):
        assert encode_term_output("abcd", b"x")[1] == 4

    def test_overhead_costante(self):
        # 2 byte di intestazione + l'id: contro il ~33% del base64.
        frame = encode_term_output("a1b2c3d4", b"y" * 4096)
        assert len(frame) == 2 + 8 + 4096


class TestEncodeInvalido:
    def test_id_vuoto(self):
        with pytest.raises(ValueError):
            encode_term_output("", b"x")

    def test_id_troppo_lungo(self):
        with pytest.raises(ValueError):
            encode_term_output("x" * (MAX_ID_LEN + 1), b"x")

    def test_id_non_ascii(self):
        with pytest.raises(ValueError):
            encode_term_output("sessione-àèì", b"x")


class TestDecodeMalformato:
    """Un frame malformato si ignora, non chiude la connessione."""

    @pytest.mark.parametrize("frame", [
        b"",                      # vuoto
        b"\x01",                  # solo il tipo
        b"\x01\x08abc",           # dichiara 8 byte di id, ne ha 3
        b"\x01\x00payload",       # lunghezza id zero
        b"\x99\x02abpayload",     # tipo sconosciuto
    ])
    def test_ritorna_none(self, frame):
        assert decode_term_output(frame) is None

    def test_id_non_ascii_nel_frame(self):
        frame = b"\x01\x02" + "àb".encode("utf-8")[:2] + b"payload"
        # Non deve sollevare, qualunque sia l'esito.
        decode_term_output(frame)

    def test_frame_troncato_a_meta_dell_id(self):
        completo = encode_term_output("a1b2c3d4", b"payload")
        assert decode_term_output(completo[:6]) is None
