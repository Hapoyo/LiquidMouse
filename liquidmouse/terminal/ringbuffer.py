"""Buffer circolare dell'output di una sessione PTY.

Serve a rimandare al client le ultime schermate quando si riaggancia dopo una
disconnessione. Tiene gli ultimi `maxsize` byte e scarta i piu' vecchi.

La versione precedente faceva `del buf[:n]` a ogni chunk una volta pieno il
ring: su bytearray e' un memmove O(n), quindi con output abbondante (una build,
un `dir /s`) si pagava una copia da 64 KB per ogni 4 KB letti. Qui lo scarto e'
solo l'avanzamento di un indice, e la compattazione avviene una volta ogni
`maxsize` byte scritti — ammortizzato O(1), stesso contenuto osservabile.
"""

DEFAULT_MAXSIZE = 65536


class RingBuffer:
    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize deve essere positivo")
        self._buf = bytearray()
        self._start = 0
        self._maxsize = maxsize

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def append(self, data: bytes) -> None:
        if not data:
            return
        self._buf += data
        excess = len(self._buf) - self._start - self._maxsize
        if excess > 0:
            self._start += excess
            # Compatta solo quando il prefisso morto e' diventato grande: cosi'
            # il memmove capita una volta ogni maxsize byte, non a ogni chunk.
            if self._start >= self._maxsize:
                del self._buf[:self._start]
                self._start = 0

    def snapshot(self) -> bytes:
        """Contenuto corrente, dal piu' vecchio conservato al piu' recente."""
        return bytes(memoryview(self._buf)[self._start:])

    def clear(self) -> None:
        self._buf.clear()
        self._start = 0

    def __len__(self) -> int:
        return len(self._buf) - self._start
