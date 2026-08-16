---
name: diagnosing-yt-dlp-download-failures
description: Use when a yt-dlp download in ytdl-hoarder fails, comes back empty/zero-byte, or throws "Signature solving failed", "Requested format is not available", repeated HTTP 403s, or rate-limit-like blocking — before assuming it's a player-client misconfiguration. Also use when a video is stuck/deferred as "not released yet" / "still processing after live stream" (post-live) though it looks available — a release-detection gate, not a download failure.
---

# Diagnosing yt-dlp Download Failures

## Overview
ytdl-hoarder wraps yt-dlp; downloads can fail for several independent reasons — a missing/stale Deno JS runtime, a stale yt-dlp/yt-dlp-ejs pin, rate limiting, or player-client selection. Player-client tweaking is only one possible fix and is usually NOT the root cause — check cheaper causes first.

## When to Use
- Downloaded file is empty / zero bytes
- Error: `Signature solving failed`
- Error: `Requested format is not available` (often appears right after the above)
- Many downloads across different videos/channels failing the same way (looks like blocking/403s)
- About to change `player_client` order as the first troubleshooting step

**NOT for** `not released yet` / `still processing after live stream` deferrals — that's release-detection, not a failure. See the next section.

## Not a Download Failure: post-live / "still processing" deferrals

`Deferring … — not released yet: Video is still processing after live stream` (also "currently live" / "upcoming premiere") is **not** a yt-dlp failure — it's ytdl-hoarder's release-detection gate (`is_video_ready_for_download`, `backend/app/ytdlp/info.py`) deliberately deferring. Skip the download-failure checklist below.

**The trap:** `post_live` is NOT proof the VOD is unavailable. yt-dlp keeps a finished livestream flagged `live_status=post_live` for hours/days after a complete, downloadable VOD already exists — `availability` can read `public` and the video be fully watchable meanwhile. So "still `post_live` → just wait" is usually WRONG for a stream that ended more than a few minutes ago.

**Diagnose by FORMATS, not `live_status`** — checking `live_status`/`availability` alone is exactly the misdiagnosis this section prevents:
```
yt-dlp -F --skip-download "<url>"
```
A normal resolution ladder with DASH VOD formats (`http_dash_segments`, e.g. `137`/`136`/`135`…) — not just a bare live `m3u8` — means it IS downloadable despite the `post_live` label. **Zero** real audio/video formats → genuinely still processing; the deferral is correct, wait.

The gate treats `post_live` as ready once real formats exist (only genuine live/upcoming, or a just-ended stream with no formats yet, stays deferred). A build that blanket-defers *any* `post_live` regardless of formats is running stale **ytdl-hoarder app code** (this is app logic in `ytdlp/info.py`, not a yt-dlp version) — rebuild/restart the backend to pick up the current gate. A stuck NOT_READY item clears on the next subscription scan (~10 min) or via manual Retry; no DB surgery.

## Diagnostic Checklist (cheapest to most involved)

Checks below state *requirements*, not today's pinned values — pinned versions drift every time someone bumps a dependency and this file doesn't auto-update. Always read the current value from the named file, don't trust a memorized number.

1. **Deno runtime.** `docker exec <container> deno --version` — requirement: ≥2.3.0, auto-discovered from PATH. Pin lives in `Dockerfile.prod` (`DENO_VERSION` ARG, one place for both the prod and dev images) — check that file for the current pinned value. Missing/too-old Deno is the actual cause of `Signature solving failed` cascading into `Requested format is not available` — not player-client.
2. **yt-dlp-ejs present.** Declared transitively via `yt-dlp[default]` in `backend/pyproject.toml` — check `backend/uv.lock` for whether it's resolved/present. No specific version requirement documented; just needs to exist alongside Deno for challenge solving to work at all.
3. **yt-dlp itself current.** Requirement: ≥2025.11.12 for JS-runtime challenge solving to exist at all (per CLAUDE.md). Check `backend/pyproject.toml` for the actual pinned floor. Rebuild the image to update — README.md already gives this as the one-line fix for empty downloads.
4. **Blanket vs isolated.** Same error across many unrelated videos → points to Deno/yt-dlp (steps 1-3). Failure on one specific video/channel only → likely video-specific (region lock, DRM, age-gate without cookies), not systemic.
5. **Rate limiting.** Repeated blocking/403-style failures across sequential downloads → three `app_settings` knobs, all editable in the Settings UI, defaults in `backend/app/models.py` `APP_SETTINGS_DEFAULTS`. Reach for them in this order:
   - `request_sleep_seconds` (default 0) → yt-dlp `sleep_interval_requests`. Try 1–2 first: it paces the request *pattern*, which is what bot detection keys on, and it is the only one of the three that also covers metadata extraction (set in both `ytdlp/options.py` and `ytdlp/info.py`). Costs channel-enumeration speed. Server-capped at 60.
   - `download_sleep_seconds` (default 60) → a Python sleep between jobs, and **only for subscription/playlist downloads** — `_rate_limit_sleep` (`backend/app/tasks/downloads.py`) returns early for one-offs, so raising it does nothing for a manually-submitted URL.
   - `download_rate_limit_kbps` (default 0 = unlimited) → yt-dlp `ratelimit`, converted to bytes/sec. Weakest lever of the three; per job body, so N parallel downloads use N × the cap. Ignored when a format falls through to the ffmpeg downloader.
6. **Player-client, last.** Defaults (`DEFAULT_PLAYER_CLIENTS` / `DEFAULT_COOKIES_PLAYER_CLIENTS`, `backend/app/models.py:100,105`) only seed *new* `app_settings` rows — an existing instance keeps its stored DB value; editing `models.py` never retroactively fixes a running install. Change the live value via Settings UI (`PUT /settings`, validated against `VALID_PLAYER_CLIENTS` in `backend/app/routers/settings.py:139-146`). Consumed in `backend/app/ytdlp/options.py:161-170` (metadata) and `:504-511` (download). Watch for clients yt-dlp removed upstream (e.g. `tv_embedded`) — a stored list still referencing one looks like "misconfiguration" but the fix is deleting the stale name. `player_client` is DB-only — it is not in `config.yml`/`config.sample.yml`.

## Quick Reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `not released yet` / `still processing after live stream` (deferred, not a failure) | Lingering yt-dlp `post_live` flag on a finished stream — VOD actually downloadable | Not a download failure — `yt-dlp -F` shows real formats; the release gate downloads once formats exist |
| `Signature solving failed` | Deno missing/too old, or yt-dlp-ejs missing | Verify Deno ≥2.3.0 in container; rebuild image |
| `Requested format is not available` right after a sig failure | Downstream of signature-solving failure | Fix Deno/yt-dlp first, don't touch player_client |
| Empty/zero-byte file | Stale yt-dlp in image | Rebuild image |
| Many videos failing the same way, 403-like | Rate limiting | Raise `request_sleep_seconds` to 1–2 in Settings first, then `download_sleep_seconds` / `download_rate_limit_kbps` |
| One stored client is invalid/rejected | Stale/removed client name in DB, not `models.py` defaults | Fix via Settings UI / `PUT /settings` |
| One video/channel fails, others fine | Video-specific (region, DRM, age-gate) | Not a config issue |

## Common Mistakes
- Reordering `player_client` before checking Deno — the recurring mistake this skill exists to prevent.
- Assuming a `models.py` default change fixes a live instance (it doesn't; DB value is separate).
- Looking for `player_client` in `config.yml` — it's DB-only (`app_settings` table).
- Treating `Requested format is not available` as root cause when it's usually downstream of a signature failure.
- Treating a `post_live` / "still processing after live stream" **deferral** as a download failure OR as "correctly still processing, just wait" — a finished stream keeps the `post_live` flag for hours/days while a complete VOD exists. Check `yt-dlp -F` for real formats instead of trusting `live_status`/`availability`.
- Do not repeat "Only images available" as an observed error string — it does not appear in this codebase or docs; treat any user mention of it as unverified.

## Key Files
- `Dockerfile.prod` — Deno version pin (`DENO_VERSION` ARG); builds both the prod and dev images
- `backend/uv.lock` — yt-dlp-ejs pin; `backend/pyproject.toml` — yt-dlp version floor
- `backend/app/models.py:82-105,618-625` — `VALID_PLAYER_CLIENTS`, defaults, `APP_SETTINGS_DEFAULTS`
- `backend/app/routers/settings.py:139-146` — `PUT /settings` validation
- `backend/app/ytdlp/options.py:161-170,504-511` — where player_client is applied
- `backend/app/ytdlp/options.py` `_throttling_options` — the throttling knobs' single conversion point for downloads; `ytdlp/info.py` sets `sleep_interval_requests` separately for metadata
- `backend/app/ytdlp/info.py` — `is_video_ready_for_download` + `_has_downloadable_formats` release-detection gate (live/upcoming defer; post-live defers only when no downloadable formats yet)
- `CLAUDE.md:229-230`, `README.md:186` — existing condensed notes (this skill goes deeper)
