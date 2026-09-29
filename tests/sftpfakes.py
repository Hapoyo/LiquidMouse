"""Doppi per i test del file manager: un host SFTP in memoria, senza rete né paramiko."""

import io
import posixpath
import stat
from types import SimpleNamespace

from liquidmouse.net.sftp import SftpSession


class FakeFile(io.BytesIO):
    """File che, se aperto in scrittura, salva il contenuto alla chiusura."""

    def __init__(self, fs, path, data=b"", write=False):
        super().__init__(data)
        self._fs, self._path, self._write = fs, path, write

    def close(self):
        if self._write and not self.closed:
            self._fs.files[self._path] = self.getvalue()
        super().close()


class FakeSftpClient:
    def __init__(self):
        self.dirs = {"/", "/home"}
        self.files = {"/home/a.txt": b"ciao"}
        self.closed = False

    def normalize(self, p):
        return "/home"

    def _attr(self, path, is_dir):
        size = 0 if is_dir else len(self.files[path])
        mode = stat.S_IFDIR | 0o755 if is_dir else stat.S_IFREG | 0o644
        return SimpleNamespace(filename=posixpath.basename(path), st_mode=mode,
                               st_size=size, st_mtime=1700000000)

    def listdir_attr(self, path):
        if path not in self.dirs:
            raise FileNotFoundError(path)
        out = []
        for d in self.dirs:
            if d != path and posixpath.dirname(d) == path:
                out.append(self._attr(d, True))
        for f in self.files:
            if posixpath.dirname(f) == path:
                out.append(self._attr(f, False))
        return out

    def stat(self, path):
        if path in self.dirs:
            return self._attr(path, True)
        if path in self.files:
            return self._attr(path, False)
        raise FileNotFoundError(path)

    def mkdir(self, path):
        self.dirs.add(path)

    def rmdir(self, path):
        self.dirs.discard(path)

    def remove(self, path):
        del self.files[path]

    def rename(self, old, new):
        if old in self.files:
            self.files[new] = self.files.pop(old)
        else:
            self.dirs.discard(old)
            self.dirs.add(new)

    def open(self, path, mode):
        if "w" in mode:
            return FakeFile(self, path, write=True)
        if path not in self.files:
            raise FileNotFoundError(path)
        return FakeFile(self, path, self.files[path])

    def close(self):
        self.closed = True


class FakeProtector:
    def protect(self, text):
        return "enc:" + text[::-1]

    def unprotect(self, blob):
        return blob[4:][::-1]


class FakeConfig:
    def __init__(self):
        self.data = {}
        self.saves = 0

    def get(self, k, d=None):
        return self.data.get(k, d)

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        self.saves += 1


def make_connector(client, fp="SHA256:abc", log=None):
    """Connettore finto: registra i parametri e rifiuta un'impronta cambiata."""
    def connector(host, port, user, password, known_fp):
        from liquidmouse.net.sftp import SftpError
        if log is not None:
            log.append((host, port, user, password, known_fp))
        if known_fp and known_fp != fp:
            raise SftpError("la chiave dell'host è cambiata", code="hostkey")
        return SftpSession("", client), fp
    return connector
