"""Mappa tasti: è il contratto fra il client JS e SendInput."""

from liquidmouse.input.keymap import (
    VK_MAP,
    normalize_text,
    resolve_hotkey_vks,
    resolve_vk,
)


class TestResolveVk:
    def test_known_key(self):
        assert resolve_vk("enter") == 0x0D

    def test_is_case_insensitive(self):
        assert resolve_vk("ENTER") == resolve_vk("Enter") == resolve_vk("enter")

    def test_unknown_key(self):
        assert resolve_vk("inesistente") is None
        assert resolve_vk("") is None

    def test_escape_aliases_agree(self):
        assert resolve_vk("esc") == resolve_vk("escape") == 0x1B

    def test_win_aliases_agree(self):
        assert resolve_vk("win") == resolve_vk("lwin") == 0x5B


class TestVkMapIntegrity:
    def test_all_names_are_lowercase(self):
        # resolve_vk fa il lower() della richiesta: una chiave con maiuscole
        # nella mappa sarebbe irraggiungibile.
        assert all(name == name.lower() for name in VK_MAP)

    def test_codes_are_in_range(self):
        assert all(0 < vk <= 0xFF for vk in VK_MAP.values())


class TestResolveHotkeyVks:
    def test_named_keys(self):
        assert resolve_hotkey_vks(["ctrl", "shift"]) == [0x11, 0x10]

    def test_letters_map_to_uppercase_ascii(self):
        assert resolve_hotkey_vks(["ctrl", "c"]) == [0x11, 0x43]
        assert resolve_hotkey_vks(["ctrl", "V"]) == [0x11, 0x56]

    def test_digits_map_to_ascii(self):
        assert resolve_hotkey_vks(["alt", "1"]) == [0x12, 0x31]

    def test_order_is_preserved(self):
        # L'ordine conta: hotkey() rilascia in ordine inverso, e rilasciare un
        # modificatore prima del tasto produrrebbe il tasto isolato.
        assert resolve_hotkey_vks(["win", "v"]) == [0x5B, 0x56]

    def test_unknown_tokens_are_dropped(self):
        assert resolve_hotkey_vks(["ctrl", "inesistente", "c"]) == [0x11, 0x43]
        assert resolve_hotkey_vks(["!", "ab"]) == []

    def test_non_strings_are_dropped(self):
        # I messaggi arrivano da JSON esterno: una lista di numeri non deve
        # far esplodere il dispatch.
        assert resolve_hotkey_vks([None, 42, {"a": 1}, "ctrl"]) == [0x11]

    def test_empty(self):
        assert resolve_hotkey_vks([]) == []


class TestNormalizeText:
    def test_smart_quotes_become_ascii(self):
        assert normalize_text("l’altro") == "l'altro"
        assert normalize_text("“virgolette”") == '"virgolette"'

    def test_ellipsis_expands(self):
        assert normalize_text("attendi…") == "attendi..."

    def test_plain_text_is_untouched(self):
        assert normalize_text("cd /home/user") == "cd /home/user"

    def test_empty(self):
        assert normalize_text("") == ""
