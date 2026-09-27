"""Anteprime del README: schermate, GIF e copertina, generate dal codice.

    xvfb-run -s "-screen 0 1920x1080x24 -dpi 192" python tools/anteprime.py

Due sorgenti, entrambe con dati dimostrativi e senza Windows:
  - client: la pagina vera (static/, servita dalla stessa whitelist del server)
    in Chromium a 390 px, con un WebSocket finto che risponde come il PC.
    L'orologio della pagina è finto anch'esso (page.clock): ogni fotogramma
    della GIF cade allo stesso istante a ogni esecuzione, non a caso;
  - finestra: la finestra Tk vera (gui/window.py) sotto Xvfb, con servizi di
    rete finti; pystray e i font privati di Windows sono sostituiti.

Servono playwright, Pillow, qrcode e tkinter. `--solo client|finestra` rifà una
parte sola; copertina e social preview si ricompongono dalle PNG già presenti.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from liquidmouse.net.static import StaticFiles  # noqa: E402
from liquidmouse.theme import (  # noqa: E402
    COLOR_AMBER, COLOR_BG, COLOR_CREAM, COLOR_LINE, COLOR_ORANGE, COLOR_PANEL,
    COLOR_TAN,
)
from liquidmouse.version import CODENAME, VERSION  # noqa: E402

OUT = ROOT / "docs" / "img"
FONTS = ROOT / "static" / "fonts"
TELEFONO = {"width": 390, "height": 844}
# Il Chromium di Playwright preinstallato nell'ambiente di sviluppo; altrove
# (None) Playwright usa il suo.
CHROMIUM = os.environ.get("LM_CHROMIUM") or next(
    (str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)


# --- CLIENT ------------------------------------------------------------------

# Il PC finto: risponde ai messaggi che app.js manda davvero (protocol.py), e
# l'output del terminale arriva in frame binari come da net/frames.py.
FAKE_WS = r"""
(() => {
  const ora = () => Date.now() / 1000;
  const SESSIONI = [
    { id: '7f3a', cmd: 'cmd.exe', alive: true, created_at: ora() - 14 * 60, viewers: 1 },
    { id: 'c21d', cmd: 'claude',  alive: true, created_at: ora() - 52 * 60, viewers: 0 },
  ];
  window.__lm = { inviati: [], ws: null };
  class FakeWS {
    constructor(url) {
      this.url = url; this.readyState = 0; this.binaryType = 'blob';
      window.__lm.ws = this;
      setTimeout(() => { this.readyState = 1; this.onopen && this.onopen({}); }, 180);
    }
    _json(obj, ritardo) {
      setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify(obj) }), ritardo || 20);
    }
    frame(id, testo) {
      const p = new TextEncoder().encode(testo);
      const b = new Uint8Array(2 + id.length + p.length);
      b[0] = 0x01; b[1] = id.length;
      for (let i = 0; i < id.length; i++) b[2 + i] = id.charCodeAt(i);
      b.set(p, 2 + id.length);
      this.onmessage && this.onmessage({ data: b.buffer });
    }
    send(s) {
      let m; try { m = JSON.parse(s); } catch (_) { return; }
      window.__lm.inviati.push(m);
      if (m.type === 'auth') this._json({ type: 'auth_ok' });
      else if (m.type === 'ping') this._json({ type: 'pong' }, 12);
      else if (m.type === 'term_list') this._json({ type: 'term_sessions', sessions: SESSIONI });
      else if (m.type === 'term_create') this._json({ type: 'term_created', id: '9b04' });
      else if (m.type === 'term_attach') setTimeout(() => this.frame(m.id, window.__lmSchermo || ''), 30);
    }
    close() { this.readyState = 3; }
  }
  FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
  window.WebSocket = FakeWS;
  window.__lmSchermo =
    'Microsoft Windows [Version 10.0.26100.4652]\r\n' +
    '(c) Microsoft Corporation. All rights reserved.\r\n\r\n' +
    'C:\\Users\\hapoyo\\projects\\site>';
})();
"""

# Dito finto: un cerchio che segue i gesti simulati, solo nelle anteprime.
DITO_CSS = """
#lm-dito { position: fixed; width: 44px; height: 44px; margin: -22px 0 0 -22px;
  border-radius: 50%; background: rgba(238,228,205,.28); border: 2px solid rgba(238,228,205,.75);
  pointer-events: none; z-index: 5000; display: none; }
#lm-dito.tap { background: rgba(242,187,91,.55); border-color: #f2bb5b; }
"""

GIT_LOG = (
    "\x1b[33m4e1c2a9\x1b[m \x1b[33m(\x1b[1;36mHEAD -> \x1b[1;32mmain\x1b[33m)\x1b[m aggiorna la pagina contatti\r\n"
    "\x1b[33m9d0b7f1\x1b[m corregge il menu su mobile\r\n"
    "\x1b[33m27aa3c4\x1b[m aggiunge la galleria\r\n"
    "\x1b[33mb81e5d0\x1b[m prima versione\r\n\r\n"
    "C:\\Users\\hapoyo\\projects\\site>"
)


class Client:
    """Pagina del telefono in Chromium, con PC e orologio finti."""

    def __init__(self, pw) -> None:
        self.static = StaticFiles(str(ROOT))
        mancanti = self.static.load()
        if mancanti:
            raise SystemExit(f"asset mancanti: {mancanti}")
        self.browser = pw.chromium.launch(executable_path=CHROMIUM)

    def pagina(self, scala: float = 2, url: str = "http://192.168.1.20:8000/"):
        ctx = self.browser.new_context(
            viewport=TELEFONO, device_scale_factor=scala, is_mobile=True,
            has_touch=True, locale="it-IT")
        page = ctx.new_page()
        page.clock.install(time=time.mktime((2026, 9, 27, 18, 30, 0, 0, 0, -1)))
        page.add_init_script(FAKE_WS)
        page.route("**/*", self._servi)
        page.goto(url)
        page.add_style_tag(content=DITO_CSS)
        page.evaluate("document.body.insertAdjacentHTML('beforeend', '<div id=lm-dito></div>')")
        return page

    def _servi(self, route) -> None:
        from urllib.parse import urlparse
        asset = self.static.get(urlparse(route.request.url).path)
        if asset is None:
            route.fulfill(status=404, body="")
        else:
            route.fulfill(status=200, body=asset.body,
                          headers={"Content-Type": asset.content_type})

    @staticmethod
    def avvia(page, attesa_ms: int = 5400) -> None:
        """Connessione e primo ping: la riga di stato arriva a "connesso 12ms"."""
        page.clock.run_for(attesa_ms)

    def chiudi(self) -> None:
        self.browser.close()


def _assesta(page) -> None:
    """Attende le transizioni CSS: vanno in tempo reale, non con page.clock."""
    page.wait_for_timeout(450)


def _dito(page, x=None, y=None, tap=False) -> None:
    if x is None:
        page.evaluate("document.getElementById('lm-dito').style.display='none'")
        return
    page.evaluate(
        "([x, y, t]) => { const d = document.getElementById('lm-dito');"
        " d.style.display='block'; d.style.left=x+'px'; d.style.top=y+'px';"
        " d.classList.toggle('tap', t); }", [x, y, tap])


def _terminale(page, sid: str, cmd: str) -> None:
    page.evaluate(
        "([sid, cmd]) => { termSessionId = sid; termSessionCmd = cmd; attachSession(sid); }",
        [sid, cmd])


def schermate_client(client: Client) -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    page = client.pagina()
    client.avvia(page)
    page.screenshot(path=OUT / "client-touchpad.png")

    page.evaluate("updateTextDisplay('ciao dal telefono')")
    page.clock.run_for(300)
    _assesta(page)
    page.screenshot(path=OUT / "client-testo.png")
    page.clock.run_for(3000)

    page.click("#btn-menu")
    page.evaluate("document.getElementById('btn-drag').classList.add('lock-active');"
                  "document.getElementById('btn-menu').classList.add('lock-active')")
    page.clock.run_for(300)
    _assesta(page)
    page.screenshot(path=OUT / "client-menu.png")
    page.evaluate("document.getElementById('btn-drag').classList.remove('lock-active');"
                  "document.getElementById('btn-menu').classList.remove('lock-active');"
                  "closeMenu()")

    page.click("#tab-terminal")
    page.clock.run_for(300)
    _assesta(page)
    page.screenshot(path=OUT / "client-sessioni.png")

    _terminale(page, "7f3a", "cmd.exe")
    page.clock.run_for(400)
    page.evaluate("t => __lm.ws.frame('7f3a', t)", "git log --oneline -4\r\n" + GIT_LOG)
    page.clock.run_for(400)
    _assesta(page)
    page.screenshot(path=OUT / "client-terminale.png")
    page.context.close()

    # Primo accesso remoto: pagina via HTTPS e PIN sbagliato.
    page = client.pagina(url="https://93.41.207.18:8443/")
    page.clock.run_for(1000)
    page.evaluate("() => { stopWithError('pin errato (4 tentativi rimasti)');"
                  " document.getElementById('pinInput').value = 'Vq7x-M2'; }")
    page.clock.run_for(300)
    _assesta(page)
    page.screenshot(path=OUT / "client-pin.png")
    page.context.close()


def gif_client(client: Client) -> list[tuple[Image.Image, int]]:
    """Fotogrammi (immagine, durata ms) della GIF: touchpad, testo, menu, terminale."""
    import io
    fotogrammi: list[tuple[Image.Image, int]] = []
    page = client.pagina(scala=1)

    def scatta(ms: int) -> None:
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        fotogrammi.append((img, ms))
        page.clock.run_for(ms)

    # connessione
    for _ in range(4):
        scatta(120)
    page.clock.run_for(5000 - 480)
    scatta(500)

    # il dito disegna una curva sul touchpad, poi tocca
    import math
    for i in range(16):
        t = i / 15
        x = 110 + 170 * t
        y = 520 - 190 * math.sin(t * math.pi) + 40 * t
        _dito(page, x, y)
        scatta(70)
    _dito(page, 280, 560, tap=True)
    scatta(220)
    _dito(page)
    scatta(300)

    # testo dalla tastiera del telefono
    frase = "ciao dal telefono"
    for i in range(1, len(frase) + 1):
        page.evaluate("c => updateTextDisplay(c)", frase[i - 1])
        if i == 1:
            _assesta(page)
        scatta(70 if i < len(frase) else 900)

    # menu rapido
    page.clock.run_for(3000)
    page.click("#btn-menu")
    _assesta(page)
    scatta(1300)
    page.evaluate("closeMenu()")

    # terminale: elenco, poi la sessione con un comando
    page.click("#tab-terminal")
    _assesta(page)
    scatta(1100)
    _terminale(page, "7f3a", "cmd.exe")
    page.clock.run_for(400)
    _assesta(page)
    scatta(500)
    cmd = "git log --oneline -4"
    for ch in cmd:
        page.evaluate("t => __lm.ws.frame('7f3a', t)", ch)
        page.clock.run_for(20)
        scatta(60)
    page.evaluate("t => __lm.ws.frame('7f3a', t)", "\r\n" + GIT_LOG)
    page.clock.run_for(40)
    scatta(2600)
    page.context.close()
    return fotogrammi


def salva_gif(fotogrammi, percorso: Path, larghezza: int | None = None) -> None:
    # Palette unica per tutta la GIF: stessi colori in ogni fotogramma, niente
    # sfarfallio fra un quantizzatore e l'altro.
    immagini = [f for f, _ in fotogrammi]
    if larghezza:
        alt = round(immagini[0].height * larghezza / immagini[0].width)
        immagini = [im.resize((larghezza, alt), Image.LANCZOS) for im in immagini]
    campione = Image.new("RGB", (immagini[0].width, immagini[0].height * 3))
    for i, idx in enumerate((0, len(immagini) // 2, len(immagini) - 1)):
        campione.paste(immagini[idx], (0, immagini[0].height * i))
    palette = campione.quantize(colors=96, method=Image.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.NONE) for im in immagini]
    frames[0].save(percorso, save_all=True, append_images=frames[1:],
                   duration=[ms for _, ms in fotogrammi], loop=0, optimize=True,
                   disposal=1)


# --- FINESTRA ------------------------------------------------------------------

class _ServiziFinti:
    def __init__(self, modo: str) -> None:
        self.remote_mode = modo
        self.external_ip = "93.41.207.18"
        self.external_port = 8443
        self.tunnel_url = "https://quiet-harbor-lemon-seven.trycloudflare.com"
        self.remote_problem = "cgnat dell'operatore"


class _SessioniFinte:
    def list_sessions(self):
        ora = time.time()
        return [
            {"id": "7f3a", "cmd": "cmd.exe", "alive": True, "created_at": ora - 14 * 60, "viewers": 1},
            {"id": "c21d", "cmd": "claude", "alive": True, "created_at": ora - 52 * 60, "viewers": 0},
            {"id": "e90b", "cmd": "powershell.exe", "alive": False, "created_at": ora - 95 * 60, "viewers": 0},
        ]


def _installa_font() -> None:
    """Space Grotesk e Space Mono visibili a Tk (fontconfig dell'utente)."""
    dest = Path.home() / ".local" / "share" / "fonts" / "liquidmouse"
    dest.mkdir(parents=True, exist_ok=True)
    for f in FONTS.glob("*.ttf"):
        shutil.copy2(f, dest / f.name)
    subprocess.run(["fc-cache", "-f", str(dest)], check=False, capture_output=True)


def _cattura(widget) -> Image.Image:
    from PIL import ImageGrab
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    return ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY"))


def schermate_finestra() -> None:
    _installa_font()
    # pystray su Linux vuole un backend grafico: la tray non serve alle anteprime.
    sys.modules.setdefault("pystray", types.SimpleNamespace(Icon=None, Menu=None, MenuItem=None))
    from liquidmouse.gui import window

    def disegna(modo: str):
        servizi = _ServiziFinti(modo)
        deps = window.GuiDeps(
            config={"pin_plain": "Vq7x-M2kTfA"}, sessions=_SessioniFinte(),
            services=lambda: servizi, local_ip="192.168.1.20",
            reset_trusted=lambda: None)
        root = window.build(deps)
        root.geometry("+40+40")
        # Animazione di avvio e dissolvenza finite prima dello scatto.
        fine = time.time() + 3.5
        while time.time() < fine:
            root.update()
            time.sleep(0.01)
        window.update_remote_ui()
        window.gui_log_sink("Telefono connesso: 192.168.1.34", color=COLOR_AMBER)
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        return root

    root = disegna("upnp")
    _cattura(root).save(OUT / "finestra-upnp.png")
    window._open_sessions_panel()
    for _ in range(20):
        root.update()
        time.sleep(0.02)
    win = window._sessions_win
    win.geometry("+60+60")
    for _ in range(20):
        root.update()
        time.sleep(0.02)
    _cattura(win).save(OUT / "finestra-sessioni.png")
    # Il pannello sessioni si riprogramma ogni 2 s: senza annullarlo Tk
    # segnalerebbe il callback orfano dopo la chiusura.
    for attesa in root.tk.call("after", "info"):
        root.tk.call("after", "cancel", attesa)
    root.destroy()
    # Stato globale della finestra (vedi CLAUDE.md): la seconda finestra non
    # deve ereditare gli elementi del canvas della prima.
    window._sessions_win = None
    window._remote_qr_item = None

    root = disegna("tunnel")
    _cattura(root).save(OUT / "finestra-tunnel.png")
    root.destroy()


# --- COMPOSIZIONI --------------------------------------------------------------

def _font(nome: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / nome), px)


def _arrotonda(img: Image.Image, raggio: int) -> Image.Image:
    maschera = Image.new("L", img.size, 0)
    ImageDraw.Draw(maschera).rounded_rectangle((0, 0, *img.size), raggio, fill=255)
    out = img.convert("RGBA")
    out.putalpha(maschera)
    return out


def _telefono(schermo: Image.Image, larghezza: int) -> Image.Image:
    """Schermata dentro una cornice da telefono (bordo scuro, angoli tondi)."""
    s = larghezza / schermo.width
    schermo = schermo.resize((larghezza, round(schermo.height * s)), Image.LANCZOS)
    bordo = max(6, larghezza // 36)
    w, h = schermo.width + bordo * 2, schermo.height + bordo * 2
    cornice = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(cornice)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=bordo * 6, fill="#0f0c0a",
                        outline=COLOR_LINE, width=max(2, bordo // 4))
    cornice.alpha_composite(_arrotonda(schermo, bordo * 5), (bordo, bordo))
    return cornice


def _ombra(img: Image.Image, raggio: int) -> Image.Image:
    pad = raggio * 3
    ombra = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    alfa = img.getchannel("A").point(lambda a: int(a * 0.55))
    nero = Image.new("RGBA", img.size, (0, 0, 0, 255))
    nero.putalpha(alfa)
    ombra.alpha_composite(nero, (pad, pad + raggio // 2))
    ombra = ombra.filter(ImageFilter.GaussianBlur(raggio))
    ombra.alpha_composite(img, (pad, pad))
    return ombra


def _fondo(larghezza: int, altezza: int) -> Image.Image:
    fondo = Image.new("RGBA", (larghezza, altezza), COLOR_BG)
    d = ImageDraw.Draw(fondo)
    # Griglia leggera, come la griglia di impaginazione di PiDash.
    passo = 40
    for x in range(0, larghezza, passo):
        d.line((x, 0, x, altezza), fill=COLOR_PANEL)
    for y in range(0, altezza, passo):
        d.line((0, y, larghezza, y), fill=COLOR_PANEL)
    return fondo


def _incolla(fondo: Image.Image, img: Image.Image, x: int, y: int) -> None:
    r = max(8, fondo.height // 70)
    fondo.alpha_composite(_ombra(img, r), (x - r * 3, y - r * 3))


def _pezzi(alt_finestra: int, alt_telefono: int):
    """Finestra (angoli tondi) e i due telefoni, touchpad e terminale."""
    fin = Image.open(OUT / "finestra-upnp.png").convert("RGBA")
    fw = round(fin.width * alt_finestra / fin.height)
    fin = _arrotonda(fin.resize((fw, alt_finestra), Image.LANCZOS), max(6, alt_finestra // 50))
    telefoni = []
    for nome in ("client-touchpad.png", "client-terminale.png"):
        schermo = Image.open(OUT / nome).convert("RGB")
        larghezza = round(schermo.width * alt_telefono / schermo.height)
        telefoni.append(_telefono(schermo, larghezza))
    return fin, telefoni


def copertina(percorso: Path) -> None:
    """Immagine d'apertura del README: la finestra del PC e i due telefoni."""
    L, A, GAP = 1680, 900, 28
    fondo = _fondo(L, A)
    fin, (t1, t2) = _pezzi(640, 740)
    tot = fin.width + 56 + t1.width + GAP + t2.width
    x = (L - tot) // 2
    _incolla(fondo, fin, x, (A - fin.height) // 2)
    x += fin.width + 56
    _incolla(fondo, t1, x, (A - t1.height) // 2)
    _incolla(fondo, t2, x + t1.width + GAP, (A - t2.height) // 2)
    fondo.convert("RGB").save(percorso, optimize=True)


def social_preview(percorso: Path) -> None:
    """1280×640, il formato della social preview di GitHub (Settings → General)."""
    L, A, M = 1280, 640, 48
    fondo = _fondo(L, A)
    d = ImageDraw.Draw(fondo)
    fin, (t1, t2) = _pezzi(330, 548)
    x_tel = L - M - t1.width - 18 - t2.width
    _incolla(fondo, t1, x_tel, (A - t1.height) // 2)
    _incolla(fondo, t2, x_tel + t1.width + 18, (A - t2.height) // 2)

    d.text((M, M), f"v{VERSION} «{CODENAME.lower()}»", font=_font("SpaceMono-Regular.ttf", 20),
           fill=COLOR_TAN)
    d.text((M - 3, M + 26), "Liquid Mouse", font=_font("SpaceGrotesk-Medium.ttf", 72),
           fill=COLOR_CREAM)
    f_sub = _font("SpaceMono-Regular.ttf", 19)
    d.text((M, M + 118), "touchpad · tastiera · terminale", font=f_sub, fill=COLOR_CREAM)
    d.text((M, M + 146), "per windows, dal browser del telefono", font=f_sub, fill=COLOR_TAN)
    d.rounded_rectangle((M, M + 190, M + 200, M + 196), 3, fill=COLOR_ORANGE)
    _incolla(fondo, fin, M, A - M - fin.height)
    fondo.convert("RGB").save(percorso, optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solo", choices=("client", "finestra", "composizioni"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.solo in (None, "client"):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            client = Client(pw)
            schermate_client(client)
            salva_gif(gif_client(client), OUT / "animazione.gif")
            client.chiudi()
    if args.solo in (None, "finestra"):
        schermate_finestra()
    # Sempre, anche con --solo: le composizioni usano le PNG di entrambe le parti.
    copertina(OUT / "copertina.png")
    social_preview(OUT / "social-preview.png")
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(ROOT)}  {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
