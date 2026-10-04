"""Cifratura con la chiave dell'utente Windows (DPAPI, CryptProtectData).

Serve a tutto ciò che sta nella config e non deve restare in chiaro: password
SFTP, PIN e chiave privata TLS. Il file copiato su un altro PC o utente non li
rivela. Dove DPAPI manca (Linux, test) `default_protector()` ritorna None e i
chiamanti mantengono il comportamento senza cifratura.
"""

import base64
import sys


class ProtectError(OSError):
    """DPAPI ha rifiutato di cifrare o decifrare."""


class DpapiProtector:
    """Cifra con la chiave dell'utente Windows (CryptProtectData): il file di
    config copiato su un altro PC o utente non rivela i segreti."""

    def protect(self, text: str) -> str:
        return base64.b64encode(_dpapi(text.encode("utf-8"), protect=True)).decode("ascii")

    def unprotect(self, blob: str) -> str:
        return _dpapi(base64.b64decode(blob), protect=False).decode("utf-8")


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                      ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise ProtectError("cifratura non riuscita")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def default_protector() -> DpapiProtector | None:
    """DPAPI su Windows; altrove None: meglio rifiutare di salvare un segreto
    che scriverlo in chiaro (SFTP) o lasciare il comportamento di prima (config)."""
    return DpapiProtector() if sys.platform == "win32" else None
