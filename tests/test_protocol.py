"""Dispatch dei messaggi: è la superficie esposta al client.

Tutto ciò che arriva qui è esterno e non fidato, quindi i test insistono sui
valori malformati quanto su quelli validi.
"""

import asyncio
import json

import pytest

from liquidmouse.net import protocol
from liquidmouse.net.protocol import (
    MOVE_CLAMP,
    PING_MIN_INTERVAL,
    SCROLL_CLAMP,
    TERM_INPUT_MAX,
    ClientConnection,
    clamp_int,
    dispatch,
    known_types,
)


class FakeWebSocket:
    def __init__(self):
        self.sent: list = []

    async def send(self, payload):
        self.sent.append(payload)

    def json_sent(self):
        return [json.loads(p) for p in self.sent if isinstance(p, str)]


class FakeSession:
    def __init__(self, sid="abc123"):
        self.id = sid


class FakeSessions:
    """Session manager finto: registra le chiamate ricevute."""

    def __init__(self):
        self.calls: list = []
        self.sessions_list: list = []
        self.create_error: Exception | None = None
        self.attach_error: Exception | None = None
        self.send_error: Exception | None = None

    def create(self, cmd):
        self.calls.append(("create", cmd))
        if self.create_error:
            raise self.create_error
        return FakeSession()

    async def attach(self, sid, ws):
        self.calls.append(("attach", sid))
        if self.attach_error:
            raise self.attach_error

    def detach(self, sid, ws):
        self.calls.append(("detach", sid))

    def detach_ws(self, ws):
        self.calls.append(("detach_ws",))

    def send(self, sid, data, ws=None):
        self.calls.append(("send", sid, data))
        if self.send_error:
            raise self.send_error

    def resize(self, sid, cols, rows, ws=None):
        self.calls.append(("resize", sid, cols, rows))

    def kill(self, sid, ws=None):
        self.calls.append(("kill", sid))

    def list_sessions(self):
        return self.sessions_list


@pytest.fixture
def ws():
    return FakeWebSocket()


@pytest.fixture
def sessions():
    return FakeSessions()


@pytest.fixture
def ctx(ws, sessions):
    return ClientConnection(ws, "192.168.1.10", sessions)


def run(coro):
    return asyncio.run(coro)


def send(ctx, **payload):
    run(dispatch(ctx, json.dumps(payload)))


class TestClampInt:
    def test_valori_dentro_il_range(self):
        assert clamp_int(5, 0, 10) == 5

    def test_limita_agli_estremi(self):
        assert clamp_int(999, 0, 10) == 10
        assert clamp_int(-999, 0, 10) == 0

    def test_accetta_float_e_stringhe(self):
        assert clamp_int(3.7, 0, 10) == 3
        assert clamp_int("4", 0, 10) == 4
        assert clamp_int("2.9", 0, 10) == 2

    def test_valori_non_interpretabili_usano_il_default(self):
        assert clamp_int(None, 0, 10, default=7) == 7
        assert clamp_int("abc", 0, 10, default=7) == 7
        assert clamp_int({}, 0, 10, default=7) == 7

    def test_negativi(self):
        assert clamp_int(-5, -200, 200) == -5


class TestDispatchRobustezza:
    def test_json_malformato_non_solleva(self, ctx):
        run(dispatch(ctx, "{ non json"))

    def test_json_non_oggetto_ignorato(self, ctx):
        run(dispatch(ctx, "[1,2,3]"))
        run(dispatch(ctx, '"stringa"'))

    def test_tipo_sconosciuto_ignorato(self, ctx, ws):
        send(ctx, type="inesistente")
        assert ws.sent == []

    def test_tipo_mancante_ignorato(self, ctx, ws):
        send(ctx, x=1)
        assert ws.sent == []

    def test_tutti_i_tipi_attesi_sono_registrati(self):
        attesi = {
            'move', 'scroll', 'click', 'drag', 'text', 'key', 'key_toggle',
            'hotkey', 'ping', 'term_list', 'term_create', 'term_attach',
            'term_detach', 'term_input', 'term_resize', 'term_kill',
        }
        assert attesi <= known_types()


class TestInput:
    def test_move_limita_i_valori(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "mouse_move", lambda x, y: visti.append((x, y)))
        send(ctx, type="move", x=10 ** 9, y=-10 ** 9)
        assert visti == [(MOVE_CLAMP, -MOVE_CLAMP)]

    def test_move_con_valori_assurdi_non_solleva(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "mouse_move", lambda x, y: visti.append((x, y)))
        send(ctx, type="move", x="abc", y=None)
        assert visti == [(0, 0)]

    def test_scroll_limita_e_ignora_lo_zero(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "mouse_scroll", lambda a: visti.append(a))
        send(ctx, type="scroll", amount=10 ** 6)
        send(ctx, type="scroll", amount=0)
        assert visti == [SCROLL_CLAMP]

    def test_text_vuoto_ignorato(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_text", lambda t: visti.append(t))
        send(ctx, type="text", char="")
        send(ctx, type="text", char="a")
        assert visti == ["a"]

    def test_hotkey_con_keys_non_lista_ignorata(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "hotkey", lambda *k: visti.append(k))
        send(ctx, type="hotkey", keys="ctrl")
        assert visti == []
        send(ctx, type="hotkey", keys=["ctrl", "c"])
        assert visti == [("ctrl", "c")]


class TestBackspaceDebounce:
    def test_ripetizioni_troppo_ravvicinate_sono_scartate(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        for _ in range(5):
            send(ctx, type="key", key="backspace")
        assert len(visti) == 1

    def test_gli_altri_tasti_non_sono_frenati(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        for _ in range(5):
            send(ctx, type="key", key="enter")
        assert len(visti) == 5

    def test_tasto_vuoto_ignorato(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="")
        assert visti == []


class TestRipetizioneTasti:
    def test_il_conteggio_produce_piu_pressioni(self, ctx, monkeypatch):
        # Il client manda i caratteri cancellati in un solo messaggio: prima ne
        # inviava uno per carattere e il debounce scartava tutti tranne il primo,
        # quindi cancellarne cinque ne cancellava uno solo.
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="backspace", count=5)
        assert visti == ["backspace"] * 5

    def test_il_conteggio_ignora_il_debounce(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="backspace", count=3)
        send(ctx, type="key", key="backspace", count=2)
        assert len(visti) == 5

    def test_il_conteggio_e_limitato(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="backspace", count=10 ** 9)
        assert len(visti) == protocol.KEY_REPEAT_MAX

    def test_conteggio_assente_equivale_a_uno(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="enter")
        assert visti == ["enter"]

    def test_conteggio_invalido_equivale_a_uno(self, ctx, monkeypatch):
        visti = []
        monkeypatch.setattr(protocol, "key_press", lambda k: visti.append(k))
        send(ctx, type="key", key="enter", count="abc")
        send(ctx, type="key", key="enter", count=0)
        send(ctx, type="key", key="enter", count=-5)
        assert visti == ["enter"] * 3


class TestTastiTenutiPremuti:
    def test_down_e_up_aggiornano_lo_stato(self, ctx):
        send(ctx, type="key_toggle", key="ctrl", state="down")
        assert "ctrl" in ctx.held_keys
        send(ctx, type="key_toggle", key="ctrl", state="up")
        assert "ctrl" not in ctx.held_keys

    def test_release_all_rilascia_i_tasti_rimasti(self, ctx, sessions, monkeypatch):
        rilasciati = []
        monkeypatch.setattr(protocol, "key_up", lambda k: rilasciati.append(k))
        monkeypatch.setattr(protocol, "mouse_button", lambda s: rilasciati.append(s))
        send(ctx, type="key_toggle", key="ctrl", state="down")
        send(ctx, type="key_toggle", key="shift", state="down")
        ctx.release_all()
        # Senza questo un client disconnesso lascerebbe Ctrl premuto sul PC.
        assert set(rilasciati) == {"ctrl", "shift", "up"}
        assert ctx.held_keys == set()
        assert ("detach_ws",) in sessions.calls

    def test_stato_mancante_ignorato(self, ctx):
        send(ctx, type="key_toggle", key="ctrl", state="")
        assert ctx.held_keys == set()


class TestPing:
    def test_risponde_pong(self, ctx, ws):
        send(ctx, type="ping")
        assert ws.json_sent() == [{"type": "pong"}]

    def test_e_limitato_in_frequenza(self, ctx, ws):
        for _ in range(10):
            send(ctx, type="ping")
        assert len(ws.sent) == 1

    def test_riprende_dopo_l_intervallo(self, ctx, ws, monkeypatch):
        adesso = [1000.0]
        monkeypatch.setattr(protocol.time, "time", lambda: adesso[0])
        send(ctx, type="ping")
        adesso[0] += PING_MIN_INTERVAL * 2
        send(ctx, type="ping")
        assert len(ws.sent) == 2


class TestTerminale:
    def test_term_list(self, ctx, ws, sessions):
        sessions.sessions_list = [{"id": "a", "cmd": "cmd.exe"}]
        send(ctx, type="term_list")
        assert ws.json_sent() == [
            {"type": "term_sessions", "sessions": [{"id": "a", "cmd": "cmd.exe"}]}
        ]

    def test_term_create_riporta_l_id(self, ctx, ws, sessions):
        send(ctx, type="term_create", cmd="cmd.exe")
        assert ("create", "cmd.exe") in sessions.calls
        assert ws.json_sent() == [{"type": "term_created", "id": "abc123"}]

    def test_term_create_su_comando_vietato_riporta_errore(self, ctx, ws, sessions):
        sessions.create_error = ValueError("Comando non consentito: 'rm'")
        send(ctx, type="term_create", cmd="rm")
        inviati = ws.json_sent()
        assert inviati[0]["type"] == "term_error"
        assert "non consentito" in inviati[0]["msg"]

    def test_term_create_notifica_il_chiamante(self, ws, sessions):
        aperti = []
        ctx = ClientConnection(ws, "192.168.1.10", sessions,
                               on_session_created=lambda sid, ip: aperti.append((sid, ip)))
        send(ctx, type="term_create")
        assert aperti == [("abc123", "192.168.1.10")]

    def test_term_attach_su_sessione_assente_riporta_errore(self, ctx, ws, sessions):
        sessions.attach_error = RuntimeError("sessione non trovata")
        send(ctx, type="term_attach", id="mancante")
        assert ws.json_sent()[0]["type"] == "term_error"

    def test_term_input_e_troncato(self, ctx, sessions):
        send(ctx, type="term_input", id="a", data="x" * (TERM_INPUT_MAX + 500))
        _, _, data = sessions.calls[0]
        assert len(data) == TERM_INPUT_MAX

    def test_term_input_non_stringa_ignorato(self, ctx, sessions):
        send(ctx, type="term_input", id="a", data={"malizioso": True})
        assert sessions.calls == []

    def test_term_input_su_sessione_morta_riporta_errore(self, ctx, ws, sessions):
        sessions.send_error = RuntimeError("sessione non disponibile")
        send(ctx, type="term_input", id="a", data="ls")
        assert ws.json_sent()[0]["type"] == "term_error"

    def test_term_resize_limita_le_dimensioni(self, ctx, sessions):
        send(ctx, type="term_resize", id="a", cols=99999, rows=0)
        assert sessions.calls == [("resize", "a", 240, 5)]

    def test_term_resize_con_valori_invalidi_usa_i_default(self, ctx, sessions):
        send(ctx, type="term_resize", id="a", cols="abc", rows=None)
        assert sessions.calls == [("resize", "a", 120, 40)]

    def test_term_kill_rimanda_la_lista(self, ctx, ws, sessions):
        send(ctx, type="term_kill", id="a")
        assert ("kill", "a") in sessions.calls
        assert ws.json_sent()[-1]["type"] == "term_sessions"

    def test_term_detach(self, ctx, sessions):
        send(ctx, type="term_detach", id="a")
        assert ("detach", "a") in sessions.calls
