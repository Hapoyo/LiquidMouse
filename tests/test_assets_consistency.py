"""Gli asset statici sono elencati in tre posti che devono restare allineati.

| File | Cosa |
|---|---|
| `LiquidControl.spec` (`datas`)        | il file finisce nel bundle |
| `liquidmouse/net/static.py`           | l'URL è servito |
| `build.py` (`check_files`)            | l'assenza è vista prima della build |

Dimenticarne uno produce guasti che non si vedono in sviluppo: un file fuori dal
`datas` dà una build verde e un EXE che risponde 404; un file fuori da
`STATIC_ROUTES` funziona finché si prova in LAN e si rompe solo da remoto.
Questi test sono l'unico controllo automatico su quel disallineamento.
"""

import re
from pathlib import Path

import pytest

from liquidmouse.net.static import STATIC_ROUTES

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"

# Elencati nello spec ma non serviti via HTTP: l'icona della finestra è letta
# dal disco da Tk, non richiesta dal browser sotto questo nome.
SOLO_BUNDLE: set[str] = set()


def _file_in_static_routes() -> set[str]:
    return {fname for fname, _ in STATIC_ROUTES.values()}


def _file_nel_datas() -> set[str]:
    spec = (ROOT / "LiquidControl.spec").read_text(encoding="utf-8")
    blocco = spec[spec.index("datas=["):spec.index("] + _winpty_data")]
    # La destinazione (secondo elemento) non è più sempre '.': da quando gli
    # asset vivono sotto static/, rispecchia il percorso sorgente. Qui conta
    # solo il primo elemento (il file sorgente), qualunque sia la destinazione.
    return set(re.findall(r"\('([^']+)',\s*'[^']*'\)", blocco))


def _file_in_check_files() -> set[str]:
    build = (ROOT / "build.py").read_text(encoding="utf-8")
    blocco = build[build.index("required = ["):build.index("]", build.index("required = ["))]
    return set(re.findall(r'"([^"]+\.(?:html|css|js|ico))"', blocco))


class TestElenchiAllineati:
    def test_ogni_asset_servito_e_nel_bundle(self):
        mancanti = _file_in_static_routes() - _file_nel_datas()
        assert not mancanti, (
            f"{mancanti} sono in STATIC_ROUTES ma non nel datas dello spec: "
            "la build resterebbe verde e l'EXE risponderebbe 404")

    def test_ogni_asset_del_bundle_e_servito(self):
        mancanti = _file_nel_datas() - _file_in_static_routes() - SOLO_BUNDLE
        assert not mancanti, (
            f"{mancanti} sono nel bundle ma non in STATIC_ROUTES: "
            "irraggiungibili via HTTP")

    def test_check_files_copre_gli_asset_del_bundle(self):
        mancanti = _file_nel_datas() - _file_in_check_files()
        assert not mancanti, (
            f"{mancanti} non sono in check_files() di build.py: "
            "l'assenza verrebbe scoperta solo a build finita")


class TestFileEsistenti:
    @pytest.mark.parametrize("nome", sorted(_file_in_static_routes()))
    def test_l_asset_esiste_nel_repo(self, nome):
        assert (ROOT / nome).is_file(), f"{nome} elencato ma assente dal repo"


class TestRiferimentiNellaPagina:
    """Ciò che index.html carica dev'essere servito."""

    def test_ogni_risorsa_referenziata_e_in_static_routes(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        riferimenti = set(re.findall(r'(?:src|href)="([^"]+)"', html))
        # Solo risorse locali: niente URL assoluti o ancore.
        locali = {r for r in riferimenti
                  if not r.startswith(("http", "#", "data:", "//"))}
        assert locali, "nessuna risorsa locale trovata in index.html"
        for risorsa in locali:
            assert f"/{risorsa}" in STATIC_ROUTES, (
                f"index.html carica {risorsa} ma non è in STATIC_ROUTES: "
                "404 in LAN e da remoto")

    def test_il_css_e_il_js_sono_file_separati(self):
        # Lo split è la ragione per cui questi controlli esistono: se il JS
        # tornasse inline, test_client_js in test_server.py scansionerebbe di
        # nuovo la pagina e questi test andrebbero rivisti.
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "<style>" not in html
        assert "<script>" not in html
        assert 'href="app.css"' in html
        assert 'src="app.js"' in html

    def test_gli_script_sono_deferiti(self):
        # xterm.js sono 283 KB render-blocking; app.js deve eseguire dopo di lui
        # e dopo il parsing del markup, che contiene gli onclick inline.
        html = INDEX_HTML.read_text(encoding="utf-8")
        for script in re.findall(r"<script[^>]*src=[^>]*>", html):
            assert "defer" in script, f"script non deferito: {script}"

    def test_app_js_non_e_un_modulo(self):
        # I 13 onclick= inline richiedono funzioni globali: con type="module"
        # tutti i bottoni della barra del terminale smetterebbero di funzionare.
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert 'src="app.js" defer' in html
        assert 'type="module"' not in html
        assert "onclick=" in html
