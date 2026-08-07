"""LiquidMouse — controllo remoto di mouse, tastiera e terminale via WebSocket.

Il pacchetto è pensato per essere importabile senza side-effect: importarlo non
apre finestre, non crea socket e non tocca lo stato del processo Windows. Tutto
questo avviene in `server.pyw` (l'entrypoint), così i moduli restano testabili
anche fuori da Windows.
"""

from liquidmouse.version import CODENAME, VERSION

__all__ = ["VERSION", "CODENAME"]
