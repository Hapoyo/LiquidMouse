"""PIN, QR remoto e IP esterno mascherati di default nella finestra, pulsante
"mostra per 30 s" e voce del tray "rigenera pin".

Tk, pystray, PIL e qrcode sono stub (vedi test_server_module): qui si controlla
la logica, non l'aspetto a schermo, che NON è verificato (serve Windows con Tk).
"""

import pytest

from tests.test_server_module import _Qualunque, gui_window, stub_gui  # noqa: F401

PIN = "Vq7x-M2kTfA"


class _Testo:
    def __init__(self):
        self.testo = None
        self.font = None
        self.fg = None

    def set(self, t):
        self.testo = t

    def set_font(self, f):
        self.font = f

    def config(self, text=None, fg=None):
        if text is not None:
            self.testo = text
        if fg is not None:
            self.fg = fg


class _Canvas:
    def __init__(self):
        self.config = []

    def itemconfig(self, item, **kw):
        self.config.append((item, kw))

    def create_image(self, *a, **k):
        return 99

    def tag_bind(self, *a, **k):
        pass


class _Root:
    """`after(0)` esegue subito; i timer lunghi aspettano `scatta()`."""

    def __init__(self):
        self.timer = {}
        self.n = 0
        self.annullati = []

    def after(self, ms, fn):
        if ms == 0:
            fn()
            return None
        self.n += 1
        self.timer[self.n] = fn
        return self.n

    def after_cancel(self, id_):
        self.annullati.append(id_)
        self.timer.pop(id_, None)

    def scatta(self):
        for id_ in list(self.timer):
            self.timer.pop(id_)()


class _Servizi:
    remote_mode = "upnp"
    external_ip = "203.0.113.5"
    external_port = 8443
    remote_problem = None


@pytest.fixture
def f(gui_window, monkeypatch):
    w = gui_window
    pin, stato, remoto, hint, ip = _Testo(), _Testo(), _Testo(), _Testo(), _Testo()
    btn = _Testo()
    root, canvas = _Root(), _Canvas()
    qr = []
    for nome, val in (("root", root), ("_main_canvas", canvas), ("_pin_var", pin),
                      ("_pin_btn_text", btn), ("_pin_max_w", 100),
                      ("_remote_status_var", remoto), ("_remote_status_label", remoto),
                      ("_remote_qr_hint", hint), ("_remote_qr_box", (0, 0, 80)),
                      ("ip_label_var", ip), ("_lan_hint_var", _Testo()),
                      ("_lan_qr_item", 7), ("_lan_qr_box", (0, 0, 100)),
                      ("_lan_ip_max_w", 300)):
        monkeypatch.setattr(w, nome, val)
    cfg = {"pin_plain": PIN}
    rigenerazioni = []
    monkeypatch.setattr(w, "_deps", w.GuiDeps(
        config=cfg, sessions=_Qualunque(), services=lambda: _Servizi(),
        local_ip="192.168.1.10", reset_trusted=lambda: None,
        regenerate_pin=lambda: (rigenerazioni.append(1),
                                cfg.update(pin_plain="NUOVO-pin-123"))))
    monkeypatch.setattr(w, "_qr_image", lambda url, lato, fill, back: qr.append(url) or url)
    monkeypatch.setattr(w, "_fit_num", lambda *a, **k: ("font", 1))
    monkeypatch.setattr(w.ImageTk, "PhotoImage", lambda img: ("foto", img), raising=False)
    w.update_remote_ui()
    return w, dict(pin=pin, btn=btn, remoto=remoto, hint=hint, root=root,
                   canvas=canvas, qr=qr, cfg=cfg, rig=rigenerazioni)


def _remoti(urls):
    """Gli URL dei QR remoti (https): il QR LAN passa dalla stessa funzione."""
    return [u for u in urls if u.startswith("https://")]


class TestMaschera:
    @pytest.mark.parametrize("testo,atteso", [
        ("UPnP attivo: 203.0.113.5:8443", "UPnP attivo: •••.•••.•••.•••:8443"),
        ("cgnat dell'operatore (100.107.62.102)", "cgnat dell'operatore (•••.•••.•••.•••)"),
        ("Sessione attiva: 192.168.1.34", "Sessione attiva: 192.168.1.34"),
        ("Sessione locale: 127.0.0.1", "Sessione locale: 127.0.0.1"),
        ("Tunnel attivo: https://quiet-harbor.trycloudflare.com",
         "Tunnel attivo: https://•••.trycloudflare.com"),
        ("nessun indirizzo qui", "nessun indirizzo qui"),
    ])
    def test_mask_sensitive(self, gui_window, testo, atteso):
        assert gui_window.mask_sensitive(testo) == atteso


class TestPredefinitoMascherato:
    def test_nascosti_all_avvio(self, f):
        w, c = f
        assert w.secrets_visible() is False

    def test_il_pannello_remoto_non_mostra_l_ip(self, f):
        w, c = f
        assert "203.0.113.5" not in c["remoto"].testo
        assert ":8443" in c["remoto"].testo
        assert c["hint"].testo == w.HINT_NASCOSTO
        assert _remoti(c["qr"]) == []   # nessun QR remoto generato

    def test_etichetta_del_tray_mascherata(self, f):
        w, _ = f
        assert "203.0.113.5" not in w._get_remote_tray_label()

    def test_il_pin_di_disegno_e_mascherato(self, f):
        w, _ = f
        assert w._masked_pin(PIN) == w.MASK_CHAR * len(PIN)

    def test_il_motivo_di_errore_con_ip_cgnat_e_mascherato(self, f, monkeypatch):
        w, c = f

        class Cgnat:
            remote_mode = "none"
            remote_problem = "cgnat dell'operatore (100.107.62.102)"

        monkeypatch.setattr(w, "_deps", w.GuiDeps(
            config={"pin_plain": PIN}, sessions=_Qualunque(), services=lambda: Cgnat(),
            local_ip="192.168.1.10", reset_trusted=lambda: None))
        w.update_remote_ui()
        assert "100.107.62.102" not in c["remoto"].testo
        assert "cgnat" in c["remoto"].testo

    def test_il_log_sulla_riga_di_stato_e_mascherato(self, f):
        w, c = f
        stato = _Testo()
        w.status_var, w.status_label = stato, _Testo()
        w.gui_log_sink("UPnP attivo: 203.0.113.5:8443")
        assert "203.0.113.5" not in stato.testo
        w.gui_log_sink("Sessione attiva: 192.168.1.34")
        assert stato.testo == "Sessione attiva: 192.168.1.34"

    def test_il_qr_lan_non_porta_il_pin(self, f, monkeypatch):
        w, _ = f
        monkeypatch.setitem(w._deps.config, "lan_require_pin", True)
        assert "pin=" not in w._lan_qr_url("192.168.1.10")


class TestMostra:
    def test_mostra_rivela_pin_qr_e_ip(self, f):
        w, c = f
        w.toggle_reveal()
        assert w.secrets_visible() is True
        assert c["pin"].testo == PIN
        assert "203.0.113.5:8443" in c["remoto"].testo
        assert _remoti(c["qr"])[-1] == f"https://203.0.113.5:8443/#pin={PIN}"
        assert c["btn"].testo == "nascondi"

    def test_dopo_30_secondi_si_rimaschera(self, f):
        w, c = f
        w.toggle_reveal()
        assert w.SHOW_SECS == 30
        assert len(c["root"].timer) == 1
        c["root"].scatta()
        assert w.secrets_visible() is False
        assert c["pin"].testo == w.MASK_CHAR * len(PIN)
        assert "203.0.113.5" not in c["remoto"].testo
        assert c["hint"].testo == w.HINT_NASCOSTO
        assert c["btn"].testo == "mostra per 30 s"
        # QR remoto nascosto sul canvas
        assert any(kw.get("state") == "hidden" for _, kw in c["canvas"].config)

    def test_un_secondo_clic_nasconde_subito_e_annulla_il_timer(self, f):
        w, c = f
        w.toggle_reveal()
        w.toggle_reveal()
        assert w.secrets_visible() is False
        assert c["root"].timer == {}
        assert c["pin"].testo == w.MASK_CHAR * len(PIN)

    def test_la_scadenza_e_monotona_30_s(self, f, monkeypatch):
        w, _ = f
        t = [1000.0]
        monkeypatch.setattr(w.time, "monotonic", lambda: t[0])
        w.toggle_reveal()
        t[0] += 29.9
        assert w.secrets_visible() is True
        t[0] += 0.2
        assert w.secrets_visible() is False

    def test_il_qr_lan_porta_il_pin_solo_mentre_e_mostrato(self, f, monkeypatch):
        w, c = f
        monkeypatch.setitem(w._deps.config, "lan_require_pin", True)
        w.toggle_reveal()
        assert f"#pin={PIN}" in w._lan_qr_url("192.168.1.10")
        c["root"].scatta()
        assert "pin=" not in w._lan_qr_url("192.168.1.10")


class TestRigeneraPin:
    def test_chiama_il_core_e_ridisegna_con_il_nuovo_pin(self, f):
        w, c = f
        w.toggle_reveal()
        w.regenerate_pin()
        assert c["rig"] == [1]
        assert c["pin"].testo == "NUOVO-pin-123"
        # Il QR remoto porta il PIN nuovo: il vecchio non vale più.
        assert _remoti(c["qr"])[-1] == "https://203.0.113.5:8443/#pin=NUOVO-pin-123"

    def test_senza_callback_non_fa_nulla(self, f, monkeypatch):
        w, c = f
        monkeypatch.setattr(w._deps, "regenerate_pin", None)
        w.regenerate_pin()
        assert c["rig"] == []

    def test_un_errore_del_core_non_solleva(self, f, monkeypatch):
        w, c = f

        def rotto():
            raise OSError("dpapi")
        monkeypatch.setattr(w._deps, "regenerate_pin", rotto)
        w.regenerate_pin()
        assert c["pin"].testo is None      # nessun ridisegno dopo l'errore

    def test_la_voce_del_tray_esiste(self, gui_window):
        from pathlib import Path
        sorgente = Path(gui_window.__file__).read_text(encoding="utf-8")
        assert "'Rigenera PIN', regenerate_pin" in sorgente
        assert "regenerate_pin" in sorgente
