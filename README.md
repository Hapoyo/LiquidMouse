# LiquidControl

**v2.4.0 «Popins»**

Turn your smartphone into a wireless touchpad, keyboard and terminal for Windows.
No app to install — the client runs entirely in the browser.

## What's new in v2.4.0

- **Smoother cursor** — slow finger movements no longer stall. The sub-pixel remainder
  of the rounding was being discarded, so gentle motion produced no movement at all.
- **Faster terminal** — PTY output now travels as raw binary WebSocket frames instead of
  base64 inside JSON: roughly 33% less bandwidth and no per-byte decoding on the phone.
- **Faster page load** — static assets are cached in memory and served with an ETag, so a
  reload revalidates with an empty `304` instead of re-transferring 283 KB of xterm.js.
- **Remote access is UPnP only** — Tailscale support has been removed. The router opens
  `8443` and the QR carries the PIN.
- **Restructured codebase** — the logic now lives in a `liquidmouse/` package with 257
  automated tests running in CI. `server.pyw` is a thin entrypoint.
- **Security** — the LAN HTTP server used to serve its whole directory without
  authentication, which exposed `server.pyw` and the config file containing the PIN.
  Both paths now serve an explicit whitelist.
- **Single remote port** — page and command channel both travel on `8443`
  (many routers/ISPs filter unusual ports; one port, one certificate).
- **UPnP self-healing** — mappings renewed every 10 minutes, survives router reboots.

## Requirements

- Windows 10 / 11
- Phone and PC on the same Wi-Fi network — **or** a router with UPnP enabled for remote use

## Installation

**Executable** — download `LiquidControl.exe` from
[Releases](https://github.com/Hapoyo/LiquidMouse/releases) and run it.

**From source** — Python 3.10–3.13 (3.14 not yet supported: `miniupnpc` has no wheel):

```bash
py -3.13 -m pip install websockets pystray Pillow qrcode cryptography pywinpty miniupnpc
py -3.13 server.pyw
```

## Usage

1. Start LiquidControl on the PC
2. Scan the QR code shown in the window (or type the address in the phone browser)
   - **HOST QR** → local network (`http://<lan-ip>:8000`)
   - **SCAN REMOTO QR** → UPnP, works away from home (PIN included in the link)
3. To quit: tray icon → Esci

## Features

- Touchpad with tap, double-tap, long-press (right-click), two-finger scroll, drag lock
- Full virtual keyboard with Unicode support
- **Terminal mode** — a real Windows terminal (xterm.js) in the browser, multi-viewer,
  sessions survive disconnections
- Quick menu: Copy, Paste, ESC, Ctrl/Shift lock, Select All, Win, Play/Pause
- Adjustable cursor sensitivity, saved on the phone
- Security: IP whitelist on LAN · PIN + SHA-256 + brute-force lockout for remote
  connections · static assets served from an explicit whitelist on both paths

## Project layout

```
server.pyw          → server (WS + WSS + HTTP + HTTPS, GUI, tray) — run directly for testing
index.html          → browser client (touchpad, keyboard, terminal)
test_server.py      → smoke test (run while the server is up)
build.py            → local build → EXE/LiquidControl.exe  (--pre → pre-release/ candidate)
release.py          → versioned release (local git-less workflow, archives to release/)
LiquidControl.spec  → PyInstaller configuration
EXE/                → latest local build
pre-release/        → timestamped release candidates
release/            → versioned final builds
build/              → PyInstaller work dir (disposable)
```

## Development

```bash
py -3.13 server.pyw          # run from source (test mode)
py -3.13 test_server.py      # smoke test against the running server
py -3.13 build.py            # build EXE/LiquidControl.exe
py -3.13 build.py --pre      # build + archive a pre-release candidate
py -3.13 release.py -v X.Y.Z --yes   # tag & push → GitHub Actions builds the release
```

## Troubleshooting

**Phone won't connect on LAN** — same Wi-Fi network? Windows Firewall must allow TCP
`8000` and `8765`. Some routers isolate Wi-Fi clients from each other ("AP isolation"):
disable it in the router settings.

**Remote shows "non disponibile"** — the router has no UPnP/IGD, it is disabled, or it
filters ports. Enable UPnP in the router settings, or forward TCP `8443` manually to the
PC's LAN address.

**Stuck on "In attesa..."** — reload the page (old cached client). If it persists,
run `py -3.13 test_server.py` and check the browser console.

## Author

[Hapoyo](https://github.com/Hapoyo)

## License

MIT — see [LICENSE](LICENSE). Fully open: use it, fork it, ship it.
