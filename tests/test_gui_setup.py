"""setup_gui spezzato in funzioni e animazione d'avvio più corta.

Tk e i widget sono stub: qui si controlla che le sezioni si compongano senza
nomi persi nello spezzamento e che l'intro finisca presto lasciando lo stato
finale di sempre (testi interi, finestra opaca). L'aspetto reale a schermo
NON è verificato da questi test (serve Windows con Tk e DWM).
"""

import heapq

import pytest

from tests.test_server_module import _Qualunque, gui_window, stub_gui  # noqa: F401


class _FinteTcl:
    def call(self, *a):
        if a[:2] == ("font", "families"):
            return ()
        if a[:2] == ("font", "measure"):
            return len(a[3]) * 9      # larghezza fittizia, proporzionale al testo
        return None


class _FintaRoot:
    """Orologio simulato: `after` accoda, `esegui` consuma in ordine di tempo."""

    tk = _FinteTcl()

    def __init__(self):
        self.coda = []
        self.n = 0
        self.alpha = None
        self.fine_ms = 0

    def after(self, ms, fn=None, *args):
        self.n += 1
        heapq.heappush(self.coda, (self.fine_ms + ms, self.n, fn))

    def attributes(self, nome, valore=None):
        if nome == "-alpha":
            self.alpha = valore

    def esegui(self):
        while self.coda:
            quando, _, fn = heapq.heappop(self.coda)
            self.fine_ms = quando
            fn()

    def wm_frame(self):
        return "0x10"      # handle esadecimale, come lo restituisce Tk su Windows

    def winfo_fpixels(self, _):
        return 96.0

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def __getattr__(self, nome):
        return _Qualunque()


class _Testo:
    def __init__(self):
        self.valori = []

    def set(self, v):
        self.valori.append(v)


@pytest.fixture
def finestra(gui_window, monkeypatch):
    root = _FintaRoot()
    monkeypatch.setattr(gui_window, "root", root)
    monkeypatch.setattr(gui_window, "apply_dwm_style", lambda hwnd: None)
    monkeypatch.setattr(gui_window, "_deps", gui_window.GuiDeps(
        config={"pin_plain": "ab12cd34"}, sessions=_Qualunque(),
        services=lambda: None, local_ip="192.168.1.10", reset_trusted=lambda: None))
    return gui_window, root


class TestSetupGui:
    def test_compone_tutte_le_sezioni(self, finestra):
        w, root = finestra
        w.setup_gui()
        # Lo stato globale che il resto del modulo (sink di log, aggiornamenti
        # di IP e di accesso remoto) si aspetta di trovare.
        for nome in ("ip_label_var", "status_var", "status_label", "_main_canvas",
                     "_status_dot", "_lan_hint_var", "_remote_status_var",
                     "_remote_status_label", "_remote_title_var"):
            assert getattr(w, nome) is not None, nome
        assert w._remote_qr_box is not None
        assert w._lan_ip_max_w > 0

    def test_il_layout_resta_dentro_la_finestra(self, finestra):
        w, _ = finestra
        w._scale = 1.0
        lay = w._make_layout()
        assert (lay.w, lay.h) == (560, 460)
        assert lay.sy1 < lay.sy2 <= lay.h
        assert lay.ry2 < lay.sy1
        assert lay.pin_l < lay.right

    def test_a_dpi_alti_le_misure_crescono_insieme(self, finestra):
        w, _ = finestra
        w._scale = 2.0
        lay = w._make_layout()
        assert (lay.w, lay.h) == (1120, 920)


class TestAnimazioneDavvio:
    def test_finisce_presto_con_lo_stato_finale_di_sempre(self, finestra):
        w, root = finestra
        w.setup_gui()
        root.esegui()
        # Prima: oltre due secondi. Il limite lascia margine ai timer di Tk,
        # che su Windows non scattano sotto ~16 ms.
        assert root.fine_ms <= 1200, root.fine_ms
        assert root.alpha == 1.0

    def test_i_testi_finali_sono_interi_e_il_cursore_non_resta(self, finestra):
        w, root = finestra
        testi = [(_Testo(), "001"), (_Testo(), "liquid mouse"),
                 (_Testo(), "192.168.1.10:8000"), (_Testo(), "Inizializzazione...")]
        w._start_intro(testi)
        root.esegui()
        for widget, finale in testi:
            assert widget.valori[-1] == finale
            assert "█" not in finale
            # Il cursore compare durante la scrittura, mai nell'ultimo valore.
            assert all(v.endswith("█") for v in widget.valori[:-1])

    def test_un_testo_lungo_si_scrive_in_pochi_passi(self, finestra):
        w, root = finestra
        t = _Testo()
        w._start_intro([(t, "x" * 40)])
        root.esegui()
        assert len(t.valori) <= w.TYPE_MAX_TICKS + 1

    def test_il_fade_arriva_a_opaco_in_modo_monotono(self, finestra):
        w, root = finestra
        visti = []
        root.attributes = lambda nome, valore=None: visti.append(valore)
        w._fade_in()
        root.esegui()
        assert visti == sorted(visti) and visti[0] == 0.0 and visti[-1] == 1.0
