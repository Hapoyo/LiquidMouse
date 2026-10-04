"""Errore di autenticazione nel client: niente riconnessione automatica.

Il blocco "contratto" di app.js (`makeAuthGate`) viene estratto ed eseguito con
node. Il bug che copre: dopo un PIN errato `stopWithError` fermava le
riconnessioni a tempo, ma `visibilitychange` (il telefono che si risveglia)
ricollegava comunque con lo stesso PIN, e al quinto errore il server blocca
l'IP per 30 minuti. Salta se node non c'è.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
INIZIO = "// --- AUTH: contratto"
FINE = "// --- fine contratto ---"

richiede_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _node(espressione: str):
    js = _js()
    assert INIZIO in js, "blocco contratto dell'autenticazione non trovato in app.js"
    blocco = js[js.index(INIZIO):]
    blocco = blocco[:blocco.index(FINE)]
    codice = blocco + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@richiede_node
class TestGate:
    def test_all_inizio_si_puo_riconnettere(self):
        assert _node("makeAuthGate().canAutoReconnect()") is True

    def test_dopo_un_errore_di_autenticazione_no(self):
        assert _node("(() => { const g = makeAuthGate(); g.fail(); return g.canAutoReconnect(); })()") is False

    def test_il_reset_riabilita(self):
        assert _node("(() => { const g = makeAuthGate(); g.fail(); g.reset(); return g.canAutoReconnect(); })()") is True

    def test_fail_e_idempotente(self):
        assert _node("(() => { const g = makeAuthGate(); g.fail(); g.fail(); g.reset(); return g.canAutoReconnect(); })()") is True


def _corpo(js: str, ancora: str) -> str:
    """Testo dalla riga dell'ancora fino alla fine del blocco `});` che la chiude."""
    i = js.index(ancora)
    return js[i:js.index("\n    });", i)]


class TestCablaggio:
    def test_visibilitychange_non_riconnette_dopo_errore_di_autenticazione(self):
        corpo = _corpo(_js(), "document.addEventListener('visibilitychange'")
        assert "authGate.canAutoReconnect()" in corpo

    def test_gli_errori_di_autenticazione_alzano_il_flag(self):
        js = _js()
        for tipo in ("auth_fail", "auth_blocked"):
            ramo = js[js.index(f"msg.type === '{tipo}'"):]
            ramo = ramo[:ramo.index("return;")]
            assert "authGate.fail()" in ramo, tipo

    def test_il_flag_si_azzera_solo_con_connetti_o_pin_modificato(self):
        js = _js()
        assert len(re.findall(r"authGate\.reset\(\)", js)) == 3
        assert "connectBtn.addEventListener('click', () => { authGate.reset();" in js
        assert "ipInput.addEventListener('keyup', (e) => { if (e.key === 'Enter') { authGate.reset();" in js
        assert "pinInput.addEventListener('input', () => authGate.reset())" in js
