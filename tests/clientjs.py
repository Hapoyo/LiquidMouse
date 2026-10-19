"""Il client JS sta in quattro script classici (static/app-*.js).

I test dei contratti cercano blocchi e funzioni per testo: invece di sapere in
quale file vive ciascuno, leggono tutto come un solo sorgente, nell'ordine in
cui index.html li carica. L'ordine qui è lo stesso di index.html e
test_assets_consistency.py lo controlla.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
CLIENT_JS = ("app-core.js", "app-touchpad.js", "app-terminal.js", "app-files.js")


def leggi_client() -> str:
    """Sorgente completo del client: i quattro file uniti, in ordine di caricamento."""
    return "\n".join((STATIC / nome).read_text(encoding="utf-8") for nome in CLIENT_JS)
