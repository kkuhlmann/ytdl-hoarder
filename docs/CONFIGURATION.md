# Configuration reference

[`config.sample.yml`](../config.sample.yml) is the authoritative annotated reference for every
application setting. This document covers the settings that need more explanation than a comment
allows: live runtime settings, the throttling knobs, and dev-mode networking.

## Where settings live

`config.yml` is the single source of application settings. `.env` is Docker Compose's variable file
and is never read by the application; it holds only values consumed outside the backend process:

| Variable | Consumed by | Purpose |
|---|---|---|
| `AUDIO_ONLY_PATH`, `VIDEO_PATH` | Compose | Host media directories, resolved before the container exists |
| `YTDL_HOARDER_IMAGE`, `YTDL_HOARDER_TAG` | Compose | Which image and release to run |
| `NEXT_PUBLIC_BACKEND_API` | Next.js dev server | Overrides the API address the dev UI calls (dev mode only; normally empty) |
| `ALLOWED_DEV_ORIGINS` | Next.js dev server | Extra hosts permitted to reach dev resources |
| `FORWARDED_ALLOW_IPS` | uvicorn | Proxy addresses whose `X-Forwarded-For` is trusted |

Settings can also be supplied as environment variables in double-underscore notation (for example
`TRANSCRIPTION__WHISPER_MODEL=small.en`), but they apply only to keys `config.yml` leaves unset — a
key present in `config.yml` always wins. Under Docker they must additionally be added to the compose
file's `environment:` block to reach the container at all.

## Live settings (Settings tab)

These are stored in the database rather than `config.yml`, are edited from the **Settings** tab, and
take effect on the next task without a restart.

**Subscription Check** is the interval in minutes between subscription scans, from 1 minute to a full
day. Slots are clock-aligned from midnight, so 15 fires at :00/:15/:30/:45 and 120 fires on every
even hour.

**Task concurrency** applies immediately. Raising a lane starts queued work right away; lowering one
lets the jobs already running finish rather than cancelling them. Raising the *Downloads* lane above
1 means the download delay no longer paces the application as a whole, increasing the risk of YouTube
rate limiting. Raising the *ML* lane runs several transcriptions at once, each loading its own
Whisper model.

Also editable live: temp-file cleanup age, yt-dlp player-client order, transcript chunking, and table
page sizes.

## Throttling

Three settings exist specifically to avoid being flagged by YouTube. All three are off or mild by
default.

- **Download Sleep** — seconds to wait between downloads. Applies to subscription and playlist
  downloads only, not one-off submissions. Default 60.
- **Speed Limit** — caps each download's speed in KB/s; `0` means unlimited. It applies *per
  download*, so with the Downloads lane above 1 the total is that many times the limit.
- **Request Sleep** — seconds to wait between the HTTP requests yt-dlp makes while reading metadata;
  `0` disables it. This is usually the more effective of the two against bot detection because it
  paces the request *pattern* rather than the bytes, but it also slows channel and playlist scanning.
  Start at 1–2 seconds.

Adjust these only after ruling out the cheaper causes in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#downloads). An out-of-date image is a far more common culprit
than throttling.

## Release pinning

`YTDL_HOARDER_TAG` in `.env` defaults to `latest`. Pin it (for example `v0.1.0`) to hold a version
through updates. Pinning *backwards* to an older release after a newer one has run its database
migrations may fail to start, since migrations are not guaranteed reversible — back up with
`task db:backup` first. The variable is read only by `docker-compose.published.yml`; the
build-from-source modes ignore it.

## Dev-mode networking

**Dev mode needs no configuration to be reached from another device.** Open
`http://<the-docker-host>:3000` from a phone, a laptop, a LAN IP, a Tailscale name or a domain and it
works — nothing to declare up front, and no rebuild. Prod and published were always like this, since
they call the API through a same-origin `/api` path; dev now matches them.

Three things make that true, and each has an escape hatch if your setup is unusual.

**The API address follows your browser.** Dev serves the UI on port 3000 and the API on port 8000, so
the frontend has to name a host. It derives one from the address you actually browsed to, so the same
dev server answers correctly on every address the machine has. Set `NEXT_PUBLIC_BACKEND_API` in `.env`
only when the API is *not* on port 8000 of that host — behind a reverse proxy, or with TLS terminated
in front. It is read when the dev server starts, so a change takes effect on:

```bash
docker compose -f docker-compose.dev.yml up -d frontend
```

**Credentialed cross-origin calls are allowed from anywhere.** Because every dev API call is
cross-origin, `auth.allowed_origins` in `config.yml` defaults to empty, which means any origin. The
auth cookie is `SameSite=lax`, so a foreign website still cannot make a credentialed request to your
API — that, rather than this list, is what keeps other sites out. To enforce a strict allowlist
anyway, list full origins including the port (`http://192.168.1.50:3000`) and restart the backend.
The production image serves the frontend same-origin and ignores the setting entirely.

**Hot reload works from any dotted host.** Next.js 16 refuses cross-origin requests to dev-server
resources unless the host is allowed, which otherwise leaves the page loading but never updating on
edit. Every dotted host is allowed — LAN IPs, `.local` names, Tailscale MagicDNS, domains — as is
`localhost`. Two shapes cannot be covered by any wildcard Next accepts: a **single-label hostname**
like `http://nas:3000`, and an **IPv6 literal**. Add those to `ALLOWED_DEV_ORIGINS` in `.env`
(comma-separated, hostnames only — no scheme or port), then restart the frontend service.
