"""Apertura automatica della porta remota via UPnP.

Se il router lo consente, evita di dover configurare a mano un port forward.
È l'unica strada per l'accesso remoto: se fallisce, resta il forward manuale
sul router.
"""

import asyncio
import atexit
import ipaddress

from liquidmouse.events import log_message
from liquidmouse.executors import NET
from liquidmouse.ports import HTTPS_PORT
from liquidmouse.theme import COLOR_MUTED

# I router FWA lenti a rispondere a SSDP venivano persi con i 300 ms di
# default: la discovery girava a vuoto e il remoto risultava non disponibile
# anche con UPnP attivo sul router.
DISCOVER_DELAY_MS = 2000

# Porte esterne provate in ordine, tutte inoltrate alla 8443 del PC. Molti
# modem degli operatori tengono la 8443 per la propria gestione remota e
# rifiutano il mapping: con una sola porta il remoto restava chiuso anche con
# UPnP attivo. Il browser si connette al WSS sulla stessa porta della pagina
# (buildWsUrl in app.js), quindi basta che il QR porti la porta esterna.
EXTERNAL_PORTS = (8443, 9443, 10443, 18443, 28443, 38443)

MAPPING_DESC = 'LiquidMouse'


# Reti che, come IP "esterno" del router, indicano un altro NAT a monte.
# Elenco esplicito e non `is_global`: interessa solo il NAT, e `is_global`
# scarterebbe anche i blocchi di documentazione usati nei test.
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")   # NAT condiviso dell'operatore
_NAT_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # LAN (RFC 1918)
    "169.254.0.0/16", "127.0.0.0/8",
)) + (_CGNAT_NET,)


def _is_public_ip(ip: str) -> bool:
    """False per indirizzi di LAN, CGNAT e non validi."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not any(addr in net for net in _NAT_NETS)


class UpnpMapper:
    """Mappatura della porta remota, con cleanup all'uscita.

    Richiamabile più volte (serve al keepalive): ricrea sempre un oggetto UPnP
    fresco, perché i router FWA possono perdere i pinhole NAT pur continuando a
    elencare i mapping (visto sul Home&Life SuperWiFi, lug 2026).
    """

    def __init__(self, internal_port: int = HTTPS_PORT,
                 external_ports: tuple[int, ...] = EXTERNAL_PORTS) -> None:
        self._internal_port = internal_port
        self._external_ports = tuple(external_ports)
        self._upnp = None
        self.external_port: int | None = None
        self._atexit_registered = False
        self.external_ip: str | None = None
        # Motivo dell'ultimo fallimento, per il log. Prima ogni causa (libreria
        # assente, nessun router trovato, IP esterno non valido, mapping
        # rifiutato, eccezione qualsiasi) finiva nello stesso "non riuscito",
        # rendendo impossibile capire cosa correggere senza leggere il codice.
        self.last_error: str | None = None

    def _candidate_ports(self) -> list[int]:
        # Al rinnovo si riprova prima la porta già in uso: cambiarla
        # invaliderebbe il QR già scansionato.
        porte = list(self._external_ports)
        if self.external_port in porte:
            porte.remove(self.external_port)
            porte.insert(0, self.external_port)
        return porte

    def _try_map(self, u, ext_port: int, local_ip: str) -> str | None:
        """Mappa `ext_port` → porta interna. None se riuscito, altrimenti il motivo."""
        try:
            u.addportmapping(ext_port, 'TCP', local_ip, self._internal_port,
                             MAPPING_DESC, '')
            return None
        except Exception as e:
            errore = str(e) or type(e).__name__
        # "ConflictInMappingEntry" (errore UPnP 718): la porta è già mappata.
        # Se il mapping è nostro (residuo di un avvio che non è passato da
        # cleanup: crash, kill, IP locale cambiato) si libera e si rimappa.
        # Se è di un altro dispositivo non si tocca: prima veniva cancellato
        # alla cieca, rompendo il port forward di qualcun altro.
        try:
            esistente = u.getspecificportmapping(ext_port, 'TCP')
        except Exception:
            esistente = None
        if not esistente:
            return errore
        host, _porta_int, desc = esistente[0], esistente[1], esistente[2]
        if host != local_ip and desc != MAPPING_DESC:
            return f"occupata da {host}"
        try:
            u.deleteportmapping(ext_port, 'TCP')
            u.addportmapping(ext_port, 'TCP', local_ip, self._internal_port,
                             MAPPING_DESC, '')
            return None
        except Exception as e:
            return str(e) or type(e).__name__

    def setup_sync(self, local_ip: str) -> str | None:
        """Discovery e mappatura. Bloccante: chiamare da `setup()`.

        Ritorna l'IP esterno, o None se il remoto via UPnP non è disponibile
        (il motivo è in `self.last_error`). La porta esterna scelta è in
        `self.external_port`.
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
            if not _is_public_ip(ext_ip):
                # Il router UPnP sta dietro un altro NAT: il mapping riuscirebbe
                # ma aprirebbe la porta solo verso lo strato sopra, e il QR
                # punterebbe a un indirizzo irraggiungibile da fuori. Messaggi
                # corti: il pannello remoto li tronca, e nella 2.6.2 la parte
                # utile ("doppio NAT o CGNAT") finiva tagliata.
                if ipaddress.ip_address(ext_ip) in _CGNAT_NET:
                    self.last_error = f"cgnat dell'operatore ({ext_ip})"
                else:
                    self.last_error = f"doppio nat, modem a monte ({ext_ip})"
                return None
            fallite = []
            scelta = None
            for porta in self._candidate_ports():
                motivo = self._try_map(u, porta, local_ip)
                if motivo is None:
                    scelta = porta
                    break
                fallite.append(f"{porta}: {motivo}")
            if scelta is None:
                # Nessuna porta aperta: dichiarare il remoto attivo sarebbe un
                # falso positivo, e il QR manderebbe il telefono nel vuoto.
                self.last_error = f"il router ha rifiutato la mappatura ({'; '.join(fallite)})"
                return None
            if fallite:
                log_message(f"UPnP: porte rifiutate ({'; '.join(fallite)}), "
                            f"uso la {scelta}", color=COLOR_MUTED)
            if self._upnp is not None and self.external_port not in (None, scelta):
                # Il rinnovo ha scelto un'altra porta: la vecchia resterebbe
                # aperta fino al riavvio del router.
                try:
                    self._upnp.deleteportmapping(self.external_port, 'TCP')
                except Exception:
                    pass
            self.external_port = scelta
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
        return await loop.run_in_executor(NET, self.setup_sync, local_ip)

    def cleanup(self) -> None:
        """Rimuove il mapping. Lasciarlo aperto esporrebbe la porta oltre la
        durata del processo."""
        if not self._upnp or self.external_port is None:
            return
        try:
            self._upnp.deleteportmapping(self.external_port, 'TCP')
        except Exception as e:
            try:
                log_message(f"UPnP cleanup porta {self.external_port}: {e}",
                            color=COLOR_MUTED)
            except Exception:
                pass
