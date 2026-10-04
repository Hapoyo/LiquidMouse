"""Configurazione persistente in %APPDATA%/LiquidMouse/config.json.

Contiene il PIN remoto (in hash per il confronto, e cifrato con DPAPI per
mostrarlo nella GUI e nel QR) e il certificato TLS auto-firmato riusato tra un
avvio e l'altro, con la chiave privata cifrata. In memoria PIN e chiave restano
in chiaro (`pin_plain`, `ssl_key`): solo su disco diventano `pin_secret` e
`ssl_key_secret`. Dove DPAPI manca il file resta come prima.

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
# Campo in chiaro (in memoria) → campo cifrato (su disco).
SECRET_FIELDS = {"pin_plain": "pin_secret", "ssl_key": "ssl_key_secret"}


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

    def __init__(self, path: pathlib.Path | None = None, protector=None) -> None:
        # La migrazione vale solo per il percorso di default: una config con
        # percorso esplicito (i test) non deve andare a leggere %APPDATA%.
        self._migra = path is None
        self.path = path or get_config_path()
        self.data: dict = {}
        self._lock = threading.RLock()
        # Oggetto con protect/unprotect (DPAPI); None = niente cifratura.
        self._protector = protector

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

        migrata = self._decifra_segreti()

        # Genera il PIN solo se la config manca del tutto o è malformata, non
        # se manca la sola chiave: così un upgrade che aggiunge campi non
        # invalida il PIN già stampato sul QR e memorizzato sui telefoni.
        if not loaded or "pin_hash" not in self.data:
            self.set_pin(secrets.token_urlsafe(PIN_BYTES))
        elif migrata:
            # Config scritta prima della cifratura: stesso PIN e stesso
            # certificato (telefoni e browser non si accorgono di nulla), ma ora
            # il file non li contiene più in chiaro.
            self.save()
        return self.data

    def _decifra_segreti(self) -> bool:
        """Porta in chiaro, in memoria, i campi cifrati letti dal file.

        Ritorna True se il file aveva ancora dei segreti in chiaro che con un
        protettore vanno riscritti cifrati. Un segreto che non si decifra
        (config copiata su un altro utente o PC, o senza DPAPI) non fa fallire
        l'avvio: lo si scarta e si rigenera, perché un PIN sbagliato in memoria
        bloccherebbe il proprietario fuori dal proprio PC. PIN scartato →
        anche l'hash, così ne nasce uno nuovo; chiave scartata → anche il
        certificato, che senza la sua chiave non serve.
        """
        da_riscrivere = False
        for chiaro, cifrato in SECRET_FIELDS.items():
            blob = self.data.pop(cifrato, None)
            if blob is not None:
                try:
                    if self._protector is None:
                        raise OSError("cifratura non disponibile su questo sistema")
                    self.data[chiaro] = self._protector.unprotect(blob)
                except Exception as e:
                    self.data.pop(chiaro, None)
                    scartati = (("pin_hash",) if chiaro == "pin_plain"
                                else ("ssl_cert", "ssl_ip"))
                    for k in scartati:
                        self.data.pop(k, None)
                    log_message(f"{chiaro} non decifrabile ({e}): rigenerato",
                                color=COLOR_ERROR)
            elif chiaro in self.data and self._protector is not None:
                da_riscrivere = True
        return da_riscrivere

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
                    json.dump(self._per_il_disco(), f, indent=2)
                os.replace(temporaneo, self.path)
            except Exception as e:
                log_message(f"Errore salvataggio config: {e}", color=COLOR_ERROR)
                try:
                    temporaneo.unlink()
                except OSError:
                    pass

    def _per_il_disco(self) -> dict:
        """Copia di `data` con i segreti cifrati; `data` resta in chiaro."""
        su_disco = dict(self.data)
        if self._protector is None:
            return su_disco
        for chiaro, cifrato in SECRET_FIELDS.items():
            if chiaro not in su_disco:
                continue
            try:
                su_disco[cifrato] = self._protector.protect(su_disco[chiaro])
            except Exception as e:
                # Meglio il file come prima della cifratura che perdere il PIN
                # già sui telefoni.
                log_message(f"Cifratura di {chiaro} non riuscita ({e}): salvato in chiaro",
                            color=COLOR_ERROR)
                continue
            del su_disco[chiaro]
        return su_disco

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value

    def __getitem__(self, key: str):
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data
