"""Palette e font — tema "cyber" di PiDash.

Computer di bordo retro futuristico: fondo quasi nero caldo, pannelli
arrotondati pieni (arancio, ambra, crema, rosa), numeri grandi in Space
Grotesk, microetichette in Space Mono minuscolo. Gli stessi valori stanno in
`static/app.css` (`:root`): cambiandone uno qui va cambiato anche là.

Modulo di sole costanti, senza import di tkinter: il core lo usa per marcare la
severità dei messaggi passati a `events.log_message`, quindi non deve trascinare
la GUI dentro moduli di rete o di terminale.
"""

# --- palette (PiDash, dash/render/theme.py) ---------------------------------
COLOR_BG     = "#1d1815"   # fondo
COLOR_PANEL  = "#2a2320"   # pannello scuro
COLOR_CREAM  = "#eee4cd"   # linguette chiuse, testo chiaro, pannelli chiari
COLOR_PAPER  = "#f6efdf"   # crema più chiaro
COLOR_TAN    = "#a59b8c"   # testo secondario, pannelli neutri
COLOR_ORANGE = "#ee7b50"
COLOR_AMBER  = "#f2bb5b"
# Un filo più chiaro del #e8505b di PiDash: là il rosa è solo un riempimento,
# qui è anche testo di errore su pannello scuro, e a #e8505b stava a 4.2:1,
# sotto la soglia WCAG AA di 4.5:1 (vedi tests/test_theme_contrast.py).
COLOR_PINK   = "#ec5c66"
COLOR_INK    = "#1d1815"   # testo scuro sui pannelli pieni
COLOR_LINE   = "#5b514a"   # linee sottili e contorni

# --- ruoli ------------------------------------------------------------------
# Il core colora i messaggi di log con questi: la GUI li mostra nella riga di
# stato. Nomi stabili, valori presi dalla palette.
COLOR_TEXT   = COLOR_CREAM
COLOR_MUTED  = COLOR_TAN
COLOR_BORDER = COLOR_LINE
COLOR_ACCENT = COLOR_ORANGE   # evento normale (sessione aperta, whitelist)
COLOR_OK     = COLOR_AMBER    # servizio attivo (UPnP, connessione)
COLOR_ERROR  = COLOR_PINK

# --- font -------------------------------------------------------------------
# File in static/fonts/, serviti al browser e caricati da Tk come font privati
# del processo (gui/effects.load_private_fonts). Se il caricamento fallisce Tk
# ripiega su FONT_*_FALLBACK.
FONT_FILES = (
    "static/fonts/SpaceGrotesk-Medium.ttf",
    "static/fonts/SpaceMono-Regular.ttf",
    "static/fonts/SpaceMono-Bold.ttf",
)
FONT_NUM   = "Space Grotesk Medium"   # numeri grandi (istanza statica a 500)
FONT_LABEL = "Space Mono"             # etichette, testi, riga di stato
FONT_NUM_FALLBACK   = "Segoe UI"
FONT_LABEL_FALLBACK = "Consolas"
