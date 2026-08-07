"""Carica davvero l'entrypoint e il modulo GUI.

Sono gli unici due punti che l'analisi statica non copre bene: intercettano un
simbolo rimasto indietro dopo un'estrazione e un side-effect reintrodotto a
import time. Girano senza Windows e senza schermo perché tkinter, pystray, PIL,
qrcode e ctypes.windll sono sostituiti da stub.

Se questi test iniziano a fallire con un ImportError su una libreria GUI in un
modulo che non sta sotto `liquidmouse/gui/`, il core ha ripreso a dipendere
dalla GUI.
"""

import ctypes
import importlib
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


@pytest.fixture
def stub_gui(monkeypatch):
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
    # Il modulo GUI potrebbe essere già in sys.modules da un test precedente,
    # importato con stub diversi: va ricaricato con questi.
    monkeypatch.delitem(sys.modules, "liquidmouse.gui.window", raising=False)


@pytest.fixture
def gui_window(stub_gui):
    pytest.importorskip("websockets")
    return importlib.import_module("liquidmouse.gui.window")


@pytest.fixture
def server_module(stub_gui, monkeypatch):
    pytest.importorskip("websockets")
    monkeypatch.syspath_prepend(str(ROOT))
    mod = types.ModuleType("server_pyw")
    mod.__file__ = str(ROOT / "server.pyw")
    codice = (ROOT / "server.pyw").read_text(encoding="utf-8")
    exec(compile(codice, "server.pyw", "exec"), mod.__dict__)
    return mod


class TestEntrypoint:
    def test_si_carica(self, server_module):
        assert server_module is not None

    @pytest.mark.parametrize("nome", [
        "main", "init_process", "load_config", "reset_trusted_ip",
        "_on_session_created", "_build_services", "_build_gui_deps",
        "start_background_services",
    ])
    def test_i_simboli_attesi_esistono(self, server_module, nome):
        assert hasattr(server_module, nome), f"{nome} non definito"

    def test_non_costruisce_niente_a_import_time(self, server_module):
        # Servizi e finestra nascono in main(): importare l'entrypoint non deve
        # aprire socket né finestre.
        assert server_module._services is None
        assert server_module._root is None

    def test_le_dipendenze_gui_sono_complete(self, server_module):
        deps = server_module._build_gui_deps()
        assert deps.config is server_module._config
        assert deps.sessions is server_module._session_manager
        assert deps.services() is None      # NetworkServices non ancora creato
        assert callable(deps.reset_trusted)


class TestModuloGui:
    @pytest.mark.parametrize("nome", [
        "build", "setup_gui", "gui_log_sink", "update_remote_ui",
        "run_tray_service", "create_tray_icon", "_open_sessions_panel",
        "_remote_endpoint", "_get_remote_tray_label", "_set_remote_qr",
        "minimize_to_tray", "restore_window", "terminate_application",
    ])
    def test_i_simboli_attesi_esistono(self, gui_window, nome):
        assert hasattr(gui_window, nome), f"{nome} non definito"

    def test_importarlo_non_apre_una_finestra(self, gui_window):
        # root nasce in build(). Prima tk.Tk() stava a livello di modulo e
        # bastava importare per far comparire una finestra.
        assert gui_window.root is None

    def test_il_log_prima_della_finestra_non_solleva(self, gui_window):
        # gui_log_sink è registrato in main() prima di build(): i messaggi
        # emessi nel frattempo non devono far cadere l'avvio.
        gui_window.gui_log_sink("prova", color="#ffffff")

    def test_update_remote_ui_prima_della_finestra_non_solleva(self, gui_window):
        gui_window.update_remote_ui()


class TestIsolamentoDelCore:
    """Il core non deve dipendere dalla GUI: è la regola che tiene i test
    eseguibili in CI su Linux, senza schermo."""

    @pytest.mark.parametrize("modulo", [
        "liquidmouse.config", "liquidmouse.events", "liquidmouse.net.server",
        "liquidmouse.net.protocol", "liquidmouse.net.frames",
        "liquidmouse.net.static", "liquidmouse.net.upnp",
        "liquidmouse.net.addresses", "liquidmouse.security.auth",
        "liquidmouse.security.tls", "liquidmouse.terminal.sessions",
        "liquidmouse.terminal.conpty", "liquidmouse.input.win32",
    ])
    def test_nessun_import_di_librerie_gui(self, modulo):
        m = importlib.import_module(modulo)
        sorgente = Path(m.__file__).read_text(encoding="utf-8")
        for vietato in ("import tkinter", "import pystray", "import qrcode",
                        "from PIL"):
            assert vietato not in sorgente, f"{modulo} importa {vietato}"
