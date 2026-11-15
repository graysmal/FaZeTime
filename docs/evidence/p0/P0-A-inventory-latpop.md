# Capability record — primary laptop inventory (P0-A)

- Capability / owning phase: host inventory for machine-role assignment (P0-A; owner question 2)
- Host alias: `latpop` — ASUS Vivobook 16 X1605ZA. Role: not yet assigned
- Checked at: 2026-11-14 20:12–20:20 CST by the coordinator, using read-only local commands
- OS / arch: Ubuntu 24.04.5 LTS, kernel 7.0.0-42-generic, x86_64
- CPU: Intel Core i5-1235U (2P + 8E cores, 12 threads, 4.4 GHz max), AVX2/FMA/F16C. This is a 15 W-class mobile part, so expect thermal throttling under sustained load
- GPU: Intel Iris Xe (Alder Lake-UP3 GT2) only. No NVIDIA/CUDA
- RAM: 38 GiB total (about 26 GiB available at check time), 8 GiB swap
- Disk: 189 GB free of 492 GB
- Power: on AC, battery 100%. GNOME suspends after 3600 s idle on AC. Disable this, or run long captures and rehearsals under `systemd-inhibit`
- Network: Wi-Fi on a private /16 network (venue or campus); client isolation not tested. The Tailscale client is online. The tailnet lists another online Linux device named `fazetime`; its role is unconfirmed and it was not contacted
- Tools:
  - Python 3.12.3 (system); 3.11.13 and 3.10 via uv; uv 0.13.6
  - Node v25.2.1 (default) and v24.22.2 via nvm; npm 11.14.1; no pnpm
  - ffmpeg/ffprobe 6.1.1 (Ubuntu); OBS Studio 32.2.0 (obs-websocket not configured)
  - Docker 29.9.3; cloudflared 2025.6.1; git 2.43.0; gh 2.99.0; Claude Code 2.1.289
  - Python sqlite3 library 3.45.1 (no sqlite3 CLI)
  - Missing: streamlink, Stripe CLI
- Browsers:
  - Google Chrome 157.0.8103.78 is installed as a Flatpak (`com.google.Chrome`). Firefox 155 is a snap. `/usr/bin/chromium-browser` is only the snap stub; Chromium is not installed
  - Flatpak Chrome can read only host-etc and the XDG Downloads/Documents/Music/Pictures/Videos folders. It cannot load an unpacked extension from `~/Projects` unless the owner grants a Flatpak filesystem override, or the build output is copied to `~/Documents`
- Twitch page policy (signal for P0-F and owner question 5): `GET https://www.twitch.tv/` returned `X-Frame-Options: SAMEORIGIN`, with no Content-Security-Policy header and no CSP meta tag (checked 2026-11-14 ~20:15 CST). So Twitch's page policy would probably not block an injected frame. This does not show that a hosted iframe's auth or cookies work
- Real smoke test: none yet; this is inventory only. Capture and ASR benchmarks on this host are in progress under `spikes/p0-media/`
- Status: VERIFIED for the inventory facts above. Throughput, thermal behaviour and network reachability: UNVERIFIED

Contains no credentials, IP addresses or phone numbers.
