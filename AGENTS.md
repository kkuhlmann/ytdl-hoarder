# AGENTS.md

Guidance for AI coding agents working in this repository.

`README.md` covers what the app does and how an end user installs it — read that for the feature
tour. This file covers what you can't get by reading the code: invariants, traps, and the reasons
behind non-obvious choices.

## Architecture

### Backend (`backend/app/`)

`database.py` keeps **dual async/sync engines**: async for FastAPI and the orchestrator control
plane, sync for job bodies running in lane threads and in the ML child process.

**Orchestrator** (`orchestrator/`) — in-process engine for all background work. The parts you wouldn't
get from the filenames:
- `lanes.py` - pop order `(priority, queue_sequence)`, ties by submission order
- `wrapper.py` - `run_job_sync`: before_start → body → on_success/on_cancel/on_retry/on_failure, NOT_READY guard, never-overwrite-CANCELLED guard, downstream chaining
- `recovery.py` - startup recovery rebuilds lanes from TaskRecord truth, since Postgres is the only durable task state; plus the due-retry loop
- `subprocess_runner.py` / `child_main.py` - spawned child for transcription; faster-whisper/ctranslate2 load **only there**, so it's SIGTERM-cancellable and memory is reclaimed per job

**Tasks** (`tasks/`) — job bodies are plain functions taking `(ctx, payload)`; `registry.py` wires
bodies/lanes/hooks/policies via `register_all_jobs()`.

`__init__.py` re-exports job bodies and deliberately does **not** import `tasks.transcription` —
that keeps faster-whisper out of the main process.

**`tasks/media.py` — the deferral rules.** Unreleased videos get a visible NOT_READY placeholder
TaskRecord (upserted per URL at populate time, soft-deleted and replaced by a QUEUED chain once the
video airs). "Unreleased" = live or upcoming premiere, or a finished livestream still flagged
`post_live` **whose VOD formats aren't available yet** — yt-dlp can keep `post_live` set for hours
or days after a downloadable VOD exists, so `is_video_ready_for_download` (`ytdlp/info.py`) allows
post-live once real formats are present.

**A deferral also persists a `NOT_READY` `MediaDetails` row** (`_defer_media`) carrying the expected
`release_timestamp` and a `next_check_at`, because the TaskRecord placeholder alone is invisible to
the subscription filter — which keys on `MediaDetails`, so without the row every premiere and every
unavailable video is re-fetched on *every* tick forever. `next_check_at` is a known future premiere
time, else an age-keyed ladder; `_evaluate_not_ready_media` honours it, except for direct downloads,
which always bypass the backoff. Two ladders: a short one for unreleased videos, a much longer one
for videos yt-dlp *positively* reports as gone. `get_url_info` swallows every failure into a `None`,
so `get_url_info_with_failure` + `classify_extraction_error` decide which — and the long ladder is
opt-in by whitelist, since a 429 or bot-check is otherwise indistinguishable from a private video and
parking a rate-limited channel for a week is the worse error.

**Three places must never accept a deferred row as resolved**, or an unreleased video downloads early
using its premiere metadata: the reuse branch and the pre-fetched-metadata shortcut in
`_use_pending_or_fetch_fresh` (both bypass the yt-dlp fetch, hence the readiness check —
`_reuse_or_delete_existing_media` blocks both at once), and the upsert on the way back out. Deferred
rows are updated in place, never delete-and-recreated like SKIPPED: the delete would reset
`created_at`, which the ladder reads. Clearing needs the explicit `sync_clear_deferral` because
`_copy_upsert_fields` refuses to write `status` when it is `NONE`.

`services/embeddings.py` — `OnnxEmbedder`: all-MiniLM-L6-v2 on onnxruntime, replacing sentence-transformers so
**torch is not a dependency at all** (~1 GB off the venv). onnxruntime/tokenizers/huggingface-hub were
already present for faster-whisper's Silero VAD. Reproduces the sentence-transformers pipeline exactly
— transformer → attention-masked mean pool → L2 normalize — so vectors stay interchangeable with those
written by the old torch build (measured: max component delta 2.3e-07, cosine 0.9999999, identical
result ordering). Two things are load-bearing: `max_seq_length` comes from the repo's
`sentence_bert_config.json` (**256**, not the tokenizer's 512 — getting it wrong silently shifts
embeddings), and the ONNX feed dict is filtered by `session.get_inputs()` since exports differ on
whether `token_type_ids` is declared. `resolve_model_repo` hard-rejects any model but
all-MiniLM-L6-v2; a different model means a different vector space, so allowing one would silently
invalidate every stored embedding.

**Models** (`models.py`) — the constraints worth knowing before you write a query:
- `Tag` unique per `(user_id, name)`; `MediaTag` unique per `(user_id, media_details_id, tag_id)`
- `MediaRating` one per `(user_id, media_details_id)`, 1–5 enforced by a CHECK constraint
- `MediaAccess` carries a source type: DIRECT, PLAYLIST, SUBSCRIPTION
- `User` also holds the recovery columns: `password_reset_requested_at`, `must_change_password`, `password_changed_at`, `recovery_code_hash`, `recovery_code_expires_at`

**Repositories** (`repositories/`) — two non-obvious bits:
- `task_records/` is a package: `crud.py` (async), `retry.py` (downstream marking + retry/dispatch), `sync_ops.py` (sync, for job bodies), `bulk.py`. `__init__.py` re-exports the externally-used names so `from repositories import task_records` keeps working
- `base_access.py` is a factory — `create_access_functions()` generates share/unshare/has_access for the *three* structurally identical access repos (subscription, playlist, clip). **`media_access.py` is hand-written and cannot join them**: `MediaAccess` is unique on `(user_id, media_details_id, source_type, source_id)`, not `(user_id, fk)`, so one user legitimately holds several rows for the same media and revoking one source must leave the others standing. Every factory signature is 2-arg and its bulk insert hardcodes `index_elements=['user_id', fk]` — wrong constraint, wrong arity. The provenance columns are also what the extra surface exists for: source-scoped revokes, `has_direct_access`, and `get_transfer_candidate_user_ids` (ownership transfer on owner-delete, ordered DIRECT > SUBSCRIPTION > PLAYLIST). Note the owner check reads `MediaDetails.owner_id`, not the `user_id` the factory assumes

**Routers** (`routers/`) — one per domain, named for the prefix they mount. Two things you wouldn't
guess: `/media-details` also owns **tags and ratings** (they have no router of their own), and its
keyword `search` supports `&&` / `||` operators (parsed in `_build_search_condition`,
`repositories/media_details.py` — `&&` binds tighter than `||`, and single `&` / `|` are literal).
`/health` is inline in `main.py`.

**`/semantic/search` is scoped by the same `_build_media_conditions` the media list uses**, so the
group-folder drill-down, tag chips, minimum rating and the keyword box all narrow which transcripts
are searched. `transcript_embeddings` has no ORM model, so the bridge is
`build_media_scope_subquery`, which compiles those conditions to a SQL fragment spliced into the raw
`text()` queries. Four things there are load-bearing:
- **The compiled fragment's bind names must stay disjoint from the ones the search builders bind by
  hand** (`query`, `embedding`, `limit`, `fts_query`, …); `test_transcript_scope_sql.py` pins it.
  `literal_binds` would remove the problem and add an injection hole — the search string is user
  input.
- **It passes `include_owned=True`.** A soft delete calls `remove_all_access_for_media`, which drops
  every `MediaAccess` row *including the owner's*, so the access subquery alone hides an owner's own
  kept transcripts from them. This is the same gap the list closes with its `owner_id` fallback for
  DELETED/SKIPPED.
- **`status` is deliberately not threaded.** Transcript search spans every status, and passing one
  would also swap that widened access branch back to the narrower `owner_id`-only one.
- **A narrow scope runs through a `MATERIALIZED` CTE specifically to deny the planner the HNSW
  index.** pgvector post-filters an index scan, so a scoped `ORDER BY embedding <=> :q LIMIT n`
  returns far fewer rows than asked — an empty result, not an error — which is exactly what drilling
  into a group folder produces. Flattening that CTE back into the outer query reintroduces it
  silently. Above `_EXACT_SCOPE_MEDIA_LIMIT` media the filter is no longer narrowing enough to beat
  the index, so the index path stays; one `count_scoped_media` query picks between them and
  short-circuits an empty scope before an embedding is ever computed. No dataset a test can seed
  makes the planner choose the index path, so `test_scoped_vector_cte_is_materialized` pins the
  keyword rather than the behaviour.

### Frontend (`frontend/app/`)

**Toolchain** — upgraded July 2026; the non-obvious parts:
- **Turbopack is the builder** for both `next dev` and `next build`. `--turbopack` is the default in 16, not a flag.
- **Lint is flat config only**: `eslint.config.mjs` + `"lint": "eslint ."`. `next lint` was removed in Next 16 and `.eslintrc.json` is gone — don't reintroduce either.
- **`noUnusedLocals` + `noUnusedParameters` are on**, and `next build` type-checks, so an unused import is a *build failure*, not editor noise.
- **`tsconfig.json` pins `"target": "ES2022"` with an explicit `"useDefineForClassFields": false`.** The second flag looks redundant and is not: Next passes `Boolean(compilerOptions.useDefineForClassFields)` straight to SWC and never derives it from `target`, so a bare `ES2022` would leave tsc assuming define-semantics the emitter doesn't produce. Leave it.
- **Node 24** is the pinned build version in both `frontend/Dockerfile` and `Dockerfile.prod`'s frontend-builder.
- **Next 16 enforces `allowedDevOrigins`** (advisory in 15): cross-origin requests to `/_next/*` and HMR are blocked unless the host is listed. `next.config.js` derives it from `NEXT_PUBLIC_BACKEND_API`, with `ALLOWED_DEV_ORIGINS` (comma-separated) as the escape hatch. Prod is a static export and unaffected.
- **Tailwind is v4 and CSS-first — there is no `tailwind.config.ts`.** The theme lives in an `@theme inline` block at the top of `app/globals.css`; `components.json` carries `"config": ""` to say so. Four things there are load-bearing and easy to undo by accident:
  - **`inline` is mandatory.** It makes each utility emit the *runtime* variable (`.bg-matrix` → `background-color: var(--matrix-green)`) instead of a copy resolved once at `:root`, which is the only reason the 92 `[data-theme]` blocks can still repaint the app. Note `inline` does **not** suppress the `:root` copy of a theme variable — it only changes what utilities reference.
  - **Theme keys must not share a name with a runtime var.** Identical names emit `--x: var(--x)` at `:root`. The theme blocks' shadow vars are called `--glow*` purely so the `--shadow-glow*` keys have something distinct to point at. No `--font-sans`/`--font-mono` keys exist for the same reason — v4 defines both by default and the unlayered theme blocks already override them.
  - **The radius scale is deliberately non-monotonic** (`--radius-xs` > `--radius-sm`). v4 shifted every rounding class one step down (`rounded` → `rounded-sm`), so the values shift one step up to cancel it out and keep the v3 pixels. Don't "fix" it without re-checking 58 call sites across all 92 themes.
  - **v4 emits real `@layer` at-rules; v3 did not.** Unlayered CSS now outranks every Tailwind utility regardless of specificity. The theme blocks, the `.rdp-*`/`.slider-matrix` overrides and the mobile-zoom rule at the bottom of `globals.css` all depend on staying unlayered — moving any of them into a `@layer` silently breaks it. This is also why that mobile rule no longer needs `!important`.
- **`@source` paths in `globals.css` are relative to that file**, i.e. to `frontend/app/` — so it is `../components`, not `../../components`. Combined with `source(none)` they replace v4's automatic detection, which would otherwise walk up to the repo root and scan `backend/`. Get one wrong and those files' classes are silently dropped from the build.

**Components with constraints worth knowing** (the rest are named for what they do):
- `AuthGuard.tsx` gates on `must_change_password` → `ForcePasswordChange.tsx`, mirroring the server-side gate. `LoginPage` swaps its card body between sign-in and the two recovery panels in `auth/`
- `auth/ChangePasswordDialog.tsx` is opened from the `KeyIcon` in `NavigationBar`, **not** Settings — that tab is `adminOnly` and every `/settings` endpoint requires `get_admin_user_id`, so a non-admin would never reach it. Shares `auth/changePassword.ts` with `ForcePasswordChange`
- `media/MediaClipEditor.tsx` is the single surface behind every scissors action (`media/actions.tsx`), dispatching on `media_type`. Note `MediaListView`'s `onClip` is optional and the scissors button renders regardless, so a new list surface that forgets to pass it gets a **silently dead button**
- `TagMixView.tsx` plays through `MediaPlayerContext` under the sentinel `TAG_MIX_PLAYLIST_ID`, and renders through the same `MediaListView`/`media/columns.tsx` as the library, so mix rows get the library's actions for free

**Hooks** — `useFetchEffect` is the project's data-fetching effect, registered in `eslint.config.mjs`
`additionalHooks` so exhaustive-deps checks it. **There are two hook directories**:
`hooks/useTaskProgress.ts` (SSE, auto-reconnect with backoff) lives in `app/hooks/`, everything else
in `app/_hooks/`.

`useAudioAnalyser.ts` - Feeds the visualizer's `AnalyserNode` by routing the real `<audio>` element through `ctx.createMediaElementSource(el)` (per-element WeakMap-cached graph, since that call may run only ONCE per element; a parallel strong `liveGraphs` list closes contexts whose element has left the DOM, bounding live AudioContexts over a long session). **Desktop-only by design, and that gate IS the iOS protection:** `createMediaElementSource` reroutes the element's native output into the AudioContext, and on iOS the browser suspends that context on screen-lock → **silences lock-screen/background audio**, with no way to un-route the element. So `getOrCreateGraph` calls `isDesktop()` (UA-based iOS/iPadOS detection + `(pointer: coarse)`) and returns null on any iOS or touch device — no AudioContext is ever created there, the `<audio>` tag stays plain and untouched, and the visualizer simply stays inert. Tapping the element via `captureStream()` → `createMediaStreamSource` looks like a way to avoid the reroute and keep the graph everywhere; it is not, because WebKit doesn't implement `captureStream` — that route is desktop-only too, minus the explicit gate. **CORS:** the real `<audio>` still needs `crossOrigin="use-credentials"` (`MediaPlayer.tsx`) or a tainted cross-origin element yields zeroed frequency data. `ensureStarted()` (called from the visualizer toggle click) creates/resumes the graph inside a user gesture — outside one the context stays suspended and the audio routes into a silent graph; a `visibilitychange` + `pointerdown`/`touchend` effect resumes it after the browser auto-suspends on tab background. `enabled`/`isPlaying` are mirrored into refs from a **commit-phase effect**, not during render, so the rAF-driven `getBars`/`isActive` read fresh values without re-creating the memoized handle.

## Authentication & Access Control

JWT via HTTP-only cookies. First registered user is auto-admin and auto-approved; the rest need admin
approval. `middleware/auth.py` sets `request.state.user_id` / `is_admin` on every request;
`dependencies.py` enforces optional / required / admin.

**Access control is three-tier:** Owner (`entity.user_id`) → Shared (AccessTable row) → Admin. The
filter is `effective_user_id = None if (admin_view and is_admin) else user_id`, where None means no
filter at all. A shared user's "delete" removes only their own access row; the entity persists for the
owner. Tags and ratings are **per-user, not per-entity** — `Tag`, `MediaTag` and `MediaRating` all
carry `user_id`, so two users sharing a media row keep independent tags and ratings on it.

**Storage limits:** `User.storage_limit_bytes` (nullable, None = unlimited), set via
`PUT /auth/users/{user_id}/storage-limit`, measured from actual files owned by the user.

**Password Recovery** (no email integration exists — every path is trust- or filesystem-based):
- **Session invalidation** is the load-bearing mechanism: `create_jwt_token` stamps an `iat` and the middleware drops any token whose `iat` predates `User.password_changed_at`. That `iat` carries **sub-second precision on purpose** — the change/reset endpoints write `password_changed_at` and then immediately mint the caller's replacement cookie, so whole-second granularity would make the replacement look contemporaneous with the tokens it must displace (and it did: a test caught exactly this). `password_changed_at` starts NULL, so tokens predating the feature survive until that user's next password change.
- **`must_change_password`** is enforced in `get_required_user_id` *and* `get_admin_user_id`, mirroring the `is_approved` gate. Consequence: `/auth/me/change-password` cannot use those dependencies — it reads `request.state.user_id` directly, since it's the endpoint a locked user needs in order to clear the flag.
- **The invariant that decides who gets flagged: a password *generated for* someone else is always temporary; a password someone *chose themselves* never is.** So `POST /users/{id}/reset-password` always sets the flag (it takes no body — there is deliberately no opt-out, and a stale client sending the old `require_change` field can't resurrect one), while `/auth/me/change-password`, `/auth/admin-recovery/complete` and the CLI script clear it. Don't add a "let them keep it" path: it would leave the admin holding a working credential for another user's account indefinitely, which is the whole thing this prevents.
- **Admin recovery** (`services/admin_recovery.py`) writes a single-use code to `/data/admin-recovery.txt` (host `./data/`, the same mount as `BACKGROUNDS_DIR`). The file holds a **code, not an already-applied password** — a live credential there would let any anonymous caller lock the admin out on demand. Requesting while an unexpired code exists is a no-op, so repeat calls can't invalidate a code the admin is mid-way through fetching. A `PermissionError` surfaces the `chown 1000:1000 data/` hint, and because the file write precedes the DB update, a failure leaves no half-issued code.
- Both unauthenticated endpoints (`/auth/forgot-password`, `/auth/admin-recovery/request`) return an identical response for unknown, non-admin, and valid usernames — they must not become username/admin oracles.
- **CLI fallback**: `backend/app/scripts/reset_password.py`, run as `task admin:reset-password -- <user>`. It lives under `backend/app/` because the prod image copies only that directory (`Dockerfile.prod`); the pre-existing `backend/scripts/` dir is bind-mounted in dev and **does not exist in prod**.

**Cancel must write a terminal `MediaDetails.status`** (`mark_download_cancelled` /
`sync_mark_download_cancelled`), from all three cancel paths: `revoke_task`, `bulk_cancel_tasks`, and
`DownloadHooks.on_cancel`. It was the only lifecycle path that didn't — `before_start`/`on_success`/
`on_failure` all write one — so a queued-then-cancelled download kept populate's `NONE`. `NONE` is
absent from `_FILTER_SKIP_STATUSES`, so every later subscription tick re-included the URL and spawned
a populate job that could never produce a download (the CANCELLED `TaskRecord` blocks task creation
via `ACTIVE_DOWNLOAD_STATUSES`) — a permanent per-tick loop growing with every cancellation. Only
in-flight statuses are overwritten, so cancelling a *transcript* task can't disown a finished download.

**`POST /ytdl/` pre-checks `_URL_BLOCKING_STATUSES` and 409s**, rather than letting the pipeline
discover the conflict. That list mirrors every status which makes `_find_duplicate_active_tasks` stand
down, so a submission that gets past it is guaranteed a chain. `CANCELLED` is checked *before* the
ownership split — a cancel holds the URL's slot against whoever asks next, not just the user who
cancelled it — and gets its own message, since the fix is to retry or delete that task rather than to
resubmit. Without this, re-requesting a cancelled URL returned 201 and then did nothing at all.

## Task Orchestrator Architecture

All background work runs inside the uvicorn process via `orchestrator/`. Postgres `task_records` is
the only durable task state. Job registration lives in `tasks/registry.py` (`register_all_jobs()`),
called from the lifespan.

### Lanes

Four lanes (`lanes.py`), each 1 wide by default except `default` at 2. **Widths live in
`app_settings` (one column per lane) and are edited live in the Settings UI**, not in `config.yml` —
the lifespan seeds `orch.start()` from the row via `settings_repo.lane_concurrency`, and every
`/settings` write path re-applies the whole mapping through `orch.set_lane_concurrency`.
`orchestrator/jobs.py`'s `DEFAULT_LANE_CONCURRENCY` is only the no-database fallback; a test pins it
to the model defaults so the two can't drift.

Three constraints on resizing:
- **A shrink is necessarily lazy.** Surplus permits are held by *running* jobs and reclaiming one
  would mean killing its job, so `set_concurrency` only retargets and the dispatcher retires permits
  via `absorb_surplus_permit` as jobs finish. `Lane.capacity` (in the `/tasks/runtime` snapshot) is
  what's actually in circulation and trails `concurrency` until then. When `absorb_surplus_permit`
  returns True the dispatcher must neither dispatch nor release — releasing would undo the shrink.
- **`set_lane_concurrency` is event-loop-thread only**, like every other queue mutation. The settings
  router is `async`, so it already is.
- **`downloads` above 1 changes what `download_sleep_seconds` means** — the sleep is per job body, so
  it stops pacing the deployment as a whole. `ml` above 1 runs a faster-whisper child per job, each
  sized by `transcription.whisper_cpu_threads`. Both are bounded to 1–8 server-side.

**The cron cadence is retargeted live, and that needs `CronJob.schedule_token`.** `cron_loop`
recomputes a fire time only *after* firing, so a change from 60 to 5 would otherwise sit unapplied
until the top of the hour. `IntervalSchedule.version` bumps on a real change and
`refresh_stale_schedules` replaces the pending fire time — before the due-time check, so a retarget
displaces the pending fire rather than racing it. `next_fire_every_n_minutes` anchors its slots on
**midnight, not the hour**, which is what lets a value above 60 mean what it says; the hour-anchored
version silently collapsed everything above 60 to hourly.

**Why the subscription pipeline has its own lane:** one pipeline job holds its slot for an entire
channel enumeration plus a DB check per video (minutes for a large channel), and priority orders the
*queue* — it cannot preempt a running job. On the `default` lane the two cron job types could occupy
both slots at once and stall manual downloads regardless of priority.

**Priority ladder** (`JobSpec.priority`, 0 = highest; the lane pops by `(priority, queue_sequence)`,
ties by submission order): `0` = explicit Prioritize button and add-subscription, `1` =
`DIRECT_DOWNLOAD_PRIORITY` (manually-submitted downloads), `5` = `SUBSCRIPTION_DOWNLOAD_PRIORITY` and
the `JobSpec` default. Constants live in `repositories/task_records/crud.py`. **Priority is not
inherited** — `JobContext` doesn't carry it and the orchestrator copies only `args` into downstream
specs, so every fan-out site sets it explicitly. Consequence: a subscription backlog can be starved by
a steady stream of manual downloads. That is intended (explicit user requests beat background sync)
and lossless — a populate that never runs leaves no `MediaDetails`, so the next enumeration
rediscovers the video.

### Subscription pipeline

Fired by the built-in cron every `app_settings.subscription_check_minutes` (Settings UI, 1–1440):

```
run_subscription_pipeline (subscriptions lane, serial; plain control flow, early return ends the tick)
├─ get_all_subscriptions_impl
├─ create_download_jobs_from_subs_impl
├─ filter_completed_downloads_impl   (batched: one url IN (...) query per media_type)
└─ fan out → populate_media_details jobs (default lane, parallel, priority 5)
       throttled: blocks while the default lane holds ≥ FANOUT_QUEUE_TARGET
```

**The fan-out crosses a lane boundary, and that is the whole reason it needs throttling.** A lane
comes from the `JobDefinition`, not the submitting job (`JobSpec` has no `lane` field;
`_submit_nowait` resolves it via `get_job_definition`), so the pipeline holds the single
`subscriptions` slot while every `POPULATE_JOB` it emits lands on `DEFAULT_LANE`. A large channel
would otherwise park thousands of untracked, in-memory-only jobs there — a spike a restart silently
loses.

`_wait_for_fanout_capacity` (`tasks/subscriptions.py`) instead blocks the producer on
`orch.queued_count(DEFAULT_LANE)`, bounding peak depth without capping throughput (the lane still
drains at its own rate; we top it up). Safe to run long because `_fire_cron_job` submits with a fixed
`task_id` and `_submit_nowait` ignores a resubmit whose task_id is already queued or running — a long
pipeline suppresses its own overlapping ticks. `FANOUT_MAX_WAIT_SECONDS` bails if the default lane
wedges, losslessly: the next tick re-enumerates.

Throttle the producer, never the cycle. A pre-enumeration backlog guard that skips the whole tick
throws away a completed channel walk and stalls every *other* subscription for the duration of a
drain.

### Download chain (per job)

```
POST /ytdl/ writes a RESOLVING placeholder TaskRecord, then submits the pipeline
run_populate_media_details (resolves URL, fetches metadata)
└─ create_download_and_transcript_chains_impl
   ├─ adopts the placeholder as the download row (or inserts one), then dispatch_download_chain →
   ├─ download job (downloads lane)
   └─ (optional) transcript JobSpec attached as `downstream` — enqueued into the
      ml lane with the download's return value once the download succeeds
```

### The RESOLVING placeholder

Resolution is slow enough to look like a hang — a yt-dlp metadata fetch, a whole
playlist enumeration for `download_playlist`, and a wait behind `DEFAULT_LANE`'s
width — so a submission must be visible before populate finishes. `POST /ytdl/`
writes the download `TaskRecord` up front in `RESOLVING`, titled with the raw URL,
and the chain **adopts that row** rather than minting its own, so the task_id the
user is watching never changes.

Four things the code can't state:

- **The placeholder task_id must never be a `JobSpec.task_id`.** The chain is dispatched
  from *inside* the still-running populate job, so `_submit_nowait`'s idempotence guard
  (`core.py`) would see that id already in `_handles` and silently drop the download. It
  travels as payload data (`DownloadJobDTO.placeholder_task_id`), which is also why
  cancellation is cooperative — `orch.cancel` has nothing to dequeue, so `revoke_task`
  writes `CANCELLED` and `_adopt_placeholder` reads it and stands down.
- **`RESOLVING` is in `ix_task_records_active_unique`'s predicate but *not* in
  `ACTIVE_DOWNLOAD_STATUSES`.** The index gives double-submits the same DB-level dedup
  every other active status gets; staying out of the status list keeps
  `_find_duplicate_active_tasks` blind to the chain's *own* placeholder, which would
  otherwise make it stand down against itself.
- **`guard_resolving_placeholders` wraps *outside* `retry_transient_db`** (see
  `registry.py`). It is the guarantee that no submission is stranded in `RESOLVING` —
  every early return and raise lands in its `finally`, and `sync_retire_placeholder`
  no-ops unless the row is still `RESOLVING`. Inside the retry wrapper it would retire
  the row between attempts, and the retry would find nothing to adopt.
- **The guard is only for a body that owns the row to resolution.** `POPULATE_JOB` does —
  it adopts or writes a specific outcome before returning. `DIRECT_DOWNLOAD_PIPELINE_JOB`
  does *not*: it hands each row to a populate job and returns while that job is still
  queued, so a blanket retire-on-exit kills every chain it just started (silently — the
  chain stands down on the non-`RESOLVING` row and `SKIPPED` is not in the default Tasks
  filter). It is therefore registered unguarded and tracks a `unclaimed` set of task_ids
  in `run_direct_download_pipeline`, discarding each on hand-off and retiring the rest in
  a `finally`. Compare by id *value*: `expand_playlists_impl` round-trips every job
  through `serialize_download_job`, so the dict submitted is never the one that arrived.
  That `finally` is also why the retry moved *inside* the body, onto
  `_fan_out_download_chains` — the ordering rule above still applies.
- **Per-video placeholders are created *after* `filter_completed_downloads_impl`**, so a
  500-video playlist where 480 are already downloaded surfaces 20 rows, not 500 that
  instantly flip to SKIPPED. The rule: a placeholder exists for every URL the user
  explicitly named, plus every video that survives playlist filtering.

Startup recovery resumes these from `TaskRecord.pending_payload`, which is what keeps a
restart mid-resolution from losing the download with no trace: both the pipeline and
populate jobs are `tracked=False`, so the persisted payload is the only record of them.

**Adding an enum value takes two revision files.** Postgres rejects DDL/DML referencing a
value added in the same transaction, and `migrations/env.py` sets
`transaction_per_migration=True` precisely so a later revision *can* use it. Put the
`ALTER TYPE` alone in one file and everything that names the value in the next.

**The schema starts at `baseline_schema`; every later revision in `migrations/versions/` is a delta on it.**
Most of it is autogenerated from SQLModel metadata; the block at the end of `upgrade()` is not,
because `--autogenerate` cannot see any of it — the `vector` extension, the `transcript_embeddings`
table and its HNSW index, `transcript_blocks.text_search` (a generated tsvector column) and its GIN
index, the standalone `task_queue_sequence`, and the seeded `app_settings` row. Alembic will
actively propose **dropping** the four schema objects there, since they are absent from
`SQLModel.metadata`. Anything added to that block needs a matching drop in `downgrade()` by hand.
One more autogenerate quirk to expect: it renders `sqlmodel.sql.sqltypes.AutoString()` for string
columns without emitting `import sqlmodel`, so a freshly generated revision `NameError`s until you
add it.

**Every foreign key's `ondelete` must be declared on the model, not just in a migration.**
`tests/conftest.py` builds the test schema with `SQLModel.metadata.create_all`, so a cascade that
exists only because some migration wrote it is absent from every test database — production deletes
cascade, test deletes raise. `models.py` carries `ondelete=` on all 31 FKs, which is also what keeps
the autogenerated baseline in step with the live schema.

**Server defaults are deliberately almost absent** — only `task_records.retry_count` has one. A
`server_default` is what `ADD COLUMN ... NOT NULL` needs to backfill existing rows; it is not a design
choice worth carrying. SQLModel propagates `Field(default=)` to the SQLAlchemy column as
a *Python-side* default, which both the ORM and Core `insert()` apply to omitted columns, so nothing
in the app depends on the database supplying one. Adding `server_default` would duplicate every
default in two places that must then be kept in sync.

### Features

- **UUID task IDs** pre-assigned before queueing (`TaskRecord.task_id`); ordering via Postgres sequence `task_queue_sequence`
- **Duplicate detection** — partial unique indexes prevent concurrent downloads of the same URL/media_type
- **Retries** — `RETRY` status + `next_retry_at` scanned by the retry scheduler; exponential backoff (downloads 300s–8h ×20), same task_id across attempts (`retry_count` = attempt number, drives cookies-on-retry)
- **Startup recovery** — re-enqueues QUEUED work, resumes interrupted downloads (yt-dlp continues `.part` files) and re-runs the populate job behind a `RESOLVING` placeholder; `tasks.purge_on_startup: true` cancels pending work instead
- **Cancellation** — queued jobs dequeue instantly; running downloads abort at the next yt-dlp progress tick via a cancel event; the transcription child is SIGTERM'd; clip and sprite ffmpeg get their process group killed; a `RESOLVING` row is cancelled cooperatively (status only — no job exists under its id yet)
- **Prioritize** reorders the in-memory queue entry to the front, task_id unchanged
- **Phase tracking** distinguishes VIDEO vs AUDIO download phases; rate limiting sleeps between downloads (cancel-event aware)
- **Observability** — `GET /tasks/runtime` (admin) or `task tasks:runtime` shows lanes + queued/running jobs

To clear pending work: cancel from the Tasks UI, set `tasks.purge_on_startup: true`, or `task clean`.

### Lifecycle hooks (`orchestrator/hooks.py`, run by `orchestrator/wrapper.py`)

`BaseStatusHooks` (status writes + SSE) · `DownloadHooks` (live-row re-resolution, NOT_READY-preserving
success guard, downstream failure marking, cancel file cleanup) · `TranscriptHooks` / `ClipHooks` /
`SpriteHooks` (cleanup of partial transcripts / clip files / truncated sprite sheets `on_cancel`).

### Sprite generation

Runs on the `ml` lane as a tracked `SPRITE_GENERATION` task (`SPR` in the Tasks UI). The row is
created at **populate time** by `_persist_download_chain_state`, alongside the download and transcript
rows (VIDEO only), and dispatched later. **The visible SPR row is the point**: the transcript behind
it sits `QUEUED`, and without a row holding the slot that wait looked like a hang.

Four constraints the code can't state:
- **`queue_sequence` is the "dispatched yet?" marker.** The chain row is inserted with it NULL, which
  is what `crud.py`'s queue-position pass and startup recovery both key on — recovery must leave a
  QUEUED sprite alone while `_upstream_still_pending`, or it tiles a file that isn't on disk yet. The
  retry path re-arms a sprite row by clearing it back to NULL.
- **Dispatch lives in `DownloadHooks.on_success`, not the job body**, because that fires for exactly
  the right outcomes: normal success plus the repeat-download and file-already-exists paths (which
  have a file on disk), but not superseded/quota (`SkipJob`, no hooks) or not-ready (returns early on
  the NOT_READY retval). It is the last statement in the hook, so a raise — absorbed by
  `wrapper._run_hook` — costs only the sheet. Moving it back into the body loses all of that.
  Sprites still beat the transcript to the lane, since `core.py` enqueues `spec.downstream` only
  after `run_job_sync` returns.
- **Sprite rows set `download_job_url`**, so `ix_task_records_active_unique` dedups the automatic and
  manual paths for free. But that index counts `CANCELLED` as active, so a cancelled row must be
  retired before inserting (status → `DELETED`; setting `deleted_at` alone does **not** free the slot
  — the predicate has no `deleted_at` clause). Scope of a cancel: **within one chain it sticks** (the
  hook must not silently recreate the row, or the cancel button is a visible no-op), **a new download
  chain wipes the slate**, and **the manual Generate button always wins** (`revive_cancelled=True`).
- **ffmpeg cannot report progress on this pipeline.** `tile` buffers every frame and emits one packet
  at EOF, and `-progress`'s counters track the first output stream — the sheet. Measured on a 30-min
  video: one progress block, at the end; `split` + a second probe output (`null`, `rawvideo`,
  `mpegts`) all still gave one. Only a two-stage pipeline (frames to a temp dir, then tile) yields a
  real percentage. Hence the elapsed-time ticker via `run_ffmpeg_cancellable`'s `on_tick` — don't
  "fix" it by reaching for `-progress` again.

**`mark_downstream_stmt` sweeps every downstream task type by default**, which is what makes a
cancelled or failed download take its whole chain with it. The one exception is the pair of
download-skip paths (repeat download / file already exists): they must end the transcript *without*
touching the sibling sprite row that `on_success` is about to dispatch, hence
`sync_skip_downstream_transcripts` and the `task_types` filter. Both paths must write *something*:
`ctx.skip_downstream` only suppresses the in-memory enqueue, so a path that writes nothing strands
the transcript at `QUEUED` forever.

## Transcription Pipeline

`services/transcript.py` chunks audio through ffmpeg rather than loading it whole, and extracts at
**32 kbps / 16 kHz mono** — Whisper's expected input, so anything richer is wasted bytes.

## yt-dlp Configuration

Browser impersonation and player-client settings avoid YouTube blocking:
- Random impersonation via `curl-cffi` (`ytdlp/options.py`); player-client fallback order set in the Settings UI (default `['visionos', 'tv_simply', 'web_safari', 'web', 'web_embedded']`)
- **Challenge solving**: yt-dlp ≥2025.11.12 needs an external JS runtime for YouTube `sig`/`n` challenges — **Deno ≥2.3.0** (auto-discovered from PATH) plus the `yt-dlp-ejs` dep. Deno is pinned via the `DENO_VERSION` ARG in `Dockerfile.prod`; too-old Deno → `Signature solving failed` → `Requested format is not available`
- Defaults live in `models.py` (`DEFAULT_PLAYER_CLIENTS` / `DEFAULT_COOKIES_PLAYER_CLIENTS`) and **only affect a fresh `app_settings` row** — existing installs keep stored values, so change them via the Settings UI, or ship a data migration as `realign_player_clients` does. Watch for clients yt-dlp removes upstream (e.g. `tv_embedded`) *and* for ones it keeps but demotes: `android_vr` still exists, but YouTube 403s every format it returns as of 2026-08-17, so a stored list still leading with it silently caps downloads at whatever the next client offers
- Downloads failing with empty files usually means yt-dlp needs updating or the player clients need adjusting
- **Throttling is three separate knobs, all `app_settings` columns (never `config.yml`), all 0 = off.**
  `download_sleep_seconds` sleeps *between* jobs and only for subscription/playlist ones
  (`_rate_limit_sleep` returns early otherwise). `download_rate_limit_kbps` → yt-dlp `ratelimit`,
  applied per job body, so it multiplies with `downloads_lane_concurrency` exactly like the sleep does.
  `request_sleep_seconds` → yt-dlp `sleep_interval_requests`, and it is deliberately set in **both**
  option builders — it is paid in `_request_webpage` during *extraction*, so downloads-only would miss
  the channel walks and populate fetches that are most of the request volume. `ratelimit` conversely
  stays out of `ytdlp/info.py`: metadata extraction has no media transfer to cap. `_throttling_options`
  (`ytdlp/options.py`) exists because inlining the two branches pushed `create_ydl_options` past ruff's
  C901 limit.
- **`_get_pot_extractor_args` deliberately emits two keys.** yt-dlp derives a POT provider's
  extractor-arg key from its *class* name (`pot/_provider.py` `PROVIDER_KEY` →
  `youtubepot-{key.lower()}`), so the CLI provider reads `youtubepot-bgutilcli:cli_path`. The
  second key, `youtubepot-bgutilscript:script_path`, is not a leftover: bgutil's HTTP provider reads
  it directly to decide whether a refused connection to its `127.0.0.1:4416` server is expected.
  Drop it and every extraction gains a warning. Unrecognised `youtubepot-*` keys are silently
  ignored, so neither mistake announces itself.
- **The cookie file is never handed to yt-dlp directly.** `YoutubeDL.close()` truncates and rewrites
  `cookiefile`, with no locking, and lanes run concurrently in one process — so a job that started
  earlier can overwrite a rotated session cookie a later job already persisted, and a run killed
  mid-close leaves a half-written file. `ytdlp/cookies.py`'s `cookie_session` is the single place that
  decides whether cookies apply *and* hands out a disposable copy. It is also the only place that
  knows metadata extraction has no attempt counter, so `RETRIES_ONLY` means never for it.
- **Impersonation is randomized only for anonymous requests.** `_get_impersonate_headers` keeps the
  extractor's per-client User-Agent, so an impersonated request pairs a browser TLS fingerprint with
  a smart-TV or Android-VR UA. Spread across anonymous requests that is cover; under one authenticated
  account a fingerprint that moves every job is a repeating mismatch, so `create_ydl_options` pins
  `get_stable_impersonate_target()` whenever `cookie_file` is set.
- **`DENO_VERSION` and `BGUTIL_POT_VERSION` are watched by a workflow, not by Dependabot.** Both are
  fetched by `curl` inside a `RUN`, and Dependabot's `docker` manager only parses `FROM` /
  `COPY --from` — so neither appears in `.github/dependabot.yml` and neither can. `Dockerfile.prod`
  must keep both as `ARG NAME=value` on their own line: `.github/workflows/pinned-release-check.yml`
  greps for exactly that, and its bump `sed` is anchored on the `=` so the bare re-declarations inside
  the builder stage keep inheriting. Do not "simplify" either pin back to `releases/latest` — that
  layer sits after the `uv.lock` COPY, so `latest` makes the PO-token provider update as a side
  effect of any Python dependency bump.

## Development Commands

`bash setup.sh` does interactive first-time setup, defaulting to the published GHCR image. Day to day
this project uses [Taskfile](https://taskfile.dev/) — run **`task help`** for the target list rather
than looking for it here.

**Three runnable compose files, one shared base.** `docker-compose.common.yml` holds `postgres` and
`backend-common`, plus `backend-prod-common` — which extends `backend-common` via a *same-file*
`extends` (no `file:` key, resolved against common.yml rather than whichever file `-f` named) and
carries the prod runtime: the `command:`, `stop_grace_period`, and the 60s healthcheck `start_period`.
`docker-compose.prod.yml` and `docker-compose.published.yml` each extend that and add only where the
image comes from. The chain exists so the released stack cannot boot differently from the one
contributors test — moving `command:` back into either leaf reintroduces exactly that drift.

Three traps when adding targets that touch a container:

- **Use `-f {{.COMPOSE_FILE}}`.** There is no default `docker-compose.yml`, so a bare `docker compose exec` fails with `no configuration file provided` — this silently broke six targets. `COMPOSE_FILE` is a global var holding a `$(…)` shell substitution that picks dev or prod based on which stack is running; because it's a plain string (not a `sh:` var) it costs nothing on `task --list` and is evaluated only by the tasks that interpolate it. Don't use the `dev 2>/dev/null || prod` fallback that `logs`/`logs-backend` use for anything stateful or interactive — on failure it runs the command twice.
- **Never redirect a container's stdio to a host file** (`> file` / `< file`). Under Task's built-in shell interpreter that makes `docker compose` fail with `write /dev/stdout: bad file descriptor`, and an `sh -c` wrapper does *not* help. `db:backup` hit this and the failure mode is nasty: pg_dump exits 0 and you get a **0-byte backup**. Stage through a file inside the container and move it with `docker compose cp`, as `db:backup`/`db:restore` now do.
- **`docker compose ps` / `images` ignore which `-f` you pass** — both resolve by project label, so `-f docker-compose.prod.yml ps` happily lists dev's `frontend`. Consequence: `COMPOSE_FILE`'s dev/prod probe has always taken its first branch, which is harmless (every consumer is exec-style and also resolves by project+service, so the named file only has to *define* `backend` and `postgres`) — don't "fix" it into a 3-way, and don't build mode detection on `ps --services`. Where mode genuinely matters, discriminate on the running **image**, as `_db:reset-impl` does: without that, `task clean` restarts a published install in dev and hands the user a surprise 45-minute build. Capture it in a task-level `sh:` var, which Task evaluates before the first cmd — after `down` there is nothing left to inspect. Match with `grep`, not `--format '{{.Image}}'`, which Task expands as its own template.

## Testing

Backend tests run on the **host** (`cd backend && uv run pytest`, or `task backend:test`) against a
session-scoped `postgres:16-alpine` testcontainer, so Docker must be up. pytest-asyncio is in `auto`
mode: a plain `async def` test just works — **don't add `@pytest.mark.anyio`**, it is redundant here
and only re-parametrizes the test id.

The fixture chain in `tests/conftest.py` is built for speed, and each piece of it is load-bearing:

- **The schema is created once per session** (`_db_engines`), not per test. Each test instead gets a
  clean slate at *setup* from `clean_database` (empty) or `test_database` (empty + seeded). Cleaning
  at setup rather than teardown is what makes a test that dies mid-transaction unable to poison the
  next one. Don't reintroduce per-test `create_all`/`drop_all` — that was ~0.83s per test.
- **Cleanup is `DELETE FROM` every table plus `ALTER SEQUENCE ... RESTART` on every sequence**, not
  `TRUNCATE`. On tables this small TRUNCATE's relfilenode churn costs ~6x more, and `RESTART
  IDENTITY` would miss standalone `task_queue_sequence` anyway. **Rewinding the sequences is not
  optional**: tests hit `/subscriptions/1` and `/tasks/1/retry`, `test_task_stats_shape_and_counts`
  asserts an exact dict over the seed, and `_populate_test_data` hardcodes
  `download_task_record_id=1`. Any replacement must still reproduce fresh-database id assignment.
- **`db._async_engine` / `db._sync_engine` and the two session factories are patched once per
  session and never restored.** That is only sound because the lifespan never runs: all ~82 client
  sites use a bare `TestClient(app)`, never `with TestClient(...)`. A test that needs the lifespan
  must save and restore those globals itself.
- **Never dispose the async engine in a sync teardown, and never drop its `NullPool`.** asyncpg
  connections are event-loop-bound; NullPool means none outlives a checkout, which is the only
  reason one engine can serve both pytest-asyncio's per-test loop and `TestClient`'s portal thread.
- **The container runs with `fsync=off -c full_page_writes=off -c synchronous_commit=off`** — it is
  thrown away at the end of the run, and durability was most of the per-test cleanup cost.
- **`_fast_bcrypt` patches `bcrypt.gensalt` to cost 4 suite-wide.** `checkpw` reads the cost from the
  hash, so register-then-login tests still exercise the real hash/verify path. Patching
  `auth.hash_password` instead would bypass the code `TestPasswordHashing` covers.
- **Keep the `_reset_rate_limiters` autouse fixture.** The limiters are module-level singletons and
  `authenticated_client` registers via a real `POST`, so without it the budget is consumed across
  unrelated tests.
- **Transcript-search tests must request `pgvector_schema`.** `transcript_embeddings` and
  `transcript_blocks.text_search` live only in `baseline_schema.py`'s hand-written block, so
  `SQLModel.metadata.create_all` never creates them and no search query can run without it. It is
  opt-in rather than autouse because most tests don't need it, and it needs no teardown —
  `transcript_embeddings` cascades off `transcript_blocks`, which `_reset_sql` already empties.
- **No private per-file engine fixtures — use `clean_database`.** A file that builds its own
  in-memory SQLite engine has to overwrite the `db` globals, and with session-scoped patching a
  failure to restore them poisons every later test. SQLite also silently skips FK enforcement, which
  is enough to make a sprite test pass vacuously.

Tests needing real ffmpeg/ffprobe carry `@requires_ffmpeg` (`tests/test_peaks.py`) and auto-skip on
hosts without it; CI installs ffmpeg and runs them.

### Frontend

Frontend tests run via **Vitest** — `task frontend:test`, or `npm test` from `frontend/`. Tests
are **co-located** next to their source as `*.test.ts` / `*.test.tsx`.

- **`environment: "node"` is the default** (`vitest.config.ts`); a file that touches the DOM opts
  in per-file with a `// @vitest-environment jsdom` docblock as its first line.
  `environmentMatchGlobs` was removed in Vitest 4, and the current file count doesn't justify a
  `projects` config.
- **Globals are off** — every test imports `describe`/`it`/`expect`/`vi`/etc. explicitly from
  `"vitest"`. That is what keeps `tsconfig.json` untouched (no `"types": ["vitest/globals"]`
  needed). Test files still sit under `tsconfig.json`'s `**/*.ts(x)` include glob like every other
  file, so they're checked by the same `next build` type-check as app code — a type error in a
  test fails the build exactly like one anywhere else.
- **RTL's automatic `cleanup()` never registers with globals off** — its `afterEach` guard probes
  for a *global* `afterEach`, which doesn't exist here. Every jsdom test file must call
  `cleanup()` from its own explicit `afterEach`, or DOM/mounted state leaks into the next test in
  that file.
- **Never assert exact output of locale-dependent formatting** (anything through
  `toLocaleString`) — CI's ICU/locale/TZ differs from a dev machine's. Assert shape with a regex
  instead, e.g. `/^in 4m \(.+\)$/`.
- **The anonymous `node_modules` volume trap:** `docker-compose.dev.yml` mounts `./frontend:/app`
  plus an anonymous `/app/node_modules` volume that masks the host directory, so after editing
  `package.json` the container keeps the old `node_modules` (`vitest: not found`) until `task
  frontend:install` runs `npm install` into the volume — the lockfile writes back through the
  bind mount, `node_modules` doesn't.

## Multi-architecture images

Images build natively for **both amd64 and arm64**; nothing is pinned to an architecture, and
`.github/workflows/release.yml` pushes a single multi-arch manifest to GHCR on `v*` tags, then opens
a GitHub Release page for the tag ([docs/RELEASING.md](docs/RELEASING.md)).
`docker-compose.published.yml` is the consumer of that manifest and the **default install path** —
`setup.sh` pulls `ghcr.io/kkuhlmann/ytdl-hoarder:latest` unless told otherwise. Nine things that are
easy to undo by accident:

- **`docker-compose.published.yml` must never gain a `build:` block.** With one, a failed pull stops
  being an error and silently becomes a 45-minute build — of the working tree, not the released
  commit. Its absence is also what lets `setup.sh` treat a non-zero `pull` as a real failure and offer
  the from-source path explicitly.
- **The published stack has to be installable from files alone, because `setup.sh` fetches them.**
  Run outside a checkout — the documented `wget setup.sh` install — it downloads
  `docker-compose.published.yml`, `docker-compose.common.yml` and `config.sample.yml` from
  `raw.githubusercontent` and generates the rest. Common is in that list because every service in the
  published file is an `extends: file:` of it, so the published file alone starts nothing. The
  consequence for edits: a **new host-path mount on `backend-common`** is a new file the installer
  must fetch or generate, and it breaks `wget` installs only — a checkout keeps working, so nothing
  local tells you. The two flags that carry this are `HAVE_SOURCE` (`Dockerfile.prod` + `backend/`
  present → build modes offered, and never fetch, since those files are tracked source someone may be
  editing) and `HAVE_COMPOSE` (→ configure the directory in place rather than nesting another one).
- **`latest` must only ever point at a released tag.** `release.yml` deliberately lists no `latest`
  rule: metadata-action's default `latest=auto` already emits it for a semver tag push and skips
  prereleases. Re-adding `type=raw,value=latest,enable={{is_default_branch}}` would let a
  `workflow_dispatch` on main publish an unreleased build straight into every new user's install.
  One thing `latest=auto` does *not* do is compare versions, so a hotfix released on an older line
  after a newer minor has shipped moves `latest` backwards onto the older code.
- **Every version is tagged twice, `v0.1.0` and `0.1.0`, and the `v` form is the load-bearing one.**
  metadata-action strips the leading `v` from `{{version}}`, but `setup.sh` (`--image-tag`, and the
  `^v[0-9]` branch that reuses the tag as a *git* ref to fetch compose files from),
  `docker-compose.published.yml` and every doc name the `v` form — so emitting only the bare one
  breaks the documented pin with `manifest unknown`, and only for users, never in CI.
- **`github_release` creates the Release page only when one doesn't already exist, and never edits.**
  Both release routes converge on the same `push: tags` event — a web-UI publish creates the tag —
  so on that route the job runs *after* someone has written the notes by hand. An unconditional
  `gh release create` fails there, and `--notes`/`edit` would overwrite them. It also `needs:
  publish`, so the page can never announce a version whose image failed to build. `contents: write`
  is scoped to that one job; the top-level token stays read-only.
- **Never reintroduce `platform:` / `platforms:` into the compose files.** Those keys pinned everything
  to amd64 and forced the backend under QEMU on ARM hosts. Omitting them makes Docker use the host
  platform, and `DOCKER_DEFAULT_PLATFORM` is the per-user override if someone genuinely needs one.
  Listing both arches under a compose `build` would also just fail — the default `docker` driver
  cannot produce a manifest list.
- **`ffmpeg_download.py` requires `TARGETPLATFORM` and exits non-zero without it.** Defaulting it to
  `linux/amd64` would bake x86-64 ffmpeg into arm64 images, which surfaces only as `exec format
  error` at transcode time, long after a green build. Guessing the *build* host's arch would be wrong
  too, since this cross-builds.
- **`frontend-builder` is `FROM --platform=$BUILDPLATFORM`**, not TARGETPLATFORM. Its only output is a
  Next static export — no native binaries — so it is arch-neutral and safe in either image, and
  pinning it to the builder keeps `npm ci` + `next build` out of emulation, where they dominated the
  cross-build. It also makes that layer byte-identical across arches, so the registry stores it once.
- **Do not "clean up untagged versions" on the GHCR package.** Now that this package is what strangers
  install, breaking it breaks every new deployment, not just a convenience path. In a manifest list the
  per-arch children
  (and the provenance attestations) *are* untagged versions — only the index carries the tag — so
  `actions/delete-package-versions` with `delete-only-untagged-versions` deletes the amd64/arm64 images
  out from under a working tag and pulls fail with manifest-unknown. Use a manifest-list-aware cleaner.

On the ML stack: ctranslate2's aarch64 wheel carries **Ruy** (ARM NEON int8) instead of the x86 build's
MKL/oneDNN, which is why `transcript.py`'s hardcoded `compute_type='int8'` is the portable choice —
`float16` on CPU would not be. It has NEON+dotprod but no i8mm, so arm64 transcription is correct but
slower than comparable x86.

## Configuration

`config.yml` is the single source of settings — see `config.sample.yml` for the full annotated set,
and `.env.sample` for compose mounts and build args.

**Priority is `config.yml` > env var > default, which is the opposite of what you'd expect.**
Double-underscore env vars (`DATABASE__URL`,
`TASKS__PURGE_ON_STARTUP`) fill in only what `config.yml` leaves *unset*:
`_create_settings_from_yaml` passes each YAML section as constructor kwargs, and pydantic-settings
ranks `init_settings` above `env_settings`. `test_yaml_values_take_precedence_over_env`
(`tests/test_config.py`) pins this. Don't "fix" it without deciding to flip the order deliberately —
several call sites assume config.yml is authoritative.

**Under Docker, env vars mostly can't reach the app at all.** Neither compose file declares
`env_file:`, so `.env` is consumed *only* by Compose's own `${...}` interpolation; the sole var
passed into the backend is `FORWARDED_ALLOW_IPS`, via an explicit `environment:` entry in both
files. Adding a new env-tunable setting therefore means adding it to `environment:` too — otherwise
it silently does nothing in every containerized deployment. `.env` holds exactly what cannot live in
`config.yml` because it's consumed outside the backend process: the two host media paths (Compose
resolves the bind-mount source before the container exists), `YTDL_HOARDER_IMAGE`/`YTDL_HOARDER_TAG`
(they name the image, so they must resolve before there is a container to configure),
`NEXT_PUBLIC_BACKEND_API` and `ALLOWED_DEV_ORIGINS` (Next.js build/dev server), and
`FORWARDED_ALLOW_IPS` (uvicorn itself, no `config.py` key). Everything else belongs in `config.yml`.

`storage.audio_path`/`storage.video_path` are pinned to the compose mount *targets* (`/mnt/audio`,
`/mnt/video`) — they are the container side, not the host side, and editing them makes the app write
to an unmounted path. `setup.sh` deliberately omits them, and `embedding.model`, from the config.yml
it generates: both already equal the code defaults and both are traps if changed.

`config.py` loads it with `pydantic-settings` + custom YAML loading, cached via `@lru_cache` at
startup, nested Pydantic models for validation. Import with `from config import settings`.

Three `.env` values that bite:
- `NEXT_PUBLIC_BACKEND_API` — dev-mode only, **baked into the JS bundle at build time** (`docker-compose.dev.yml` build arg; default `http://localhost:8000`). Wrong for non-Docker-host access (LAN IP/domain) → every API call fails silently, including `/auth/setup-status`, so a fresh install falls back to the login page instead of showing setup. `setup.sh` prompts for this when launching dev mode. Prod and published hardcode `/api` in `Dockerfile.prod`, ignoring `.env` — unaffected.
- `ALLOWED_DEV_ORIGINS` — comma-separated escape hatch for Next 16's `allowedDevOrigins` enforcement.
- `YTDL_HOARDER_TAG` — read **only** by `docker-compose.published.yml`, so setting it under prod or dev does nothing at all. `setup.sh --image-tag` writes it here rather than using it once, so a later `docker compose pull` stays on the release the user chose.

**Lane widths and the subscription cadence live in `app_settings`, never in `config.yml`.** Don't add `tasks.default_concurrency` or `tasks.schedule_frequency_minutes` to `setup.sh` or `config.sample.yml`: `TasksSettings` has neither field and `extra='ignore'` swallows both, so a config.yml carrying them is silently inert rather than an error.

**Runtime settings** live in the single-row `app_settings` table (see the `AppSettings` model) and are
edited in the Settings UI, taking effect on the next task execution without a restart. **The row is
INSERTed by `baseline_schema.py`, so the model's field defaults never execute for this table** — the
migration is the source of truth for what a live install actually runs, and nothing keeps the two in
step on its own. `tests/test_migration_defaults.py` runs the migration against a scratch database and
asserts the seeded row equals `APP_SETTINGS_DEFAULTS`, column by column over `tuple(APP_SETTINGS_DEFAULTS)`
— so a new column needs its value in the migration *and* in that constant, or the test fails. That is
also why the seed uses literals rather than importing the constant: importing it would make the test
compare the constant against itself. Note the test runs `upgrade head`, not just the baseline, so a
later revision that rewrites a seeded column (`realign_player_clients`) has to agree with the constant
too — and changing a default that existing installs must also pick up takes **both** an edited baseline
seed and a data migration, since the baseline only ever runs on a fresh database.

## Code Style

- **Default to no comment. Fewer, higher-value comments beat more of them.** Before writing one, ask
  whether the code can say it via naming/structure instead — if so, don't add it. A comment earns its
  place only when it captures something the code can't: a non-obvious constraint, an invariant, a
  workaround, or a reason a "cleaner" alternative would be wrong. This cuts both ways: don't add
  low-value comments, and delete existing ones that don't clear the bar when you're already touching
  that code.
  - Bad — restates the line below it: `# Return the final tags` above a tag-select query, or
    `# Initialize SQLAlchemy database engines` above `db.initialize_database()`. Delete on sight.
  - Good — states a constraint the code can't: `# Race condition: another worker already created a task
    for this URL. The partial unique index (ix_task_records_active_unique) prevents duplicates.`
    Worth keeping.
- **Don't narrate history** ("this used to do X", "previously we..."). That belongs in the commit message,
  not the code, and it rots as the codebase moves on. The one exception: when the past behavior is the
  only thing that makes a present-day invariant make sense — and even then, keep the present-day
  constraint as the point, with the history as one clause in service of it, not a changelog entry. (E.g.
  explaining a cache is keyed on a value's *contents* because that value used to be a fresh object
  literal each render — enough to stop someone from "simplifying" it back to an identity check.)
- **Docstrings get a different bar than inline comments, not a free pass.** Their audience is a caller who
  won't read the implementation, so describing parameters/return shape/side effects is their actual job —
  that's not a WHAT-violation. But a docstring that only restates the function name in prose (e.g.
  `"""Get all subscriptions for a user."""` above `get_all_subscriptions_impl(user_id)`) adds nothing a
  signature didn't already say, and should go. FastAPI route docstrings are a further special case: they
  render in the generated OpenAPI/Swagger UI as end-user-facing API documentation, so judge them as
  documentation for API consumers, not narration for code readers.
- Backend: Ruff formatter, single quotes, 100 char lines. Frontend: ESLint flat config, TypeScript strict.
- **React Compiler rules — 10 are deliberately held at `warn`, and that list is a regression net, not a backlog.** `eslint-config-next@16` pulls in `eslint-plugin-react-hooks@7`, which turns the whole React Compiler rule set on as errors; that was 78 findings on arrival, so `reactCompilerRules` in `eslint.config.mjs` downgraded them to be worked off rule by rule. Every rule that ever had a finding — `purity`, `immutability`, `refs`, `set-state-in-effect`, `set-state-in-render` — is now clear and back at `error`. The 10 still listed have **zero** findings in the current tree and stay at `warn` only so a future violation surfaces as a warning to triage rather than an immediate hard build break. **This is intentional, not a broken config** — anything absent from that array keeps the default `error`, so removing a rule from it is how a rule gets promoted. Lint must stay at **0 errors**.
- **Query-building convention** (repositories):
  - **Conditions list** for queries with optional/conditional filters: `conditions = []` → append → `stmt.where(and_(*conditions))`
  - **Inline `.where()`** for fixed-condition queries: `select(Model).where(Model.id == id)`
  - Avoid chaining conditional `.where()` calls; use the conditions list pattern instead

## README Maintenance

`README.md` targets **end users**; this file targets **developers and agents**. When a change touches
user-facing behavior, config options, architecture, compose setup, dev commands, or troubleshooting,
check whether the README needs the same update.
