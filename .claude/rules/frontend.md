---
paths:
  - "frontend/**/*"
---

# Frontend (`frontend/app/`)

## Toolchain — upgraded July 2026; the non-obvious parts
- **Turbopack is the builder** for both `next dev` and `next build`. `--turbopack` is the default in 16, not a flag.
- **Lint is flat config only**: `eslint.config.mjs` + `"lint": "eslint ."`. `next lint` was removed in Next 16 and `.eslintrc.json` is gone — don't reintroduce either.
- **`noUnusedLocals` + `noUnusedParameters` are on**, and `next build` type-checks, so an unused import is a *build failure*, not editor noise.
- **`tsconfig.json` pins `"target": "ES2022"` with an explicit `"useDefineForClassFields": false`.** The second flag looks redundant and is not: Next passes `Boolean(compilerOptions.useDefineForClassFields)` straight to SWC and never derives it from `target`, so a bare `ES2022` would leave tsc assuming define-semantics the emitter doesn't produce. Leave it.
- **Node 24** is the pinned build version in both `frontend/Dockerfile` and `Dockerfile.prod`'s frontend-builder.
- **Next 16 enforces `allowedDevOrigins`** (advisory in 15): cross-origin requests to `/_next/*` and HMR are blocked unless the host is listed. Same-origin page loads send no `Origin` and are never blocked, so in practice this governs **hot reload**. `next.config.js` ships `["**.*"]`, the widest pattern Next's matcher accepts — every IPv4 literal and every dotted name. **A bare `"*"` or `"**"` matches nothing**: `matchWildcardDomain` (`next/dist/server/app-render/csrf-protection`) rejects a single-segment wildcard outright, so "simplifying" the pattern silently blocks everything. Nothing can match a single-label host (`http://nas:3000`) or an IPv6 literal — that is what `ALLOWED_DEV_ORIGINS` (comma-separated) remains for. `localhost` is always allowed by Next itself. Prod is a static export and unaffected.
- **Tailwind is v4 and CSS-first — there is no `tailwind.config.ts`.** The theme lives in an `@theme inline` block at the top of `app/globals.css`; `components.json` carries `"config": ""` to say so. Four things there are load-bearing and easy to undo by accident:
  - **`inline` is mandatory.** It makes each utility emit the *runtime* variable (`.bg-matrix` → `background-color: var(--matrix-green)`) instead of a copy resolved once at `:root`, which is the only reason the 92 `[data-theme]` blocks can still repaint the app. Note `inline` does **not** suppress the `:root` copy of a theme variable — it only changes what utilities reference.
  - **Theme keys must not share a name with a runtime var.** Identical names emit `--x: var(--x)` at `:root`. The theme blocks' shadow vars are called `--glow*` purely so the `--shadow-glow*` keys have something distinct to point at. No `--font-sans`/`--font-mono` keys exist for the same reason — v4 defines both by default and the unlayered theme blocks already override them.
  - **The radius scale is deliberately non-monotonic** (`--radius-xs` > `--radius-sm`). v4 shifted every rounding class one step down (`rounded` → `rounded-sm`), so the values shift one step up to cancel it out and keep the v3 pixels. Don't "fix" it without re-checking 58 call sites across all 92 themes.
  - **v4 emits real `@layer` at-rules; v3 did not.** Unlayered CSS now outranks every Tailwind utility regardless of specificity. The theme blocks, the `.rdp-*`/`.slider-matrix` overrides and the mobile-zoom rule at the bottom of `globals.css` all depend on staying unlayered — moving any of them into a `@layer` silently breaks it. This is also why that mobile rule no longer needs `!important`.
- **`@source` paths in `globals.css` are relative to that file**, i.e. to `frontend/app/` — so it is `../components`, not `../../components`. Combined with `source(none)` they replace v4's automatic detection, which would otherwise walk up to the repo root and scan `backend/`. Get one wrong and those files' classes are silently dropped from the build.

## Components with constraints worth knowing (the rest are named for what they do)
- `AuthGuard.tsx` gates on `must_change_password` → `ForcePasswordChange.tsx`, mirroring the server-side gate. `LoginPage` swaps its card body between sign-in and the two recovery panels in `auth/`
- `auth/ChangePasswordDialog.tsx` is opened from the `KeyIcon` in `NavigationBar`, **not** Settings — that tab is `adminOnly` and every `/settings` endpoint requires `get_admin_user_id`, so a non-admin would never reach it. Shares `auth/changePassword.ts` with `ForcePasswordChange`
- `media/MediaClipEditor.tsx` is the single surface behind every scissors action (`media/actions.tsx`), dispatching on `media_type`. Note `MediaListView`'s `onClip` is optional and the scissors button renders regardless, so a new list surface that forgets to pass it gets a **silently dead button**
- `TagMixView.tsx` plays through `MediaPlayerContext` under the sentinel `TAG_MIX_PLAYLIST_ID`, and renders through the same `MediaListView`/`media/columns.tsx` as the library, so mix rows get the library's actions for free

## Hooks

`useFetchEffect` is the project's data-fetching effect, registered in `eslint.config.mjs`
`additionalHooks` so exhaustive-deps checks it. **There are two hook directories**:
`hooks/useTaskProgress.ts` (SSE, auto-reconnect with backoff) lives in `app/hooks/`, everything else
in `app/_hooks/`.

`useAudioAnalyser.ts` - Feeds the visualizer's `AnalyserNode` by routing the real `<audio>` element through `ctx.createMediaElementSource(el)` (per-element WeakMap-cached graph, since that call may run only ONCE per element; a parallel strong `liveGraphs` list closes contexts whose element has left the DOM, bounding live AudioContexts over a long session). **Desktop-only by design, and that gate IS the iOS protection:** `createMediaElementSource` reroutes the element's native output into the AudioContext, and on iOS the browser suspends that context on screen-lock → **silences lock-screen/background audio**, with no way to un-route the element. So `getOrCreateGraph` calls `isDesktop()` (UA-based iOS/iPadOS detection + `(pointer: coarse)`) and returns null on any iOS or touch device — no AudioContext is ever created there, the `<audio>` tag stays plain and untouched, and the visualizer simply stays inert. Tapping the element via `captureStream()` → `createMediaStreamSource` looks like a way to avoid the reroute and keep the graph everywhere; it is not, because WebKit doesn't implement `captureStream` — that route is desktop-only too, minus the explicit gate. **CORS:** the real `<audio>` still needs `crossOrigin="use-credentials"` (`MediaPlayer.tsx`) or a tainted cross-origin element yields zeroed frequency data. `ensureStarted()` (called from the visualizer toggle click) creates/resumes the graph inside a user gesture — outside one the context stays suspended and the audio routes into a silent graph; a `visibilitychange` + `pointerdown`/`touchend` effect resumes it after the browser auto-suspends on tab background. `enabled`/`isPlaying` are mirrored into refs from a **commit-phase effect**, not during render, so the rAF-driven `getBars`/`isActive` read fresh values without re-creating the memoized handle.

## Testing

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
