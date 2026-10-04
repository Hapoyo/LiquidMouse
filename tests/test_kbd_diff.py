"""Diff della tastiera del telefono: prefisso comune fra valore vecchio e nuovo.

Il blocco "contratto" di app.js viene estratto ed eseguito con node. Il diff
per sola lunghezza perdeva le sostituzioni (correzione automatica, suggerimenti):
"ciao" -> "ciaone" non e' lo stesso di "cia" -> "cie".
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
INIZIO = "// --- TASTIERA: contratto"
FINE = "// --- fine contratto ---"

richiede_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _diff(prev: str, new: str) -> dict:
    js = APP_JS.read_text(encoding="utf-8")
    assert INIZIO in js, "blocco contratto della tastiera non trovato in app.js"
    inizio = js.index(INIZIO)
    blocco = js[inizio:js.index(FINE, inizio)]
    codice = blocco + f"\nprocess.stdout.write(JSON.stringify(diffTastiera({json.dumps(prev)}, {json.dumps(new)})));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True,
                         timeout=30, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@richiede_node
class TestDiffTastiera:
    @pytest.mark.parametrize("prev, new, cancella, aggiungi", [
        ("", "ciao", 0, "ciao"),
        ("cia", "ciao", 0, "o"),
        ("ciao", "cia", 1, ""),
        ("ciao", "", 4, ""),
        ("ciao", "ciao", 0, ""),
        # Correzione automatica: stessa lunghezza, testo diverso.
        ("teh", "the", 2, "he"),
        # Sostituzione piu' lunga della parte tolta.
        ("cia", "cie!", 1, "e!"),
        # Completamento che accorcia e riscrive.
        ("ciaoo", "ciao mondo", 1, " mondo"),
    ])
    def test_diff(self, prev, new, cancella, aggiungi):
        assert _diff(prev, new) == {"del": cancella, "add": aggiungi}

    def test_emoji_conta_un_solo_backspace(self):
        assert _diff("a\U0001F600", "a") == {"del": 1, "add": ""}

    def test_non_spezza_una_coppia_surrogata(self):
        # Due emoji che condividono la prima unita' UTF-16.
        assert _diff("\U0001F600", "\U0001F601") == {"del": 1, "add": "\U0001F601"}
