"""Effetti nativi della finestra su Windows (DWM).

Solo ctypes: non tocca Tk, riceve un handle di finestra e basta.
"""

import ctypes


def apply_dwm_acrylic(hwnd: int) -> bool:
    """Applica DWM Acrylic/Mica backdrop su Windows 11 (build 22000+).
    Ritorna True se riuscito, False su fallback (Win10 o errore)."""
    try:
        # La finestra va marcata dark-mode PRIMA del backdrop: senza questo
        # flag DWM compone il Mica nella variante chiara (anche a tema di
        # sistema scuro) e le aree transparentcolor diventano bande bianche
        # illeggibili dietro i testi.
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
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2  # Mica (finestra principale, Win11 22H2+ build 22621)
        value = ctypes.c_int(DWMSBT_MAINWINDOW)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        return res == 0
    except Exception:
        return False
