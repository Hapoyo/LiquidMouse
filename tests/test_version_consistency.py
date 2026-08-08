"""La versione è dichiarata in un posto solo, ma letta da quattro.

`liquidmouse/version.py` è la fonte di verità; build.py, il workflow di build e
test_server.py la leggono con una regex (senza importare il modulo) e il README
la ripete a mano. Questi test intercettano il disallineamento, che altrimenti si
manifesta solo come una release pubblicata con l'EXE della versione sbagliata.
"""

import re
from pathlib import Path

import pytest

from liquidmouse.version import VERSION

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "liquidmouse" / "version.py"


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION


def test_version_file_is_regex_parsable():
    # È così che la leggono la CI e build.py: se il formato cambia, la build
    # ripiega su 'dev' senza fallire.
    src = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
    assert m is not None
    assert m.group(1) == VERSION


def test_readme_declares_the_same_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    versioni = set(re.findall(r"v(\d+\.\d+\.\d+)", readme.split("\n## ")[0]))
    assert versioni, "il README non dichiara nessuna versione nell'intestazione"
    assert versioni == {VERSION}, f"README {versioni} != version.py {VERSION}"


@pytest.mark.parametrize(
    "percorso",
    ["build.py", "test_server.py", ".github/workflows/build.yml"],
)
def test_consumers_read_the_version_file(percorso):
    testo = (ROOT / percorso).read_text(encoding="utf-8")
    assert "VERSION" in testo
    assert "liquidmouse/version.py" in testo or "\"version.py\"" in testo, (
        f"{percorso} non punta piu' a liquidmouse/version.py"
    )
