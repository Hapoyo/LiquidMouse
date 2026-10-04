"""Configurazione persistente in %APPDATA%/LiquidMouse/config.json.

Contiene il PIN remoto (in chiaro per mostrarlo nella GUI e nel QR, e in hash
per il confronto) e il certificato TLS auto-firmato riusato tra un avvio e
l'altro.

Fino alla 2.5.x il programma si chiamava LiquidControl e la config stava in
%APPDATA%/LiquidControl: al primo avvio viene copiata nella cartella nuova
(vedi `migrate_legacy`), così il PIN salvato sui telefoni e il certificato
già accettato restano validi.
"""

import json
import os
import pathlib
import secrets
import shutil
import threading

from liquidmouse.events import log_message
from liquidmouse.security.auth import hash_pin
from liquidmouse.theme import COLOR_ERROR

PIN_BYTES = 8  # secrets.token_urlsafe(8) → ~11 caratteri
APP_DIR = "LiquidMouse"
LEGACY_APP_DIRS = ("LiquidControl",)  # nomi precedenti, dal più recente


def _appdata() -> pathlib.Path:
    return pathlib.Path(os.environ.get("APPDATA", str(pathlib.Path.home())))


def get_config_path() -> pathlib.Path:
    return _appdata() / APP_DIR / "config.json"


def migrate_legacy(path: pathlib.Path, base: pathlib.Path | None = None) -> bool:
    """Copia la config di un nome precedente in `path`, se `path` non esiste.

    Copia e non sposta: tornando a una versione vecchia la config è ancora al
    suo posto. Ritorna True se ha copiato qualcosa. Non solleva.
    """
    if path.exists():
        return False
    base = base if base is not None else _appdata()
    for nome in LEGACY_APP_DIRS:
        vecchio = base / nome / path.name
        if not vecchio.is_file():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vecchio, path)
        except OSError as e:
            log_message(f"Migrazione config da {nome} fallita: {e}", color=COLOR_ERROR)
            return False
        return True
    return False


class Config:
    """Config caricata da disco, con salvataggio esplicito.

    Prima era un dizionario globale mutato da più moduli; qui resta un
    dizionario (`data`) ma con un proprietario chiaro, così i test possono
    istanziarne una su una directory temporanea senza toccare %APPDATA%.
    """

    def __init__(self, path: pathlib.Path | None = None) -> None:
        # La migrazione vale solo per il percorso di default: una config con
        # percorso esplicito (i test) non deve andare a leggere %APPDATA%.
        self._migra = path is None
        self.path = path or get_config_path()
        self.data: dict = {}
        self._lock = threading.RLock()

    def load(self) -> dict:
        """Carica la config, generando il PIN se assente. Ritorna `self.data`."""
        if self._migra:
            migrate_legacy(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        loaded = False
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
                    loaded = True
            except Exception:
                self.data = {}
        else:
            self.data = {}

        # Genera il PIN solo se la config manca del tutto o è malformata, non
        # se manca la sola chiave: così un upgrade che aggiunge campi non
        # invalida il PIN già stampato sul QR e memorizzato sui telefoni.
        if not loaded or "pin_hash" not in self.data:
            self.set_pin(secrets.token_urlsafe(PIN_BYTES))
        return self.data

    def set_pin(self, pin: str) -> None:
        self.data["pin_plain"] = pin
        self.data["pin_hash"] = hash_pin(pin)
        self.save()

    def save(self) -> None:
        """Scrive la config. Non solleva: un errore qui non deve impedire
        l'avvio, il PIN resterebbe comunque valido per questa sessione."""
        # File temporaneo + os.replace: aprire config.json in "w" lo tronca, e
        # un crash a metà lasciava un file vuoto (PIN dei telefoni perso). Il
        # lock evita due save concorrenti (loop e executor) sullo stesso
        # temporaneo e un dict mutato mentre json.dump lo scorre.
        temporaneo = self.path.with_name(self.path.name + ".tmp")
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(temporaneo, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
                os.replace(temporaneo, self.path)
            except Exception as e:
                log_message(f"Errore salvataggio config: {e}", color=COLOR_ERROR)
                try:
                    temporaneo.unlink()
                except OSError:
                    pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value

    def __getitem__(self, key: str):
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data
