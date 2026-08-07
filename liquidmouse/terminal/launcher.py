"""Apertura del terminale web in una finestra reale sul PC.

Quando una sessione viene creata dal telefono, il PC apre la stessa sessione in
una finestra del browser in modalità app (senza barra degli indirizzi), così si
può passare dall'uno all'altro senza perdere il contesto.
"""

import os
import shutil
import subprocess

from liquidmouse.events import log_message
from liquidmouse.ports import HTTP_PORT
from liquidmouse.theme import COLOR_MUTED

_BROWSER_CANDIDATES = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
]


def open_pc_terminal(sid: str) -> None:
    """Apre la sessione `sid` in una finestra sul PC.

    Prova Edge/Chrome in modalità --app (finestra pulita), fallback al browser
    predefinito.
    """
    url = f"http://127.0.0.1:{HTTP_PORT}/?term={sid}"
    candidates = [os.path.expandvars(p) for p in _BROWSER_CANDIDATES]
    candidates += [shutil.which("msedge"), shutil.which("chrome")]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=920,620"])
                return
            except Exception:
                pass
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception as e:
        log_message(f"Apertura finestra PC fallita: {e}", color=COLOR_MUTED)
