"""Apertura automatica della porta remota via UPnP.

Se il router lo consente, evita di dover configurare a mano un port forward.
È l'unica strada per l'accesso remoto: se fallisce, resta il forward manuale
sul router.
"""

import asyncio
import atexit

from liquidmouse.events import log_message
from liquidmouse.ports import HTTPS_PORT
from liquidmouse.theme import COLOR_MUTED

# I router FWA lenti a rispondere a SSDP venivano persi con i 300 ms di
# default: la discovery girava a vuoto e il remoto risultava non disponibile
# anche con UPnP attivo sul router.
DISCOVER_DELAY_MS = 2000


class UpnpMapper:
    """Mappatura della porta remota, con cleanup all'uscita.

    Richiamabile più volte (serve al keepalive): ricrea sempre un oggetto UPnP
    fresco, perché i router FWA possono perdere i pinhole NAT pur continuando a
    elencare i mapping (visto sul Home&Life SuperWiFi, lug 2026).
    """

    def __init__(self, ports: list[int] | None = None) -> None:
        self._ports_wanted = ports if ports is not None else [HTTPS_PORT]
        self._upnp = None
        self._mapped: list[int] = []
        self._atexit_registered = False
        self.external_ip: str | None = None

    def setup_sync(self, local_ip: str) -> str | None:
        """Discovery e mappatura. Bloccante: chiamare da `setup()`.

        Ritorna l'IP esterno, o None se il remoto via UPnP non è disponibile.
        """
        try:
            import miniupnpc
        except ImportError:
            return None
        try:
            u = miniupnpc.UPnP()
            u.discoverdelay = DISCOVER_DELAY_MS
            if u.discover() == 0:
                return None
            u.selectigd()
            ext_ip = u.externalipaddress()
            if not ext_ip or ext_ip == '0.0.0.0':
                return None
            mapped = []
            for port in self._ports_wanted:
                try:
                    u.addportmapping(port, 'TCP', local_ip, port, 'LiquidControl', '')
                    mapped.append(port)
                except Exception:
                    pass
            if not mapped:
                # Nessuna porta aperta: dichiarare il remoto attivo sarebbe un
                # falso positivo, e il QR manderebbe il telefono nel vuoto.
                return None
            self._mapped = mapped
            self._upnp = u
            self.external_ip = ext_ip
            if not self._atexit_registered:
                atexit.register(self.cleanup)
                self._atexit_registered = True
            return ext_ip
        except Exception:
            return None

    async def setup(self, local_ip: str) -> str | None:
        """Come `setup_sync`, ma senza bloccare l'event loop.

        La discovery aspetta fino a 2 s: eseguita nel loop bloccherebbe tutti i
        WebSocket attivi.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.setup_sync, local_ip)

    def cleanup(self) -> None:
        """Rimuove i mapping. Lasciarli aperti esporrebbe la porta oltre la
        durata del processo."""
        if not self._upnp:
            return
        for port in self._mapped:
            try:
                self._upnp.deleteportmapping(port, 'TCP')
            except Exception as e:
                try:
                    log_message(f"UPnP cleanup porta {port}: {e}", color=COLOR_MUTED)
                except Exception:
                    pass
