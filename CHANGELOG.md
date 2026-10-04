# Changelog

All notable changes to Liquid Mouse. Versions follow `liquidmouse/version.py`; each one is
published on [Releases](https://github.com/Hapoyo/LiquidMouse/releases) with its executable.

## Unreleased

- **Cleaner phone client** — same "cyber" filing-cabinet theme, tighter hierarchy: tab number
  and name aligned left with the open tab's number in amber; the session list starts at the
  top like the SSH profiles, with a count next to the title; file rows on dark outlined panels
  (cream stays for sessions and profiles), a vector rename icon instead of the emoji pencil,
  38 px action buttons, a fixed toolbar grid, an upload progress bar and a dashed empty state.
  Terminal and file headers and error banners now share one style. Visible keyboard focus,
  labelled form fields and `role="alert"` banners. The touchpad no longer shrinks on touch.
- **Motion animations** — [Motion](https://motion.dev) 14.0.0 ships as a local file
  (`static/vendor/motion.js`, MIT), no CDN, so it works on an offline LAN. Short springs and
  fades on tab changes, staggered session/profile/file lists, the quick menu, the typed-text
  echo, banners, status changes (a small shake on errors), delete/close confirmations and
  button presses. Nothing runs on the touchpad path. With "reduce motion" enabled, or if the
  file fails to load, the client works exactly as before.

## 2.8.0 — 2026-09-29

- **File manager (tab 003)** — browse, download and upload files over SSH/SFTP from the phone,
  FileZilla style. The PC is the SFTP client (default profile: the Windows OpenSSH server on
  `127.0.0.1:22`), so credentials never leave it: profiles are stored in the config with the
  password encrypted by Windows (DPAPI). The host key is pinned on first use and a changed key
  is refused before the password is sent. Rename, delete (second tap to confirm), new folder,
  multi-file upload with progress. Files travel over HTTP with one-time, 60-second tickets
  requested through the authenticated WebSocket. Over the remote route (8443 / tunnel)
  downloads are capped at 64 MB and uploads are not available yet. New dependency: `paramiko`.
- **README rewritten** in the style of [PiDash](https://github.com/Hapoyo/PiDash): cover image,
  animated demo, screenshots of the phone client and of the desktop window, requirements,
  connection modes, gestures, security, architecture and credits in numbered sections.
- **Previews generated from the code** — `tools/anteprime.py` draws every image in `docs/img`
  with demo data: the real client in Chromium at 390 px against a fake PC, the real desktop
  window under Xvfb. Also produces the 1280×640 social preview for the GitHub page.
- **CHANGELOG.md** — the "What's new" sections move here from the README.

## 2.7.0 — 2026-09-27

- **Remote access behind CGNAT** — when UPnP can't open a port (the ISP shares one public
  IP among customers, common on FWA/4G/5G lines), the PC starts a free Cloudflare quick
  tunnel instead: the remote QR points to `https://<words>.trycloudflare.com`. It works
  without any port forwarding, the certificate is valid (no browser warning) and the PIN
  is still required. The address changes at every start, so scan the QR again.
  `cloudflared` (~55 MB) is downloaded once into `%APPDATA%\LiquidMouse\bin`.
- **Shorter remote diagnosis** — the panel now tells `cgnat dell'operatore` apart from
  `doppio nat` instead of cutting the message off.

## 2.6.2 — 2026-09-27

- **Phone keyboard no longer hides the terminal** — the page now follows the visible area
  above the keyboard: the prompt line and the shortcut keys stay on screen while typing.
  With the keyboard open the tabs and the terminal header step aside to leave more rows.
- **UPnP fallback ports** — many ISP modems keep `8443` for themselves and refuse the
  mapping. The PC now tries `9443`, `10443`, `18443`, `28443` and `38443` as external
  ports (all forwarded to `8443` on the PC) and the QR carries whichever one was granted.
- **Clear double-NAT diagnosis** — if the UPnP router itself sits behind another modem or
  the ISP's CGNAT, the remote panel says so instead of showing an unreachable QR.

## 2.6.1 — 2026-09-27

- **Close terminal sessions** — every session in the resume list has a `×`: the first tap
  asks for confirmation (`chiudi?`), the second one ends the shell on the PC. Sessions used
  to stay open forever: `esc` goes to the shell, and the list was unreachable once inside.
- **Back to the list** — a `‹ sessioni` button above the terminal returns to the session
  list without closing the session.

## 2.6.0 — 2026-09-27

- **Back to the name Liquid Mouse** — the executable is now `LiquidMouse.exe`. The
  settings folder moves from `%APPDATA%\LiquidControl` to `%APPDATA%\LiquidMouse`: on
  first start the old one is copied over, so the PIN saved on your phones and the
  certificate you already accepted keep working.
- **"Cyber" look, shared with [PiDash](https://github.com/Hapoyo/PiDash)** — warm near-black
  background, filled rounded panels in orange, amber, cream and pink, big numbers in
  Space Grotesk and lowercase labels in Space Mono. Both the phone client and the desktop
  window are laid out as a card file: numbered tabs (`001 touchpad`, `002 terminale`)
  over an open folder. The desktop window now scales with the screen DPI.
- **Key bar in the terminal** — two rows under the terminal: `esc`, `tab`, `ctrl` and
  `alt` (one-shot: they apply to the next key or typed character, e.g. `ctrl` + `r`), the
  four arrows, `home`/`end`, page up/down, and the shortcuts `^c ^d ^z ^l`. Arrows and
  page keys repeat while held; tapping a key keeps the phone keyboard open.
- **A wrong PIN no longer locks you out** — the client used to reconnect on its own with
  the same wrong PIN until the server blocked the IP for 30 minutes. It now stops and
  asks again.
- **Terminal sessions that exit are released** — a session closed with `exit` used to
  keep its PTY and buffer allocated until the program was closed. With the built-in
  ConPTY backend (used when pywinpty is missing) it even stayed "active" forever: the
  pseudo console is now closed as soon as the process exits.

## 2.5.1 — 2026-08-10

- **Desktop window restyled** — flat panels and monospace type, matching the terminal
  look the phone client adopted in 2.5.0.

## 2.5.0 — 2026-08-09

- **Terminal-styled UI** — the client now uses a black/white/gray palette and monospace
  type throughout, flat surfaces and hairline borders instead of frosted glass, and a
  blinking block cursor next to the status line — the same signature the desktop panel's
  boot animation already used.
- **New terminal session opens cmd.exe** — the "New session" button used to only offer
  `claude`; it now starts a real Windows terminal by default.
- **More robust remote access** — a broken UPnP native dependency (e.g. mismatched DLLs
  in the EXE) used to fail silently and show a bare "Remote unavailable" with no reason;
  it's now reported. The remote panel also no longer reports UPnP as active if the TLS
  certificate isn't actually available.

## 2.4.0 — 2026-08-08

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

## Earlier versions

1.8.1 – 2.3.0 (March – July 2026): see the
[release notes on GitHub](https://github.com/Hapoyo/LiquidMouse/releases).
