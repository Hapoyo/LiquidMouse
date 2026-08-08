"""Risoluzione dei percorsi degli asset, in sorgente e dentro il bundle.

PyInstaller (onefile) estrae i `datas` in una directory temporanea esposta come
`sys._MEIPASS`; da sorgente gli stessi file stanno accanto a server.pyw.
"""

import os
import sys


def base_dir() -> str:
    """Directory che contiene gli asset: `sys._MEIPASS` se congelato."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = base_dir()
ICON_PATH = os.path.join(BASE_DIR, "static", "icon.ico")
