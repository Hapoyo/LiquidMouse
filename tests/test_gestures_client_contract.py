"""Decisioni pure dei gesti del touchpad nel client (tap a due/tre dita, tap-e-
trascina, scroll orizzontale), con il blocco "GESTI: contratto" di app.js
eseguito da node, e allineamento con i valori che il server accetta.
Salta se node non c'è.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from liquidmouse.net.protocol import CLICK_BUTTONS, SCROLL_CLAMP, known_types

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
INIZIO = "// --- GESTI: contratto"
FINE = "// --- fine contratto ---"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _node(espressione: str):
    js = APP_JS.read_text(encoding="utf-8")
    assert INIZIO in js, "blocco contratto dei gesti non trovato in app.js"
    blocco = js[js.index(INIZIO):]
    blocco = blocco[:blocco.index(FINE)]
    codice = blocco + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
class TestMultiTap:
    @pytest.mark.parametrize("dita, ms, mossa, atteso", [
        (2, 120, 2, "right"),          # due dita = destro
        (3, 120, 2, "middle"),         # tre dita = centrale
        (2, 299, 14, "right"),         # ai limiti
        (2, 300, 2, None),             # troppo lungo
        (2, 120, 15, None),            # le dita si sono mosse: era uno scroll
        (1, 50, 0, None),              # un dito non è un multi-tap
        (4, 120, 2, None),             # quattro dita: nessun gesto
        (0, 0, 0, None),
    ])
    def test_pulsante(self, dita, ms, mossa, atteso):
        assert _node(f"multiTapButton({dita}, {ms}, {mossa})") == atteso

    def test_i_pulsanti_prodotti_sono_accettati_dal_server(self):
        prodotti = {_node(f"multiTapButton({n}, 100, 0)") for n in (2, 3)}
        assert prodotti <= set(CLICK_BUTTONS)


@needs_node
class TestTapETrascina:
    @pytest.mark.parametrize("fine, ora, dist, bloccato, atteso", [
        (1000, 1200, 5, False, True),      # secondo tocco entro 300 ms e vicino
        (1000, 1299, 40, False, True),     # ai limiti
        (1000, 1300, 5, False, False),     # troppo tardi
        (1000, 1200, 41, False, False),    # troppo lontano
        (0, 1200, 0, False, False),        # nessun tap precedente
        (1000, 1200, 5, True, False),      # il blocco "trascina" del menu ha la precedenza
    ])
    def test_armato(self, fine, ora, dist, bloccato, atteso):
        assert _node(f"dragArmed({fine}, {ora}, {dist}, {json.dumps(bloccato)})") is atteso


@needs_node
class TestScrollDelta:
    def test_verticale_come_sempre(self):
        # Stesso guadagno e stesso verso di prima: dita giù = positivo.
        d = _node("scrollDelta(0, 8)")
        assert d["v"] == pytest.approx(3.0) and d["h"] == 0

    def test_orizzontale_dita_a_destra_scorre_a_sinistra(self):
        d = _node("scrollDelta(8, 0)")
        assert d["h"] == pytest.approx(-3.0) and d["v"] == 0

    def test_il_tremolio_dell_altro_asse_si_scarta(self):
        d = _node("scrollDelta(10, 2)")
        assert d["v"] == 0 and d["h"] != 0
        d = _node("scrollDelta(2, 10)")
        assert d["h"] == 0 and d["v"] != 0

    def test_la_diagonale_vera_conta_su_entrambi_gli_assi(self):
        d = _node("scrollDelta(8, 8)")
        assert d["v"] != 0 and d["h"] != 0

    def test_fermo(self):
        assert _node("scrollDelta(0, 0)") == {"v": 0, "h": 0}


class TestAllineamentoConIlServer:
    def test_il_client_manda_solo_tipi_registrati(self):
        js = APP_JS.read_text(encoding="utf-8")
        tipi = set(re.findall(r"type:\s*'([a-z_]+)'", js))
        gesti = {"click", "drag", "scroll", "move"}
        assert gesti <= tipi
        assert gesti <= known_types()

    def test_lo_scroll_orizzontale_usa_il_campo_che_il_server_legge(self):
        js = APP_JS.read_text(encoding="utf-8")
        assert "msg.h = hAmount" in js
        protocol = (Path(APP_JS).parent.parent / "liquidmouse" / "net" / "protocol.py").read_text(
            encoding="utf-8")
        assert "data.get('h')" in protocol

    def test_i_pulsanti_inviati_sono_quelli_ammessi(self):
        js = APP_JS.read_text(encoding="utf-8")
        inviati = set(re.findall(r"sendClick\('([a-z]+)'\)", js))
        inviati |= set(re.findall(r"return maxTouches === 2 \? '([a-z]+)' : \(maxTouches === 3 \? '([a-z]+)'",
                                  js)[0])
        assert inviati <= set(CLICK_BUTTONS)
        assert "middle" in inviati

    def test_il_tetto_dello_scroll_copre_i_messaggi_del_client(self):
        # Un messaggio di scroll vale al massimo qualche scatto per frame.
        assert SCROLL_CLAMP >= 20

    def test_nessuna_animazione_nei_gestori_dei_gesti(self):
        js = APP_JS.read_text(encoding="utf-8")
        blocco = js[js.index("// --- GESTI: tap, tap-e-trascina"):js.index("// --- CLICK ---")]
        assert "anima(" not in blocco and "Motion" not in blocco
        assert "transition" not in blocco and "animate" not in blocco
