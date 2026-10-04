"""CloudflareTunnel: individuazione di cloudflared, lettura dell'indirizzo e
ciclo di vita del processo, senza rete né processi reali."""

import hashlib
import io
import json
import threading

import pytest

from liquidmouse.net.tunnel import (
    CLOUDFLARED_ASSET,
    CLOUDFLARED_EXE,
    MIN_BINARY_BYTES,
    CloudflareTunnel,
    download_cloudflared,
    fetch_release_asset,
    parse_tunnel_url,
)


class TestParseTunnelUrl:
    def test_riga_con_l_indirizzo(self):
        riga = "2026-09-27T16:00:00Z INF |  https://bright-cat-river-moon.trycloudflare.com  |"
        assert parse_tunnel_url(riga) == "https://bright-cat-river-moon.trycloudflare.com"

    def test_ignora_l_api_nei_messaggi_d_errore(self):
        # cloudflared nomina api.trycloudflare.com quando la richiesta del
        # quick tunnel fallisce: non è l'indirizzo del tunnel.
        riga = 'ERR failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel"'
        assert parse_tunnel_url(riga) is None

    def test_riga_qualsiasi(self):
        assert parse_tunnel_url("INF Starting tunnel") is None


class _FakeProc:
    """Processo finto: emette `righe`, poi resta vivo finché non è terminato
    (se `blocca`) ed esce con `codice`."""

    def __init__(self, righe, codice=0, blocca=False):
        self._righe = list(righe)
        self._codice = codice
        self._fine = threading.Event()
        if not blocca:
            self._fine.set()
        self.terminato = False
        self.stdout = self._leggi()

    def _leggi(self):
        yield from self._righe
        self._fine.wait(5)

    def terminate(self):
        self.terminato = True
        self._fine.set()

    def wait(self):
        self._fine.wait(5)
        return self._codice


def _tunnel(tmp_path, *, which=None, can_download=True, download=None, popen=None):
    return CloudflareTunnel(
        8767, tmp_path,
        popen=popen or (lambda *a, **k: _FakeProc([])),
        download=download or (lambda dest: dest.write_bytes(b"x")),
        which=which or (lambda nome: None),
        can_download=can_download,
    )


class TestBinario:
    def test_preferisce_quello_nel_path(self, tmp_path):
        t = _tunnel(tmp_path, which=lambda nome: "/usr/bin/cloudflared")
        assert t.binary() == "/usr/bin/cloudflared"

    def test_usa_quello_gia_scaricato(self, tmp_path):
        (tmp_path / CLOUDFLARED_EXE).write_bytes(b"x")
        scaricati = []
        t = _tunnel(tmp_path, download=scaricati.append)
        assert t.binary() == str(tmp_path / CLOUDFLARED_EXE)
        assert scaricati == []

    def test_scarica_se_manca(self, tmp_path):
        t = _tunnel(tmp_path)
        assert t.binary() == str(tmp_path / CLOUDFLARED_EXE)
        assert (tmp_path / CLOUDFLARED_EXE).is_file()

    def test_download_fallito_lo_dice(self, tmp_path):
        def rotto(dest):
            raise OSError("rete assente")
        t = _tunnel(tmp_path, download=rotto)
        assert t.binary() is None
        assert "rete assente" in t.status

    def test_fuori_da_windows_non_scarica(self, tmp_path):
        t = _tunnel(tmp_path, can_download=False)
        assert t.binary() is None
        assert "non trovato" in t.status


class TestProcesso:
    def test_comando_verso_la_porta_locale(self, tmp_path):
        chiamate = []

        def popen(cmd, **kw):
            chiamate.append((cmd, kw))
            return _FakeProc([])

        t = _tunnel(tmp_path, popen=popen)
        t._run_once("cloudflared")
        cmd, kw = chiamate[0]
        assert cmd[:2] == ["cloudflared", "tunnel"]
        assert "--no-autoupdate" in cmd
        assert cmd[cmd.index("--url") + 1] == "http://127.0.0.1:8767"

    def test_legge_l_indirizzo_e_avvisa(self, tmp_path):
        avvisi = []
        proc = _FakeProc(["INF Requesting new quick Tunnel\n",
                          "INF |  https://a-b-c.trycloudflare.com  |\n"], blocca=True)
        t = _tunnel(tmp_path, popen=lambda *a, **k: proc)
        t.on_change = lambda: avvisi.append((t.url, t.status))
        th = threading.Thread(target=t._run_once, args=("cloudflared",))
        th.start()
        for _ in range(100):
            if t.url:
                break
            threading.Event().wait(0.01)
        assert t.url == "https://a-b-c.trycloudflare.com"
        assert t.status is None
        assert ("https://a-b-c.trycloudflare.com", None) in avvisi
        t.stop()
        th.join(5)
        assert proc.terminato
        assert t.url is None

    def test_uscita_inattesa_azzera_l_indirizzo(self, tmp_path):
        proc = _FakeProc(["INF |  https://a-b-c.trycloudflare.com  |\n"], codice=1)
        t = _tunnel(tmp_path, popen=lambda *a, **k: proc)
        assert t._run_once("cloudflared") is True
        assert t.url is None
        assert "codice 1" in t.status

    def test_l_errore_di_cloudflared_diventa_il_motivo(self, tmp_path):
        # Output reale di cloudflared quando Cloudflare rifiuta il quick tunnel.
        proc = _FakeProc([
            "2026-09-27T16:29:26Z INF Requesting new quick Tunnel on trycloudflare.com...\n",
            "quick tunnel provisioning failed with status 403\n",
        ], codice=1)
        t = _tunnel(tmp_path, popen=lambda *a, **k: proc)
        assert t._run_once("cloudflared") is False
        assert t.status == "quick tunnel provisioning failed with status 403"

    def test_popen_fallito(self, tmp_path):
        def popen(*a, **k):
            raise OSError("accesso negato")
        t = _tunnel(tmp_path, popen=popen)
        assert t._run_once("cloudflared") is False
        assert "accesso negato" in t.status


def test_start_e_stop(tmp_path):
    proc = _FakeProc(["INF |  https://a-b-c.trycloudflare.com  |\n"], blocca=True)
    t = _tunnel(tmp_path, which=lambda n: "cloudflared", popen=lambda *a, **k: proc)
    t.start()
    for _ in range(200):
        if t.url:
            break
        threading.Event().wait(0.01)
    assert t.running
    assert t.url == "https://a-b-c.trycloudflare.com"
    t.stop()
    t._thread.join(5)
    assert not t.running
    assert proc.terminato


class _Risposta:
    """Corpo HTTP finto, usabile come context manager e da copyfileobj."""

    def __init__(self, dati: bytes):
        self._io = io.BytesIO(dati)

    def read(self, n=-1):
        return self._io.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestDownloadVerificato:
    """cloudflared parte con i permessi dell'utente: va controllato contro lo
    SHA-256 pubblicato dalla release prima di metterlo dove verrà lanciato."""

    DATI = b"MZ" + b"x" * (MIN_BINARY_BYTES + 10)

    def _scarica(self, tmp_path, sha, dati=None):
        dati = self.DATI if dati is None else dati
        dest = tmp_path / "bin" / CLOUDFLARED_EXE
        download_cloudflared(
            dest, fetch_asset=lambda: ("https://example/x.exe", sha),
            opener=lambda url, timeout: _Risposta(dati))
        return dest

    def test_hash_corretto_installa(self, tmp_path):
        dest = self._scarica(tmp_path, hashlib.sha256(self.DATI).hexdigest())
        assert dest.read_bytes() == self.DATI
        assert not dest.with_name(dest.name + ".part").exists()

    def test_hash_diverso_non_installa(self, tmp_path):
        with pytest.raises(OSError, match="SHA-256"):
            self._scarica(tmp_path, "0" * 64)
        assert not (tmp_path / "bin" / CLOUDFLARED_EXE).exists()
        assert not (tmp_path / "bin" / (CLOUDFLARED_EXE + ".part")).exists()

    def test_hash_diverso_non_sostituisce_il_file_esistente(self, tmp_path):
        dest = tmp_path / "bin" / CLOUDFLARED_EXE
        dest.parent.mkdir()
        dest.write_bytes(b"vecchio")
        with pytest.raises(OSError):
            self._scarica(tmp_path, "0" * 64)
        assert dest.read_bytes() == b"vecchio"

    def test_maiuscole_nell_hash_sono_ammesse(self, tmp_path):
        self._scarica(tmp_path, hashlib.sha256(self.DATI).hexdigest().upper())

    def test_troppo_piccolo(self, tmp_path):
        piccolo = b"<html>403</html>"
        with pytest.raises(OSError, match="incompleto"):
            self._scarica(tmp_path, hashlib.sha256(piccolo).hexdigest(), piccolo)


class TestAssetDellaRelease:
    def _release(self, assets):
        corpo = json.dumps({"tag_name": "2026.9.3", "assets": assets}).encode()
        return lambda url, timeout: _Risposta(corpo)

    def test_legge_url_e_digest(self):
        sha = "ab" * 32
        url, atteso = fetch_release_asset(opener=self._release([
            {"name": "cloudflared-windows-amd64.msi", "digest": "sha256:" + "11" * 32,
             "browser_download_url": "https://x/msi"},
            {"name": CLOUDFLARED_ASSET, "digest": "sha256:" + sha,
             "browser_download_url": "https://x/exe"},
        ]))
        assert (url, atteso) == ("https://x/exe", sha)

    def test_senza_digest_rifiuta(self):
        with pytest.raises(OSError, match="SHA-256"):
            fetch_release_asset(opener=self._release([
                {"name": CLOUDFLARED_ASSET, "digest": None,
                 "browser_download_url": "https://x/exe"}]))

    def test_asset_assente(self):
        with pytest.raises(OSError, match="non trovato"):
            fetch_release_asset(opener=self._release([]))

    def test_url_non_https_rifiutato(self):
        with pytest.raises(OSError):
            fetch_release_asset(opener=self._release([
                {"name": CLOUDFLARED_ASSET, "digest": "sha256:" + "ab" * 32,
                 "browser_download_url": "http://x/exe"}]))


class TestPrecedenzaBinario:
    def test_il_file_in_appdata_batte_il_path(self, tmp_path):
        # Un cloudflared nel PATH puo' essere sostituito da chiunque scriva in
        # quella cartella; quello in %APPDATA% e' stato verificato da noi.
        (tmp_path / CLOUDFLARED_EXE).write_bytes(b"x")
        t = _tunnel(tmp_path, which=lambda nome: "/usr/bin/cloudflared")
        assert t.binary() == str(tmp_path / CLOUDFLARED_EXE)
