# Pull request archive

The write-ups from the pull requests of the original repository, kept because the
repository itself was deleted and recreated to purge screenshots that had leaked a
home-directory path. The code history is unchanged and complete; this is the prose
that lived only in GitHub's pull requests.

Exported 10 pull requests.


---

## #1 — M0: stop the bleeding

*merged, m0-stop-the-bleeding → main, opened 2026-09-17, merged 2026-09-17*

Milestone **M0 — Stop the bleeding** from [docs/ROADMAP.md](docs/ROADMAP.md): the bugs that broke shipped workflows in the Docker + Postgres deployment. No M1+ work, no UI rework, no Alembic (that stays M2).

## What changed, per M0 item

**1. Filmstock create/update on Postgres (R#1, R#22)**
`film_stocks.expired` is a `Boolean` column now. The API coerces whatever the client sends (`true`, `1`, `"true"`, `None`) and `filmstock_to_dict` always returns a real JSON boolean, so the stray `0` on every non-expired card is gone as well. Existing Postgres databases are migrated in the startup hook with a guarded `ALTER COLUMN expired TYPE BOOLEAN USING (expired <> 0)`. `filmstocks-list.tsx` renders the badge with a ternary instead of `&&`, and the `Filmstock.expired: boolean` type in `lib/api.ts` finally matches what the API sends.

**2. Browser URLs (R#2, R#3)**
- `next.config.mjs` rewrites `/static/:path*` to the backend next to `/api/:path*`.
- `lib/api.ts` owns every base decision: `apiBase()` for fetches (server side `API_BASE`, browser `NEXT_PUBLIC_API_BASE`, empty in Docker so requests stay same-origin) and `backendUrl()` / `getCatalogImageUrl()` for URLs the browser loads itself. The local `API_BASE` constants in `catalog-list.tsx` and `filmstocks-list.tsx` are deleted, `createContactSheet` uses the same base as the other mutations, and the SSR helpers no longer fall back to `localhost:8010` when called from a client component.
- The create/update/upload helpers unwrap the `{ok, <entity>}` envelope so the forms actually get an id back.
- `frontend/Dockerfile` now copies `next.config.mjs` into the runner stage.

**3. Legacy HTML routers (R#4)**
`app/routers/{films,images,search,cameras,filmstocks,lenses}.py` and their `include_router` lines are gone, together with `Jinja2` in `requirements.txt` and `static/css/style.css`. `app/services/face.py` and the `Face`/`Person` models are untouched but now unreachable — nothing imports DeepFace at startup any more. `app/schemas.py` stays for M2.

**4. Uploads without a film (R#5, R#12)**
`image_assets.film_roll_id` is `Mapped[int | None]`, `nullable=True`, with a guarded `ALTER TABLE … DROP NOT NULL` for existing Postgres databases. `PUT /api/images/{id}` honours `film_roll_id: null` and unassigns. `image_to_dict` passes the null through; the images page, the image detail page and the edit form already guard on it. `image-upload-form.tsx` no longer posts the `"none"` placeholder as a film id.

**5. Full objects from PUT (R#6)**
`PUT /api/lenses/{id}` and `PUT /api/filmstocks/{id}` return the object like cameras do, so uploading a catalog image while editing works.

**6. Film form "None" (R#8)**
`film-form.tsx` maps `"None"` to `null` before submit; the backend normalises the literal `"None"` and `""` to `NULL` on create and update; a guarded one-off startup fixup nulls existing `"None"` strings in `film_rolls.camera/lens/film_type`.

**7. Docker (R#25)**
`.dockerignore` for the backend context (frontend/, .git, docs/, screenshots/, `*.db`, static/uploads, `__pycache__`, .venv) and `frontend/.dockerignore` (node_modules, .next, .env*). Compose gained a `pg_isready` healthcheck with `depends_on: condition: service_healthy`, lost the obsolete `version:` key, and defaults `DEEPFACE_ENABLED` to `false`. README ports already matched compose (UI on 8021, API unpublished).

**8. Docs**
Every M0 checkbox in `docs/ROADMAP.md` is ticked; the README's Known issues drops the bullets M0 fixed and keeps the rest, and the project structure, API reference and Docker notes match the code again.

## Verification

Python 3.11 venv, `requirements.txt` minus `deepface`, `DEEPFACE_ENABLED=false`, throwaway `postgres:16` on port 55433.

- `pytest tests -q` → **10 passed** against Postgres. New suite in `tests/`: boolean `expired` on create and update, upload without `film_roll_id`, `PUT /api/images/{id}` with `film_roll_id: null`, full objects from the lens and filmstock PUTs, `camera: "None"` stored as null, legacy `GET /films` → 404, `GET /openapi.json` with no non-`/api` paths. Without `DATABASE_URL` all 10 skip instead of falling back to SQLite.
- Upgrade path proven separately: built the schema, downgraded it to the pre-M0 shape (`expired INTEGER`, `film_roll_id NOT NULL`, rolls holding `'None'`), booted the app, and the startup hook turned the column into `BOOLEAN`, dropped the NOT NULL and nulled the `'None'` strings, with the migrated row still updatable from a JSON boolean.
- Frontend: `npm ci --legacy-peer-deps`, `npx tsc --noEmit` (clean) and `npx next build` (20 routes) both pass. `routes-manifest.json` contains both rewrites.
- Docker: `docker compose config` validates; `docker compose build web` and `build frontend` both succeed (frontend ~95 s), and the backend image contains only `app/ static/ tests/ requirements.txt Dockerfile docker-compose.yml`.
- Full stack `docker compose up -d`: db reports healthy before web starts; `GET http://localhost:8021/static/catalog/films/fomapan-100.svg` → 200 `image/svg+xml` through the new rewrite; the rendered `/filmstocks` and `/cameras` HTML contains same-origin `/static/catalog/...` sources and zero `localhost:8010`; `POST /api/filmstocks {"expired": true}` → `"expired": true`; upload without a film → `film_roll_id: null`; `GET /films` on the backend → 404. Stack and throwaway database removed afterwards.

## Deliberately left out

R#7 (original filenames), R#9 (file lifecycle), R#10 (face rows blocking film delete), R#11 (seed on every restart), R#13–R#21, R#23 (Alembic), R#26–R#34 — all M1/M2/M3 items. `services/face.py`, the `Face`/`Person` models, `app/schemas.py` and the `deepface` requirement are kept untouched as instructed; the DeepFace download still makes the backend image large until M2 decides its fate.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #2 — M1: UI rework

*merged, m1-ui-rework → main, opened 2026-09-17, merged 2026-09-17*

Milestone **M1 — UI rework** from [docs/ROADMAP.md](docs/ROADMAP.md), complete. The UI is now built
around the workflow the roadmap describes — *new roll → dump scans → number and annotate frames →
find it later* — instead of one table or card grid per entity. Stack unchanged: Next.js 16 app
router, React 19, TypeScript, Tailwind 4, shadcn/ui.

## The M1 checklist

**1. Information architecture.** Rolls are the home page (`/`; `/films` renders the same page so
old links keep working). Each row carries a strip of real thumbnails, the film, the camera, the
shot date range, the frame count and the storage location. Cameras, lenses and film stocks are one
**Gear** section with three tabs. Search is no longer a page: the filter bar above the roll list
does text (title, notes, serial, folder, gear), camera, film and date range, and `/search?q=`
redirects to `/?q=`. Navigation went from six flat links to three: Rolls, Frames, Gear.

**2. The roll page is a workspace.** Contact sheet on top (generate one, or drop the scan of the
paper one), then the drop zone, then the frames. Every cell shows its frame number and capture
date; the number and the note are edited **in place** — Enter or blur saves, Escape reverts, a
failed save puts the old value back and says why. Keyboard: arrows walk the grid (the column count
is read off the DOM so it follows the CSS), Enter opens the viewer, Space selects, Escape clears.
Multi-select raises a sticky bulk bar: delete, move to another roll (or out of every roll), set a
capture date. The drop zone takes many files and ZIPs at once, one request per file so each
progress bar is real, and reuses the existing `bulk` and `bulk_zip` endpoints.

**3. Frame viewer.** Replaces both the image detail page and the image edit page. Previous/next by
button and arrow key, zoom (buttons, `+`/`-`/`0`, double-click, drag to pan), download, Escape to
close, and the metadata panel beside the image editing frame number, capture date, roll and notes.
`/images/{id}` is still a route and opens the viewer with the rest of its roll loaded, so
previous/next works when you arrive by URL; `/images/{id}/edit` redirects to it.

**4. Forms are dialogs and side panels.** The new-roll wizard and the gear forms are `Dialog`, the
roll editor is a `Sheet`. Validation messages come from the API's error body and land on the field
that caused them (a duplicate camera name shows *"A camera named “Nikon F5” already exists."* under
the name field, not "Failed to save"). Saving keeps you where you were and calls `router.refresh()`.

**5. New roll wizard.** Title and dates → gear and film → storage, then straight into the upload
zone, then "Open roll". The last camera, lens and film are remembered in `localStorage`, so the
next roll off the same body is two clicks. Also: the film-kind select finally lists all four kinds
instead of "the kinds already in use" (R#21).

**6. Mobile / tablet.** Navigation collapses into a `Sheet` below `md`, the roll list is one
column, targets are 44px. Tested at 375px: no horizontal scrolling on any route.

**7. Empty, loading and error states.** One `EmptyState` and one `ErrorState` used everywhere, a
`loading.tsx` skeleton per section that mirrors the layout it replaces, an `error.tsx` per section
with a retry, and `not-found.tsx` for a roll or frame that is gone. Toasts are only used for
background results (uploads, bulk actions, deletes).

**8. Visual pass.** `ThemeProvider` is wired in `layout.tsx` with `attribute="class"` and there is
a light/dark toggle in the header. A four-step typography scale (page / section / body / meta) plus
a monospace class for numbers. Real thumbnails everywhere, and a `.frame-cell` utility that renders
every scan at 3:2 with `object-contain` — no square crops.

**9. Cleanup.** 42 unused components deleted from `components/ui` (15 remain: alert-dialog, badge,
button, checkbox, dialog, input, label, progress, select, sheet, skeleton, tabs, textarea, toast,
toaster); each was grep-checked, including the ui files that import each other, transitively. The
31 dependencies only those files imported went with them (42 → 19), among them `@vercel/analytics`
and four of the five `"latest"` specifiers. `@vercel/analytics` and the three unused Google font
loaders are gone from `layout.tsx`; the font stack is the system one, so the frontend builds and
runs without internet.

## Backend changes

Kept to what the UI needs. No Alembic, no foreign keys, nothing else from M2+.

- **Disk thumbnail cache for `GET /api/images/{id}/preview`** — `static/cache/<id>_<width>_<mtime>.jpg`,
  git-ignored, atomic writes, superseded entries swept, `X-Preview-Cache: hit|miss`. Keyed by the
  source file's mtime, so a re-scan can never serve a stale thumbnail. Pulled forward from M3 with
  the owner's agreement, because the roll list and the frame grid ask for a preview per frame.
- **`POST /api/images/bulk_update`** (`{ids, film_roll_id?, capture_date?, frame_number?}`; only
  the keys you send are written, `film_roll_id: null` unassigns) and **`POST /api/images/bulk_delete`**
  (`{ids, delete_file}`) for the bulk bar.
- **`GET /api/films` returns `image_count`, `cover_image_id` and `cover_image_ids`** (at most four)
  so the roll list shows a count and a thumbnail strip without an N+1 — two grouped queries for the
  whole list. `cover_image_ids` is one field beyond the brief; the roadmap asks for a *thumbnail
  strip* per row, and shipping four ids costs nothing extra on the same query while the alternative
  was fetching every image in the archive to render a list.
- **A structured error body** for the validation failures the new dialogs can actually produce:
  `{"error": {"code", "message"}}` with a real 4xx. Codes: `invalid_json`, `invalid_title`,
  `invalid_name`, `invalid_date`, `invalid_date_range`, `invalid_number`, `invalid_kind`,
  `invalid_type`, `invalid_ids`, `nothing_to_update`, `not_enough_images` (400), `duplicate_name`
  (409), `unknown_roll` (404). Everything else is deliberately untouched — "not found" is still
  HTTP 200 with `{"error": "not_found"}`, because turning that around is R#17 in M2.
- `GET /api/films/{id}` sorts a roll's scans by frame number (nulls last) so the grid order matches
  `cover_image_id`.

One frontend-side change worth noting: the eight moved routes are `redirects()` entries in
`next.config.mjs` rather than pages that call `redirect()`, so they answer a real **307** instead of
redirecting after hydration.

## Verification

| Check | Result |
|---|---|
| `pytest tests` against Postgres 16 (throwaway container, `DEEPFACE_ENABLED=false`) | **42 passed** — 13 M0 + 29 new in `tests/test_m1.py` |
| `npx tsc --noEmit` | clean |
| `npx next build` | succeeds (7 routes) |
| Playwright smoke test, real backend + frontend, seeded archive | **48/48 checks, 0 console errors** |
| `docker compose config` | valid |
| `docker build -f frontend/Dockerfile frontend` | succeeds |

`tests/test_m1.py` covers all four backend additions: counts and the cover strip, bulk update
(reassign, set date, unassign, bad date, unknown roll, empty selection, nothing to update), bulk
delete (with and without `delete_file`), the preview cache (hit/miss, keyed by width, invalidated
by mtime, swept on delete) and each structured error.

The smoke test (`frontend/e2e/smoke.mjs`, `npm run e2e`) runs against a backend on `:8010` with
four seeded rolls of generated JPEG **and TIFF** scans. It visits every route at 1440px and at
375px, creates a roll through the wizard (including the "a roll needs a title" path), uploads two
files through the drop zone, checks the gear is remembered, edits a frame number and a note in
place and reloads to prove they stuck, opens the bulk bar, walks the grid with the arrow keys,
opens the viewer with Enter and closes it with Escape, pages through frames with the button and the
arrow key, zooms, checks all eight redirects, toggles dark mode, deletes the roll it created, and
fails on any console error or failed request.

## Screenshots

README: roll list, roll workspace, frame viewer, roll list at 375px, roll workspace at 375px, the
wizard, gear, and the frames page in dark mode.

## Deliberately left out

- **Pagination and server-side search** (R#20, M3). The roll list still fetches every roll and
  filters in the browser — but it no longer fetches every image, which is what the new
  `image_count` / `cover_image_ids` fields are for.
- **Original filenames and frame numbers parsed from them** (R#7, M2). Bulk-uploaded frames still
  arrive unnumbered; the grid is built so numbering them is fast, which is the M1 answer.
- **"Not found" as a real 404** and validation on endpoints the UI does not touch (R#16/R#17, M2).
- **`delete_file`** is supported by the bulk endpoint but the UI always passes `false`, and both
  delete dialogs say the files stay on disk — the file lifecycle is R#9 in M2.
- `next.config.mjs` still carries `middlewareClientMaxBodySize`, which Next 16 warns is
  unrecognised. It predates this branch and I did not want to guess its replacement; large uploads
  through the Docker proxy should be checked when that is sorted out.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #3 — M2: archive integrity

*merged, m2-archive-integrity → main, opened 2026-09-17, merged 2026-09-17*

Milestone **M2 — Archive integrity** from [docs/ROADMAP.md](docs/ROADMAP.md), complete.

The data model is the archive's memory, and it was leaking: filenames were thrown away on upload,
gear was referenced by a string that a rename silently broke, deleting a roll left its files on
disk forever, the schema was maintained by guarded `ALTER TABLE`s inside `try/except: pass`, and
"not found" was an HTTP 200. This closes R#7, R#9, R#10, R#11, R#14, R#15, R#16, R#17, R#18,
R#21, R#23, R#24 and, in passing, R#13.

## What is in it

1. **Postgres only.** `DATABASE_URL` is required and must be a Postgres URL; without it the
   backend stops at startup and explains how to set one. The SQLite branches are gone
   (`check_same_thread`, the `Text` variant on the JSON column), columns are native
   `Boolean`/`Date`, and `tests/conftest.py` refuses a non-Postgres URL.
   `scripts/migrate_sqlite_to_pg.py` copies an old `negarchive.db` across — it migrates the
   target schema first, keeps ids (so stored paths and bookmarks still resolve), resolves gear
   names to the new foreign keys, drops the `"None"` strings the old form stored, fixes the id
   sequences afterwards and refuses a target that already holds rolls.
2. **Original filenames and frame numbers (R#7, R#24).** `image_assets.original_filename` is
   written by the single, bulk and ZIP upload paths. When the client sends no `frame_number` it
   is parsed from the name: an explicit `frame<n>` wins, otherwise the last group of one to four
   digits (`Roll12_007.tif`, `NEG-2024-011_007.jpg`, `_Frame007`, `007.jpg`, `img_0007`, NegPy's
   `{roll}_{frame}` → 7; `Roll12.tif` → nothing, because a number glued to a word is part of the
   word). Every list sorts by `frame_number NULLS LAST, id`, including the contact sheet's input,
   and the download is named after the original. The frame viewer's side panel shows it.
3. **Gear by foreign key (R#14).** `film_rolls.camera_id`, `lens_id`, `film_stock_id`, nullable,
   `ON DELETE SET NULL`, backfilled from the name columns by the migration. The name columns stay
   for one release and now answer with the catalog entry's *current* name, so renaming a camera
   reaches every roll instead of orphaning them. The API accepts ids or names and returns both.
   Deleting gear that rolls still use is a 409 with the count unless `?force=true`; forced, the
   rolls lose the id and keep the name as plain text. The wizard, the edit sheet and the roll
   list's filters all use ids.
4. **Seed data (R#11).** Startup seeds a catalog table only while it is empty; `POST /api/seed`
   asks for the starter gear back on purpose. A deleted Nikon F5 stays deleted across restarts.
5. **Validation and status codes (R#16, R#17).** Pydantic request *and* response models for every
   endpoint. 404 for anything missing, 400 for input the API parses itself, 422 for a body of the
   wrong shape, 409 for duplicates and gear in use, 413 over the size limit, 415 for a file that
   is not an image. One body everywhere, now with the field:
   `{"error": {"code", "message", "field"}}`; `lib/api.ts` puts the message on that input.
6. **File lifecycle (R#9).** Deleting an image or a roll deletes the managed files too;
   `?keep_files=true` (and a checkbox in every delete dialog) opts out.
   `POST /api/maintenance/sweep_orphans` lists files under `static/uploads` with no record and
   records whose file is missing — a dry run unless `?apply=true`, which deletes the orphan
   *files* only; records are reported, never deleted. A file is never deleted when its row is not
   `managed` or when it lives outside the uploads root.
7. **Upload allowlist (R#18).** `jpg jpeg png tif tiff webp dng` by extension *and* by magic
   bytes, a configurable `MAX_UPLOAD_MB` (default 512), an all-or-nothing bulk upload that leaves
   no half-written files behind, and a static mount that can never serve an upload as `text/html`
   (neutral type + `Content-Disposition: attachment` + `nosniff` everywhere under `/static`).
8. **Faces deleted (R#10, R#15).** `app/services/face.py`, the `Face` and `Person` models, their
   tables and the `deepface` and `scikit-learn` requirements. `opencv-python-headless` stays —
   the preview fallback still needs it for 16-bit TIFFs. `DEEPFACE_ENABLED` and
   `FACE_MATCH_THRESHOLD` are out of compose and the README. **The backend image went from about
   2 GB to 0.28 GB and contains no TensorFlow.**
9. **Film stock fields (R#21).** `manufacturer` and `format` on film stocks, `format` on rolls
   (`35mm`, `120`, `4x5`, `8x10`, `other`), in the API and in the gear dialog and roll forms. The
   `kind` select already listed the enum since M1; it is now covered by a test.
10. **Docs.** The M2 checklist is ticked with what actually shipped; the README covers the
    migration workflow, the SQLite move, the error table, the new fields and endpoints, the env
    vars and the allowlist.

## Migration notes

* Two revisions, a linear chain: **`0001_baseline` → `0002_m2_archive_integrity`** (head).
  `alembic.ini` keeps `sqlalchemy.url` empty and `alembic/env.py` reads `DATABASE_URL`, failing
  loudly when it is unset. Files are `alembic/versions/<YYYYMMDD_HHMM>_<slug>.py`.
* `0001_baseline` reproduces the pre-M2 schema on an empty database **and does nothing on a
  database that already has those tables**, so `alembic upgrade head` is the single upgrade path
  for a fresh install and for an archive that has been running since M0.
* `app/main.py` runs `alembic upgrade head` in process at startup (`alembic.command.upgrade` with
  a `Config` built in code, reusing the app's engine) instead of the old `ALTER TABLE` hook.
  `Base.metadata.create_all` is not called anywhere any more — change a model *and* write a
  revision.
* **For the M3 branch:** your revisions should set `down_revision = "0002_m2_archive_integrity"`.
  `image_assets.storage_mode` already exists, `NOT NULL DEFAULT 'managed'`, with `'linked'` as
  the other accepted value; the delete path already refuses to touch a file whose row is not
  `managed`, so import-by-reference can rely on it.
* Downgrading `0002` restores empty `faces`/`persons` tables and drops the new columns; the
  backfilled ids are not written back into the name columns, because the name columns never left.

## Breaking API changes

| Change | Before | Now |
|---|---|---|
| Missing record | HTTP 200 `{"error": "not_found"}` | HTTP 404 `{"error": {code, message, field}}` |
| `DELETE /api/images/{id}`, `DELETE /api/films/{id}` | never deleted files | delete the managed files; `?keep_files=true` opts out. `?delete_file=` still wins when sent explicitly |
| `POST /api/images/bulk_delete` | `{"delete_file": false}` default kept files | `{"keep_files": true}` opts out; `delete_file` still honoured |
| Upload of a non-image | accepted and served back (stored XSS) | 415 `unsupported_file_type` |
| Upload over `MAX_UPLOAD_MB` | accepted | 413 `file_too_large` |
| Deleting gear a roll uses | silently orphaned the roll | 409 `gear_in_use` with the count, unless `?force=true` |
| Body of the wrong shape | bare 500 | 422 `invalid_request` naming the field |
| `GET /api/images` order | by id | by `frame_number NULLS LAST, id` |
| Image `url` | derived from the record's *type*, so it broke after a type change (R#13) | derived from the stored path |
| New response fields | — | `original_filename`, `storage_mode`; `camera_id`/`lens_id`/`film_stock_id`, `format` on rolls; `manufacturer`, `format` on film stocks |
| `DATABASE_URL` | optional, fell back to SQLite | required, must be Postgres |

`tests/test_m1.py` has exactly one adjusted expectation, marked in place with why:
`test_bulk_delete_removes_rows_but_keeps_files_by_default` became
`test_bulk_delete_keeps_the_files_when_asked_to` (the default flipped, and the "not found" body
it asserted is now a 404). `tests/test_m0.py` is untouched.

## Touched outside M2's ownership

Kept minimal, flagged here for the M3 branch:

* `docker-compose.yml`, `web` service **environment only**: `DEEPFACE_ENABLED` and
  `FACE_MATCH_THRESHOLD` removed (M2 deletes the feature), `MAX_UPLOAD_MB` added, a comment on
  `DATABASE_URL`. The `db` service, the volumes and the frontend service are untouched.
* `tests/conftest.py`: drops the schema (including `alembic_version`) so every run migrates from
  the first revision, and turns a non-Postgres `DATABASE_URL` into an error.
* `frontend/e2e/smoke.mjs`: the M1 smoke test, updated for the API changes (filename-derived
  frame numbers, the re-sorted grid, the original filename in the viewer, the keep-files
  checkbox, gear remembered as ids).
* `frontend/components/upload-zone.tsx`: the `accept` default now mirrors the backend allowlist.
* `app/main.py`: startup runs the migrations and the static mount is the safe one; also moved
  from the deprecated `@app.on_event("startup")` to a lifespan handler.

## Verification

* `pytest tests` → **140 passed** against a throwaway Postgres 16, with new
  `tests/test_m2_*.py` files for the migrations, the SQLite move, filenames and ordering, gear
  ids, validation and status codes, and the file lifecycle and allowlist.
* Alembic on an empty database: `upgrade head` → `alembic check` clean → `downgrade base` →
  `upgrade head` again, all green (the enum types are dropped with their tables, so the second
  upgrade does not trip over them).
* The pre-M2 upgrade path, proven twice: once in the suite from `0001_baseline`, and once by
  building the old schema with `origin/main`'s `app/models.py` + `create_all` in a second empty
  database, inserting rolls with camera names, images, a person and a face, then running
  `upgrade head` — the ids backfill (case- and whitespace-insensitively), an uncatalogued name
  keeps its free text, rolls and images keep every field, `original_filename` is NULL for rows
  that predate it, `storage_mode` defaults to `managed`, and `faces`/`persons` are gone.
* `scripts/migrate_sqlite_to_pg.py` is tested as a real subprocess against a scratch Postgres:
  dry run writes nothing, a full run preserves ids, dates, notes and the boolean `expired`, and
  the sequences are usable afterwards.
* Frontend: `npm ci --legacy-peer-deps`, `npx tsc --noEmit` (clean), `npx next build` (clean),
  and `npm run e2e` against a real backend + frontend: **52 checks, 0 failed**, including the
  four new ones.
* `docker compose config` valid; `docker compose build web` succeeds; `pip list` inside the image
  shows no `tensorflow`, `deepface`, `keras` or `scikit-learn`, and `alembic upgrade head` runs
  from inside the container. Starting it with an empty `DATABASE_URL` fails with the intended
  message.

## Deliberately not done

* The README screenshots still show the M1 UI. The visible differences are small (an extra line
  in the viewer's panel, two badges on a gear card, a checkbox in the delete dialog) and
  refreshing them belongs with M3's compose rework, which changes the paths anyway.
* The orphan sweep has no UI. M3 owns the settings/maintenance screens; the endpoint is there and
  documented for it.
* `film_rolls.camera`/`lens`/`film_type` are kept — "one release", as the roadmap says. Dropping
  them is a one-line revision whenever the owner decides no client needs them.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #4 — M3: offline-first

*merged, m3-offline-first → main, opened 2026-09-17, merged 2026-09-17*

Milestone **M3 — Offline-first and easy local use** (`docs/ROADMAP.md`), complete.

The short version: installing NegArchive is now `docker compose up`, the whole
archive lives in one directory you can copy, scans no longer have to be copied
into it at all, and the UI installs on a phone and still answers "which binder is
this roll in" with the server switched off.

---

## What is in it

**1. Dependencies (R#29, R#30).** The three remaining `"latest"` specifiers are
pinned to the versions npm had already resolved, `pnpm-lock.yaml` is gone (the
Dockerfile and CI both use npm; two lockfiles that disagree is worse than none),
the package is renamed `negarchive-frontend`, and `typescript.ignoreBuildErrors`
is `false`.

`middlewareClientMaxBodySize` was checked as asked — and it was a real bug. It is
in Next 16's schema, but under `experimental`, and it was set at the **top
level**, where Next ignores it with an "Unrecognized key(s)" warning. Bulk
uploads had been capped at the 10 MB default all along — one 16-bit scan. In Next
16 that spelling is also deprecated, so it is now
`experimental.proxyClientMaxBodySize` and the build is warning-free.

**2. One Compose stack, one directory.** Postgres + backend + frontend, and a
single bind-mounted `./data/` holding `postgres/`, `uploads/`, `catalog/`,
`cache/` and `backups/`. `.env.example` documents every variable and each has a
working default, so an empty `.env` — or none — still starts. Healthchecks on
`db` (`pg_isready`) and `web` (`/api/health`, which queries the database), and
the frontend waits for `web` to be *healthy*, not merely started: the first page
is server-rendered, so a frontend that comes up before the migrations have run
serves an error page. No named volumes at all — a volume you cannot see is a
volume you forget to back up.

`app/paths.py` is the only thing that knows where a file lives. `/static` URLs
are unchanged; only the directory behind them moved out of the source tree, and
`paths.resolve()` falls back to the old in-tree location so an M0/M1 archive
keeps rendering without a migration step.

Plus a `Makefile` (`up`, `dev`, `test`, `backup`, and `down/logs/lint/typecheck/
build/e2e/restore`) and `.python-version` = 3.11 (**R#31**). `make test` starts
and removes its own throwaway Postgres.

**3. Pagination and server-side search (R#20).** `GET /api/films` takes `q`,
`camera_id`, `film_stock_id`, `camera`, `film_type`, `from`, `to`, `limit`,
`offset`; `GET /api/images` takes `film_id`, `type`, `q`, `unassigned`,
`storage_mode`, `limit`, `offset`.

The response shape is backwards compatible on purpose: **without `limit` both
still answer with a bare JSON array**, so every existing caller and every M0/M1
test keeps working; **with `limit`** they answer `{items, total, limit, offset,
has_more}`. `X-Total-Count` is set either way. Gear filtering uses M2's foreign
key when the column exists and the name column until then, so nothing has to
change when M2 lands. The roll list and the frames page render their first page
on the server from the query string — `/?q=harbour` is a link you can keep — and
"Load more" the rest.

**4. Import by reference ("link mode").** `POST /api/library/roots` registers a
folder; a scan turns each subfolder into a roll draft (title and serial parsed
from the folder name) and each image into a frame with `storage_mode='linked'`,
`source_path`, `content_hash`, `original_filename` and a parsed frame number.
Rescans are idempotent by path, a file edited in place updates its hash, and a
file that *moved* is re-homed onto its existing record — so reorganising a
library does not lose frame numbers or notes. Preview and download work for
linked files; `_delete_asset_file` refuses to touch anything linked or outside
`DATA_DIR`, even with `delete_file=true`.

It is **off by default**: `LIBRARY_ROOTS_ALLOW` is empty, and with nothing
configured no folder can be registered at all. The API has no password by default
and "POST me any path" would otherwise turn the archive into a file server for
the whole disk.

**5. Watch folder.** An asyncio task sweeps the roots marked `watch` every
`WATCH_INTERVAL_SECONDS`; the scan runs in a thread, a failed sweep is logged and
the loop carries on, and the UI toggle is re-read on every tick. Polling rather
than inotify because the interesting case is an SMB share on a NAS. Settings has
the toggle and a last-scan readout.

Note a deliberate deviation from the brief: **unset means off**, and the Compose
stack sets `30`. Defaulting to 30 meant that running `uvicorn` for any reason
started a process walking directories every half minute.

**6. Content hash.** `app/services/hashing.py`: SHA-256 of the decimal file size,
the first 1 MiB, the last 1 MiB and 16 evenly spaced 256 KiB interior chunks. The
module docstring *is* the specification — NegPy is GPL-3 and is not imported or
consulted. At most ~6 MiB is read per file however large it is (there is a test
that measures this). Computed on every upload and every link, and indexed.

**7. Backup and restore.** `scripts/backup.sh` writes
`data/backups/negarchive-<timestamp>.tar.gz` with `pg_dump --clean --if-exists`,
the managed files and a MANIFEST that says how to put it back, then prunes to
`BACKUP_KEEP`. `scripts/restore.sh` unpacks one, stops `web`, reloads the
database, copies the files back, clears the preview cache (its keys reference the
old mtimes) and starts `web`; it confirms first unless `FORCE=1`.

`GET /api/export` streams a ZIP of `export.json` — every table as ordinary JSON,
ISO dates, no SQL dialect — plus the managed files and a `README.txt`, chunk by
chunk, so a 300 GB archive is never staged. `POST /api/import` merges one back
with `?dry_run=`, id remapping and skip-by-content-hash, and **never overwrites**.
`GET /api/export/rolls.csv` is the spreadsheet. Restore is documented step by
step in the README, including the extra first step for a fresh machine.

**8. PWA.** `manifest.webmanifest`, generated icons (`scripts/make_icons.py`, so
they are reproducible rather than mystery PNGs) and a hand-written service worker
— ~150 lines, no dependency, no build step. It caches the app shell, the roll
list and the rolls you have visited; navigations and API reads are network-first,
hashed chunks and previews are cache-first; there is an offline banner. Nothing
that changes data is cached or replayed, and there is no background sync queue on
purpose: an edit that silently lands three hours later is a good way to lose the
link between paper and record.

**Honest caveat, documented in the README and the roadmap:** browsers only
register a service worker in a secure context. `http://localhost` counts,
`http://192.168.1.37:8021` does not, so over plain HTTP on the LAN the app does
not install and caches nothing. Getting the offline version onto a phone needs
TLS in front (Caddy, mkcert, Tailscale); shipping that is its own piece of work
and is now a roadmap item.

**9. LAN discoverability.** `GET /api/system/info` reports the LAN addresses and
the UI URL, the backend logs them at startup, and the app-shell footer shows the
URL with a QR code rendered server-side as SVG (`segno`, ~60 kB, pure Python), so
the frontend needs no QR library and it works with no internet. In Docker the
container only sees its bridge address, so `NEGARCHIVE_PUBLIC_HOST` overrides it.

**10. Optional shared password (R#26).** `NEGARCHIVE_PASSWORD`; off by default.
With it set, everything needs a token except `/api/health`, `/api/system/info`
and the login endpoint — **`/static` included**, because a photo archive whose
pictures are readable without the password is not protected. The frontend shows a
sign-in sheet and every request goes through one `apiFetch`, which attaches the
token; server-side it forwards the cookie from the page request, so
server-rendered pages work for a signed-in visitor. The token is derived from the
password, so updating the container is not a logout and changing the password
revokes every session. `app/auth.py` says plainly what it is not (no rate
limiting, no lockouts, not for the internet).

**11. Tests and CI.** 86 new tests in `tests/test_m3_*.py`, 128 in total, all
against Postgres 16. `.github/workflows/ci.yml` has four jobs — **backend**
(ruff, an Alembic up → down → up round trip, pytest against a Postgres service
container), **frontend** (eslint, `tsc`, `next build`), **e2e** (the Playwright
smoke test against a real backend and a production build, over an archive seeded
by the new `scripts/seed_demo.py`), **compose** (`docker compose config` and a
syntax check of both scripts). Lint configs are checked in: `ruff.toml` and
`frontend/eslint.config.mjs`.

**12. Docs.** Every M3 box ticked in `docs/ROADMAP.md` with what was actually
built, and three things listed as deliberately left. `README.md` has a new
install section, an env table with ten new variables, and new sections on import
by reference, backup and restore, offline use, the LAN, and the password.

---

## New environment variables

| Variable | Default | What it does |
|---|---|---|
| `DATA_DIR` | `./data` (`/data` in the container) | the one directory the archive lives in |
| `UI_PORT` | `8021` | the port the browser uses; the backend needs it to print the right URL |
| `NEGARCHIVE_PUBLIC_HOST` | empty | host to advertise in the footer and QR code; needed in Docker |
| `NEGARCHIVE_PASSWORD` | empty | optional shared password; empty means no login |
| `LIBRARY_ROOTS_ALLOW` | empty | `:`-separated folders link mode may read; **empty disables the feature** |
| `LIBRARY_HOST_DIR` | `./data/library` | host folder mounted read-only at `/library` |
| `WATCH_INTERVAL_SECONDS` | unset = off; Compose sets `30` | watch-folder sweep interval |
| `BACKUP_KEEP` | `7` | how many backups `scripts/backup.sh` keeps |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `negarchive` | database credentials |

---

## Rebased onto M2

M2 is merged; this branch is rebased on top of it and the two are reconciled. What
that took, in case it matters later:

* **The Alembic chain is linear.** M3's duplicate baseline is deleted, M2's
  `alembic.ini` and `env.py` are kept, and the M3 revision is now
  `0003_m3_offline_first` with `down_revision = "0002_m2_archive_integrity"`. Its
  guarded adds for `original_filename` and `storage_mode` are kept rather than
  deleted: they are no-ops against a database that ran M2's revision, and they are
  what lets the file be applied to an archive whose history took another route.
  Verified up → down → up from empty against Postgres 16.
* **One frame-number parser.** M3's temporary copy is gone; link mode calls M2's
  `frame_number_from_filename` and uses its `ALLOWED_EXTENSIONS`, so a linked file
  and an uploaded one are read by the same rules. The duplicated parser tests went
  with it; `tests/test_m2_filenames.py` owns that now.
* **`app/models.py`** — M2's `original_filename` / `storage_mode` definitions kept
  as they are; M3 adds `source_path`, `content_hash`, `film_rolls.source_dir`,
  `LibraryRoot` and `Setting`.
* **`app/routers/api.py`** — M2's Pydantic rewrite is the base. M3 re-applies: file
  paths through `app/paths.py` (`_abs()` is now the single mapping from a stored
  path to a location on disk), pagination and search on `/films` and `/images`, the
  content hash in `_new_image`, `source_path` / `content_hash` / the linked `url` in
  `image_to_dict`. M2's `delete_asset_file` already refused to touch a `linked`
  row — it anticipated this — and only its "inside uploads" check needed to move to
  `DATA_DIR`.
* **`app/schemas.py`** — `ImageOut` gains `source_path` and `content_hash`. M2's
  response models are strict, so without this the API stopped returning them, which
  is that strictness earning its keep.
* **`app/main.py`** — M2's in-process `alembic upgrade head`, `SafeStaticFiles` and
  exception handlers, plus M3's `DATA_DIR` mount, auth middleware, watcher task, LAN
  banner and three extra routers.
* **`app/seed.py`** — M2's "seed only when empty" logic kept; it creates the catalog
  directories under `DATA_DIR` now and copies the bundled pictures in, because that
  is where `/static` reads from.
* **`docker-compose.yml`** — M3's restructuring with M2's `DATABASE_URL` comment and
  `MAX_UPLOAD_MB` re-applied (and exposed in `.env.example`).
* **`frontend/lib/api.ts`** — M2's `field`-aware `ApiError`, gear ids and
  `keep_files` kept; every request re-routed through M3's `apiFetch`, which attaches
  the session token.
* **`roll-browser.tsx`** — M2's id-based gear filters and keep-files delete dialog,
  on top of M3's server-side paging. The filters send `camera_id` /
  `film_stock_id`; a `?camera=<name>` bookmark from before M2 still resolves, on the
  server and in the browser.
* **`tests/`** — M2's file and filename tests resolve paths through `app.paths`,
  because M3 moved the bytes under `DATA_DIR` while leaving the stored `static/…`
  form alone (same assertions, one indirection).
  `test_m2_migrations.py` asked for a literal head revision and now asks Alembic.
* **`ruff check`** met M2's code for the first time: import sorting, and eight
  `raise … from exc`.
* The orphan sweep reports the stored form (`static/uploads/…`) rather than a path
  relative to the working directory, which stopped meaning anything once `DATA_DIR`
  could be elsewhere.

## Deliberate omissions

- **Alembic autogenerate is not checked in CI.** The roadmap asks for it under
  M2, which owns the baseline. CI runs the migrations up, down and up again
  instead, which catches a migration that cannot be rolled back.
- **No background sync queue in the service worker**, and there should not be one
  (see above).
- **`GET /api/images/{id}/preview` still does blocking file IO** on the event
  loop (**R#19**). Out of scope here; noted in the README's known issues.
- **No TLS in the stack**, which is what keeps the PWA from installing over the
  LAN. Documented rather than quietly shipped.
- **`requirements.txt` is not trimmed** — M2's job.

## Verification

Run against a throwaway Postgres 16 on port 55441 and a full Compose stack,
removed afterwards.

- `pytest tests` — **217 passed** (M0, M1, M2 and M3 together), Python 3.11,
  Postgres 16.
- `ruff check .` — clean.
- `npx tsc --noEmit` — clean.
- `npx next build` with `ignoreBuildErrors: false` — clean, and no config warning.
- `npx eslint .` — 0 errors (21 warnings, all the Next 16 React Compiler rules on
  pre-existing M1 components; set to warn with a note in the config).
- `npm run e2e` against a real backend and a production build — **72 checks, all
  green**, M2's and M3's together, including the PWA, the LAN footer, the settings
  page, pagination and the keep-files delete dialog.
- Alembic `upgrade head` → `downgrade base` → `upgrade head` from an empty database
  against Postgres 16, across all three revisions.
- `docker compose config` valid. `docker compose up -d --build` from a clean
  `data/`: all three services healthy, `data/` came out with exactly
  `postgres/ uploads/ catalog/ cache/ backups/`. Through port 8021 only —
  `/api/health`, `/api/system/info`, the QR SVG (`image/svg+xml`, `currentColor`),
  a roll created, a scan uploaded (`content_hash` and `original_filename` both
  filled in), its preview rendered, `/library` registered and scanned
  (*"2 new, 0 re-homed, 0 updated, 0 unchanged, 1 new rolls"*, serial `2024-0099`
  parsed out of the folder name), a linked file downloaded, the export ZIP
  (`{'managed': 1, 'linked': 2}` — the linked files listed but not copied), and
  the roll CSV.
- `scripts/backup.sh` → a 12 KB archive with `database.sql`, `uploads/`,
  `catalog/` and a MANIFEST. A **second stack** (`-p negarchive2`, `DATA_DIR=./data2`,
  port 8022) started empty, then `FORCE=1 scripts/restore.sh <archive>`. Diffing
  `/api/export.json` between the two: `cameras`, `film_rolls`, `film_stocks`,
  `image_assets`, `lenses` and `settings` **byte-identical**. The only difference
  was `library_roots.last_scan_at` / `last_scan_summary`, because the watch-folder
  poller on the first stack swept again six seconds *after* the backup was taken —
  which is the watcher working, not a restore bug.
- `docker compose down -v` on both projects, and `data/`, `data2/`, `scanlib/`
  and `.env` removed afterwards. The working tree is clean.

**CI on this PR: all four jobs green** — backend 1m31s, frontend 42s, e2e 2m21s,
compose 7s.

It failed on the first run and found something worth having: `tests/` is not a
package, so pytest puts *that* directory on `sys.path` rather than the repository
root. `python -m pytest` works because `-m` adds the working directory; a bare
`pytest tests`, which is what CI runs, died with
`ModuleNotFoundError: No module named 'app'`. Fixed with a `pytest.ini` carrying
`pythonpath = .`, so both invocations agree, and re-verified by running the suite
exactly the way CI does.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #5 — M4: paper ↔ virtual — locations, serials, lifecycle, scanning, printouts

*merged, m4-paper → main, opened 2026-09-17, merged 2026-09-17*

Roadmap M4, per docs/M4_PAPER.md (owner interview) plus the scanner workflows.

## What is in it

**Data model (Alembic 0004)** — `sleeve_layouts` (PrintFile 7×6 default, 7×5, two 120 variants), `locations` (any depth: building/room/shelf/row/box/binder/envelope/sleeve), `location_moves`; rolls gain `location_id`, `strips`, `status` + six timestamps, `loaded_camera_id`, `label_printed_at`. Serials `NEG-YYYY-NNNN` are allocated, unique (partial functional index), backfilled, and frozen once a label is printed. `building`/`folder` are migrated into location nodes and kept read-only for one release.

**API** — `/api/locations` tree + detail (pages, next free page, discrepancies), `POST /films/{id}/move` and `bulk_move` (a binder resolves to its next free page; an occupied sleeve is a 409 naming the roll in it), `/films/{id}/moves`, `/films/{id}/layout` (sleeve grid), `/films/{id}/status`, `/cameras/{id}/load` (refuses a second roll), `/work` lists, `/scan/resolve` (one grammar for QR URLs, Code128 tokens, typed serials, `CMD-*` commands), `/codes/qr.svg` + `/codes/code128.svg`, `/rolls/by-serial/{serial}`, `/print/queue` + `/print/mark`. Settings: `serial_prefix`, `public_base_url`, label sizes.

**UI** — Locations tree and detail pages (binder pages, add pages, take out, QR/Code128 per node); location picker + serial + strips + status in the roll forms; lifecycle stepper, location, move history and Move… on the roll page; work-list chips and a status filter on the home page; Load film on cameras; strip/position on every frame cell; `/s/{serial}` and `/l/{id}` for QR codes.

**Scanner** — a keyboard-wedge listener opens any scanned roll or location from any page; the Scan console runs sequences: Move (rolls…, then destination), Set status, Mark printed, Look up; the phone camera scans QR/Code128 (`BarcodeDetector`, jsQR fallback); printable `CMD-*` command cards switch modes without touching the screen.

**Printouts** (plain A4, browser Print / Save as PDF, one `print.css`) — sleeve cover sheet whose grid mirrors the strips, stickers 50×25 (20/A4), index cards A6 (4/A4), binder spine label 50×200, location label 90×40, binder index, storage tree, command cards. Print queue with "mark printed".

## Verification
- `pytest tests`: 242 passed on Postgres 16 (25 new in `tests/test_m4_paper.py`), Alembic up/down/up, `ruff` clean
- `tsc`, `eslint` (0 errors), `next build` clean
- Playwright `npm run e2e`: 105/105 — creates a binder with pages, moves a roll by scanning serial then `LOC-id`, `/s/{serial}`, wedge scan from another page, Load film, and checks the cover sheet is A4 wide and a sticker is 50×25 mm
- Screenshots 10–15 added to the README

## Notes
- Fixes a latent M3 bug on the way: the LAN footer QR was an SVG without `xmlns`, which `<img>` will not render.
- TLS for the LAN (so the phone camera scanner works off localhost) stays on the roadmap.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #6 — M5 — NegPy integration: metadata ingest, sidecars, gear sync, roll handoff

*merged, m5-negpy → main, opened 2026-09-17, merged 2026-09-18*

Roadmap **M5** ([docs/ROADMAP.md](docs/ROADMAP.md), formats in
[docs/NEGPY_INTEGRATION.md](docs/NEGPY_INTEGRATION.md)). NegArchive and
[NegPy](https://github.com/marcinz606/NegPy) exchange **files, never code**: NegPy is GPL-3 where
this is MIT, and it has no CLI, no URL scheme and no importable API. Nothing here imports, copies
or vendors a line of it; where a behaviour has to match, the algorithm is re-implemented from its
written specification and that specification is the docstring.

## What it does

**A scan exported from NegPy already knows what it is.** Every upload path — and every file link
mode touches — now reads the file's EXIF and the `negpy:` XMP namespace and fills in the frame
number, the capture date, the frame's notes and the roll's camera, lens and film.
`negpy:CaptureRoll` files a loose frame into the roll whose serial (or unambiguous title) it names.

**Ingest only ever fills a blank.** Anything you typed wins, so it is safe to leave on and a
re-ingest is a no-op. Gear is *matched* against the catalog, not invented, unless you ask for it:
EXIF spellings ("NIKON CORPORATION NIKON F5") would otherwise fill the Gear page with
near-duplicates of entries somebody curated.

**The filename is the metadata of last resort.** The recommended NegPy export pattern
`{{ roll }}_{{ frame|pad(3) }}_{{ film }}` is published in the UI and parsed back — strictly, and
before M2's last-number-wins rule. That ordering is not a detail: the preset ends in the film name
and most film names end in their ISO, so `NEG-2024-0002_013_Kodak Gold 200.jpg` would otherwise be
frame 200, and so would every other frame on the roll. Found while seeding a demo archive; it has
its own regression test.

**`.negpy` sidecars** are kept: uploaded beside their scan (single files or in a ZIP), found next
to a linked file, re-read when the sidecar's mtime moves (editing in NegPy does not touch the scan,
so nothing else would notice), carried into the export and into a handoff, deleted with the frame.
The viewer shows an "Edited in NegPy" badge and a one-line summary — the recipe is stored whole and
deliberately not interpreted.

**Gear sync** writes `cameras.json`, `lenses.json`, `film_stocks.json` in NegPy's camelCase schema.
Ids are `na-cam-3` and friends, and an entry whose id is not ours keeps its content *and its
position*; ours are updated in place, and one whose row was deleted here is dropped. Both file
shapes (bare array, `{"cameras": […]}`) survive a round trip, and the write is atomic because NegPy
reloads on mtime.

**"Open in NegPy"** prepares `<handoff dir>/<serial>/`: every scan hard-linked (or copied) under
its preset name, the sidecars, a README, and `presets/metadata/<serial>.json` with the serial, the
date and the `na-…` gear ids. Add the folder as a NegPy library root, apply the preset, and every
frame comes out carrying the serial printed on the sleeve the negatives are in. Nothing original is
moved, renamed or written to.

**The content hash** was already NegPy's; this makes it usable in both directions —
`GET /api/negpy/lookup?hash=…` answers with the roll, the serial and the frame number, so a row in
NegPy's `edits.db` can be traced to the physical negative.

## Safety

* **Ingest never overwrites.** One rule, and it is what lets this run automatically.
* **XMP is parsed defensively.** Pillow's `getxmp()` needs `defusedxml` and `xml.etree` is
  documented as vulnerable to entity expansion, so a packet declaring a DTD or an entity — or one
  over 4 MiB — is refused before the parser sees it. Files come off a scanner's share: data, not
  instructions.
* **Writes are fenced.** With nothing configured everything stays inside `DATA_DIR/negpy`, which
  needs no mount and is part of a backup. A path set in Settings must resolve inside that,
  `NEGPY_USER_DIR`, `NEGPY_EXPORT_DIR`, `NEGPY_DIRS_ALLOW` or `LIBRARY_ROOTS_ALLOW`, or it is a 403
  — the same rule as M3's library roots, because the API has no password by default.

## API

`GET /api/negpy/status`, `POST /api/negpy/gear/sync[?dry_run=true]`,
`POST /api/negpy/rolls/{id}/handoff` (`{"mode": "link"|"copy"}`), `POST /api/negpy/ingest` (the
catch-up for everything imported before M5), `GET /api/negpy/lookup?hash=…&path=…`.

## Schema

`0005_m5_negpy`: four nullable columns on `image_assets` (`capture_metadata`, `sidecar_path`,
`negpy_edited_at`, `negpy_recipe`). Guarded, re-runnable, and nothing is backfilled — reading every
file in an archive is a job for the endpoint, not for a migration that has to finish before the app
can start. `alembic upgrade head → downgrade base → upgrade head` is clean.

## Tests

* `tests/test_m5_negpy.py`, 77 new (**319 pass in total**, none of the existing ones changed
  meaning). Including a hash test that re-implements the documented sampling algorithm a second
  time and compares: if someone "optimises" `services/hashing.py`, every record here silently stops
  matching NegPy's `edits.db`, and this is the only thing that would notice.
* Playwright smoke test: 13 new checks — it splices an XMP packet into a JPEG by hand, uploads it
  with its sidecar, reads the viewer's panel, prepares a handoff, writes the gear library and looks
  a frame up by hash. **119 checks pass** against a production build.
* `ruff`, `eslint`, `tsc --noEmit`, `next build` and `docker compose config` all clean.

## Screenshots


## Left for later, on purpose

The upstream proposals to NegPy (a physical-storage field group, a headless export entry point)
are still just drafts in the integration doc, and nothing here depends on them. Reading `edits.db`
directly is not done — the hash lookup is the half that does not need NegPy's schema to stay
stable. Developer/dilution/push-pull still land in the roll's notes until M7 gives them columns.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

### Comment by @dahunni — 2026-09-18

### Follow-up: the three "left for later" items are done too

**1 · Reading NegPy's `edits.db`** ([`app/services/negpy/edits.py`](https://github.com/dahunni/NegArchive/blob/m5-negpy/app/services/negpy/edits.py))

NegPy keys its edits by the same sampled content hash this archive stores, so on one machine every
scan that has been worked on can be found **without a single sidecar** — which is the case that was
previously invisible for an archive whose owner never turned sidecars on.

* **Read-only, always**: `mode=ro&immutable=1`, so the driver will not write, create the file, take
  locks or touch a WAL. One test asserts an `INSERT` raises; another fingerprints the file (size,
  mtime, sha256) before and after a full match.
* **Never required**: no database, a locked one, or a schema it does not recognise all mean "no
  extra information". The table and columns are sniffed from `sqlite_master` / `PRAGMA table_info`,
  so a rename upstream degrades instead of breaking.
* **A sidecar wins**: it travels with the scan, while `edits.db` is one machine's private state.
  The stored recipe now records which it was (`source: "sidecar" | "edits.db"`), and the viewer
  shows it.

`POST /api/negpy/edits/match` does a batched pass; uploads, ZIPs, library scans and
`POST /api/negpy/ingest` open the index once per request. Verified against a stand-in database in
the real UI: 5 frames matched, file byte-identical afterwards, no journal left beside it.

**2 · Development fields on a roll** (`0006_m5_development`)

`developer`, `development_dilution`, `push_pull`, `development_time` — free text, because that is
how it is written on the envelope. M5 had been appending "Developed in Rodinal · 1+50" to the
roll's notes, which could not be searched, printed in a binder index, or corrected without editing
prose. Filled by ingest (blanks only), editable in their own group in the roll form, shown on the
roll page, appended to the roll CSV. Nothing is backfilled and no existing notes are rewritten.

**3 · Upstream proposals** ([docs/NEGPY_UPSTREAM.md](https://github.com/dahunni/NegArchive/blob/m5-negpy/docs/NEGPY_UPSTREAM.md))

Both drafted in full — the physical-storage field group (framed as capture provenance, because
NegPy's library deliberately has no index database) and the headless export entry point — each with
what NegArchive would do with it and what it would deliberately *not* do (it would never call a
converter from a web request). **Not filed**: opening an issue or a PR on somebody else's project
happens under the owner's name, so that is @dahunni's call. The file ends with how to do it.
Nothing in NegArchive depends on either.

### Verification

* **330 pytest tests pass** (11 new), `alembic upgrade head → downgrade base → upgrade head` clean
  through `0006`.
* **125 Playwright checks pass** against a production build (6 new).
* ruff, eslint, `tsc --noEmit`, `next build` clean.

Still open on purpose, and now written down as such in the roadmap: per-frame ratings from NegPy's
`file_marks` (M7 owns it), and a development *catalog* rather than four strings per roll — worth it
once there are enough rolls to make the repetition annoying, and the strings migrate into one
cleanly then.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #7 — M5 follow-ups: NegPy's edits.db, development fields, upstream proposal drafts

*merged, m5-followups → main, opened 2026-09-18, merged 2026-09-18*

The three items M5 ([#6](https://github.com/dahunni/NegArchive/pull/6)) deliberately left for
later. They were pushed to `m5-negpy` just after that PR was merged, so they are here on their own
branch instead.

## 1 · Reading NegPy's `edits.db`

[`app/services/negpy/edits.py`](https://github.com/dahunni/NegArchive/blob/m5-followups/app/services/negpy/edits.py)

NegPy keys every edit by the same sampled content hash this archive already stores, so on one
machine every scan that has been worked on can be found **without a single sidecar** — the case
that was previously invisible for an archive whose owner never turned sidecars on.

Three rules, none of them negotiable:

* **Read-only, always.** `sqlite3.connect("file:…?mode=ro&immutable=1", uri=True)`: the driver will
  not write, will not create the file, takes no locks and leaves any WAL or journal alone, so a
  NegPy that happens to be running is not disturbed. One test asserts an `INSERT` raises; another
  fingerprints the file (size, mtime, sha256) before and after a full match.
* **Never required.** No database, a locked one, or a schema it does not recognise all mean "no
  extra information", never an error. The table and its three columns are sniffed from
  `sqlite_master` and `PRAGMA table_info`, so a future NegPy that renames `settings_json` degrades
  instead of breaking.
* **A sidecar wins.** A `.negpy` file travels with the scan; `edits.db` is one machine's private
  state. The stored recipe now records which it was (`source: "sidecar" | "edits.db"`), and the
  viewer shows it.

A row becomes the same `Sidecar` object a `.negpy` file produces, so the viewer, the API and the
tests cannot tell — and must not care — where a recipe came from. `POST /api/negpy/edits/match`
does a batched pass (one query per 400 hashes) and 404s cleanly with `no_edits_db`;
`GET /api/negpy/status` reports the path, readability, table and row count; uploads, ZIPs, library
scans and `POST /api/negpy/ingest` open the index **once per request**.

Checked against a stand-in database in the running UI: 5 frames matched, the file byte-identical
afterwards, no journal left beside it.

## 2 · Development fields on a roll

`0006_m5_development` adds `developer`, `development_dilution`, `push_pull`, `development_time` —
free text, because a developer is "Rodinal" or "the lab down the road" and a time is "9:30" or
"9 min at 20 °C". M5 had been appending *"Developed in Rodinal · 1+50"* to the roll's **notes**,
which could not be searched, printed in a binder index, or corrected without editing somebody's
prose around it.

Filled by ingest from `negpy:Developer` / `DevelopmentDilution` / `PushPull` / `DevelopmentTime`
(blanks only, like everything else it touches), editable in their own group in the roll form, shown
on the roll page, and appended to the roll CSV. Nothing is backfilled and no existing notes are
rewritten.

## 3 · Upstream proposals — drafted, not filed

[docs/NEGPY_UPSTREAM.md](https://github.com/dahunni/NegArchive/blob/m5-followups/docs/NEGPY_UPSTREAM.md)
writes up both, each with the part usually missing from a proposal — what the other project would
have to accept, and what NegArchive would deliberately *not* do with it:

* a **"Physical storage" field group** in `MetadataConfig` (serial, container, sleeve, position →
  `negpy:` XMP), framed as capture provenance because NegPy's maintainer has documented the
  decision that the library has no index database. The mapping onto M4's location tree is decided
  in advance, and the fields would be a cross-check, never an instruction;
* a **headless export entry point**, which NegArchive would *not* call from the server — running a
  converter inside a web request is how an archive becomes a machine that is busy for twenty
  minutes and cannot answer — it would print the command in the handoff's `README.txt`.

**Neither is filed.** Opening an issue or a PR on somebody else's project happens under your name,
so that is your call; the file ends with how to do it (issues first, separately, read against
current `main`). Nothing in NegArchive depends on either.

## Verification

* **330 pytest tests pass** (11 new); `alembic upgrade head → downgrade base → upgrade head` clean
  through `0006`.
* **125 Playwright checks pass** against a production build (6 new). The one that asks for a clean
  404 does so from Node rather than from the page, because a 404 in the page is a console error and
  the suite fails on those — correctly.
* ruff, eslint, `tsc --noEmit`, `next build` clean.

## Still open, on purpose

Per-frame ratings from NegPy's `file_marks` (M7 owns it), and a development *catalog* — processes
as catalog entries, like cameras — rather than four strings per roll: worth it once there are
enough rolls to make the repetition annoying, and the strings migrate into one cleanly then. Both
are written down as such in the roadmap.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #8 — Print the negative in the preview — one file on disk, two ways of looking at it

*merged, negpy-preview → main, opened 2026-09-18, merged 2026-09-18*

You asked whether NegPy could be integrated into the web UI so the archive stores the raw scan and
still shows the edited version, since the edits are recipes. This is the answer, and it has two
halves — one that is done here, one that cannot be done here and why.

## What this does

**Prints the negative on screen, storing nothing extra.** The rendering happens on demand and lands
in `data/cache/`, the same disposable cache every thumbnail has always used. There is still exactly
one file per frame on disk, and it is the scan. A test asserts the scan is byte-identical after
rendering it both ways.

**Applies your edit's tone controls and crop.** If a frame has a `.negpy` sidecar or a row in
`edits.db`, the render uses its numbers: the grade, the print exposure, the toe and the shoulder,
the zone densities, the midtone snap, and the crop and rotation exactly.

**Says what it could not render.** The viewer names it:

> Preview: 6 of 11 settings rendered · not rendered: cast_removal_strength, lab.clahe_strength,
> local_masks, paper_profile…

**Prints conservatively.** `preview_render` defaults to `auto`: only a frame the archive *knows* is
a negative — its roll names a negative film stock, or NegPy has an edit for it. A scan whose film is
unknown is left alone, because it might be a scan of a print. Contact sheets are never inverted,
slides are not inverted, and a black-and-white negative collapses to a single density before the
curve, the way paper sees it. Settings can force either way, and the viewer has a toggle (◑) back
to the scan that is remembered per browser.

## What it deliberately does not do

It does not run NegPy's pipeline, and it must not pretend to. That pipeline is nine stages —
flat-field, sensor crosstalk unmix, HDR merge, paper profiles with dye-coupling matrices, cast
removal, CLAHE, retouching, dodge and burn, contrast masks, toning, ICC soft-proofing — with WebGPU
shaders and a linear raw decode this backend deliberately cannot do (M2 removed the two-gigabyte
dependency stack). Reimplementing it would drift out of date silently every time NegPy retunes a
constant, and would still not match.

So this is a **tone reproduction**: the steps and constants come from the pipeline NegPy documents
in [`docs/PIPELINE.md`](https://github.com/marcinz606/NegPy/blob/main/docs/PIPELINE.md), the same
bargain as the content hash — re-implemented from a written description, no NegPy code imported or
copied, and the module says so where somebody will read it.

Two constants are **ours, not NegPy's**, and are marked as such. Their Auto Density and Auto Grade
meter a linear raw decode against fixed bounds; this renderer's axis is normalized per frame, so a
picture occupying the lower third of the axis printed far too bright with their numbers. Measured
against a reference photograph put through a synthetic film gamma and orange mask: their constants
give an RMS error of **54** on a 0–255 scale, ours give **25**.

For the faithful render there are two routes that still cost no second copy: export from NegPy into
a folder registered as a library root (linked, not copied), or the new **proposal 3** in
`docs/NEGPY_UPSTREAM.md` — NegPy writes a small preview JPEG beside the sidecar when it saves an
edit. That is the smallest of the three asks (the buffer is already on screen) and the only one
whose benefit lands outside this repository too. Still not filed; that is your call.

## Screenshots

The same frame printed, and as the scanner handed it over. One file on disk.


## Verification

* **360 pytest tests pass** (30 new). The tone tests are numbers, not opinions: a reference
  photograph through a synthetic film gamma and orange mask has to come back within an RMS of 35 —
  while being nothing like the negative it was given — and flat, normal and contrasty negatives all
  have to print sensibly.
* **129 Playwright checks pass** against a production build (4 new).
* ruff, eslint, `tsc --noEmit`, `next build` clean. No new dependencies: numpy and Pillow were
  already there.
* Checked by hand in the running UI: the grid and viewer serve the print (measured off the canvas,
  not eyeballed), the toggle switches to the scan and back, and the choice persists.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #9 — Print fixes: no rows sliced across page breaks, and a usable print queue

*merged, print-fixes → main, opened 2026-09-18, merged 2026-09-18*

Both of the things you reported, diagnosed and fixed.

## "When you print a page there is something cut off at the top"

It was real and I reproduced it: printing the **print queue** page, every page after the first
started with the bottom half of a roll — the row was sliced across the page break.

Printing an ordinary page of the app had **no print styles at all**, so:

* list rows and cards were paginated straight through the middle;
* the navigation, the footer and every button printed with them;
* a dark-themed screen printed light grey text on white paper, because browsers do not print
  background colours.

`globals.css` gets a print block: `break-inside: avoid` on rows, cards and frame cells; the app's
chrome marked `data-print-hide`; headings that do not end a page with their content overleaf; and
the light palette forced for print. The `/print/*` printouts keep their own sheet geometry in
`print.css` and are untouched — those were already right, and a `@page` rule here would have broken
them.

Measured on the queue page: **11 pages of sliced rows before, 3 clean ones after.**

## The print queue

Three things made it hard to work through, and the third is the one that matters:

1. It sent **every roll in the archive** as one unpaged list with a thumbnail strip each — 145 of
   them on the machine I found this on.
2. There was no way to see how many you were looking at, or to select a batch.
3. It arrived with **every roll already selected**, so the primary button read *"Mark 145 printed"*.
   Marking a label printed **freezes that roll's serial**. A button one click away from freezing the
   whole archive is not a good default.

Now nothing is selected until you select it, "Select these 50" does the page, the button says what
it will do to how many, a readout says how many of how many are shown, and the list pages 50 at a
time with Load more — the pattern every other list has had since M3. `?reason=never_printed` or
`?reason=moved_since_print` narrows it.

The endpoint also stopped reading every row of `location_moves` into a dict to work out the latest
move per roll: that is a grouped subquery now, and the whole filter runs in Postgres.

## Verification

* **362 pytest tests** (2 new: paging, and the reason filter).
* **134 Playwright checks** (5 new): the empty selection, the button arming, the readout, and —
  under `emulateMedia({media: "print"})` — that the navigation is gone and a queue row reports
  `break-inside: avoid`.
* Checked against real PDFs generated through Chrome's own print path, before and after.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## #10 — Publish the images to GHCR, so a deploy is a pull

*merged, ghcr-publish → main, opened 2026-09-18, merged 2026-09-18*

Yes — GHCR, and it needs no secrets, which is the practical reason to prefer it over Docker Hub
(that would need a Docker Hub account plus an access token stored as repository secrets, which only
you can create).

## What this publishes

```
ghcr.io/dahunni/negarchive-web        the FastAPI backend
ghcr.io/dahunni/negarchive-frontend   the Next.js frontend
```

Both for **linux/amd64 and linux/arm64**, so the same compose file runs on an Apple Silicon Mac, an
Intel NAS or a Pi.

* a `v*` tag → `latest`, `1.2.3`, `1.2`
* a commit on main → `main` and its SHA, **only after CI has passed on that commit**
  (`workflow_run`), so a red build never becomes an image somebody pulls
* `workflow_dispatch` for a manual run

## Deploying from it

```bash
docker compose pull
docker compose up -d
```

That is also the update. `NEGARCHIVE_TAG` chooses `latest` (default), a version, or `main`;
`NEGARCHIVE_IMAGE_OWNER` points at a fork. `docker compose up --build -d` still builds locally and
replaces whatever a pull would have fetched, so development is unchanged.

This matters beyond convenience: building the two images locally needs a toolchain and several
gigabytes of free disk — which is exactly what ran out on the machine this was written on today,
mid-build. Pulling a 0.3 GB image does not.

## One manual step after merging

GitHub creates the first package **private**, even for a public repository. To let anyone (or
another machine of yours without a token) pull them:

*Packages → negarchive-web → Package settings → Change visibility → Public*, and the same for
`negarchive-frontend`.

## A gotcha written down rather than rediscovered

The frontend image bakes `http://web:8000` into its `/api` and `/static` rewrites at **build** time,
because Next resolves rewrites into the build manifest. That is the compose service name, so the
published image is right for this stack — but pointing it at a differently named backend needs a
rebuild with `API_BASE` set, not just an environment variable. (I hit this during M5 and it cost an
hour of confusion; it is now in the README.)

## Untested until it runs

Workflows cannot be exercised locally, and this machine's Docker is currently in a bad state, so the
first run on main is the real test. The action versions are the current majors as of today
(`build-push-action@v7`, `metadata-action@v6`, `login-action@v4`, `setup-buildx@v4`, `setup-qemu@v4`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
