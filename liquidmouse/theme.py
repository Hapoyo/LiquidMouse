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
# Schiarito da #6B6880: contro gli sfondi scuri dell'app (#0D0D0D e #1C1C1E)
# quel valore era a 3.2-3.6:1 di contrasto WCAG, sotto la soglia AA di 4.5:1
# per testo normale — leggibile per etichette da 7-8pt solo in teoria, e
# usato anche per contenuto vero (riga di stato, messaggi UPnP). Questo valore
# tiene la stessa tonalità lavanda-grigio ma sale a 5.1-4.5:1.
COLOR_MUTED       = "#918EA4"        # testo secondario/muted
COLOR_BORDER      = "#2A2A2A"        # bordo sottile
COLOR_BORDER_GLOW = "#3A3540"        # bordo glass luminoso
COLOR_ERROR       = "#E55B5B"
COLOR_OK          = "#5BA878"
# Ex colore chiave "-transparentcolor": la trasparenza keyed produceva puntini
# bianchi sui bordi (pixel anti-aliasing degli angoli finti non combaciano col
# colore chiave). Ora la finestra è opaca e gli angoli li arrotonda DWM.
COLOR_TRANSPARENT = COLOR_BG
