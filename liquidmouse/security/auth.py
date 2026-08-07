"""Anti-bruteforce sull'autenticazione remota con PIN.

Cinque tentativi falliti dallo stesso IP e quell'IP resta bloccato per 30
minuti. Il contatore si azzera da solo anche senza raggiungere la soglia, così
tentativi legittimi distanti nel tempo non si sommano all'infinito.
"""

import hashlib
import hmac
import time
from collections.abc import Callable

AUTH_MAX_FAILS = 5
AUTH_BLOCK_SECS = 1800  # 30 minuti


def hash_pin(pin: str) -> str:
    """Hash del PIN come salvato in config. Confrontare con `pin_matches`."""
    return hashlib.sha256(pin.encode()).hexdigest()


def pin_matches(candidate: str, expected_hash: str) -> bool:
    """Confronto a tempo costante, per non far trapelare il PIN dai tempi."""
    return hmac.compare_digest(hash_pin(candidate), expected_hash)


class AuthGuard:
    """Contatore di fallimenti per IP.

    `clock` è iniettabile per i test: di default `time.time`.
    """

    def __init__(
        self,
        max_fails: int = AUTH_MAX_FAILS,
        block_secs: int = AUTH_BLOCK_SECS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._failures: dict[str, tuple[int, float]] = {}
        self._in_progress: set[str] = set()
        self._max_fails = max_fails
        self._block_secs = block_secs
        self._clock = clock

    def is_blocked(self, ip: str) -> bool:
        """True se `ip` è in blocco. Ripulisce le voci scadute passando."""
        entry = self._failures.get(ip)
        if not entry:
            return False
        count, last_t = entry
        now = self._clock()
        if count >= self._max_fails:
            if (now - last_t) < self._block_secs:
                return True
            self._failures.pop(ip, None)
        elif (now - last_t) >= self._block_secs:
            self._failures.pop(ip, None)
        return False

    def record_fail(self, ip: str) -> None:
        prev = self._failures.get(ip, (0, 0.0))
        self._failures[ip] = (prev[0] + 1, self._clock())

    def clear(self, ip: str) -> None:
        self._failures.pop(ip, None)

    def remaining(self, ip: str) -> int:
        """Tentativi ancora disponibili prima del blocco."""
        count = self._failures.get(ip, (0, 0.0))[0]
        return max(0, self._max_fails - count)

    # --- handshake in corso ---------------------------------------------
    # Un solo tentativo di autenticazione alla volta per IP: senza questo, un
    # attaccante potrebbe aprire N connessioni in parallelo e provare N PIN
    # prima che il contatore dei fallimenti raggiunga la soglia.

    def begin(self, ip: str) -> bool:
        """False se per quell'IP c'è già un handshake in corso."""
        if ip in self._in_progress:
            return False
        self._in_progress.add(ip)
        return True

    def end(self, ip: str) -> None:
        self._in_progress.discard(ip)
