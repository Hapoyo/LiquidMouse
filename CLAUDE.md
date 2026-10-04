# Liquid Mouse — CLAUDE.md

Versione 2.9.0 · 2026-10-04

## 1. Scopo
Il telefono diventa touchpad, tastiera e terminale per un PC Windows. Il server Python
gira sul PC (finestra Tk + icona nella tray); il client è una pagina web servita dal PC,
nessuna app da installare. In LAN su HTTP/WS, da remoto su HTTPS/WSS porta 8443 via UPnP
con PIN, o via tunnel Cloudflare quando UPnP non può (CGNAT). Unico stile: tema "cyber" di [PiDash](https://github.com/Hapoyo/PiDash).

## 2. Struttura
```
server.pyw               entrypoint: costruisce le dipendenze e le collega, nessuna logica
liquidmouse/
  version.py             VERSION e CODENAME, unica fonte (letta anche via regex)
  theme.py               palette e font; stessi valori in static/app.css (:root)
  config.py              %APPDATA%/LiquidMouse/config.json, migra da LiquidControl
  events.py              log_message → sink registrati (la GUI è un sink)
  executors.py           pool di thread dedicati (read/write PTY, SFTP, rete): mai run_in_executor(None)
  paths.py, ports.py     percorsi degli asset (anche nel bundle), porte 8000/8765/8443/8766/8767
  net/                   server.py (servizi), protocol.py (messaggi), static.py (whitelist
                         asset), frames.py (frame binari), upnp.py, tunnel.py
                         (cloudflared), addresses.py, sftp.py (file manager: profili, paramiko,
                         DPAPI), transfers.py (biglietti monouso per /sftp/dl e /sftp/up)
  input/                 keymap.py (nomi tasto → VK), win32.py (SendInput)
  terminal/              sessions.py, conpty.py (pywinpty o ConPTY ctypes), commands.py
                         (whitelist comandi), ringbuffer.py, launcher.py (finestra sul PC)
  security/              auth.py (PIN, anti brute force), tls.py (certificato auto-firmato),
                         dpapi.py (DPAPI: password SFTP, PIN e chiave TLS della config)
  gui/                   window.py (finestra, tray, pannello sessioni), effects.py (DWM,
                         font privati). Unico pacchetto che importa tkinter/pystray/PIL/qrcode
static/                  index.html, app.css, app.js, icon.ico
static/fonts/            Space Grotesk Medium, Space Mono (sottoinsieme latino) + OFL
static/vendor/           xterm.js, xterm.css, motion.js (Motion 14.0.0 UMD, global `Motion`)
                         + LICENSE-motion.txt: non modificare; per aggiornare Motion
                         copiare `dist/motion.js` del pacchetto npm `motion`
tests/                   pytest, girano su Linux senza Windows né schermo
tools/anteprime.py       rigenera le immagini di docs/img (client in Chromium, finestra Tk
                         sotto Xvfb, dati dimostrativi e WebSocket finto)
docs/img/                schermate, GIF, copertina e social preview del README (solo docs/img
                         è tracciata: il resto di docs/ resta locale, vedi .gitignore)
README.md, CHANGELOG.md  in inglese, stile PiDash (sezioni numerate); le novità vanno nel
                         CHANGELOG, non nel README
test_server.py           smoke test da lanciare con il server avviato (solo Windows)
build.py, LiquidMouse.spec   build PyInstaller → EXE/LiquidMouse.exe
.github/workflows/       test.yml (ogni push e PR: Linux 3.12 e Windows 3.10/3.13), dependabot.yml, build.yml (EXE; release con pubblica=true
                         o con il push di un tag v*)
```

## 3. Comandi
- Dipendenze: `requirements.txt` (versioni minime verificate; `.github/dependabot.yml` apre le PR di aggiornamento).
- Test: `pip install pytest websockets && python -m pytest` (node serve ai test dei contratti JS)
  Su Windows: `PYTHONUTF8=1 py -3.13 -m pytest` (senza, l'output UTF-8 di node letto in cp1252
  fa fallire test_files_client_contract sui nomi accentati)
- Core senza GUI: i moduli elencati in `.github/workflows/test.yml` devono importarsi su Linux
- Avvio da sorgente (Windows): `py -3.13 -m pip install -r requirements.txt` poi `py -3.13 server.pyw`
- Smoke test (Windows, server avviato): `py -3.13 test_server.py`
- Anteprime del README: `xvfb-run -s "-screen 0 1920x1080x24 -dpi 192" python tools/anteprime.py`
  (su Windows funziona `--solo client`, con `PYTHONUTF8=1`; Motion non segue `page.clock`,
  quindi le pagine emulano prefers-reduced-motion e mostrano gli stati finali)
  (servono playwright, Pillow, qrcode e tkinter; qui tkinter c'è solo in `/usr/bin/python3.12`
  dopo `apt install python3-tk`). Rigenerarle quando cambia l'aspetto di client o finestra.
- Build locale: `py -3.13 build.py` (`--pre` archivia una candidate in pre-release/)
- Rilascio: versione in `liquidmouse/version.py` + README + CHANGELOG (la voce "Unreleased"
  prende numero e data), unire in main, poi avviare
  `build.yml` su main con `pubblica=true` (workflow_dispatch, anche via API GitHub): crea
  tag e release `vX.Y.Z` con `LiquidMouse_vX.Y.Z.exe`. Da qui il push dei tag non passa.
  In alternativa il push di un tag `vX.Y.Z` fa lo stesso (il tag deve coincidere con VERSION).

## 4. Modo di lavorare
- L'utente lavora solo tramite Claude Code: nessun file locale, questo CLAUDE.md è l'unica
  memoria del progetto. Aggiornarlo quando cambiano comandi, struttura o convenzioni.
- Qui non c'è Windows: ciò che tocca Win32, Tk, EXE o rete reale va verificato con test su
  Linux (stub/finti) e anteprime (Tk sotto Xvfb, client con Playwright a 390 px); le prove
  su Windows vanno elencate all'utente come passi da eseguire.
- Sviluppo solo tramite Claude Code e GitHub: lavorare su un ramo, aprire una PR verso
  `main` e unirla (merge commit) appena i controlli sono verdi. Unire sempre in `main`:
  niente lavoro lasciato su rami. Un ramo già unito riparte da `origin/main`.
- Commit: uno per intervento, messaggi in italiano all'imperativo. Non riscrivere commit
  già pubblicati (il force push è bloccato).
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
- Animazioni del client: solo tramite `anima()` in app.js (unico punto che legge
  `window.Motion`; null se Motion manca o con prefers-reduced-motion). Senza Motion
  valgono le riserve CSS `html:not(.motion) ...`. Mai animazioni sul percorso del
  touchpad; sulla cartella (`.tab-content`) e su `#terminal-active` solo opacità: una
  trasformazione sposterebbe i figli `position: fixed` (tests/test_motion_client.py).

## 6. Elenchi da tenere allineati (i test li controllano)
| Cosa | Dove |
|---|---|
| Asset statici | `LiquidMouse.spec` (datas) · `net/static.py` (STATIC_ROUTES) · `build.py` (required) |
| Versione | `version.py` · intestazione del README · tag git · titolo in CHANGELOG.md |
| Immagini del README | link in `README.md` · file in `docs/img` (test_readme.py) |
| Palette | `theme.py` · `static/app.css` `:root` |
| Frame binari del terminale | `net/frames.py` · `handleBinaryFrame` in app.js |
| Tasti del terminale | `TERM_KEYS` in app.js · `.tkey[data-key]` in index.html |
| Tipi di messaggio | `@handles` in `net/protocol.py` · `ws.send` in app.js |
| Funzioni pure del file manager | blocco `// --- FILE: contratto` in app.js · `join_path` in `net/sftp.py` (test_files_client_contract.py) |

## 7. Decisioni
- Accesso remoto: UPnP se apre la porta, altrimenti tunnel Cloudflare (quick tunnel, senza
  account; Tailscale rimosso in 2.4.0 perché voleva l'app sul telefono). Porta unica 8443
  per pagina e WSS. Una sola decisione in `NetworkServices._refresh_remote` (avvio e
  keepalive): UPnP riuscito ferma il tunnel.
- Tunnel: cloudflared non è nel bundle (~55 MB): si usa quello in `%APPDATA%/LiquidMouse/bin`,
  poi quello nel PATH, altrimenti si scarica lì verificando lo SHA-256 dell'API della release. Origine su 127.0.0.1:8767 (TUNNEL_PORT): lì ogni client
  arriva da loopback, quindi `via_tunnel` forza sempre il PIN, e l'anti brute force usa
  `CF-Connecting-IP` (altrimenti chiunque bloccherebbe il proprietario). Indirizzo
  `*.trycloudflare.com` diverso a ogni avvio.
  Se il modem rifiuta la 8443 esterna si provano le porte di `EXTERNAL_PORTS` (net/upnp.py),
  sempre verso la 8443 interna: il QR porta la porta esterna, il client usa quella della
  pagina. IP esterno del router privato/CGNAT = errore esplicito, niente QR UPnP.
- Tastiera del telefono: il body segue `visualViewport` (`--vv-h`, `--vv-top`) invece di
  100dvh; `kbd-open` sul body nasconde linguette e intestazione del terminale.
- LAN senza PIN ma whitelist "primo arrivato" (reset dal menu tray); CGNAT 100.64/10 = remoto.
- Asset serviti da cache in memoria con ETag; qualunque path fuori whitelist → 404.
- Output del terminale in frame binari, non base64 in JSON.
- Terminale: il read loop del PTY accoda soltanto; ogni viewer ha una coda limitata
  (`MAX_QUEUED_BYTES`, 1 MB) e un task di invio (`_Pump` in terminal/sessions.py). Chi supera
  la soglia è tolto e la sua connessione chiusa (1013): il client riconnette e si riaggancia
  dal ring buffer. L'attach resta senza race (snapshot+offset, `catching_up`). Le scritture nel
  PTY passano da una coda per sessione e dall'executor `PTY_WRITE` (ordine garantito, tetto
  `MAX_PENDING_WRITE`); ConPTY completa le `WriteFile` parziali.
- Sessioni terminale sopravvivono alla disconnessione (ring buffer 64 KB); quelle uscite
  vengono chiuse e rimosse. ConPTY: un thread chiude la pseudo-console all'uscita del
  processo, altrimenti ReadFile non riceve mai EOF.
- Sessioni: si chiudono con la × dell'elenco (conferma al secondo tocco); `term_kill` non
  richiede l'aggancio, che non è un confine (term_attach è libero per i client autenticati).
  `esc` va alla shell, non chiude. "‹ sessioni" torna all'elenco lasciando la sessione viva.
- Errore di autenticazione nel client = niente riconnessione automatica (evita il blocco IP).
- Nome: LiquidControl fino alla 2.5.x, Liquid Mouse dalla 2.6.0 (config migrata copiando).
- File manager (scheda 003): il PC è client SFTP (paramiko, import pigro) verso un host SSH
  scelto da un profilo in `config.json` (`sftp_profiles`; di norma l'OpenSSH del PC stesso,
  127.0.0.1:22). Password cifrata con DPAPI, mai rimandata al client; dove DPAPI manca non si
  salva nessuna password. Host key TOFU: impronta salvata alla prima connessione, se cambia
  la connessione è rifiutata prima di inviare la password. Le operazioni bloccanti girano in
  executor (il dispatch è sequenziale). I file passano da HTTP con un biglietto monouso
  (60 s) chiesto via WS (`sftp_ticket`): sulla 8000 in streaming; da remoto (8443/tunnel) il
  download è letto in memoria con tetto 64 MB e l'upload non c'è (websockets non riceve il
  corpo di un POST). Nomi con `/`, `\`, `..` rifiutati (`validate_name`).
- Config: `pin_plain` e `ssl_key` sono in chiaro solo in memoria; su disco `pin_secret` e
  `ssl_key_secret` (DPAPI, `Config(protector=...)`). Una config vecchia in chiaro viene riscritta
  cifrata al primo avvio con PIN e certificato invariati. Senza DPAPI il file resta come prima;
  un segreto non decifrabile viene rigenerato (PIN nuovo = QR da rifare).
- Font TTF e non woff2: gli stessi file servono al browser e a Tk (AddFontResourceEx privato).

## 8. Vincoli noti
- Python 3.14 non supportato (miniupnpc senza wheel).
- ConPTY via ctypes richiede Windows 10 1809+; pywinpty è il backend preferito.
- Certificato auto-firmato: al primo accesso remoto il browser mostra l'avviso.
- Ancora da provare su Windows: file manager (OpenSSH locale, download/upload di file grandi, DPAPI, paramiko nell'EXE, migrazione della config con PIN/chiave cifrati), font privati in Tk, ConPTY senza pywinpty, barra tasti del
  terminale, chiusura delle sessioni, EXE 2.6.x. Sul telefono: tastiera aperta nel
  terminale (Safari e Chrome). Tunnel Cloudflare reale (qui il proxy lo blocca con 403):
  download di cloudflared, QR trycloudflare, PIN, niente finestra nera di cloudflared.

## 9. Glossario
- **PTY / ConPTY**: pseudo-terminale; ConPTY è quello nativo di Windows.
- **VT / CSI**: sequenze di escape del terminale (`ESC [ A` = freccia su; `CSI 1;5D` = ctrl+←).
- **UPnP / IGD**: protocollo con cui il PC chiede al router di aprire la porta 8443.
- **CGNAT**: NAT condiviso dell'operatore, range 100.64.0.0/10 (la linea dell'utente è così).
- **Quick tunnel**: tunnel Cloudflare senza account, indirizzo casuale `*.trycloudflare.com`.
- **DWM**: compositore di Windows (angoli arrotondati, modalità scura della finestra).
- **Schedario**: stile a linguette numerate (001, 002) preso da PiDash.
