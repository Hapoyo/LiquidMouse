# CLAUDE.md — LiquidMouse

LiquidMouse trasforma uno smartphone in touchpad/tastiera wireless per Windows.
Server Python sul PC, client HTML5 sul telefono via browser.
**Repo**: https://github.com/Hapoyo/LiquidMouse | **Lingua**: Italiano

## File

```
server.pyw          → Server (WebSocket + HTTP + GUI tkinter + system tray)
index.html          → Client mobile (touchpad, scroll, tastiera, menu)
build.py            → Build PyInstaller → dist/LiquidMouse.exe
LiquidMouse.spec    → Config PyInstaller
icon.ico            → Icona
release.py          → Utility rilascio (gitignored)
.github/workflows/build.yml → CI: tag v* → build EXE → GitHub Release
```

## Stack

- **Backend**: Python 3.7+ — asyncio, websockets, pystray, Pillow, qrcode, tkinter, ctypes
- **Frontend**: HTML5/CSS3/JS vanilla
- **Protocollo**: JSON over WebSocket porta `8765`, HTTP statico porta `8000`
- **Build**: PyInstaller `.spec`, output singolo EXE standalone

## Comandi

```bash
python server.pyw                              # Avvio
python build.py                               # Build EXE
pip install websockets pystray Pillow qrcode  # Dipendenze
```

## Workflow modifiche → release

1. **Modifica file** su `O:\`
2. **Build locale** (obbligatorio dopo ogni modifica): `python build.py` dalla dir del progetto
3. **Push su main** via clone temp (il network drive non supporta git direttamente):
   ```bash
   git clone https://github.com/Hapoyo/LiquidMouse "C:\Users\GENERALE Popino\AppData\Local\Temp\LiquidMouse_release"
   # copiare i file modificati nel clone
   git add . && git commit -m "..." && git push origin main
   rmdir /s /q "...\LiquidMouse_release"
   ```
4. **Release** (solo su comando esplicito): `git tag vX.Y.Z && git push origin vX.Y.Z`
   → attiva GitHub Actions → build EXE → crea GitHub Release automatica

> **Regola**: il build si fa sempre dopo le modifiche. Il tag/release aspetta il comando dell'utente.

## Protocollo WebSocket

| Tipo | Campi | Note |
|------|-------|------|
| `move` | `x`, `y` | Delta; sensitivity applicata client-side |
| `scroll` | `amount` | Scroll wheel |
| `click` | `btn` `left`/`right` | Click istantaneo |
| `text` | `char` | Unicode, smart quote replacement server-side |
| `key` | `key` | Singolo tasto; backspace debounce 80ms server |
| `key_toggle` | `key`, `state` `down`/`up` | Tasto mantenuto |
| `drag` | `state` `down`/`up` | Mouse button hold |
| `hotkey` | `keys` (array) | Lettere, cifre e VK_MAP supportati |
| `ping` | — | Risposta `pong` per RTT |

## Convenzioni & Note tecniche

- Commenti e UI in italiano; sezioni `# --- NOME ---`; `.pyw` = no console Windows
- Input via `ctypes.windll.user32.SendInput` (no pyautogui)
- Sicurezza: whitelist IP (primo client autorizzato; reset da tray)
- `BASE_DIR`: gestisce esecuzione diretta e PyInstaller frozen
- Client: movimento batching `requestAnimationFrame` 60fps; scroll accumulator; exponential backoff reconnect
- GUI palette: sfondo `#0D0D0D`, accento `#DA7756`
