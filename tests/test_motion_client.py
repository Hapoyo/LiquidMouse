"""Motion (motion.dev) nel client: asset locale, ordine di caricamento.

Motion è un abbellimento: la pagina deve funzionare identica se il file manca
o non si carica. Per questo arriva come file locale (niente CDN: il client
gira anche in una LAN senza internet, e ogni path fuori whitelist è 404) e
viene caricato prima di app.js, entrambi deferiti.
"""

import re
from pathlib import Path

from liquidmouse.net.static import STATIC_ROUTES

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"
MOTION_JS = ROOT / "static" / "vendor" / "motion.js"
LICENZA = ROOT / "static" / "vendor" / "LICENSE-motion.txt"


class TestAsset:
    def test_e_la_build_umd_che_espone_il_global(self):
        testa = MOTION_JS.read_text(encoding="utf-8")[:400]
        assert ".Motion={}" in testa, "motion.js non è la build UMD con il global `Motion`"

    def test_la_licenza_mit_lo_accompagna(self):
        testo = LICENZA.read_text(encoding="utf-8")
        assert "MIT License" in testo and "Motion" in testo

    def test_entrambi_serviti(self):
        assert STATIC_ROUTES["/motion.js"][0] == "static/vendor/motion.js"
        assert STATIC_ROUTES["/LICENSE-motion.txt"][0] == "static/vendor/LICENSE-motion.txt"


class TestCaricamento:
    def test_motion_prima_di_app_js_e_deferito(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        script = re.findall(r'<script src="([^"]+)" defer></script>', html)
        assert "motion.js" in script, "motion.js non caricato (o non deferito)"
        assert script.index("motion.js") < script.index("app.js"), (
            "motion.js deve eseguire prima di app.js: gli script deferiti "
            "girano nell'ordine del documento")

    def test_niente_cdn(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert not re.search(r'src="(https?:)?//', html), "script da CDN: in LAN offline è 404"
