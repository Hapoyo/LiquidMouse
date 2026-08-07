"""Traduzione dei nomi di tasto inviati dal client in virtual-key code Win32.

Modulo puro: nessun ctypes, nessuna chiamata di sistema. È il contratto fra il
client JS e il server, quindi qualsiasi tasto nuovo lato UI passa da qui.
"""

VK_MAP: dict[str, int] = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D,
    'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12,
    'capslock': 0x14, 'esc': 0x1B, 'escape': 0x1B,
    'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'insert': 0x2D, 'delete': 0x2E,
    'win': 0x5B, 'lwin': 0x5B, 'rwin': 0x5C,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72,  'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76,  'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'numlock': 0x90, 'scrolllock': 0x91, 'printscreen': 0x2C,
    'volumemute': 0xAD, 'volumedown': 0xAE, 'volumeup': 0xAF,
    'media_next': 0xB0, 'media_prev': 0xB1, 'media_stop': 0xB2, 'media_play_pause': 0xB3,
}

# Le tastiere mobili sostituiscono automaticamente apostrofi e virgolette con
# le varianti tipografiche, che come scan-code Unicode arrivano a destinazione
# come caratteri diversi da quelli attesi (rompendo path, comandi e codice).
# Una translate() è un singolo passaggio a livello C, contro cinque .replace().
SMART_QUOTES = str.maketrans({
    '‘': "'", '’': "'",
    '“': '"', '”': '"',
    '…': '...',
})


def resolve_vk(key: str) -> int | None:
    """Virtual-key code di un tasto nominato, None se sconosciuto."""
    return VK_MAP.get(key.lower())


def resolve_hotkey_vks(keys) -> list[int]:
    """Virtual-key code di una combinazione, scartando i token non validi.

    Oltre ai nomi noti accetta un singolo carattere alfanumerico: i codici VK
    di lettere e cifre coincidono con l'ASCII maiuscolo ('c' → 0x43, '1' → 0x31),
    così `hotkey('ctrl', 'c')` funziona senza mappare l'intero alfabeto.
    """
    vks: list[int] = []
    for k in keys:
        if not isinstance(k, str):
            continue
        vk = VK_MAP.get(k.lower())
        if vk is not None:
            vks.append(vk)
        elif len(k) == 1 and k.isalpha():
            vks.append(ord(k.upper()))
        elif len(k) == 1 and k.isdigit():
            vks.append(ord(k))
    return vks


def normalize_text(text: str) -> str:
    """Testo pronto per l'invio come scan-code Unicode."""
    return text.translate(SMART_QUOTES)
