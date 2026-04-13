# LiquidMouse

Turn your smartphone into a wireless touchpad and keyboard for Windows.
No app to install — the client runs entirely in the browser.

## Requirements

- Windows 10 / 11
- PC and smartphone on the same Wi-Fi network

## Installation

**Executable** — download `LiquidMouse.exe` from [Releases](https://github.com/Hapoyo/LiquidMouse/releases).

**From source** — Python 3.7+:

```bash
pip install websockets pystray Pillow qrcode cryptography
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
- Security: IP whitelist, local network only, no cloud

## First-time setup on iPhone / iPad (Safari)

LiquidMouse uses a self-signed SSL certificate to encrypt the connection. Safari requires you to trust it once before connecting.

1. Right-click the tray icon → **Install certificate on phone**
2. Scan the QR code with Safari (not the Camera app)
3. Tap **Allow** to download the profile → go to **Settings**
4. **Settings → Profile Downloaded → Install**
5. **Settings → General → About → Certificate Trust Settings → enable LiquidMouse**

After this, Safari will connect without warnings on that device. Repeat if you change Wi-Fi networks (the certificate is tied to the PC's local IP).

## Troubleshooting

**Smartphone won't connect** — make sure both devices are on the same Wi-Fi network and that Windows Firewall allows ports `8000`, `8001` and `8765`.

**Ports in use** — find the process with `netstat -ano | findstr :8765`, then kill it with `taskkill /PID <id> /F`.

**Safari shows a security warning** — follow the certificate installation steps above. Once installed and trusted, the warning won't appear again.

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
