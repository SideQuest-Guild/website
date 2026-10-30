# SideQuest Guild

A WoW: Forever guild's site and API. One uv workspace, one Docker image, two Cabotage processes (`Procfile`:
`release` migrates, `web` serves the API and built site). The Discord bot lives in a separate repo,
[SideQuest-Guild/bot](https://github.com/SideQuest-Guild/bot), and talks to this API only over HTTP
(`X-API-Key`). `README.md` is the feature reference; keep it current.

## Layout
- `api/` Litestar API. `domain/<area>/` = `controllers.py` + `services.py` + `dependencies.py`. Migrations in
  `api/src/sidequest_api/lib/migrations/versions/`. `lib/website.py` serves `website/dist`.
- `packages/sidequest-common/` models, schemas, settings shared with the bot repo (pinned there as a git
  dependency on a commit of this repo).
- `website/` Astro static site. `src/layouts/Room.astro` for inner pages, `src/components/Art.astro` for images,
  `service-worker/` for the worker. `DESIGN.md`/`PRODUCT.md` are local-only design references.
- `tests/unit/api/`.

## Working
- `make install`, `make db-up`, `make migrate`, `make api` (site + API on http://localhost:8000; `:4321` is another
  project). `make dev` for hot reload. Local Postgres is on host port **55432**.
- `make fmt`, then `make ci`. Commit and push only when `make ci` exits 0 (gate on the exit code, e.g.
  `make ci && git commit …`). Conventional commit subjects in plain language.
- Commits are SSH-signed via 1Password. If signing fails, ask the user to unlock it; never disable signing.
- Other agents and the user work in this tree at the same time: never `git stash`, `checkout`, `reset`, or commit
  files you didn't change.
- **Website changes need a look, not just a build.** `make web-e2e` (in `make ci`) runs every page in desktop Chrome,
  iPhone WebKit, Android and a 320px phone; read the screenshots in `website/test-results/` for anything visual. A new
  page goes in `PAGES` in `e2e/layout.spec.ts`; a new API call needs a handler in `e2e/fixtures.ts` (unhandled calls
  fail the test).

## Rules that bite
- **Rolling deploys:** old and new API pods run side by side. New schema fields get defaults; new migrations revise
  the current head (check `versions/` and `main` first, the user also adds migrations). The bot lives in
  [SideQuest-Guild/bot](https://github.com/SideQuest-Guild/bot) and pins `sidequest-common` to a commit of this
  repo; bump that pin after a schema/settings/template change the bot needs.
- No function-level imports (ruff PLC0415). Pyrefly known errors live in `pyrefly-baseline.json`. Tests fail on
  warnings.
- Signup status is `signed | tentative | absent`.
- Anything that changes what data is kept or shown: update `website/src/pages/privacy/index.astro`.

## Website
- **No page reloads.** Astro's ClientRouter swaps pages in place and module scripts run once per visit, so every
  page script starts with `onPage(rootSelector, (signal) => …)` (`src/scripts/page.ts`) and passes `signal` to
  window/document listeners, timers and observers. Pure helpers go outside `onPage` (oxlint
  `consistent-function-scoping`). Inline scripts that must run on each arrival need `data-astro-rerun`.
- **Service worker** (`service-worker/sw.js`): pages, scripts and fonts are precached per build; data for the pages
  in `STALE_FIRST` shows from the device, then re-renders via `onFreshData` in `src/scripts/api.ts`. A page added to
  `STALE_FIRST` must register `onFreshData` for what it shows. Kill switch: `SERVICE_WORKER = false` in
  `astro.config.mjs`.
- Images: use `Art.astro` (AVIF + WebP, `fallbackFormat: "webp"`, or the build balloons with PNGs). Its `<picture>`
  is `display: contents`, so the `<img>` is the layout item: grid/flex rules must target the `img`, never
  `parent > *` alone (that broke the phone homepage hero). Grid tracks use `minmax(0, 1fr)` so fixed-width items
  can't widen a 320px screen.
- Lint runs with `--deny-warnings`; `make fmt` can skip `.astro` if ruff fails first, so run `npx oxfmt` in
  `website/`.

## Caching and prod
- Cloudflare caches pages (60 s fresh, then stale while refreshing) and `/api/discord/live`; everything else under
  `/api` and `/auth` is never cached. A route is edge-cached only if it sends `Cloudflare-CDN-Cache-Control` and
  skips the session middleware (`SKIP_SESSION`), so it can never carry `Set-Cookie`. Details in the README.
- Cloudflare CLI: `cf` (installed through mise as `cloudflare-cf`, signed in with `cf auth login`).
- Prod is Cabotage on Kubernetes. How to reach it (AWS profile, kubeconfig, namespace) is in `ops.local.md` at the
  repo root, which is gitignored because this repo is public. The database rejects direct connections; run Python
  inside the web or worker pod with the app's settings instead. A deploy is done when `SOURCE_COMMIT` in both pods
  matches.
- Cabotage deploys a push only after its CI passes, and only if that one commit touches the app's watch paths: a
  push that changes just `.github/` or docs deploys nothing, even when an earlier undeployed commit is underneath.
  Its log line is `skipping …: no changes in watch paths` (`kubectl -n cabotage logs` on the cabotage-app-worker).
- After each prod web deploy, `.github/workflows/deployed.yml` purges Cloudflare's cache and runs the e2e suite
  against sidequest-guild.com. Check that run (`gh run list --workflow deployed.yml`) before calling a deploy good.
