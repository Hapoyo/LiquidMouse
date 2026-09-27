"""Effetti nativi della finestra su Windows (DWM) e font privati del processo.

Solo ctypes: non tocca Tk, riceve un handle di finestra o dei percorsi e basta.
"""

import ctypes
import os
import sys

FR_PRIVATE = 0x10  # il font resta visibile solo a questo processo


def load_private_fonts(paths) -> int:
    """Rende disponibili a Tk i TTF del tema senza installarli nel sistema.

    Va chiamata prima di creare `tk.Tk()`: Tk elenca i font GDI alla prima
    richiesta. FR_PRIVATE li lega al processo, quindi spariscono all'uscita e
    non servono diritti di amministratore. Ritorna quanti font sono stati
    caricati; 0 fuori da Windows o se GDI rifiuta i file (allora Tk usa i
    font di ripiego del tema).
    """
    if sys.platform != "win32":
        return 0
    caricati = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            if ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0) > 0:
                caricati += 1
        except (AttributeError, OSError):
            return caricati
    return caricati


def apply_dwm_style(hwnd: int) -> bool:
    """Applica dark-mode e angoli smussati DWM su Windows 11 (build 22000+).

    Niente backdrop Mica/acrylic: la finestra e' un pannello piatto e opaco,
    coerente con il tema cyber del client web. Ritorna True se riuscito,
    False su fallback (Win10 o errore).
    """
    try:
        # La finestra va marcata dark-mode: senza questo flag DWM la
        # compone nella variante chiara (anche a tema di sistema scuro).
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20   # build 19041+; 19 su build precedenti
        dark = ctypes.c_int(1)
        res_dark = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))
        if res_dark != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        # Angoli arrotondati reali (Win11): sostituiscono il vecchio rounding
        # finto via transparentcolor che lasciava puntini di anti-aliasing.
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        corner = ctypes.c_int(DWMWCP_ROUND)
        res_corner = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        return res_dark == 0 and res_corner == 0
    except Exception:
        return False
