# CLAUDE.md — LiquidMouse

## Progetto

LiquidMouse trasforma uno smartphone in touchpad/tastiera wireless per Windows.
Server Python sul PC, client HTML5 sul telefono via browser.

- **Repository**: https://github.com/Hapoyo/LiquidMouse
- **Licenza**: GPL v3
- **Lingua**: Italiano (commenti, UI, docs)

## Struttura

```
server.pyw              → Server (WebSocket + HTTP + GUI tkinter + system tray)
index.html              → Client mobile (touchpad, scroll, tastiera, menu)
build.py                → Build PyInstaller → dist/LiquidMouse.exe
LiquidMouse.spec        → Configurazione PyInstaller
icon.ico                → Icona applicazione
release.py              → Utility rilascio locale (gitignored)
.github/workflows/build.yml → CI: push tag v* → build EXE → GitHub Release
```

## Stack

- **Backend**: Python 3.7+ — asyncio, websockets, pystray, Pillow, qrcode, tkinter, ctypes (Win32 input nativo)
- **Frontend**: HTML5/CSS3/JS vanilla (zero dipendenze)
- **Protocollo**: JSON over WebSocket (porta 8765), HTTP statico (porta 8000)
- **Build**: PyInstaller via `.spec` file
- **Distribuzione**: Singolo EXE Windows standalone

## Dipendenze Python

```
websockets pystray Pillow qrcode
```

Built-in: asyncio, json, socket, threading, tkinter, ctypes, http.server, os, sys, time

## Comandi

```bash
python server.pyw                                    # Avvio
python build.py                                      # Build EXE
pip install websockets pystray Pillow qrcode          # Dipendenze
```

## Architettura Server (server.pyw)

- **Input engine** (Win32 ctypes): `SendInput` nativo, zero overhead — mouse_move, mouse_click, mouse_scroll, key_press, key_text, hotkey
- **WebSocket handler**: messaggi `move`, `scroll`, `click`, `text`, `key`, `key_toggle`, `drag`, `hotkey`
- **HTTP server**: serve `index.html` sulla LAN
- **GUI tkinter**: finestra frameless, angoli arrotondati, QR code, animazione typewriter, fade-in con easing cubico
- **System tray**: pystray con menu Apri/Reset connessione/Esci
- **Sicurezza**: whitelist IP (primo client che si connette viene autorizzato)
- **Porte**: `PORT=8765` (WebSocket), `HTTP_PORT=8000` (HTTP)

## Architettura Client (index.html)

- Design glass-morphism responsive mobile-first
- Touchpad con batching movimento a 60fps
- Scroll a due dita con accumulator
- Gesture: tap-to-click, double-tap, long-press (click destro)
- Menu overlay 3x3: ESC, Copia, Incolla, Ctrl lock, Tastiera, Shift lock, Seleziona tutto, Trascina lock
- Slider sensibilità cursore (salvato in localStorage)
- Auto-connessione via hostname o IP salvato
- Riconnessione automatica (max 5 tentativi)
- Gestione visibility change (sleep/wake smartphone)

## Protocollo WebSocket (JSON)

| Tipo | Campi | Descrizione |
|------|-------|-------------|
| `move` | `x`, `y` | Delta movimento (sensitivity applicata client-side) |
| `scroll` | `amount` | Quantità scroll |
| `click` | `btn` (`left`/`right`) | Click mouse |
| `text` | `char` | Carattere da digitare (unicode) |
| `key` | `key` | Pressione singola tasto |
| `key_toggle` | `key`, `state` (`down`/`up`) | Tasto tenuto premuto |
| `drag` | `state` (`down`/`up`) | Drag mouse |
| `hotkey` | `keys` (array) | Combinazione tasti |

## Convenzioni

- Commenti e UI in italiano
- Sezioni: `# --- NOME SEZIONE ---`
- Testing manuale, nessun linter configurato
- `.pyw` evita finestra console su Windows

## Note Tecniche

- Input via `ctypes.windll.user32.SendInput` — no pyautogui
- Backspace: debounce 80ms lato server
- Disconnessione client: rilascio automatico tasti/mouse bloccati
- QR code con `?v=timestamp` per evitare cache browser
- Smart replacement curly quotes → straight nel handler `text`
- `BASE_DIR` gestisce sia esecuzione diretta che PyInstaller frozen
- GUI: palette Claude Code (sfondo `#0D0D0D`, accento `#DA7756`), easing cubico fade-in ~60fps
