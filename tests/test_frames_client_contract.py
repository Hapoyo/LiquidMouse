"""Il decoder JS e l'encoder Python devono concordare sul formato del frame.

Sono due implementazioni dello stesso contratto in linguaggi diversi, in due
file che si modificano separatamente: è esattamente il tipo di disallineamento
che passa inosservato fino a quando il terminale smette di mostrare l'output.

Il test estrae `handleBinaryFrame` da app.js, lo esegue con node su frame
prodotti da liquidmouse/net/frames.py e verifica che ricostruisca gli stessi
byte. Se node non è installato, viene saltato.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from liquidmouse.net.frames import encode_term_output

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node non disponibile"
)


def _estrai_decoder() -> str:
    """Prende dal client la costante del tipo di frame e handleBinaryFrame."""
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    costante = re.search(r"const FRAME_TERM_OUTPUT = (0x[0-9a-fA-F]+);", js)
    assert costante, "FRAME_TERM_OUTPUT non trovata in app.js"
    inizio = js.index("function handleBinaryFrame(buf)")
    fine = js.index("\n    }", inizio) + len("\n    }")
    return f"const FRAME_TERM_OUTPUT = {costante.group(1)};\n" + js[inizio:fine]


def _decodifica_con_node(frame: bytes, session_id: str | None):
    """Esegue il decoder del client e riporta cosa e' finito in xterm."""
    script = f"""
{_estrai_decoder()}

// Stub del contorno che handleBinaryFrame tocca.
let scritti = [];
let xtermOpened = true;
let xterm = {{ write: (b) => scritti.push(Array.from(b)) }};
let xtermPendingData = [], xtermPendingBytes = 0;
const PENDING_MAX_BYTES = 65536;
let termSessionId = {json.dumps(session_id)};

handleBinaryFrame(Uint8Array.from({json.dumps(list(frame))}).buffer);
console.log(JSON.stringify(scritti));
"""
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


class TestContrattoConIlClient:
    def test_payload_ricostruito_identico(self):
        payload = b"ciao dal terminale\r\n"
        scritti = _decodifica_con_node(encode_term_output("a1b2c3d4", payload), "a1b2c3d4")
        assert scritti == [list(payload)]

    def test_payload_binario_non_utf8(self):
        # Il motivo per cui il payload viaggia grezzo: l'output del PTY puo'
        # contenere byte che non formano UTF-8 valido.
        payload = bytes(range(256))
        scritti = _decodifica_con_node(encode_term_output("id01", payload), "id01")
        assert scritti == [list(payload)]

    def test_id_di_lunghezza_diversa_da_otto(self):
        # La lunghezza e' esplicita nel frame: il client non deve assumere 8.
        payload = b"xyz"
        scritti = _decodifica_con_node(encode_term_output("abc", payload), "abc")
        assert scritti == [list(payload)]

    def test_frame_di_un_altra_sessione_scartato(self):
        frame = encode_term_output("altra123", b"non mia")
        assert _decodifica_con_node(frame, "mia12345") == []

    def test_payload_vuoto(self):
        assert _decodifica_con_node(encode_term_output("abcd", b""), "abcd") == [[]]

    @pytest.mark.parametrize("frame", [
        b"", b"\x01", b"\x01\x08abc", b"\x01\x00dati", b"\x99\x02abdati",
    ])
    def test_frame_malformati_non_scrivono_nulla(self, frame):
        assert _decodifica_con_node(frame, None) == []
