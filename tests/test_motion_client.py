"""Motion (motion.dev) nel client: asset locale, ordine di caricamento.

Motion è un abbellimento: la pagina deve funzionare identica se il file manca
o non si carica. Per questo arriva come file locale (niente CDN: il client
gira anche in una LAN senza internet, e ogni path fuori whitelist è 404) e
viene caricato prima di app.js, entrambi deferiti.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from liquidmouse.net.static import STATIC_ROUTES

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"
APP_JS = ROOT / "static" / "app.js"
MOTION_JS = ROOT / "static" / "vendor" / "motion.js"
LICENZA = ROOT / "static" / "vendor" / "LICENSE-motion.txt"
INIZIO_MOTION = "// --- MOTION:"
FINE_MOTION = "    // Colore della riga di stato"


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


class TestUsoInAppJs:
    def test_il_global_si_tocca_solo_nella_guardia(self):
        # Un `Motion.animate(...)` diretto lancerebbe ReferenceError con
        # motion.js assente e fermerebbe il resto dello script.
        js = APP_JS.read_text(encoding="utf-8")
        assert not re.findall(r"(?<![\w.])Motion\.", js), "uso diretto di Motion fuori da anima()"
        fuori = js[:js.index(INIZIO_MOTION)] + js[js.index(FINE_MOTION):]
        assert "window.Motion" not in fuori, "window.Motion letto fuori dal blocco MOTION"

    def test_niente_animazioni_sul_percorso_del_touchpad(self):
        # Dal touchstart del touchpad fino ai click: ogni animazione lì è
        # latenza sul cursore.
        js = APP_JS.read_text(encoding="utf-8")
        blocco = js[js.index("function flushSend()"):js.index("// --- CLICK ---")]
        assert "anima(" not in blocco and "Motion" not in blocco

    def test_il_touchpad_non_e_premibile(self):
        js = APP_JS.read_text(encoding="utf-8")
        premibili = js[js.index("const PREMIBILI"):js.index("let premuto")]
        assert "touchpad" not in premibili


def _node_motion(prologo: str, espressione: str):
    js = APP_JS.read_text(encoding="utf-8")
    blocco = js[js.index(INIZIO_MOTION):js.index(FINE_MOTION)]
    codice = prologo + "\n" + blocco + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


DOCUMENTO_FINTO = """
const classi = [];
const document = { documentElement: { classList: { add: c => classi.push(c) } },
                   addEventListener: () => {} };
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
class TestDegrado:
    def test_senza_motion_anima_non_fa_nulla(self):
        prologo = DOCUMENTO_FINTO + "const window = {};"
        assert _node_motion(prologo, "[anima({}, {opacity: 1}), animaElenco({children: [1]}), classi]") \
            == [None, None, []]

    def test_con_meno_movimento_anima_non_fa_nulla(self):
        prologo = DOCUMENTO_FINTO + """
const window = { Motion: { animate: () => 'animato', stagger: () => 0 },
                 matchMedia: () => ({ matches: true }) };"""
        # La classe .motion c'è (le riserve CSS tacciono), ma nessuna animazione.
        assert _node_motion(prologo, "[anima({}, {opacity: 1}), classi]") == [None, ["motion"]]

    def test_con_motion_anima_delega(self):
        prologo = DOCUMENTO_FINTO + """
const window = { Motion: { animate: () => 'animato', stagger: () => 0 },
                 matchMedia: () => ({ matches: false }) };"""
        assert _node_motion(prologo, "[anima({}, {opacity: 1}), anima(null, {}), anima([], {})]") \
            == ["animato", None, None]

    def test_un_errore_di_motion_non_esce(self):
        prologo = DOCUMENTO_FINTO + """
const window = { Motion: { animate: () => { throw new Error('x'); }, stagger: () => 0 },
                 matchMedia: () => ({ matches: false }) };"""
        assert _node_motion(prologo, "anima({}, {opacity: 1})") is None
