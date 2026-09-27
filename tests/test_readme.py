"""I collegamenti locali del README e del CHANGELOG puntano a file esistenti.

Le immagini stanno in docs/img e si rigenerano con tools/anteprime.py: un nome
cambiato lì lascerebbe sulla pagina GitHub un'immagine rotta che nessun altro
test vedrebbe.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ![alt](percorso), [testo](percorso) e <img src="percorso">
_LINK = re.compile(r'\]\(([^)\s]+)\)|<img[^>]*\bsrc="([^"]+)"')


def _link_locali(testo: str) -> list[str]:
    link = [a or b for a, b in _LINK.findall(testo)]
    return [l.split("#")[0] for l in link
            if not l.startswith(("http://", "https://", "#", "mailto:"))]


@pytest.mark.parametrize("documento", ["README.md", "CHANGELOG.md"])
def test_local_links_exist(documento):
    testo = (ROOT / documento).read_text(encoding="utf-8")
    mancanti = [l for l in _link_locali(testo) if not (ROOT / l).exists()]
    assert not mancanti, f"{documento}: collegamenti a file inesistenti {mancanti}"


def test_readme_shows_the_previews():
    testo = (ROOT / "README.md").read_text(encoding="utf-8")
    immagini = {l for l in _link_locali(testo) if l.startswith("docs/img/")}
    assert "docs/img/animazione.gif" in immagini
    assert len(immagini) >= 8


def test_anchor_links_point_to_headings():
    testo = (ROOT / "README.md").read_text(encoding="utf-8")
    # Ancore alla maniera di GitHub: minuscolo, spazi → trattini, via la punteggiatura.
    ancore = {
        re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
        for h in re.findall(r"^#+ (.+)$", testo, flags=re.M)
    }
    for ancora in re.findall(r"\]\(#([^)]+)\)", testo):
        assert ancora in ancore, f"ancora #{ancora} senza titolo corrispondente"


def test_changelog_has_the_current_version():
    from liquidmouse.version import VERSION
    testo = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(VERSION)} — \d{{4}}-\d{{2}}-\d{{2}}$", testo, flags=re.M), \
        f"CHANGELOG.md senza la voce della versione {VERSION}"
