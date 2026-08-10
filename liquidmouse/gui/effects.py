"""Effetti nativi della finestra su Windows (DWM).

Solo ctypes: non tocca Tk, riceve un handle di finestra e basta.
"""

import ctypes


def apply_dwm_style(hwnd: int) -> bool:
    """Applica dark-mode e angoli smussati DWM su Windows 11 (build 22000+).

    Niente backdrop Mica/acrylic: la finestra e' una card piatta e opaca,
    coerente col "terminal chrome" del client web (bordi netti, superfici
    piatte, senza vetro smerigliato). Ritorna True se riuscito, False su
    fallback (Win10 o errore).
    """
    try:
        # La finestra va marcata dark-mode: senza questo flag DWM la
        # compone nella variante chiara (anche a tema di sistema scuro) e
        # le aree transparentcolor diventano bande bianche illeggibili
        # dietro i testi.
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
