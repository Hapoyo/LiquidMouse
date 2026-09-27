"""Contrasto WCAG della palette (tema cyber da v2.6.0): COLOR_MUTED era il colore reale usato per
contenuto leggibile (riga di stato, messaggi UPnP nel pannello remoto), non
solo per etichette decorative — a #6B6880 stava sotto la soglia AA (4.5:1 per
testo normale) contro entrambi gli sfondi scuri dell'app. Questo test impedisce
che la palette torni sotto soglia senza che qualcuno se ne accorga leggendo un
pixel su schermo.
"""

from liquidmouse.theme import (
    COLOR_ACCENT,
    COLOR_AMBER,
    COLOR_BG,
    COLOR_CREAM,
    COLOR_ERROR,
    COLOR_INK,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_ORANGE,
    COLOR_PANEL,
    COLOR_PINK,
    COLOR_TAN,
    COLOR_TEXT,
)

WCAG_AA_NORMAL_TEXT = 4.5

# Colori di testo effettivamente usati come fg su sfondo scuro nella GUI.
# COLOR_BORDER e' un bordo, non testo: escluso apposta.
TEXT_COLORS = {
    "COLOR_TEXT": COLOR_TEXT,
    "COLOR_ACCENT": COLOR_ACCENT,
    "COLOR_MUTED": COLOR_MUTED,
    "COLOR_ERROR": COLOR_ERROR,
    "COLOR_OK": COLOR_OK,
}

# I due sfondi scuri reali dietro il testo: il fondo e il pannello scuro.
BACKGROUNDS = {"COLOR_BG": COLOR_BG, "COLOR_PANEL": COLOR_PANEL}

# Stile PiDash: pannelli pieni colorati con il testo in inchiostro scuro sopra
# (bottoni, PIN, sessioni). Anche quel testo deve reggere la soglia AA.
PANNELLI_PIENI = {
    "COLOR_CREAM": COLOR_CREAM,
    "COLOR_ORANGE": COLOR_ORANGE,
    "COLOR_AMBER": COLOR_AMBER,
    "COLOR_PINK": COLOR_PINK,
    "COLOR_TAN": COLOR_TAN,
}


def _linearizza(canale: int) -> float:
    c = canale / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminanza(hex_colore: str) -> float:
    hex_colore = hex_colore.lstrip("#")
    r, g, b = (int(hex_colore[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linearizza(r) + 0.7152 * _linearizza(g) + 0.0722 * _linearizza(b)


def contrasto(colore1: str, colore2: str) -> float:
    """Rapporto di contrasto WCAG 2.x fra due colori esadecimali."""
    l1, l2 = _luminanza(colore1), _luminanza(colore2)
    piu_chiaro, piu_scuro = max(l1, l2), min(l1, l2)
    return (piu_chiaro + 0.05) / (piu_scuro + 0.05)


class TestFormula:
    def test_bianco_su_nero_e_il_massimo(self):
        assert contrasto("#FFFFFF", "#000000") == 21.0

    def test_stesso_colore_e_1_a_1(self):
        assert contrasto("#6B6880", "#6B6880") == 1.0

    def test_e_simmetrico(self):
        assert contrasto("#F0EDE8", "#0D0D0D") == contrasto("#0D0D0D", "#F0EDE8")


class TestPaletteRispettaAA:
    def test_ogni_colore_di_testo_su_ogni_sfondo(self):
        insufficienti = []
        for nome_col, colore in TEXT_COLORS.items():
            for nome_bg, bg in BACKGROUNDS.items():
                rapporto = contrasto(colore, bg)
                if rapporto < WCAG_AA_NORMAL_TEXT:
                    insufficienti.append(
                        f"{nome_col} su {nome_bg}: {rapporto:.2f}:1 (< {WCAG_AA_NORMAL_TEXT})")
        assert not insufficienti, "\n".join(insufficienti)

    def test_muted_specificamente_sopra_soglia(self):
        # Il caso che ha causato il bug: non basta che sia "leggibile a
        # occhio" in un caso, deve reggere su entrambi gli sfondi reali.
        assert contrasto(COLOR_MUTED, COLOR_BG) >= WCAG_AA_NORMAL_TEXT
        assert contrasto(COLOR_MUTED, COLOR_PANEL) >= WCAG_AA_NORMAL_TEXT

    def test_inchiostro_sui_pannelli_pieni(self):
        insufficienti = [
            f"COLOR_INK su {nome}: {contrasto(COLOR_INK, bg):.2f}:1"
            for nome, bg in PANNELLI_PIENI.items()
            if contrasto(COLOR_INK, bg) < WCAG_AA_NORMAL_TEXT
        ]
        assert not insufficienti, "\n".join(insufficienti)


class TestCssAllineatoAlTema:
    """app.css ripete la palette in `:root`: i due elenchi devono coincidere,
    altrimenti telefono e finestra desktop tornano a due grigi diversi."""

    def test_variabili_css_uguali_alla_palette(self):
        import re
        from pathlib import Path

        css = (Path(__file__).resolve().parent.parent / "static" / "app.css").read_text(encoding="utf-8")
        attese = {
            "--bg": COLOR_BG, "--panel": COLOR_PANEL, "--cream": COLOR_CREAM,
            "--tan": COLOR_TAN, "--orange": COLOR_ORANGE, "--amber": COLOR_AMBER,
            "--pink": COLOR_PINK, "--ink": COLOR_INK,
        }
        for var, valore in attese.items():
            m = re.search(rf"{var}:\s*(#[0-9a-fA-F]{{6}})", css)
            assert m, f"{var} non definita in app.css"
            assert m.group(1).lower() == valore.lower(), f"{var}: {m.group(1)} != {valore}"
