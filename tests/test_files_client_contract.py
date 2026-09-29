"""Funzioni pure del file manager nel client (formato dimensioni, percorsi).

Come test_term_keys.py: il blocco "contratto" di app.js viene estratto ed
eseguito con node. Il percorso deve comporsi come lo compone il server
(`join_path`), altrimenti la lista mostra una cartella e il server ne apre
un'altra. Salta se node non c'è.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from liquidmouse.net.sftp import join_path

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
INIZIO = "// --- FILE: contratto"
FINE = "// --- fine contratto ---"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _node(espressione: str):
    js = APP_JS.read_text(encoding="utf-8")
    assert INIZIO in js, "blocco contratto dei file non trovato in app.js"
    blocco = js[js.index(INIZIO):]
    blocco = blocco[:blocco.index(FINE)]
    codice = blocco + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.parametrize("n, atteso", [
    (0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"),
    (10 * 1024, "10 KB"), (5 * 1024 ** 2, "5.0 MB"), (3 * 1024 ** 3, "3.0 GB"),
])
def test_formato_dimensioni(n, atteso):
    assert _node(f"formatSize({n})") == atteso


def test_dimensione_non_valida():
    assert _node("formatSize(-1)") == ""
    assert _node("formatSize(undefined)") == ""


@pytest.mark.parametrize("cartella, nome", [
    ("/", "a.txt"), ("/home", "a.txt"), ("/home/", "a b.txt"), ("/C:/Users/jack", "è.txt"),
])
def test_joinpath_coincide_con_il_server(cartella, nome):
    assert _node(f"joinPath({json.dumps(cartella)}, {json.dumps(nome)})") == join_path(cartella, nome)


@pytest.mark.parametrize("percorso, padre", [
    ("/", "/"), ("/home", "/"), ("/home/jack", "/home"), ("/home/jack/", "/home"),
    ("/C:/Users", "/C:"),
])
def test_parentpath(percorso, padre):
    assert _node(f"parentPath({json.dumps(percorso)})") == padre
