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
| `NEXT_PUBLIC_BACKEND_API` | Next.js build | API URL compiled into the frontend bundle (dev mode only) |
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

`NEXT_PUBLIC_BACKEND_API` tells the frontend where to find the API. It matters only in dev mode: it
is compiled into the JS bundle at *build time*, not read at runtime, so editing `.env` alone has no
effect until the frontend is rebuilt.

If the UI is only ever opened from the machine running Docker, the default `http://localhost:8000` is
correct and `setup.sh` does not prompt for it. When running dev mode on a server and connecting from
another device (phone, laptop, LAN IP, domain), `setup.sh` asks for that address when dev mode is
selected and rebuilds automatically. To set it manually later, edit `.env` and run:

```bash
docker compose -f docker-compose.dev.yml up -d --build frontend
```

Setting it by hand also requires adding the address you browse to (port 3000) to
`auth.allowed_origins` in `config.yml`. Dev mode calls the API cross-origin and only listed origins
may send credentials. `setup.sh` adds it automatically.

The same variable controls **hot reload** from another device. Next.js 16 blocks cross-origin
requests to dev-server resources unless the host is explicitly allowed, so opening the dev UI as
anything other than `localhost` — a LAN IP, a Tailscale name, a reverse proxy — otherwise leaves the
page loading but never updating on edit. The allowed list is derived from `NEXT_PUBLIC_BACKEND_API`
automatically. If the UI is reached on a different hostname than the API, add the extras to
`ALLOWED_DEV_ORIGINS` in `.env` (comma-separated hostnames). `localhost` is always allowed.

The published and prod modes have neither issue: they call the API through a same-origin `/api` path,
so any address works with no configuration, and they are static exports with no dev server.
