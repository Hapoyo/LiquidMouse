"""Classificazione degli indirizzi IP e scoperta degli indirizzi locali.

Da qui dipende il modello di autorizzazione: il server decide se una
connessione è locale (fidata) o remota (PIN obbligatorio) solo guardando
l'indirizzo, quindi le regole di questo modulo sono di fatto un controllo di
sicurezza. Sono anche l'unica parte del progetto testabile senza Windows.
"""

import ipaddress
import socket
import threading

# Range CGNAT: molti ISP ci mettono i propri clienti dietro NAT condiviso.
# Formalmente non è "privato" ai fini di questo progetto — vedi is_private_ip.
CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def is_private_ip(ip: str) -> bool:
    """True per LAN e link-local, ma **False dentro il CGNAT**.

    L'esclusione del 100.64/10 è deliberata e va tenuta: senza di essa un altro
    cliente dello stesso ISP, che dietro CGNAT ha un indirizzo di quel range,
    verrebbe classificato come "LAN" e salterebbe l'autenticazione con PIN.
    """
    try:
        addr = ipaddress.ip_address(ip)
        if addr in CGNAT_NET:
            return False
        return addr.is_private or addr.is_link_local
    except ValueError:
        return False


def is_loopback(ip: str) -> bool:
    """True per 127.0.0.1 / ::1 — la stessa macchina, sempre fidata."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def get_local_ip() -> str:
    """IP LAN di questa macchina, "127.0.0.1" se non determinabile.

    Non invia nulla: il connect UDP serve solo a far scegliere al kernel
    l'interfaccia di uscita.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class TrustedPeer:
    """Whitelist LAN "primo arrivato".

    In LAN non c'è PIN: il primo client che si connette occupa lo slot e gli
    altri vengono rifiutati finché non si usa "Reset connessione locale" dal
    menu tray. Lo stato è letto dal loop asyncio e azzerato dal thread della
    GUI, da cui il lock.
    """

    def __init__(self) -> None:
        self._ip: str | None = None
        self._lock = threading.Lock()

    @property
    def ip(self) -> str | None:
        with self._lock:
            return self._ip

    def claim(self, ip: str) -> bool:
        """Assegna lo slot a `ip` se libero. True se `ip` può procedere."""
        with self._lock:
            if self._ip is None:
                self._ip = ip
                return True
            return self._ip == ip

    def reset(self) -> None:
        with self._lock:
            self._ip = None
