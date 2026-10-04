"""La finestra rifà indirizzo e QR LAN quando il core segnala un nuovo IP.

Stesse tecniche di test_server_module: tkinter/PIL/qrcode sono stub e i widget
sono registratori, quindi gira senza schermo.
"""

import pytest

from tests.test_server_module import _Qualunque, gui_window, stub_gui  # noqa: F401


class _Testo:
    def __init__(self):
        self.testo = None
        self.font = None

    def set(self, t):
        self.testo = t

    def set_font(self, f):
        self.font = f


class _Canvas:
    def __init__(self):
        self.config = []

    def itemconfig(self, item, **kw):
        self.config.append((item, kw))


class _Root:
    def __init__(self):
        self.differite = 0

    def after(self, _ms, fn):
        self.differite += 1
        fn()


@pytest.fixture
def finestra(gui_window, monkeypatch):
    w = gui_window
    testo, canvas, root = _Testo(), _Canvas(), _Root()
    monkeypatch.setattr(w, "root", root)
    monkeypatch.setattr(w, "ip_label_var", testo)
    monkeypatch.setattr(w, "_main_canvas", canvas)
    monkeypatch.setattr(w, "_lan_qr_item", 7)
    monkeypatch.setattr(w, "_lan_qr_box", (10, 20, 100))
    monkeypatch.setattr(w, "_lan_ip_max_w", 300)
    monkeypatch.setattr(w, "_deps", w.GuiDeps(
        config={}, sessions=_Qualunque(), services=lambda: None,
        local_ip="192.168.1.10", reset_trusted=lambda: None))
    qr_urls = []
    monkeypatch.setattr(w, "_qr_image", lambda url, lato, fill, back: qr_urls.append(url) or url)
    monkeypatch.setattr(w, "_fit_num", lambda text, max_w, max_px, min_px=12: ("font", len(text)))
    monkeypatch.setattr(w.ImageTk, "PhotoImage", lambda img: ("foto", img), raising=False)
    return w, testo, canvas, root, qr_urls


class TestAggiornamentoLan:
    def test_indirizzo_e_qr_seguono_il_nuovo_ip(self, finestra):
        w, testo, canvas, _, qr_urls = finestra
        w.update_lan_ui("10.0.0.7")
        assert testo.testo == f"10.0.0.7:{w.HTTP_PORT}"
        assert testo.font is not None
        assert qr_urls and qr_urls[0].startswith(f"http://10.0.0.7:{w.HTTP_PORT}/")
        assert canvas.config and canvas.config[-1][0] == 7
        assert w._deps.local_ip == "10.0.0.7"

    def test_il_disegno_passa_dal_thread_tk(self, finestra):
        w, _, _, root, _ = finestra
        w.update_lan_ui("10.0.0.7")
        assert root.differite == 1

    def test_prima_della_finestra_non_solleva_e_ricorda_l_ip(self, gui_window, monkeypatch):
        w = gui_window
        monkeypatch.setattr(w, "_deps", w.GuiDeps(
            config={}, sessions=_Qualunque(), services=lambda: None,
            local_ip="192.168.1.10", reset_trusted=lambda: None))
        w.update_lan_ui("10.0.0.7")
        # setup_gui disegnerà l'indirizzo giusto, non quello dell'avvio.
        assert w._deps.local_ip == "10.0.0.7"

    def test_un_errore_di_disegno_non_solleva(self, finestra, monkeypatch):
        w, testo, *_ = finestra

        def rotto(*a, **k):
            raise RuntimeError("tk")

        monkeypatch.setattr(w, "_qr_image", rotto)
        w.update_lan_ui("10.0.0.7")
        assert testo.testo is not None
