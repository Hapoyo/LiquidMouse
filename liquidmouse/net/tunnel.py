"""Accesso remoto tramite tunnel Cloudflare, quando UPnP non può funzionare.

Dietro CGNAT (l'operatore condivide un IP pubblico fra più clienti, tipico
delle linee FWA) nessuna porta si apre da casa, né con UPnP né a mano. Il
tunnel ribalta il verso: `cloudflared` apre una connessione in uscita verso
Cloudflare e riceve un indirizzo https://<parole>.trycloudflare.com (quick
tunnel: gratis, senza account). Il traffico arriva sul PC in chiaro su
127.0.0.1:TUNNEL_PORT; il TLS lo termina Cloudflare con un certificato valido,
quindi sul telefono niente avviso.

L'eseguibile non è nel bundle (sono decine di MB): si usa quello nel PATH o
lo si scarica una volta in %APPDATA%/LiquidMouse/bin.
"""

import atexit
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable

from liquidmouse.events import log_message
from liquidmouse.theme import COLOR_ERROR, COLOR_MUTED, COLOR_OK

CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/"
                   "download/cloudflared-windows-amd64.exe")
CLOUDFLARED_EXE = "cloudflared.exe"
# Sotto questa soglia il download è una pagina d'errore, non l'eseguibile.
MIN_BINARY_BYTES = 1_000_000

# Gli indirizzi dei quick tunnel sono parole separate da trattini. Il vincolo
# del trattino esclude https://api.trycloudflare.com, che compare nei messaggi
# d'errore di cloudflared e passerebbe per l'indirizzo del tunnel.
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")

# Prefisso delle righe di log di cloudflared: "2026-09-27T16:29:26Z ERR ".
_LOG_PREFIX_RE = re.compile(r"^\S+Z\s+[A-Z]{3}\s+")

RESTART_MIN_SECS = 10
RESTART_MAX_SECS = 300


def parse_tunnel_url(riga: str) -> str | None:
    """L'indirizzo del quick tunnel contenuto in una riga di log, se c'è."""
    m = TUNNEL_URL_RE.search(riga)
    return m.group(0) if m else None


def error_line(riga: str) -> str | None:
    """La riga, senza data e livello, se descrive un errore."""
    testo = riga.strip()
    if not (" ERR " in testo or "failed" in testo or "error" in testo.lower()):
        return None
    return _LOG_PREFIX_RE.sub("", testo) or None


def download_cloudflared(dest: pathlib.Path, url: str = CLOUDFLARED_URL,
                         timeout: float = 60) -> None:
    """Scarica cloudflared in `dest`. Solleva OSError se non riesce.

    Scrive in un .part e rinomina alla fine: un download interrotto non deve
    lasciare un eseguibile troncato che al prossimo avvio verrebbe lanciato.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    parziale = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as risposta, \
                open(parziale, "wb") as f:
            shutil.copyfileobj(risposta, f)
        if parziale.stat().st_size < MIN_BINARY_BYTES:
            raise OSError("download incompleto")
        os.replace(parziale, dest)
    finally:
        try:
            parziale.unlink()
        except OSError:
            pass


class CloudflareTunnel:
    """Processo cloudflared con riavvio automatico.

    Gira in un thread proprio: `url` è l'indirizzo pubblico quando il tunnel è
    su, `status` il motivo per cui non lo è (o cosa sta facendo). A ogni
    cambiamento chiama `on_change`. Le dipendenze di sistema (Popen, download,
    ricerca nel PATH, attesa) sono iniettabili per i test.
    """

    def __init__(self, local_port: int, bin_dir: pathlib.Path, *,
                 popen=subprocess.Popen,
                 download: Callable[[pathlib.Path], None] = download_cloudflared,
                 which: Callable[[str], str | None] = shutil.which,
                 can_download: bool = sys.platform == "win32") -> None:
        self._local_port = local_port
        self._bin_path = pathlib.Path(bin_dir) / CLOUDFLARED_EXE
        self._popen = popen
        self._download = download
        self._which = which
        self._can_download = can_download
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = None
        self._lock = threading.Lock()
        self._atexit_registered = False
        self.on_change: Callable[[], None] | None = None
        self.url: str | None = None
        self.status: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _set(self, url: str | None, status: str | None) -> None:
        if (url, status) == (self.url, self.status):
            return
        self.url, self.status = url, status
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def binary(self) -> str | None:
        """Percorso di cloudflared, scaricandolo se serve. None se non disponibile
        (il motivo va in `status`)."""
        trovato = self._which("cloudflared")
        if trovato:
            return trovato
        if self._bin_path.is_file():
            return str(self._bin_path)
        if not self._can_download:
            self._set(None, "cloudflared non trovato")
            return None
        self._set(None, "download di cloudflared…")
        log_message("Tunnel: download di cloudflared (solo la prima volta)",
                    color=COLOR_MUTED)
        try:
            self._download(self._bin_path)
        except Exception as e:
            self._set(None, f"download di cloudflared fallito: {e}")
            return None
        return str(self._bin_path)

    def start(self) -> None:
        """Avvia il tunnel se non è già attivo. Non blocca."""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True

    def stop(self) -> None:
        """Ferma il tunnel. Lasciare cloudflared vivo dopo l'uscita terrebbe
        aperto l'indirizzo pubblico verso una porta ormai di nessuno."""
        self._stop.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._set(None, None)

    def _run(self) -> None:
        attesa = RESTART_MIN_SECS
        while not self._stop.is_set():
            percorso = self.binary()
            if percorso is not None:
                if self._run_once(percorso):
                    # Il tunnel era su: l'uscita è un incidente, non un rifiuto
                    # ripetuto, quindi si riparte dall'attesa minima.
                    attesa = RESTART_MIN_SECS
                if self._stop.is_set():
                    break
            log_message(f"Tunnel non attivo: {self.status}", color=COLOR_MUTED)
            # Attesa crescente: se Cloudflare rifiuta (limite dei quick tunnel,
            # rete giù) riprovare a raffica non serve e riempie il log.
            if self._stop.wait(attesa):
                break
            attesa = min(attesa * 2, RESTART_MAX_SECS)

    def _run_once(self, percorso: str) -> bool:
        """Un ciclo di vita di cloudflared. True se il tunnel è arrivato su."""
        self._set(None, "avvio del tunnel…")
        comando = [percorso, "tunnel", "--no-autoupdate",
                   "--url", f"http://127.0.0.1:{self._local_port}"]
        # Senza CREATE_NO_WINDOW, da un .pyw/EXE senza console Windows aprirebbe
        # una finestra nera per cloudflared.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = self._popen(comando, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=flags)
        except OSError as e:
            self._set(None, f"cloudflared non avviabile: {e}")
            return False
        with self._lock:
            self._proc = proc
        if self._stop.is_set():
            proc.terminate()
        su = False
        # Ultimo errore letto: "uscito (codice 1)" da solo non dice nulla, la
        # riga di cloudflared sì ("quick tunnel provisioning failed with
        # status 403" = Cloudflare rifiuta, di solito per troppe richieste).
        ultimo_errore = None
        for riga in proc.stdout:
            ultimo_errore = error_line(riga) or ultimo_errore
            url = parse_tunnel_url(riga)
            if url and url != self.url:
                su = True
                log_message(f"Tunnel attivo: {url}", color=COLOR_OK)
                self._set(url, None)
        codice = proc.wait()
        with self._lock:
            self._proc = None
        if not self._stop.is_set():
            motivo = ultimo_errore or f"cloudflared uscito (codice {codice})"
            log_message(f"Tunnel chiuso: {motivo}", color=COLOR_ERROR)
            self._set(None, motivo)
        return su
