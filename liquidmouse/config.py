"""Configurazione persistente in %APPDATA%/LiquidControl/config.json.

Contiene il PIN remoto (in chiaro per mostrarlo nella GUI e nel QR, e in hash
per il confronto) e il certificato TLS auto-firmato riusato tra un avvio e
l'altro.
"""

import json
import os
import pathlib
import secrets

from liquidmouse.events import log_message
from liquidmouse.security.auth import hash_pin
from liquidmouse.theme import COLOR_ERROR

PIN_BYTES = 8  # secrets.token_urlsafe(8) → ~11 caratteri


def get_config_path() -> pathlib.Path:
    appdata = os.environ.get("APPDATA", str(pathlib.Path.home()))
    return pathlib.Path(appdata) / "LiquidControl" / "config.json"


class Config:
    """Config caricata da disco, con salvataggio esplicito.

    Prima era un dizionario globale mutato da più moduli; qui resta un
    dizionario (`data`) ma con un proprietario chiaro, così i test possono
    istanziarne una su una directory temporanea senza toccare %APPDATA%.
    """

    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or get_config_path()
        self.data: dict = {}

    def load(self) -> dict:
        """Carica la config, generando il PIN se assente. Ritorna `self.data`."""
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
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            log_message(f"Errore salvataggio config: {e}", color=COLOR_ERROR)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value

    def __getitem__(self, key: str):
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data
