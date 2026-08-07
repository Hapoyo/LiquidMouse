"""Palette dei colori — glassmorphism.

Modulo di sole costanti, senza import di tkinter: il core lo usa per marcare la
severità dei messaggi passati a `events.log_message`, quindi non deve trascinare
la GUI dentro moduli di rete o di terminale.
"""

COLOR_BG          = "#0D0D0D"        # sfondo opaco (fallback / area non-glass)
COLOR_SURFACE     = "#181818"        # surface secondaria
COLOR_GLASS       = "#1C1C1E"        # base glass card (pre-acrylic)
COLOR_TEXT        = "#F0EDE8"        # testo primario
COLOR_ACCENT      = "#DA7756"        # accento arancio (invariato)
COLOR_MUTED       = "#6B6880"        # testo secondario/muted
COLOR_BORDER      = "#2A2A2A"        # bordo sottile
COLOR_BORDER_GLOW = "#3A3540"        # bordo glass luminoso
COLOR_ERROR       = "#E55B5B"
COLOR_OK          = "#5BA878"
# Ex colore chiave "-transparentcolor": la trasparenza keyed produceva puntini
# bianchi sui bordi (pixel anti-aliasing degli angoli finti non combaciano col
# colore chiave). Ora la finestra è opaca e gli angoli li arrotonda DWM.
COLOR_TRANSPARENT = COLOR_BG
