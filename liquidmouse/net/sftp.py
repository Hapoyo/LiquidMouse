"""File manager via SFTP: il PC fa da client SSH, il telefono sfoglia.

Il client web non parla mai SSH: chiede al PC (messaggi `sftp_*`), che apre la
connessione con paramiko e gira i risultati. Le credenziali restano sul PC,
salvate nei profili della config con la password cifrata (DPAPI su Windows).

paramiko si importa solo al primo collegamento: il modulo deve restare
importabile dove non c'è (CI Linux, avvio senza la dipendenza) e l'errore va
mostrato al telefono, non far cadere il server.

Tutto qui è bloccante: il chiamante lo esegue in un executor (vedi protocol.py),
perché il dispatch dei messaggi è sequenziale e un elenco lento fermerebbe
mouse e terminale dello stesso client.
"""

import base64
import hashlib
import posixpath
import stat
import sys
import threading
from dataclasses import dataclass

CHUNK = 64 * 1024
CONNECT_TIMEOUT = 10
NAME_MAX = 255
PATH_MAX = 1024
LIST_MAX = 5000
PROFILES_MAX = 20
DEFAULT_PORT = 22


class SftpError(Exception):
    """Errore da mostrare all'utente (testo già in italiano)."""

    def __init__(self, msg: str, code: str = "error") -> None:
        super().__init__(msg)
        self.code = code


# --- validazione: valori dal client, non fidati ------------------------------

def validate_name(name) -> str:
    """Nome di un singolo elemento: niente separatori, niente `.`/`..`.

    Un nome con `/` o `..` uscirebbe dalla cartella che l'utente sta guardando.
    """
    if not isinstance(name, str) or not name or len(name) > NAME_MAX:
        raise SftpError("nome non valido")
    if "\x00" in name or "/" in name or "\\" in name or name in (".", ".."):
        raise SftpError("nome non valido")
    return name


def validate_path(path) -> str:
    """Percorso assoluto in stile SFTP (`/C:/Users/x`), normalizzato."""
    if not isinstance(path, str) or not path or len(path) > PATH_MAX or "\x00" in path:
        raise SftpError("percorso non valido")
    return posixpath.normpath("/" + path.replace("\\", "/").lstrip("/"))


def join_path(folder: str, name: str) -> str:
    return posixpath.join(validate_path(folder), validate_name(name))


# --- password cifrate --------------------------------------------------------

class DpapiProtector:
    """Cifra con la chiave dell'utente Windows (CryptProtectData): il file di
    config copiato su un altro PC o utente non rivela le password."""

    def protect(self, text: str) -> str:
        return base64.b64encode(_dpapi(text.encode("utf-8"), protect=True)).decode("ascii")

    def unprotect(self, blob: str) -> str:
        return _dpapi(base64.b64decode(blob), protect=False).decode("utf-8")


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                      ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise SftpError("cifratura password non riuscita")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def default_protector():
    """DPAPI su Windows; altrove None: meglio rifiutare di salvare una password
    che scriverla in chiaro."""
    return DpapiProtector() if sys.platform == "win32" else None


# --- connessione -------------------------------------------------------------

@dataclass
class SftpSession:
    """Una connessione aperta: `client` è un paramiko.SFTPClient (o un finto)."""
    profile: str
    client: object
    ssh: object = None

    def close(self) -> None:
        for obj in (self.client, self.ssh):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass


def fingerprint(key) -> str:
    """Impronta SHA256 della chiave host, nel formato di OpenSSH."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def paramiko_connector(host: str, port: int, user: str, password: str,
                       known_fp: str | None) -> tuple[SftpSession, str]:
    """Apre SSH+SFTP. Ritorna (sessione, impronta della chiave host).

    L'impronta nota va confrontata prima di mandare la password: con una chiave
    cambiata la password finirebbe a un impostore.
    """
    try:
        import paramiko
    except ImportError as e:
        raise SftpError("manca la libreria paramiko (pip install paramiko)") from e

    seen: dict = {}

    class _Policy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            seen["fp"] = fingerprint(key)
            if known_fp and seen["fp"] != known_fp:
                raise SftpError("la chiave dell'host è cambiata: connessione rifiutata",
                                code="hostkey")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(_Policy())
    try:
        ssh.connect(host, port=port, username=user, password=password,
                    timeout=CONNECT_TIMEOUT, banner_timeout=CONNECT_TIMEOUT,
                    auth_timeout=CONNECT_TIMEOUT, look_for_keys=False,
                    allow_agent=False)
        client = ssh.open_sftp()
    except SftpError:
        ssh.close()
        raise
    except paramiko.AuthenticationException as e:
        ssh.close()
        raise SftpError("utente o password non accettati", code="auth") from e
    except Exception as e:
        ssh.close()
        raise SftpError(f"connessione non riuscita: {e}") from e
    return SftpSession("", client, ssh), seen.get("fp", "")


PARZIALE = ".part"


class _ScritturaAtomica:
    """File remoto scritto su un parziale e rinominato alla chiusura.

    Aprire direttamente il file di destinazione in "wb" lo tronca subito: un
    telefono che perde la connessione a metà upload lasciava un file monco al
    posto dell'originale.
    """

    def __init__(self, client, dest: str, fh) -> None:
        self._client, self._dest, self._fh = client, dest, fh
        self._finito = False

    def write(self, dati: bytes):
        return self._fh.write(dati)

    def close(self) -> None:
        """Chiude il parziale e lo rinomina sul file di destinazione."""
        if self._finito:
            return
        self._finito = True
        parziale = self._dest + PARZIALE
        try:
            self._fh.close()
            # posix_rename sostituisce la destinazione; il rename SFTP v3
            # classico fallirebbe se il file esiste già.
            posix = getattr(self._client, "posix_rename", None)
            if posix is not None:
                posix(parziale, self._dest)
            else:
                if SftpManager._exists(self._client, self._dest):
                    self._client.remove(self._dest)
                self._client.rename(parziale, self._dest)
        except (OSError, IOError):
            self._rimuovi(parziale)
            raise

    def abort(self) -> None:
        """Scarta il parziale. Idempotente, non solleva."""
        if self._finito:
            return
        self._finito = True
        try:
            self._fh.close()
        except (OSError, IOError):
            pass
        self._rimuovi(self._dest + PARZIALE)

    def _rimuovi(self, parziale: str) -> None:
        try:
            self._client.remove(parziale)
        except (OSError, IOError, KeyError):
            pass


class SftpManager:
    """Profili (nella config) e connessioni aperte, una per client.

    `connector` e `protector` arrivano dal costruttore per poterli sostituire
    nei test: niente rete né Windows.
    """

    def __init__(self, config, connector=paramiko_connector, protector=None) -> None:
        self.config = config
        self.connector = connector
        self.protector = protector
        self._sessions: dict[int, SftpSession] = {}
        self._lock = threading.Lock()

    # --- profili ----------------------------------------------------------

    def _profiles(self) -> list[dict]:
        profili = self.config.get("sftp_profiles", [])
        return profili if isinstance(profili, list) else []

    def list_profiles(self) -> list[dict]:
        """Vista pubblica: mai il segreto né l'impronta."""
        return [{"name": p["name"], "host": p["host"], "port": p["port"],
                 "user": p["user"], "has_password": bool(p.get("secret"))}
                for p in self._profiles()]

    def _find(self, name: str) -> dict:
        for p in self._profiles():
            if p["name"] == name:
                return p
        raise SftpError("profilo inesistente")

    def save_profile(self, name, host, port, user, password) -> None:
        """Crea o aggiorna un profilo. Password vuota = tiene quella salvata, ma
        solo se host, porta e utente non cambiano."""
        if not all(isinstance(v, str) and v.strip() and len(v) <= NAME_MAX
                   for v in (name, host, user)):
            raise SftpError("nome, host e utente sono obbligatori")
        if not isinstance(password, str) or len(password) > NAME_MAX:
            raise SftpError("password non valida")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise SftpError("porta non valida")
        name, host, user = name.strip(), host.strip(), user.strip()
        profili = self._profiles()
        esistente = next((p for p in profili if p["name"] == name), None)
        if esistente is None and len(profili) >= PROFILES_MAX:
            raise SftpError("troppi profili")
        secret = esistente.get("secret", "") if esistente else ""
        stessa_destinazione = bool(esistente) and (
            esistente["host"], esistente["port"], esistente["user"]) == (host, port, user)
        if not stessa_destinazione:
            # Il segreto salvato vale solo per la destinazione per cui è stato
            # inserito: cambiando host, porta o utente senza dare una password
            # nuova, la vecchia verrebbe inviata a un server scelto da chi
            # modifica il profilo. Va reinserita.
            secret = ""
        if password:
            if self.protector is None:
                raise SftpError("cifratura password non disponibile su questo sistema")
            secret = self.protector.protect(password)
        nuovo = {"name": name, "host": host, "port": port, "user": user, "secret": secret}
        # Cambiando host o porta l'impronta vecchia non vale più: la prima
        # connessione al nuovo indirizzo ne registra una nuova.
        if esistente and esistente["host"] == host and esistente["port"] == port:
            nuovo["hostkey"] = esistente.get("hostkey", "")
        self.config["sftp_profiles"] = [p for p in profili if p["name"] != name] + [nuovo]
        self.config.save()

    def delete_profile(self, name) -> None:
        self.config["sftp_profiles"] = [p for p in self._profiles() if p["name"] != name]
        self.config.save()

    # --- connessioni ------------------------------------------------------

    def connect(self, owner: int, name: str) -> str:
        """Apre la connessione del client `owner`. Ritorna la cartella iniziale."""
        profilo = self._find(name)
        password = ""
        if profilo.get("secret"):
            if self.protector is None:
                raise SftpError("cifratura password non disponibile su questo sistema")
            password = self.protector.unprotect(profilo["secret"])
        self.close_owner(owner)
        sessione, fp = self.connector(profilo["host"], profilo["port"], profilo["user"],
                                      password, profilo.get("hostkey") or None)
        sessione.profile = name
        if fp and not profilo.get("hostkey"):
            # Prima connessione: si fida dell'impronta vista (TOFU, come ssh).
            profilo["hostkey"] = fp
            self.config.save()
        with self._lock:
            self._sessions[owner] = sessione
        try:
            return sessione.client.normalize(".")
        except Exception:
            return "/"

    def _get(self, owner: int) -> SftpSession:
        with self._lock:
            sessione = self._sessions.get(owner)
        if sessione is None:
            raise SftpError("non collegato", code="disconnected")
        return sessione

    def close_owner(self, owner: int) -> None:
        with self._lock:
            sessione = self._sessions.pop(owner, None)
        if sessione is not None:
            sessione.close()

    def close_all(self) -> None:
        with self._lock:
            sessioni, self._sessions = list(self._sessions.values()), {}
        for s in sessioni:
            s.close()

    # --- operazioni -------------------------------------------------------

    def list_dir(self, owner: int, path: str) -> dict:
        path = validate_path(path)
        client = self._get(owner).client
        try:
            attrs = client.listdir_attr(path)
        except (OSError, IOError) as e:
            raise SftpError(f"impossibile leggere la cartella: {e}") from e
        voci = []
        for a in attrs[:LIST_MAX]:
            mode = a.st_mode or 0
            is_dir = stat.S_ISDIR(mode)
            if stat.S_ISLNK(mode):
                # Un link a cartella va mostrato come cartella, altrimenti non
                # si può entrare.
                try:
                    is_dir = stat.S_ISDIR(client.stat(posixpath.join(path, a.filename)).st_mode or 0)
                except (OSError, IOError):
                    pass
            voci.append({"name": a.filename, "dir": is_dir,
                         "size": 0 if is_dir else int(a.st_size or 0),
                         "mtime": int(a.st_mtime or 0)})
        voci.sort(key=lambda v: (not v["dir"], v["name"].lower()))
        return {"path": path, "entries": voci, "truncated": len(attrs) > LIST_MAX}

    def mkdir(self, owner: int, folder: str, name: str) -> None:
        self._op(owner, "mkdir", join_path(folder, name))

    def rename(self, owner: int, folder: str, old: str, new: str) -> None:
        client = self._get(owner).client
        dest = join_path(folder, new)
        if self._exists(client, dest):
            raise SftpError("esiste già un elemento con quel nome", code="exists")
        self._op(owner, "rename", join_path(folder, old), dest)

    def delete(self, owner: int, folder: str, name: str, is_dir: bool) -> None:
        self._op(owner, "rmdir" if is_dir else "remove", join_path(folder, name))

    def _op(self, owner: int, op: str, *args) -> None:
        try:
            getattr(self._get(owner).client, op)(*args)
        except (OSError, IOError) as e:
            raise SftpError(f"operazione non riuscita: {e}") from e

    @staticmethod
    def _exists(client, path: str) -> bool:
        try:
            client.stat(path)
            return True
        except (OSError, IOError):
            return False

    def file_size(self, owner: int, path: str) -> int:
        """Dimensione di un file (errore se è una cartella): serve a rifiutare
        subito i download troppo grandi per la strada remota."""
        client = self._get(owner).client
        try:
            attr = client.stat(validate_path(path))
        except (OSError, IOError) as e:
            raise SftpError(f"file non leggibile: {e}") from e
        if stat.S_ISDIR(attr.st_mode or 0):
            raise SftpError("è una cartella")
        return int(attr.st_size or 0)

    def exists(self, owner: int, path: str) -> bool:
        return self._exists(self._get(owner).client, validate_path(path))

    def open_read(self, owner: int, path: str):
        """File remoto aperto in lettura, con la sua dimensione."""
        size = self.file_size(owner, path)
        try:
            return self._get(owner).client.open(validate_path(path), "rb"), size
        except (OSError, IOError) as e:
            raise SftpError(f"file non leggibile: {e}") from e

    def open_write(self, owner: int, path: str):
        """File in scrittura: i dati vanno su `nome.part` e solo `close()` li
        sostituisce al file vero; `abort()` scarta il parziale."""
        client = self._get(owner).client
        dest = validate_path(path)
        try:
            return _ScritturaAtomica(client, dest, client.open(dest + PARZIALE, "wb"))
        except (OSError, IOError) as e:
            raise SftpError(f"file non scrivibile: {e}") from e
