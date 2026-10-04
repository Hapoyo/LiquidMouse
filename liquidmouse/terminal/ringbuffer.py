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
        # Byte scritti in totale dalla creazione: non scende mai, nemmeno quando
        # il ring scarta o viene svuotato. Permette a chi prende uno snapshot di
        # chiedere poi solo "cio' che e' arrivato dopo" senza perdere byte.
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def append(self, data: bytes) -> None:
        if not data:
            return
        self._buf += data
        self._total += len(data)
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

    def snapshot_with_offset(self) -> tuple[bytes, int]:
        """Snapshot e contatore letti insieme (nessun await in mezzo)."""
        return self.snapshot(), self._total

    def since(self, offset: int) -> bytes:
        """Byte scritti dopo `offset`; se il ring ne ha gia' scartati, quanto resta."""
        n = min(self._total - offset, len(self))
        if n <= 0:
            return b""
        return bytes(memoryview(self._buf)[len(self._buf) - n:])

    def clear(self) -> None:
        self._buf.clear()
        self._start = 0

    def __len__(self) -> int:
        return len(self._buf) - self._start
