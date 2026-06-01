# LiquidMouse

Turn your smartphone into a wireless touchpad and keyboard for Windows.
No app to install — the client runs entirely in the browser.

## Requirements

- Windows 10 / 11
- Python 3.7+ (source only)

## Installation

**Executable** — download `LiquidMouse.exe` from [Releases](https://github.com/Hapoyo/LiquidMouse/releases).

**From source** — Python 3.7+:

```bash
pip install websockets pystray Pillow qrcode cryptography miniupnpc
python server.pyw
```

## Usage

1. Start LiquidMouse on your PC
2. Scan the QR code with your smartphone or type the IP shown in the window
3. To quit: tray icon → Exit

## Features

- Touchpad with tap, double-tap, long-press (right-click) and two-finger scroll
- Full virtual keyboard with Unicode support
- Quick menu: Copy, Paste, ESC, Ctrl/Shift lock, Drag lock, Select All, Win, Play/Pause
- Adjustable cursor sensitivity, saved locally
- Terminal emulator (cmd.exe) via PTY
- **Remote access** — control your PC from any network, not just local Wi-Fi

## Remote Access

LiquidMouse supports two connection modes simultaneously:

| Mode | How it works | Requirements |
| :--- | :--- | :--- |
| **Local** | Direct Wi-Fi connection | Same network |
| **Remote (UPnP)** | Automatic port forwarding on your router | UPnP enabled (default on most home routers) |
| **Remote (Relay)** | Traffic routed via relay server | Internet access; relay server deployed |

### First remote connection

1. Start LiquidMouse — the main window shows the **ACCESSO REMOTO** section with the URL and PIN
2. Scan the remote QR code or open the URL on your smartphone
3. When prompted, enter the **PIN** shown in the window
4. The first time, your browser will show a certificate warning (self-signed TLS) — tap **Advanced → Proceed**

The PIN is generated once and stored locally. To regenerate it, delete `%APPDATA%\LiquidMouse\config.json` and restart.

### Security

- **PIN auth** — 8-character alphanumeric PIN required for all remote connections
- **Brute-force protection** — IP blocked for 30 minutes after 5 failed attempts
- **TLS encryption** — all remote traffic encrypted with a self-signed certificate
- **Local connections** — unchanged: IP whitelist, no PIN required on the same network

### Relay server (self-hosted)

If UPnP is unavailable, LiquidMouse falls back to a relay server.
The relay code (`relay_server.py`) is included in this repository.

Deploy example with [Caddy](https://caddyserver.com/) for automatic HTTPS:

```
# Caddyfile
relay.yourdomain.com {
    reverse_proxy localhost:8080
}
```

```bash
pip install websockets
python relay_server.py --host 0.0.0.0 --port 8080
```

Then set `RELAY_URL = "wss://relay.yourdomain.com"` in `server.pyw` before building.

## First-time setup on iPhone / iPad (Safari)

LiquidMouse uses a self-signed TLS certificate. Safari requires you to trust it once.

1. Open the HTTPS URL shown in the LiquidMouse window in **Safari**
2. Tap **Advanced → Proceed to site** to accept the certificate warning
3. The page loads — enter your PIN to connect

After this, Safari will connect without warnings on that device.

## Troubleshooting

**Smartphone won't connect (local)** — make sure both devices are on the same Wi-Fi network and that Windows Firewall allows ports `8000` and `8765`.

**Smartphone won't connect (remote)** — allow ports `8443` and `8766` in Windows Firewall. If UPnP is disabled on your router, forward these ports manually to your PC's local IP.

**Ports in use** — find the process with `netstat -ano | findstr :8765`, then kill it with `taskkill /PID <id> /F`.

**PIN not accepted** — check that you are entering the PIN shown in the **ACCESSO REMOTO** section of the LiquidMouse window. The PIN is stored in `%APPDATA%\LiquidMouse\config.json`.

**Connection drops repeatedly** — some mobile browsers throttle background WebSocket connections. Keep the browser tab in the foreground or disable battery saver mode.

## Supported browsers

| Browser | iOS | Android |
| :--- | :---: | :---: |
| Safari | ✅ | — |
| Chrome | ✅ | ✅ |
| Firefox | ⚠️ | ✅ |
| Edge | — | ✅ |

## Author

[Hapone](https://github.com/Hapoyo)

## License

GPL v3 — see [LICENSE](LICENSE)
