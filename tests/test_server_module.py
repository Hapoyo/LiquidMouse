"""Carica davvero server.pyw.

È l'unico test che tocca l'entrypoint. Serve a intercettare gli errori che
l'analisi statica non vede — un simbolo rimasto indietro dopo un'estrazione, un
side-effect reintrodotto a import time — senza richiedere Windows né uno schermo:
tkinter, pystray, PIL, qrcode e ctypes.windll sono sostituiti da stub.

Se questo test inizia a fallire con un ImportError su una libreria GUI, quasi
certamente il core ha ripreso a dipendere dalla GUI.
"""

import ctypes
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _Qualunque:
    """Stub permissivo: accetta qualsiasi chiamata e attributo."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, nome):
        return _Qualunque()

    def __call__(self, *a, **k):
        return _Qualunque()


def _installa_stub(monkeypatch):
    def modulo(nome, **attrs):
        m = types.ModuleType(nome)
        for k, v in attrs.items():
            setattr(m, k, v)
        monkeypatch.setitem(sys.modules, nome, m)
        return m

    tk = modulo(
        "tkinter", Tk=_Qualunque, Canvas=_Qualunque, Label=_Qualunque,
        Frame=_Qualunque, Entry=_Qualunque, Button=_Qualunque,
        StringVar=_Qualunque, Toplevel=_Qualunque, Text=_Qualunque,
        Scale=_Qualunque, PhotoImage=_Qualunque,
        HORIZONTAL="h", END="end", BOTH="both", LEFT="left",
    )
    tk.messagebox = modulo("tkinter.messagebox", showerror=lambda *a, **k: None)
    modulo("pystray", Icon=_Qualunque, Menu=_Qualunque, MenuItem=_Qualunque)
    modulo("PIL", Image=_Qualunque(), ImageDraw=_Qualunque(), ImageTk=_Qualunque())
    modulo("qrcode", QRCode=_Qualunque, make=lambda *a, **k: _Qualunque())
    if not hasattr(ctypes, "windll"):
        monkeypatch.setattr(ctypes, "windll", _Qualunque(), raising=False)


@pytest.fixture
def server_module(monkeypatch):
    pytest.importorskip("websockets")
    _installa_stub(monkeypatch)
    monkeypatch.syspath_prepend(str(ROOT))
    mod = types.ModuleType("server_pyw")
    mod.__file__ = str(ROOT / "server.pyw")
    codice = (ROOT / "server.pyw").read_text(encoding="utf-8")
    exec(compile(codice, "server.pyw", "exec"), mod.__dict__)
    return mod


class TestCaricamento:
    def test_il_modulo_si_carica(self, server_module):
        assert server_module is not None

    @pytest.mark.parametrize("nome", [
        "main", "setup_gui", "_gui_log_sink", "start_background_services",
        "init_process", "reset_trusted_ip", "load_config", "_build_services",
        "create_tray_icon", "run_tray_service", "_on_session_created",
        "_remote_endpoint", "_get_remote_tray_label", "_update_remote_ui",
        "_set_remote_qr", "_open_sessions_panel",
    ])
    def test_i_simboli_attesi_esistono(self, server_module, nome):
        assert hasattr(server_module, nome), f"{nome} non definito"

    def test_il_log_non_solleva_prima_che_la_gui_esista(self, server_module):
        # _gui_log_sink viene registrato in main() prima di setup_gui(): i
        # messaggi emessi nel frattempo non devono far cadere l'avvio.
        server_module._gui_log_sink("prova", color="#ffffff")
