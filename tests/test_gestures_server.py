"""Lato server dei gesti del touchpad: click centrale, scroll orizzontale e
whitelist dei pulsanti. Win32 è sostituito da un finto `user32`."""

import asyncio
import ctypes
import json

import pytest

from liquidmouse.input import win32
from liquidmouse.net import protocol
from liquidmouse.net.protocol import SCROLL_CLAMP, ClientConnection, dispatch


class _Ws:
    async def send(self, payload):
        pass


class _Sessioni:
    def detach_ws(self, ws):
        pass


@pytest.fixture
def ctx():
    return ClientConnection(_Ws(), "192.168.1.30", _Sessioni())


def send(ctx, **payload):
    asyncio.run(dispatch(ctx, json.dumps(payload)))


class _User32:
    def __init__(self):
        self.chiamate = []

    def SendInput(self, n, arr, size):
        # Copia i campi subito: i buffer di move/scroll sono riusati.
        self.chiamate.append([(arr[i].value.mi.dwFlags, arr[i].value.mi.mouseData)
                              for i in range(n)])
        return n


@pytest.fixture
def user32(monkeypatch):
    finto = _User32()
    monkeypatch.setattr(win32, "_user32", finto)
    return finto


class TestWin32:
    def test_click_sinistro(self, user32):
        win32.mouse_click("left")
        assert [f for f, _ in user32.chiamate[0]] == [win32.MOUSEEVENTF_LEFTDOWN,
                                                        win32.MOUSEEVENTF_LEFTUP]

    def test_click_destro(self, user32):
        win32.mouse_click("right")
        assert [f for f, _ in user32.chiamate[0]] == [win32.MOUSEEVENTF_RIGHTDOWN,
                                                        win32.MOUSEEVENTF_RIGHTUP]

    def test_click_centrale(self, user32):
        win32.mouse_click("middle")
        assert [f for f, _ in user32.chiamate[0]] == [win32.MOUSEEVENTF_MIDDLEDOWN,
                                                        win32.MOUSEEVENTF_MIDDLEUP]
        assert win32.MOUSEEVENTF_MIDDLEDOWN == 0x0020 and win32.MOUSEEVENTF_MIDDLEUP == 0x0040

    def test_pulsante_sconosciuto_non_diventa_un_click_destro(self, user32):
        # Prima ogni valore diverso da 'left' faceva un click destro.
        win32.mouse_click("banana")
        assert user32.chiamate == []

    def test_scroll_orizzontale(self, user32):
        win32.mouse_hscroll(3)
        (flag, dati), = user32.chiamate[0]
        assert flag == win32.MOUSEEVENTF_HWHEEL == 0x1000
        assert dati == 3 * win32.WHEEL_DELTA

    def test_scroll_orizzontale_negativo_e_a_sinistra(self, user32):
        win32.mouse_hscroll(-2)
        (_, dati), = user32.chiamate[0]
        # mouseData è un c_ulong (32 bit su Windows, 64 su Linux): lo stesso valore
        # che il codice produce per lo scroll verticale, in complemento a due.
        assert dati == ctypes.c_ulong(-2 * win32.WHEEL_DELTA).value

    def test_scroll_verticale_invariato(self, user32):
        win32.mouse_scroll(2)
        (flag, dati), = user32.chiamate[0]
        assert flag == win32.MOUSEEVENTF_WHEEL and dati == 2 * win32.WHEEL_DELTA

    def test_fuori_da_windows_non_fa_nulla(self, monkeypatch):
        monkeypatch.setattr(win32, "_user32", None)
        win32.mouse_click("middle")
        win32.mouse_hscroll(1)

    def test_esportate(self):
        assert "mouse_hscroll" in win32.__all__


class TestProtocolloClick:
    @pytest.mark.parametrize("btn", ["left", "right", "middle"])
    def test_pulsanti_ammessi(self, ctx, monkeypatch, btn):
        visti = []
        monkeypatch.setattr(protocol, "mouse_click", visti.append)
        send(ctx, type="click", btn=btn)
        assert visti == [btn]

    def test_senza_pulsante_e_sinistro(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "mouse_click", visti.append)
        send(ctx, type="click")
        assert visti == ["left"]

    @pytest.mark.parametrize("btn", ["banana", "", None, 3, ["left"], {"x": 1}, "LEFT", "x1"])
    def test_pulsanti_non_ammessi_sono_ignorati(self, ctx, monkeypatch, btn):
        visti = []
        monkeypatch.setattr(protocol, "mouse_click", visti.append)
        send(ctx, type="click", btn=btn)
        assert visti == []


class TestProtocolloScroll:
    def _spia(self, monkeypatch):
        v, h = [], []
        monkeypatch.setattr(protocol, "mouse_scroll", v.append)
        monkeypatch.setattr(protocol, "mouse_hscroll", h.append)
        return v, h

    def test_solo_verticale_come_prima(self, ctx, monkeypatch):
        v, h = self._spia(monkeypatch)
        send(ctx, type="scroll", amount=5)
        assert (v, h) == ([5], [])

    def test_solo_orizzontale(self, ctx, monkeypatch):
        v, h = self._spia(monkeypatch)
        send(ctx, type="scroll", h=-4)
        assert (v, h) == ([], [-4])

    def test_entrambi(self, ctx, monkeypatch):
        v, h = self._spia(monkeypatch)
        send(ctx, type="scroll", amount=2, h=3)
        assert (v, h) == ([2], [3])

    def test_l_orizzontale_e_limitato(self, ctx, monkeypatch):
        v, h = self._spia(monkeypatch)
        send(ctx, type="scroll", h=10 ** 9)
        send(ctx, type="scroll", h=-10 ** 9)
        assert h == [SCROLL_CLAMP, -SCROLL_CLAMP]

    @pytest.mark.parametrize("valore", [None, "abc", {}, [], 0, "0"])
    def test_valori_non_validi_o_zero_sono_ignorati(self, ctx, monkeypatch, valore):
        v, h = self._spia(monkeypatch)
        send(ctx, type="scroll", amount=valore, h=valore)
        assert (v, h) == ([], [])


class TestDragInvariato:
    def test_down_e_up(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "mouse_button", visti.append)
        send(ctx, type="drag", state="down")
        send(ctx, type="drag", state="up")
        assert visti == ["down", "up"]

    def test_la_disconnessione_rilascia_il_pulsante(self, ctx, monkeypatch):
        # Il tap-e-trascina tiene premuto il sinistro: un client che sparisce
        # a metà non deve lasciarlo giù sul PC.
        visti = []
        monkeypatch.setattr(protocol, "mouse_button", visti.append)
        monkeypatch.setattr(protocol, "key_up", lambda k: None)
        ctx.release_all()
        assert visti == ["up"]
