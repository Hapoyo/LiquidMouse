"""Iniezione di input via Win32 SendInput (ctypes nativo, zero dipendenze).

Il modulo si importa anche fuori da Windows — le strutture ctypes sono
portabili, solo `user32` non esiste — così i test della mappa tasti e del
protocollo girano in CI su Linux. Le funzioni di invio, se chiamate altrove,
non fanno nulla invece di sollevare.
"""

import ctypes
import sys

from liquidmouse.input.keymap import VK_MAP, normalize_text, resolve_hotkey_vks, resolve_vk

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None

INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE      = 0x0001
MOUSEEVENTF_LEFTDOWN  = 0x0002
MOUSEEVENTF_LEFTUP    = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP   = 0x0010
MOUSEEVENTF_WHEEL     = 0x0800

KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
WHEEL_DELTA       = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _INPUT_UNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong), ("value", _INPUT_UNION))


_INPUT_SIZE = ctypes.sizeof(INPUT)


def _send(*inputs):
    if _user32 is None:
        return
    arr = (INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), arr, _INPUT_SIZE)


def _mi(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.value.mi.dx = dx
    i.value.mi.dy = dy
    i.value.mi.mouseData = ctypes.c_ulong(ctypes.c_long(data).value).value
    i.value.mi.dwFlags = flags
    return i


def _ki(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.value.ki.wVk = vk
    i.value.ki.wScan = scan
    i.value.ki.dwFlags = flags
    return i


# Buffer riutilizzabili per i path a 60Hz (move/scroll): mutati in place a ogni
# evento per evitare di allocare una INPUT + array a ogni movimento del cursore.
_move_arr   = (INPUT * 1)(_mi(MOUSEEVENTF_MOVE))
_scroll_arr = (INPUT * 1)(_mi(MOUSEEVENTF_WHEEL))


def mouse_move(dx, dy):
    if dx == 0 and dy == 0:
        return
    if _user32 is None:
        return
    mi = _move_arr[0].value.mi
    mi.dx = dx
    mi.dy = dy
    _user32.SendInput(1, _move_arr, _INPUT_SIZE)


def mouse_scroll(amount):
    if _user32 is None:
        return
    _scroll_arr[0].value.mi.mouseData = ctypes.c_ulong(
        ctypes.c_long(amount * WHEEL_DELTA).value).value
    _user32.SendInput(1, _scroll_arr, _INPUT_SIZE)


def mouse_click(button='left'):
    if button == 'left':
        _send(_mi(MOUSEEVENTF_LEFTDOWN), _mi(MOUSEEVENTF_LEFTUP))
    else:
        _send(_mi(MOUSEEVENTF_RIGHTDOWN), _mi(MOUSEEVENTF_RIGHTUP))


def mouse_button(state, button='left'):
    if button == 'left':
        flag = MOUSEEVENTF_LEFTDOWN if state == 'down' else MOUSEEVENTF_LEFTUP
    else:
        flag = MOUSEEVENTF_RIGHTDOWN if state == 'down' else MOUSEEVENTF_RIGHTUP
    _send(_mi(flag))


def key_press(key):
    vk = resolve_vk(key)
    if vk is not None:
        _send(_ki(vk=vk), _ki(vk=vk, flags=KEYEVENTF_KEYUP))
    elif len(key) == 1:
        key_text(key)


def _send_vk(key, flags=0):
    vk = resolve_vk(key)
    if vk:
        _send(_ki(vk=vk, flags=flags))


def key_down(key):
    _send_vk(key)


def key_up(key):
    _send_vk(key, KEYEVENTF_KEYUP)


def key_text(text):
    text = normalize_text(text)
    inputs = []
    for c in text:
        sc = ord(c)
        inputs += [
            _ki(scan=sc, flags=KEYEVENTF_UNICODE),
            _ki(scan=sc, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        ]
    if inputs:
        _send(*inputs)


def hotkey(*keys):
    """Preme i tasti in ordine e li rilascia in ordine inverso.

    L'ordine inverso al rilascio è quello che rende affidabili le combinazioni
    con modificatori: rilasciare 'ctrl' prima di 'c' produrrebbe una 'c'
    isolata nell'applicazione di destinazione.
    """
    vks = resolve_hotkey_vks(keys)
    downs = [_ki(vk=vk) for vk in vks]
    ups = [_ki(vk=vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vks)]
    _send(*downs, *ups)


__all__ = [
    "VK_MAP", "WHEEL_DELTA",
    "mouse_move", "mouse_scroll", "mouse_click", "mouse_button",
    "key_press", "key_down", "key_up", "key_text", "hotkey",
]
