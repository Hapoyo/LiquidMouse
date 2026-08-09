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
        # Motivo dell'ultimo fallimento, per il log. Prima ogni causa (libreria
        # assente, nessun router trovato, IP esterno non valido, mapping
        # rifiutato, eccezione qualsiasi) finiva nello stesso "non riuscito",
        # rendendo impossibile capire cosa correggere senza leggere il codice.
        self.last_error: str | None = None

    def setup_sync(self, local_ip: str) -> str | None:
        """Discovery e mappatura. Bloccante: chiamare da `setup()`.

        Ritorna l'IP esterno, o None se il remoto via UPnP non è disponibile
        (il motivo è in `self.last_error`).
        """
        try:
            import miniupnpc
        except ImportError:
            self.last_error = "libreria miniupnpc non disponibile in questa build"
            return None
        except Exception as e:
            # Non solo ImportError: un'estensione nativa compilata male (DLL
            # incompatibili in un EXE PyInstaller) puo' far fallire l'import
            # con un errore diverso. Senza questo ramo l'eccezione si
            # propagava non gestita fuori da setup_sync, e piu' su fuori da
            # `await self.upnp.setup(...)` in start_websocket_server: l'intero
            # thread dei servizi di rete moriva zitto, con last_error rimasto
            # None e remote_mode fermo su "none" — lo stesso sintomo di
            # "Remoto non disponibile" ma senza alcun dettaglio nel log.
            self.last_error = f"libreria miniupnpc non caricabile: {e}"
            return None
        try:
            u = miniupnpc.UPnP()
            u.discoverdelay = DISCOVER_DELAY_MS
            if u.discover() == 0:
                self.last_error = (
                    "nessun router UPnP/IGD trovato in rete (discovery fallita)")
                return None
            u.selectigd()
            ext_ip = u.externalipaddress()
            if not ext_ip or ext_ip == '0.0.0.0':
                self.last_error = (
                    "il router non riporta un IP pubblico valido "
                    "(probabile doppio NAT: un altro router/modem a monte)")
                return None
            mapped = []
            fallite = []
            for port in self._ports_wanted:
                try:
                    u.addportmapping(port, 'TCP', local_ip, port, 'LiquidControl', '')
                    mapped.append(port)
                except Exception as e:
                    # "ConflictInMappingEntry" (errore UPnP 718): la porta e'
                    # gia' mappata, tipicamente residuo di un avvio precedente
                    # che non e' passato da cleanup() (crash, kill, o un IP
                    # locale cambiato nel frattempo). Si prova a liberarla e
                    # rimappare una volta sola, prima di arrendersi.
                    try:
                        u.deleteportmapping(port, 'TCP')
                        u.addportmapping(port, 'TCP', local_ip, port, 'LiquidControl', '')
                        mapped.append(port)
                        continue
                    except Exception:
                        pass
                    fallite.append(f"{port}: {e}")
            if not mapped:
                # Nessuna porta aperta: dichiarare il remoto attivo sarebbe un
                # falso positivo, e il QR manderebbe il telefono nel vuoto.
                self.last_error = f"il router ha rifiutato la mappatura ({'; '.join(fallite)})"
                return None
            self._mapped = mapped
            self._upnp = u
            self.external_ip = ext_ip
            self.last_error = None
            if not self._atexit_registered:
                atexit.register(self.cleanup)
                self._atexit_registered = True
            return ext_ip
        except Exception as e:
            self.last_error = f"errore inatteso: {e}"
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
