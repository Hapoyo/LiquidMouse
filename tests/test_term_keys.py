"""Barra tasti del terminale: sequenze VT inviate al PTY.

Il blocco "contratto" di app.js (TERM_KEYS, ctrlChar, withMods) viene estratto
ed eseguito con node; qui si confrontano i risultati con le sequenze che
Windows Terminal/xterm mandano per gli stessi tasti. Un errore qui non si
vede in LAN finché qualcuno non preme ctrl+← e il cursore non si muove.
Se node non è installato, i test che lo richiedono vengono saltati.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
INDEX_HTML = ROOT / "static" / "index.html"

INIZIO = "// --- TASTI DEL TERMINALE: contratto"
FINE = "// --- fine contratto ---"

richiede_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _contratto() -> str:
    js = APP_JS.read_text(encoding="utf-8")
    assert INIZIO in js and FINE in js, "blocco contratto dei tasti non trovato in app.js"
    return js[js.index(INIZIO):js.index(FINE)]


def _node(espressione: str):
    """Valuta `espressione` (JSON-serializzabile) dopo il blocco contratto."""
    codice = _contratto() + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


NESSUNO = "{ctrl: false, alt: false}"
CTRL = "{ctrl: true, alt: false}"
ALT = "{ctrl: false, alt: true}"
CTRL_ALT = "{ctrl: true, alt: true}"


@richiede_node
class TestSequenze:
    @pytest.mark.parametrize("tasto, attesa", [
        ("esc", "\x1b"), ("tab", "\t"), ("enter", "\r"),
        ("up", "\x1b[A"), ("down", "\x1b[B"), ("right", "\x1b[C"), ("left", "\x1b[D"),
        ("home", "\x1b[H"), ("end", "\x1b[F"), ("pgup", "\x1b[5~"), ("pgdn", "\x1b[6~"),
        ("ctrl-c", "\x03"), ("ctrl-d", "\x04"), ("ctrl-z", "\x1a"), ("ctrl-l", "\x0c"),
    ])
    def test_tasto_senza_modificatori(self, tasto, attesa):
        assert _node(f"withMods(TERM_KEYS[{tasto!r}], {tasto!r}, {NESSUNO})") == attesa

    @pytest.mark.parametrize("tasto, mods, attesa", [
        ("left", CTRL, "\x1b[1;5D"),       # parola precedente
        ("right", CTRL, "\x1b[1;5C"),
        ("up", ALT, "\x1b[1;3A"),
        ("home", CTRL, "\x1b[1;5H"),
        ("end", CTRL_ALT, "\x1b[1;7F"),
    ])
    def test_frecce_con_modificatori(self, tasto, mods, attesa):
        assert _node(f"withMods(TERM_KEYS[{tasto!r}], {tasto!r}, {mods})") == attesa

    @pytest.mark.parametrize("carattere, mods, attesa", [
        ("c", CTRL, "\x03"),
        ("C", CTRL, "\x03"),               # maiuscola dalla tastiera del telefono
        ("r", CTRL, "\x12"),               # ricerca nella cronologia (bash/pwsh)
        ("[", CTRL, "\x1b"),
        (" ", CTRL, "\x00"),
        ("1", CTRL, "1"),                  # nessun codice di controllo: invariato
        ("f", ALT, "\x1bf"),
        ("x", CTRL_ALT, "\x1b\x18"),
        ("a", NESSUNO, "a"),
    ])
    def test_carattere_digitato(self, carattere, mods, attesa):
        assert _node(f"withMods({json.dumps(carattere)}, null, {mods})") == attesa

    def test_tab_con_ctrl_non_diventa_una_freccia(self):
        # Solo frecce e home/end hanno la forma CSI 1;<mod>: il resto passa da
        # ctrlChar, che sul tab (già un codice di controllo) non fa nulla.
        assert _node(f"withMods(TERM_KEYS.tab, 'tab', {CTRL})") == "\t"


class TestBarraNellaPagina:
    def _tasti_html(self) -> list[str]:
        html = INDEX_HTML.read_text(encoding="utf-8")
        return re.findall(r'class="tkey[^"]*"\s+data-key="([^"]+)"', html)

    def _tasti_js(self) -> set[str]:
        blocco = _contratto()
        mappa = blocco[blocco.index("const TERM_KEYS = {"):blocco.index("};")]
        # Chiavi con o senza apici: esc: '...', 'ctrl-c': '...'
        return {quotata or nuda
                for quotata, nuda in re.findall(r"(?:'([\w-]+)'|\b(\w+))\s*:\s*'", mappa)}

    def test_ogni_tasto_della_barra_ha_una_sequenza(self):
        tasti = self._tasti_html()
        assert tasti, "nessun tasto .tkey in index.html"
        mancanti = set(tasti) - self._tasti_js() - {"ctrl", "alt"}
        assert not mancanti, f"tasti senza sequenza in TERM_KEYS: {mancanti}"

    def test_frecce_e_scorciatoie_presenti(self):
        tasti = set(self._tasti_html())
        assert {"up", "down", "left", "right"} <= tasti
        assert {"ctrl-c", "ctrl", "alt", "esc", "tab"} <= tasti

    def test_le_frecce_si_ripetono(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        for tasto in ("up", "down", "left", "right"):
            assert re.search(rf'data-key="{tasto}" data-repeat', html), tasto
