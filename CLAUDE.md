# Liquid Mouse — CLAUDE.md

Versione 2.6.0 · 2026-09-27

## 1. Scopo
Il telefono diventa touchpad, tastiera e terminale per un PC Windows. Il server Python
gira sul PC (finestra Tk + icona nella tray); il client è una pagina web servita dal PC,
nessuna app da installare. In LAN su HTTP/WS, da remoto su HTTPS/WSS porta 8443 via UPnP
con PIN. Unico stile: tema "cyber" di [PiDash](https://github.com/Hapoyo/PiDash).

## 2. Struttura
```
server.pyw               entrypoint: costruisce le dipendenze e le collega, nessuna logica
liquidmouse/
  version.py             VERSION e CODENAME, unica fonte (letta anche via regex)
  theme.py               palette e font; stessi valori in static/app.css (:root)
  config.py              %APPDATA%/LiquidMouse/config.json, migra da LiquidControl
  events.py              log_message → sink registrati (la GUI è un sink)
  paths.py, ports.py     percorsi degli asset (anche nel bundle), porte 8000/8765/8443/8766
  net/                   server.py (servizi), protocol.py (messaggi), static.py (whitelist
                         asset), frames.py (frame binari), upnp.py, addresses.py
  input/                 keymap.py (nomi tasto → VK), win32.py (SendInput)
  terminal/              sessions.py, conpty.py (pywinpty o ConPTY ctypes), commands.py
                         (whitelist comandi), ringbuffer.py, launcher.py (finestra sul PC)
  security/              auth.py (PIN, anti brute force), tls.py (certificato auto-firmato)
  gui/                   window.py (finestra, tray, pannello sessioni), effects.py (DWM,
                         font privati). Unico pacchetto che importa tkinter/pystray/PIL/qrcode
static/                  index.html, app.css, app.js, icon.ico
static/fonts/            Space Grotesk Medium, Space Mono (sottoinsieme latino) + OFL
static/vendor/           xterm.js, xterm.css: non modificare
tests/                   pytest, girano su Linux senza Windows né schermo
test_server.py           smoke test da lanciare con il server avviato (solo Windows)
build.py, LiquidMouse.spec   build PyInstaller → EXE/LiquidMouse.exe
.github/workflows/       test.yml (ogni push), build.yml (tag v* → release con l'EXE)
```

## 3. Comandi
- Test: `pip install pytest websockets && python -m pytest` (node serve ai test dei contratti JS)
- Core senza GUI: i moduli elencati in `.github/workflows/test.yml` devono importarsi su Linux
- Avvio da sorgente (Windows): `py -3.13 -m pip install websockets pystray Pillow qrcode cryptography pywinpty miniupnpc` poi `py -3.13 server.pyw`
- Smoke test (Windows, server avviato): `py -3.13 test_server.py`
- Build locale: `py -3.13 build.py` (`--pre` archivia una candidate in pre-release/)
- Rilascio: versione in `liquidmouse/version.py` + README, unire in main, poi avviare
  `build.yml` su main con `pubblica=true` (workflow_dispatch, anche via API GitHub): crea
  tag e release `vX.Y.Z` con `LiquidMouse_vX.Y.Z.exe`. Da qui il push dei tag non passa.
  In alternativa il push di un tag `vX.Y.Z` fa lo stesso (il tag deve coincidere con VERSION).

## 4. Modo di lavorare
- L'utente lavora solo tramite Claude Code: nessun file locale, questo CLAUDE.md è l'unica
  memoria del progetto. Aggiornarlo quando cambiano comandi, struttura o convenzioni.
- Qui non c'è Windows: ciò che tocca Win32, Tk, EXE o rete reale va verificato con test su
  Linux (stub/finti) e anteprime (Tk sotto Xvfb, client con Playwright a 390 px); le prove
  su Windows vanno elencate all'utente come passi da eseguire.
- Commit: uno per intervento, messaggi in italiano all'imperativo.
- Modifiche estese: prima un piano numerato dei file, poi l'esecuzione.

## 5. Convenzioni
- Python ≥ 3.10, type hints, docstring brevi, errori espliciti; commenti in italiano che
  spiegano il perché (il bug evitato), non il cosa.
- Dipendenze a senso unico: la GUI conosce il core, il core non conosce la GUI. Il core
  segnala con `events.log_message(msg, color=COLOR_*)`.
- Stato globale solo in `server.pyw` e `gui/window.py`; il resto riceve le dipendenze.
- Testi a video in italiano minuscolo (etichette `nome // dettaglio`); README in inglese.
- Grafica: solo colori di `theme.py` / `:root` di app.css; numeri grandi in Space Grotesk,
  etichette in Space Mono. Contrasto testo ≥ 4.5:1 (test_theme_contrast.py).
- Finestra desktop: tutto disegnato sul canvas, misure in px a 96 dpi passate da `_px`.
- Client: app.js è uno script classico (non modulo: gli onclick inline vogliono globali),
  caricato con defer. Colori della riga di stato via classi (`setStatus(text, kind)`).
- Valori dal client = non fidati: passare da `clamp_int` e dalle whitelist.

## 6. Elenchi da tenere allineati (i test li controllano)
| Cosa | Dove |
|---|---|
| Asset statici | `LiquidMouse.spec` (datas) · `net/static.py` (STATIC_ROUTES) · `build.py` (required) |
| Versione | `version.py` · intestazione del README · tag git |
| Palette | `theme.py` · `static/app.css` `:root` |
| Frame binari del terminale | `net/frames.py` · `handleBinaryFrame` in app.js |
| Tasti del terminale | `TERM_KEYS` in app.js · `.tkey[data-key]` in index.html |
| Tipi di messaggio | `@handles` in `net/protocol.py` · `ws.send` in app.js |

## 7. Decisioni
- Accesso remoto solo UPnP (Tailscale rimosso in 2.4.0); porta unica 8443 per pagina e WSS.
- LAN senza PIN ma whitelist "primo arrivato" (reset dal menu tray); CGNAT 100.64/10 = remoto.
- Asset serviti da cache in memoria con ETag; qualunque path fuori whitelist → 404.
- Output del terminale in frame binari, non base64 in JSON.
- Sessioni terminale sopravvivono alla disconnessione (ring buffer 64 KB); quelle uscite
  vengono chiuse e rimosse. ConPTY: un thread chiude la pseudo-console all'uscita del
  processo, altrimenti ReadFile non riceve mai EOF.
- Errore di autenticazione nel client = niente riconnessione automatica (evita il blocco IP).
- Nome: LiquidControl fino alla 2.5.x, Liquid Mouse dalla 2.6.0 (config migrata copiando).
- Font TTF e non woff2: gli stessi file servono al browser e a Tk (AddFontResourceEx privato).

## 8. Vincoli noti
- Python 3.14 non supportato (miniupnpc senza wheel).
- ConPTY via ctypes richiede Windows 10 1809+; pywinpty è il backend preferito.
- Certificato auto-firmato: al primo accesso remoto il browser mostra l'avviso.
- Ancora da provare su Windows: font privati in Tk, ConPTY senza pywinpty, EXE 2.6.0.

## 9. Glossario
- **PTY / ConPTY**: pseudo-terminale; ConPTY è quello nativo di Windows.
- **VT / CSI**: sequenze di escape del terminale (`ESC [ A` = freccia su; `CSI 1;5D` = ctrl+←).
- **UPnP / IGD**: protocollo con cui il PC chiede al router di aprire la porta 8443.
- **CGNAT**: NAT condiviso dell'operatore, range 100.64.0.0/10.
- **DWM**: compositore di Windows (angoli arrotondati, modalità scura della finestra).
- **Schedario**: stile a linguette numerate (001, 002) preso da PiDash.
