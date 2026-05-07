# Cloudflare Tunnel for Remote Access

This folder gives Ratan's Private Battery Manager a public URL so the UI
can be opened from a phone or another laptop, while the actual Flask
server keeps running on the Windows machine.

## Files

- **`start-all.bat`** — double-click after a reboot to relaunch Flask + tunnel together. Writes the current public URL to `tunnel-url.txt`.
- **`cloudflared.exe`** — the tunnel binary (62 MB, gitignored — re-download with `curl -L -o tunnel/cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe`).
- **`credentials.json`** — your auth username + password (gitignored — keep secret).
- **`tunnel-url.txt`** — the current public URL (gitignored, regenerated on each restart).
- **`tunnel.log` / `flask.log`** — process logs (gitignored).

## How it works

```
   Phone / browser anywhere      ←─ HTTPS ─→     Cloudflare edge
                                                       │
                                                       │  encrypted tunnel
                                                       ▼
                                   Windows laptop  ──→  Flask :5000  ──→  YRCARKIT data
```

- Cloudflared opens an outbound connection from Windows → Cloudflare. No firewall changes needed.
- Cloudflare edge serves a `*.trycloudflare.com` URL that proxies to your local Flask.
- HTTP basic auth in `app.py` is enforced for any request that has `X-Forwarded-For` or `Cf-Connecting-IP` headers (= came from the tunnel). Localhost requests skip auth so the laptop user isn't prompted.

## Quick Tunnel quirks

- The URL is **random** and changes on every restart of `cloudflared.exe`. To get a stable URL, sign up for a free Cloudflare account and create a Named Tunnel — see Cloudflare docs.
- One free TCP connection — fine for personal use.
- Free tier — no charge.

## Auth

Username / password live in `credentials.json` (chmod-restricted, gitignored). Your browser will prompt once and remember the credentials.

To change the password:
1. Edit `tunnel/credentials.json`
2. Restart Flask: kill the python process, run `python -m battery_ui.app`

To disable auth entirely (NOT recommended when tunnel is exposed):
- Delete or rename `tunnel/credentials.json`. Flask reads it on every request — absent file means no auth.

## After a Windows reboot

1. Double-click `start-all.bat`
2. Read the public URL from the popup or from `tunnel-url.txt`
3. Open it on your phone with the saved username/password
