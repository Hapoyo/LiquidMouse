"""Interruttore `lan_require_pin` nel menu del tray e nella finestra, più
l'allineamento client/server dell'handshake `auth_required`.
"""

import re
from pathlib import Path

import pytest

from tests.test_gui_lan_update import _Canvas, _Root, _Testo  # noqa: F401
from tests.test_server_module import _Qualunque, gui_window, stub_gui  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


class _Cfg(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.salvataggi = 0

    def save(self):
        self.salvataggi += 1


@pytest.fixture
def finestra(gui_window, monkeypatch):
    w = gui_window
    cfg = _Cfg(pin_plain="abcd1234")
    suggerimento, ip, canvas, root = _Testo(), _Testo(), _Canvas(), _Root()
    monkeypatch.setattr(w, "root", root)
    monkeypatch.setattr(w, "ip_label_var", ip)
    monkeypatch.setattr(w, "_lan_hint_var", suggerimento)
    monkeypatch.setattr(w, "_main_canvas", canvas)
    monkeypatch.setattr(w, "_lan_qr_item", 7)
    monkeypatch.setattr(w, "_lan_qr_box", (0, 0, 100))
    monkeypatch.setattr(w, "_lan_ip_max_w", 300)
    monkeypatch.setattr(w, "_deps", w.GuiDeps(
        config=cfg, sessions=_Qualunque(), services=lambda: None,
        local_ip="192.168.1.10", reset_trusted=lambda: None))
    qr = []
    monkeypatch.setattr(w, "_qr_image", lambda url, lato, fill, back: qr.append(url) or url)
    monkeypatch.setattr(w, "_fit_num", lambda *a, **k: ("font", 1))
    monkeypatch.setattr(w.ImageTk, "PhotoImage", lambda img: img, raising=False)
    return w, cfg, suggerimento, qr


class TestInterruttore:
    def test_di_default_e_spento(self, finestra):
        w, cfg, _, _ = finestra
        assert w.lan_require_pin() is False
        assert "lan_require_pin" not in cfg

    def test_il_toggle_accende_salva_e_ridisegna(self, finestra):
        w, cfg, suggerimento, qr = finestra
        w.toggle_lan_require_pin()
        assert cfg["lan_require_pin"] is True and cfg.salvataggi == 1
        assert w.lan_require_pin() is True
        assert suggerimento.testo == w.LAN_HINT_PIN
        # Il QR LAN porta il PIN, come quello remoto.
        assert qr and "&pin=abcd1234" in qr[-1]

    def test_il_toggle_spegne_e_toglie_il_pin_dal_qr(self, finestra):
        w, cfg, suggerimento, qr = finestra
        w.toggle_lan_require_pin()
        w.toggle_lan_require_pin()
        assert cfg["lan_require_pin"] is False and cfg.salvataggi == 2
        assert suggerimento.testo == w.LAN_HINT
        assert "pin=" not in qr[-1]

    def test_senza_opzione_il_qr_lan_non_ha_il_pin(self, finestra):
        w, *_ = finestra
        assert "pin=" not in w._lan_qr_url("192.168.1.10")

    def test_la_voce_del_tray_esiste_con_lo_stato_spuntato(self, gui_window):
        sorgente = Path(gui_window.__file__).read_text(encoding="utf-8")
        assert "PIN anche dalla LAN" in sorgente
        assert "checked=lambda item: lan_require_pin()" in sorgente


class TestHandshakeClientServer:
    def test_il_client_risponde_ad_auth_required(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        assert "msg.type === 'auth_required'" in js
        blocco = js[js.index("msg.type === 'auth_required'"):]
        blocco = blocco[:blocco.index("msg.type === 'auth_ok'")]
        assert "type: 'auth'" in blocco and "ws.send" in blocco

    def test_il_server_manda_lo_stesso_tipo(self):
        py = (ROOT / "liquidmouse" / "net" / "server.py").read_text(encoding="utf-8")
        assert re.search(r'"type":\s*"auth_required"', py)

    def test_il_default_non_cambia_il_client_non_aspetta_auth_required(self):
        # In onopen il ramo LAN resta quello di sempre: connesso subito.
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        onopen = js[js.index("ws.onopen = () => {"):js.index("function _onAuthenticated")]
        assert "_onAuthenticated(ip);" in onopen
