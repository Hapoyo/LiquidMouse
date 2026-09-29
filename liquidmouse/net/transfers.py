"""Token monouso per i trasferimenti file via HTTP.

L'HTTP non ha autenticazione (serve solo asset pubblici), ma un download o un
upload agisce sul disco di un altro host con i permessi dell'utente SSH. Il
client autenticato via WebSocket chiede un biglietto (`sftp_ticket`); l'HTTP lo
accetta una volta sola, entro pochi secondi, e solo per quel file e quella
direzione. Chi non ha passato dal WS (PIN compreso) non ne ha uno.
"""

import secrets
import threading
import time
from dataclasses import dataclass

TICKET_TTL_SECS = 60.0
TICKETS_MAX = 200

# Sulla porta remota (8443/tunnel) la risposta passa da websockets, che non fa
# streaming e non riceve corpi di POST: il download viene letto in memoria (con
# un tetto) e l'upload non c'è. Sulla porta 8000 nessuno dei due limiti vale.
REMOTE_DOWNLOAD_MAX = 64 * 1024 * 1024

DOWNLOAD = "dl"
UPLOAD = "up"


@dataclass(frozen=True)
class Ticket:
    owner: int        # id della connessione WS che l'ha chiesto
    direction: str    # DOWNLOAD | UPLOAD
    path: str         # file completo (per l'upload: cartella + nome)
    expires: float


class TransferRegistry:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def issue(self, owner: int, direction: str, path: str) -> str:
        if direction not in (DOWNLOAD, UPLOAD):
            raise ValueError("direzione non valida")
        token = secrets.token_urlsafe(16)
        now = self._clock()
        with self._lock:
            self._purge(now)
            if len(self._tickets) >= TICKETS_MAX:
                raise RuntimeError("troppi trasferimenti in corso")
            self._tickets[token] = Ticket(owner, direction, path, now + TICKET_TTL_SECS)
        return token

    def redeem(self, token: str, direction: str) -> Ticket | None:
        """Consuma il biglietto. None se sconosciuto, scaduto o di altra
        direzione (e in quel caso il biglietto resta bruciato)."""
        with self._lock:
            ticket = self._tickets.pop(token, None)
        if ticket is None or ticket.expires < self._clock() or ticket.direction != direction:
            return None
        return ticket

    def revoke_owner(self, owner: int) -> None:
        with self._lock:
            self._tickets = {t: k for t, k in self._tickets.items() if k.owner != owner}

    def _purge(self, now: float) -> None:
        self._tickets = {t: k for t, k in self._tickets.items() if k.expires >= now}
