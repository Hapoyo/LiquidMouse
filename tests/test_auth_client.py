"""Errore di autenticazione nel client: niente riconnessione automatica.

Il blocco "contratto" di app-core.js (`makeAuthGate`) viene estratto ed eseguito con
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

from tests.clientjs import leggi_client
INIZIO = "// --- AUTH: contratto"
FINE = "// --- fine contratto ---"

richiede_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _js() -> str:
    return leggi_client()


def _node(espressione: str):
    js = _js()
    assert INIZIO in js, "blocco contratto dell'autenticazione non trovato nel client"
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


@richiede_node
class TestSmistamento:
    """HANDLERS + dispatchMessage eseguiti con node su dipendenze finte."""

    PROLOGO = """
const log = [];
const authGate = { fail: () => log.push('fail') };
const stopWithError = (t) => log.push('stop:' + t);
const setStatus = (t, k) => log.push('status:' + t + ':' + k);
const sendAuth = () => log.push('sendAuth');
const onAuthenticated = () => log.push('authenticated');
const handleFilesMessage = (m) => log.push('files:' + m.type);
"""

    def _esegui(self, corpo: str):
        js = _js()
        # Dalla tabella alla fine di dispatchMessage (che precede connectServer).
        i = js.index("const HANDLERS = new Map(")
        j = js.index("function connectServer")
        codice = self.PROLOGO + js[i:j] + corpo + "\nprocess.stdout.write(JSON.stringify(log));\n"
        out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_instrada_i_tipi_noti_e_gli_sftp(self):
        log = self._esegui("""
const conn = { pingTimestamp: 0 };
dispatchMessage({ type: 'auth_required' }, conn);
dispatchMessage({ type: 'auth_ok' }, conn);
dispatchMessage({ type: 'auth_fail', remaining: 2 }, conn);
dispatchMessage({ type: 'auth_blocked' }, conn);
dispatchMessage({ type: 'sftp_listing' }, conn);
dispatchMessage({ type: 'sconosciuto' }, conn);
""")
        assert log == ["sendAuth", "authenticated", "fail", "stop:pin errato (2 tentativi rimasti)",
                       "fail", "stop:bloccato — riprova tra 30 min", "files:sftp_listing"]

    def test_il_pong_senza_ping_non_fa_nulla(self):
        log = self._esegui("""
dispatchMessage({ type: 'pong' }, { pingTimestamp: 0 });
dispatchMessage({ type: 'pong' }, { pingTimestamp: Date.now() });
""")
        assert len(log) == 1 and log[0].startswith("status:connesso ")

    def test_un_tipo_come_constructor_non_trova_i_membri_di_object(self):
        log = self._esegui("dispatchMessage({ type: 'constructor' }, {});")
        assert log == []

    def test_un_messaggio_senza_tipo_lancia_per_essere_loggato(self):
        log = self._esegui("""
for (const m of [null, {}, { type: 5 }]) {
    try { dispatchMessage(m, {}); log.push('ok'); } catch (e) { log.push('throw'); }
}""")
        assert log == ["throw", "throw", "throw"]


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
        # Gestori della tabella HANDLERS: ognuno finisce al `},` della riga
        # con la sola indentazione del gestore.
        for tipo in ("auth_fail", "auth_blocked"):
            ramo = js[js.index(f"        {tipo}: "):]
            ramo = ramo[:ramo.index("\n        },")]
            assert "authGate.fail()" in ramo, tipo

    def test_il_flag_si_azzera_solo_con_connetti_o_pin_modificato(self):
        js = _js()
        assert len(re.findall(r"authGate\.reset\(\)", js)) == 3
        assert "connectBtn.addEventListener('click', () => { authGate.reset();" in js
        assert "ipInput.addEventListener('keyup', (e) => { if (e.key === 'Enter') { authGate.reset();" in js
        assert "pinInput.addEventListener('input', () => authGate.reset())" in js
