# Changelog

All notable changes to Liquid Mouse. Versions follow `liquidmouse/version.py`; each one is
published on [Releases](https://github.com/Hapoyo/LiquidMouse/releases) with its executable.

## Unreleased

Security and robustness pass from a full code review, plus follow-ups.

- **WebSocket Origin check** — the four WebSocket servers now refuse browser handshakes whose
  `Origin` is not localhost, a numeric LAN/WAN IP or `*.trycloudflare.com`. A web page open on
  the PC or on the phone can no longer drive the loopback session (terminal, keyboard, SFTP),
  and DNS rebinding with an arbitrary hostname is rejected. Clients without an `Origin`
  (smoke test, desktop terminal window) are unaffected.
- **SFTP password no longer follows a changed host** — saving a profile with a different host,
  port or user and an empty password now drops the stored password instead of keeping it, so a
  client could not make the PC send it to another server.
- **A wrong PIN is not retried on wake-up** — the phone page no longer reconnects when it
  returns to the foreground after an authentication error (five wake-ups used to lock the IP).
- **Remote keepalive and start-up survive errors** — an exception in the UPnP/tunnel refresh no
  longer stops the keepalive or the servers, and a busy port is reported with its real number
  without tearing down the ones already running.
- **Limits** — at most 8 terminal sessions, bounded text and hotkey length, and a timeout on the
  HTTP handler (slow connections no longer hold a thread forever).
- **Terminal re-attach no longer drops output** — output produced while the snapshot was being
  sent is now delivered right after it, and a slow client no longer blocks other attaches.
- **Emoji and autocorrect** — characters outside the BMP are typed as UTF-16 surrogate pairs
  instead of a wrong private-use character, and the phone keyboard diff uses the common prefix,
  so autocorrect and predictive text replace words correctly.
- **Malformed PIN handshake** — a non-object JSON or a non-string PIN counts as a failed attempt
  instead of dropping the connection with a traceback.
- **Atomic writes** — uploads go to `name.part` and are renamed when complete (an interrupted
  upload keeps the original file); `config.json` is written through a temporary file, so a crash
  cannot leave it empty and lose the PIN.
- **cloudflared is verified** — the downloaded tunnel binary is checked against the SHA-256 that
  the GitHub release publishes before it replaces anything, and the copy in
  `%APPDATA%/LiquidMouse/bin` is now preferred over one found in `PATH`.
- **CI and dependencies** — `requirements.txt` with the real minimum versions (websockets 14
  for the new asyncio API), tests also run on `windows-latest` with Python 3.10 and 3.13,
  Dependabot for pip and GitHub Actions, and the unused `websockets.legacy` hidden imports are
  gone from the PyInstaller spec.
- **PIN and TLS key encrypted at rest** — `config.json` no longer stores the PIN or the
  certificate's private key in clear: they are protected with Windows DPAPI, like the SFTP
  passwords (the PIN hash is kept for comparison). An old config is read and rewritten
  encrypted on first start; the PIN stays the same, so phones already set up keep working,
  and the certificate the browser accepted stays valid. Where DPAPI is missing (Linux, tests)
  nothing changes; if a secret cannot be decrypted (config copied to another user or PC) the
  PIN or certificate is regenerated instead of failing to start.
- **Terminal back-pressure** — every viewer of a terminal session now has its own bounded send
  queue and sender task: a slow phone no longer stalls the PTY read loop or the other viewers,
  and a viewer that falls more than 1 MB behind is disconnected (the client reconnects and
  re-attaches from the ring buffer). Input is written to the PTY in a dedicated thread, in
  order and with a bounded backlog, and the ConPTY backend now completes partial `WriteFile`
  calls and reports write errors. PTY reads, PTY writes, SFTP and UPnP each run on their own
  thread pool instead of the shared default one, and the idle poll of the pywinpty backend backs
  off from 10 to 50 ms while the shell is silent.
- **Faster, safer asset serving** — assets are gzipped once at start-up and served with
  `Accept-Encoding` (xterm.js goes from 283 KB to about a quarter of that over the 4G link);
  `index.html` references every file as `?v=VERSION`, and versioned URLs plus the fonts are sent
  with `Cache-Control: max-age=31536000, immutable`, so a returning phone only revalidates the
  page itself (`no-cache` + ETag, a different ETag for the gzip variant). Every response now also
  carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options:
  DENY` and a Content-Security-Policy. The three inline `onclick` handlers of the tab bar moved
  into `app.js`, so `script-src` is just `'self'`. `style-src` still allows `'unsafe-inline'`
  (xterm.js injects `<style>` elements and a few `style=""` attributes remain): moving to nonces
  or hashes is a follow-up. `motion.js` was already `defer` (non-blocking), so it is unchanged.
- **Network change while running** — the keepalive now re-evaluates the PC's LAN address every
  30 s. If it changes (other Wi-Fi, new DHCP lease) the UPnP mapping is redone towards the new
  address right away, the TLS certificate is regenerated with the new SAN and reloaded into the
  running HTTPS/WSS servers, and the LAN QR code and address in the window are redrawn. A loss
  of network (loopback) is ignored until a real address returns.
- **LAN touchpad is available sooner** — the LAN WebSocket (and the tunnel origin) now open
  first; the RSA key generation (first start only), the UPnP discovery and the remote servers
  follow, so the phone no longer waits on "connecting" for those few seconds.
- **Choose the terminal shell** — the "nuova sessione" card now has a drop-down instead of the
  single `cmd` button: `cmd.exe`, PowerShell, `pwsh`, WSL, `bash` and `claude`, limited to those
  found on the PC. The list comes from the server (`shells` in `term_sessions`, same source as
  the command whitelist, which stays the authority), so the client never offers or sends
  anything the server would refuse; the last choice is remembered on the phone.

## 2.9.0 — 2026-10-04

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
