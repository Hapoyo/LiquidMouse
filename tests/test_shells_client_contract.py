"""Scelta della shell del terminale: il client e la whitelist del server devono
restare allineati.

Come test_files_client_contract.py: il blocco "SHELL: contratto" di app.js viene
estratto ed eseguito con node. Il server manda l'elenco (`shells` in
`term_sessions`, derivato da terminal/commands.py); il client non ne conosce
nessuna di suo e invia solo un `cmd` presente in quell'elenco, che la whitelist
accetta. Salta se node non c'è.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from liquidmouse.terminal.commands import SHELLS, TERM_ALLOWED_CMDS, available_shells, resolve_argv

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
INIZIO = "// --- SHELL: contratto"
FINE = "// --- fine contratto ---"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")


def _node(espressione: str):
    js = APP_JS.read_text(encoding="utf-8")
    assert INIZIO in js, "blocco contratto delle shell non trovato in app.js"
    blocco = js[js.index(INIZIO):]
    blocco = blocco[:blocco.index(FINE)]
    codice = blocco + f"\nprocess.stdout.write(JSON.stringify({espressione}));\n"
    out = subprocess.run(["node", "-e", codice], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _msg_del_server(which):
    """Il `shells` che il server metterebbe in term_sessions, passato da JSON."""
    return json.loads(json.dumps(available_shells(which=which)))


@needs_node
class TestContrattoShell:
    def test_il_client_accetta_l_elenco_del_server_cosi_com_e(self):
        shells = _msg_del_server(lambda c: c)
        assert _node(f"parseShells({json.dumps(shells)})") == shells

    def test_ogni_shell_offerta_produce_un_term_create_accettato_dal_server(self):
        shells = _msg_del_server(lambda c: c)
        for s in shells:
            msg = _node(f"termCreateMessage(parseShells({json.dumps(shells)}), {json.dumps(s['cmd'])})")
            assert msg == {"type": "term_create", "cmd": s["cmd"]}
            # Il server lo accetta (resolve_argv solleva ValueError se non in whitelist).
            resolve_argv(msg["cmd"], which=lambda c: c, isabs=lambda p: False,
                         exists=lambda p: False)

    @pytest.mark.parametrize("cmd", ["rm", "format.exe", "cmd.exe /c calc", "", "CMD.EXE"])
    def test_un_comando_fuori_elenco_non_parte_nemmeno_dal_client(self, cmd):
        shells = _msg_del_server(lambda c: None)       # solo cmd.exe
        assert _node(f"termCreateMessage(parseShells({json.dumps(shells)}), {json.dumps(cmd)})") is None

    def test_senza_elenco_dal_server_resta_cmd(self):
        # Server vecchio (nessun campo `shells`) o messaggio malformato.
        for raw in ("undefined", "null", "'cmd.exe'", "{}", "[]", "[1, null, {}]"):
            assert _node(f"parseShells({raw})") == [{"cmd": "cmd.exe", "label": "cmd"}]

    def test_voci_malformate_o_ripetute_sono_scartate(self):
        raw = [
            {"cmd": "cmd.exe", "label": "cmd"},
            {"cmd": "cmd.exe", "label": "doppione"},
            {"cmd": "a b", "label": "spazio"},
            {"cmd": "x" * 40, "label": "lungo"},
            {"cmd": "bash", "label": ""},
            {"cmd": 5, "label": "numero"},
            {"cmd": "wsl", "label": "wsl"},
        ]
        assert _node(f"parseShells({json.dumps(raw)})") == [
            {"cmd": "cmd.exe", "label": "cmd"}, {"cmd": "wsl", "label": "wsl"}]

    def test_la_scelta_salvata_vale_solo_se_ancora_offerta(self):
        shells = _msg_del_server(lambda c: c in ("bash",))
        assert _node(f"pickShell({json.dumps(shells)}, 'bash')") == "bash"
        assert _node(f"pickShell({json.dumps(shells)}, 'pwsh.exe')") == "cmd.exe"
        assert _node(f"pickShell({json.dumps(shells)}, '')") == "cmd.exe"
        assert _node(f"pickShell({json.dumps(shells)}, null)") == "cmd.exe"


class TestAllineamentoSenzaNode:
    def test_il_client_non_ha_un_elenco_di_shell_proprio(self):
        js = APP_JS.read_text(encoding="utf-8")
        for cmd in TERM_ALLOWED_CMDS - {"cmd.exe"}:
            assert f"'{cmd}'" not in js and f'"{cmd}"' not in js, (
                f"app.js nomina {cmd}: l'elenco arriva dal server")

    def test_il_client_legge_il_campo_shells_di_term_sessions(self):
        js = APP_JS.read_text(encoding="utf-8")
        assert "msg.shells" in js
        assert "term_sessions" in js

    def test_il_server_lo_manda(self):
        sorgente = (ROOT / "liquidmouse" / "net" / "protocol.py").read_text(encoding="utf-8")
        assert '"shells"' in sorgente

    def test_nessun_cmd_fisso_nell_invio(self):
        # Prima: ws.send(... cmd: 'cmd.exe') cablato nel pulsante.
        js = APP_JS.read_text(encoding="utf-8")
        assert not re.search(r"type:\s*'term_create',\s*cmd:\s*'", js)

    def test_ogni_shell_ha_una_etichetta_per_il_selettore(self):
        assert all(label for _, label in SHELLS)
