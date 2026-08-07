"""Classificazione degli indirizzi IP e scoperta degli indirizzi locali.

Da qui dipende il modello di autorizzazione: il server decide se una
connessione è locale (fidata) o remota (PIN obbligatorio) solo guardando
l'indirizzo, quindi le regole di questo modulo sono di fatto un controllo di
sicurezza. Sono anche l'unica parte del progetto testabile senza Windows.
"""

import ipaddress
import socket
import threading
import time
from collections.abc import Callable

# Range CGNAT: è quello che Tailscale assegna ai nodi del tailnet, ma è anche
# quello che molti ISP usano per i loro clienti. Le due cose vanno distinte con
# cura — vedi is_private_ip e is_tailscale_conn.
CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def is_private_ip(ip: str) -> bool:
    """True per LAN e link-local, ma **False dentro il CGNAT**.

    L'esclusione del 100.64/10 è deliberata: senza di essa un altro cliente
    dello stesso ISP in CGNAT verrebbe classificato come "LAN" e salterebbe
    l'autenticazione con PIN.
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


def get_tailscale_ip() -> str | None:
    """IP Tailscale (100.64/10) di questa macchina, None se la VPN non è attiva.

    Trucco senza dipendenze: un connect UDP verso il resolver MagicDNS di
    Tailscale (100.100.100.100) sceglie l'interfaccia instradata sul tailnet;
    se getsockname non è nel range CGNAT, Tailscale non c'è.

    Attenzione: apre un socket con timeout 1 s. Non chiamarla su un path caldo
    né da un callback sincrono della GUI — usare `cached_tailscale_ip()`.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(1)
            s.connect(("100.100.100.100", 53))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip if ipaddress.ip_address(ip) in CGNAT_NET else None
    except Exception:
        return None


class CachedTailscaleIp:
    """`get_tailscale_ip` con cache a scadenza.

    La sonda apre un socket con timeout 1 s. Il menu tray la usa come callable
    lazy, quindi veniva rivalutata a ogni apertura del menu: con Tailscale
    spento si pagava fino a un secondo di finestra congelata ogni volta.
    """

    def __init__(self, ttl: float = 30.0, probe=get_tailscale_ip,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._probe = probe
        self._clock = clock
        self._value: str | None = None
        self._checked_at: float | None = None
        self._lock = threading.Lock()

    def __call__(self) -> str | None:
        with self._lock:
            now = self._clock()
            if self._checked_at is not None and (now - self._checked_at) < self._ttl:
                return self._value
        # La sonda gira fuori dal lock: e' lenta, e tenere il lock bloccherebbe
        # il thread della GUI proprio nel caso che vogliamo evitare.
        value = self._probe()
        with self._lock:
            self._value = value
            self._checked_at = self._clock()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._checked_at = None


def is_tailscale_conn(websocket) -> bool:
    """True se la connessione arriva via tailnet: sorgente E destinazione nel
    range 100.64/10.

    Il controllo sulla destinazione (l'IP locale del socket) impedisce a un
    vicino di CGNAT dell'ISP di spacciarsi per peer Tailscale attraverso una
    porta UPnP-mappata: quel traffico arriverebbe sull'IP LAN, non sul 100.x.
    """
    try:
        remote = ipaddress.ip_address(websocket.remote_address[0])
        local = ipaddress.ip_address(websocket.local_address[0])
        return remote in CGNAT_NET and local in CGNAT_NET
    except Exception:
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
