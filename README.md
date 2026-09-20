# NegArchive

A self-hosted archive for film photography: film rolls, their scans and contact sheets, the
cameras, lenses and film stocks they were shot with, and where the physical negatives live.
FastAPI JSON backend + Next.js frontend.

**Status: alpha, single user, meant for a home network.** Authentication is *optional* and off by
default (see [A shared password](#a-shared-password)). A full review with confirmed bugs is in
[docs/REVIEW.md](docs/REVIEW.md); the task list is in [docs/ROADMAP.md](docs/ROADMAP.md).
Milestones M0 (the bugs that broke shipped workflows in Docker), M1 (the UI rework), M2 (archive
integrity: Postgres only, Alembic, original filenames, gear foreign keys, validation, file
lifecycle), M3 (offline-first: one Compose stack, import by reference, backup, PWA), M4 (the
physical archive: serials, locations, lifecycle, codes, printouts, scanner console), M5 (the
NegPy integration: metadata ingest, gear sync, roll handoff, sidecars) and M6 (the network share,
so NegPy on a laptop and NegArchive on a server work in the same folder) are done;
read the [Known issues](#known-issues) section before deploying.

## Where this is going

Three goals drive the roadmap (details and reasoning in [docs/ROADMAP.md](docs/ROADMAP.md)):

1. **NegArchive is the system of record for the physical archive.** Rolls, frames, serials,
   storage locations and the gear catalog live here. [NegPy](https://github.com/marcinz606/NegPy)
   stays the negative-conversion tool; the two exchange files (gear JSON, XMP metadata, `.negpy`
   sidecars, filenames), never code. See [docs/NEGPY_INTEGRATION.md](docs/NEGPY_INTEGRATION.md)
   for why, and for the field mappings. *(M5, done — see [Working with NegPy](#working-with-negpy-m5).)*
   Since M6 the two can work in the same folder on a network share, so an edit in NegPy shows up
   here on its own — see [Working live in NegPy](#working-live-in-negpy-m6).
2. **Offline-first, on Postgres.** No runtime network calls, one Compose stack that includes
   Postgres, one command to run, everything exportable as plain files, import-by-reference so
   scans are not duplicated, a watch folder for scanner output, and an installable PWA for the
   phone at the shelf. *(M3, done.)* Postgres is the only supported database since M2; see
   [Moving an old SQLite database](#moving-an-old-sqlite-database).
3. **Paper ↔ virtual.** Archive serials with printable QR labels for sleeves and binders, a storage
   hierarchy (location → container → sleeve → strip), printable contact sheets and binder index
   sheets, "scan the QR to open the roll", and darkroom prints as assets with their own location.

## Using it

A **roll** is the unit of work, so the roll list is the home page and everything else hangs off it.

- **Rolls** (`/`, also reachable at `/films`) — one row per roll with a strip of real thumbnails,
  the film, the camera, the dates you shot it and where the negatives are filed. The filter bar
  above the list searches titles, notes, serials and folders and narrows by camera, film and date
  range; there is no separate search page.
- **New roll** opens a three-step wizard (title and dates → gear and film → storage) and then the
  upload zone, so a roll goes from nothing to scanned in one dialog. It remembers the camera, lens
  and film you used last.
- **A roll page** is a workspace: the contact sheet on top, a drop zone for the scans, then the
  frames. Drag files or a whole ZIP onto the zone and each one gets its own progress bar. In the
  grid, the frame number and the note are edited in place — arrow keys walk the grid, `Enter`
  opens the viewer, `Space` selects, `Escape` clears the selection. With frames selected, the bar
  at the bottom deletes them, moves them to another roll or sets a capture date on all of them.
- **The frame viewer** (click a frame, or go to `/images/{id}`) has previous/next on the arrow
  keys, zoom, download and the metadata panel beside the image, editable in place.
- **Frames** (`/images`) is every scan in the archive including the ones not in a roll yet; select
  them and use "Move to roll" to file them.
- **Gear** (`/gear`) is the cameras, lenses and film stocks catalog, three tabs, edited in dialogs.
- **Settings** (`/settings`) is the archive itself: the folders it links scans from, the watch
  folder toggle and its last-scan readout, and export / import / CSV.
- The layout works down to 375px: the navigation collapses into a drawer and the roll list becomes
  one column. There is a light/dark toggle in the header, and the footer shows the address to type
  on a phone plus a QR code for it.
- **It installs.** Add it to a phone's home screen and the shell, the roll list and the rolls you
  have already opened keep working with the archive switched off — see
  [At the shelf, offline](#at-the-shelf-offline).

## Stack

- Backend: FastAPI, SQLAlchemy 2, **Postgres 16 (required — there is no SQLite fallback)**,
  Alembic for the schema, Pillow + OpenCV for previews of TIFF and other non-web formats,
  `segno` for the LAN QR code
- Frontend: Next.js 16 (app router), React 19, TypeScript, Tailwind 4, shadcn/ui (15 components,
  the rest were removed in M1), `next-themes` for dark mode, no web fonts and no analytics, and a
  hand-written service worker with no PWA library behind it
- Storage: **one directory**, `DATA_DIR` (default `./data`), holding `postgres/`, `uploads/`,
  `catalog/`, `cache/` and `backups/`. Files are still served at `/static/...`; only the directory
  behind those URLs left the source tree (M3). The path, the name the scanner gave the file,
  whether NegArchive owns it and its content hash are stored in the database
- Face detection was deleted in M2: no DeepFace, no TensorFlow, no scikit-learn. People come
  from Immich in M7. The backend image is about 0.28 GB instead of 2 GB.

## Project structure

```
app/                    FastAPI backend
  main.py               app, CORS, safe static mount, migrations at startup, seeding,
                        the LAN banner, the optional password and the watch-folder task
  paths.py              the one place that knows where a file lives (DATA_DIR)
  auth.py               the optional shared password
  db.py                 engine and session; DATABASE_URL is required and must be Postgres
  models.py             SQLAlchemy models (FilmRoll, ImageAsset, Camera, Lens, FilmStock,
                        LibraryRoot, Setting)
  errors.py             the {"error": {code, message, field}} body and the input parsers
  schemas.py            Pydantic request and response models for every endpoint
  seed.py               the starter catalog, added only when a table is empty
  routers/api.py        rolls, frames, uploads, previews, catalog, maintenance
  routers/library.py    library roots — import by reference and the watch folder
  routers/backup.py     export, import and the roll CSV
  routers/system.py     health, LAN info, the QR code, login, settings
  routers/locations.py  the storage tree, binder pages, moves (M4)
  routers/scan.py       the scanner console's grammar and command cards (M4)
  routers/negpy.py      status, gear sync, roll handoff, ingest, hash lookup (M5)
  routers/smb.py        the network share and the live-mode setup (M6)
  services/smb.py       the only place that runs `mount`: validation, credentials, status (M6)
  services/livemode.py  one button: folders, watched roots, NegPy's folders, gear (M6)
  services/hashing.py   the sampled SHA-256 that identifies a scan — and ties it to NegPy
  services/importer.py  scanning a library root into rolls and linked frames
  services/watcher.py   the background poller
  services/backup.py    the export/import format
  services/network.py   which address the phone should type
  services/serials.py   NEG-YYYY-NNNN: allocated, unique, frozen once printed (M4)
  services/locations.py the tree, page order and next-free-page (M4)
  services/strips.py    which strip and position a frame sits at (M4)
  services/lifecycle.py loaded → shot → at the lab → back → scanned → sleeved (M4)
  services/codes.py     QR and Code128 as SVG (M4)
  services/preview.py   printing a negative as a positive for the preview cache (M5)
  services/negpy/       everything about NegPy, and nothing of NegPy (M5):
                        xmp.py + metadata.py read a scan's EXIF and `negpy:` XMP,
                        naming.py the export filename preset, sidecar.py the `.negpy`
                        files, edits.py NegPy's edits.db (read-only, by content hash),
                        recipe.py maps an edit onto the renderer and reports what it
                        could not apply,
                        gear.py writes NegPy's gear/*.json, handoff.py prepares
                        a roll folder and preset, dirs.py where any of that may be written
alembic/                the schema: versions/<YYYYMMDD_HHMM>_<slug>.py, env.py reads DATABASE_URL
alembic.ini             `sqlalchemy.url` deliberately empty
scripts/                backup.sh, restore.sh, seed_demo.py, make_icons.py,
                        migrate_sqlite_to_pg.py (the one-way door off SQLite)
frontend/               Next.js app (app router)
  app/                  page.tsx (rolls), films/[id] (roll workspace), images, images/[id]
                        (frame viewer), gear, settings; a loading.tsx and error.tsx beside each
  components/           app-shell, roll-browser, roll-wizard, roll-edit-sheet, roll-workspace,
                        frame-grid, frame-viewer, upload-zone, gear-section, gear-dialog,
                        settings-workspace, lan-footer, login-gate, offline-banner,
                        empty/error states and skeletons; components/ui is shadcn
  components/negpy-handoff-button.tsx  "Open in NegPy": prepare the folder, hand over the paths
  lib/api.ts            typed fetch helpers, API base handling, the session token, ApiError
  lib/format.ts         date range, storage and frame-label formatting
  public/sw.js          the service worker; public/manifest.webmanifest and public/icons
  e2e/smoke.mjs         Playwright smoke test (`npm run e2e`)
  next.config.mjs       the /api and /static rewrites, and the M1 route redirects
tests/                  pytest suite, Postgres only (skipped without DATABASE_URL); test_m2_*
                        cover the migrations, filenames, gear ids, validation and files;
                        test_m3_* cover link mode, backup, pagination, LAN and the password;
                        test_m4_paper.py the physical archive; test_m5_negpy.py the NegPy
                        formats — XMP, sidecars, gear merge, handoff, hash compatibility
docs/                   REVIEW.md, ROADMAP.md, NEGPY_INTEGRATION.md, M4_PAPER.md,
                        NEGPY_UPSTREAM.md (three drafts for NegPy itself, not filed),
                        pull-request-archive.md (the write-ups from the pull requests
                        of the repository this one replaced)
static/catalog/         the bundled catalog art, copied into DATA_DIR/catalog on first start
data/                   everything the archive owns (git-ignored; DATA_DIR)
Makefile, .env.example, Dockerfile, docker-compose.yml, frontend/Dockerfile
.github/workflows/ci.yml
```

Routes that moved in M1 still work — `/films`, `/cameras`, `/lenses`, `/filmstocks`, `/search`,
`/films/new`, `/films/{id}/edit`, `/images/upload` and `/images/{id}/edit` all redirect (HTTP 307)
to their new home.

## Requirements

- Docker + Compose. That is the whole list for running it.
- For working on it: Python **3.11** (pinned in `.python-version`; `uv venv --python 3.11` is the
  easy way on macOS, which still ships 3.9) and Node 20+ (built and type-checked on Node 24).

## Install it

```bash
git clone git@github.com:dahunni/NegArchive.git
cd NegArchive
docker compose up          # or: make up
```

That is the whole installation. Open `http://localhost:8021`. The backend prints the address to
use from another machine, and the footer in the UI shows it with a QR code.

### Published images (no local build)

Both images are published to the GitHub Container Registry for **amd64 and arm64**, so the machine
that runs the archive — a NAS, a mini PC, an Apple Silicon Mac — does not need a toolchain or the
several gigabytes a build wants:

```bash
docker compose pull        # ghcr.io/dahunni/negarchive-web and -frontend
docker compose up -d
```

Updating is the same two commands. `NEGARCHIVE_TAG` picks what you get — `latest` (the newest
release, the default), a version like `v1.2.3`, or `main` for the newest commit that passed CI —
and `NEGARCHIVE_IMAGE_OWNER` points at a fork's images. `docker compose up --build -d` still builds
locally and replaces whatever a pull would have fetched, which is what you want while developing.

The images are built by [`.github/workflows/publish.yml`](.github/workflows/publish.yml): a `v*` tag
publishes `latest` and the version, and a commit on main publishes `main` and its SHA **after CI has
passed on it**, so a red build never becomes an image somebody pulls. No secrets are involved; the
workflow's own `GITHUB_TOKEN` can write its repository's packages. GitHub creates the first package
as private even for a public repository, so make it public once under
*Packages → negarchive-web → Package settings → Change visibility* (and the same for the frontend)
if you want anyone else to be able to pull it.

The frontend image bakes the backend address `http://web:8000` into its `/api` and `/static`
rewrites at build time, which is the compose network's service name. Running the published frontend
image against a backend that is *not* called `web` on the same network needs a rebuild with
`API_BASE` set, not just an environment variable.

To change anything — the port, the database password, where the data lives — copy the example
first. Every variable has a working default, so this is optional:

```bash
cp .env.example .env
```

### One directory

Everything the archive owns lives in **one bind-mounted directory**, `DATA_DIR`, `./data` by
default:

```
data/
  postgres/     the database cluster
  uploads/      scans and contact sheets NegArchive manages
  catalog/      camera, lens and film stock pictures
  cache/        rendered previews; delete it any time, it rebuilds
  backups/      scripts/backup.sh writes here
```

Stop the stack, copy that directory, and you have the archive. There are no named Docker volumes:
a volume you cannot see is a volume you forget to back up.

Other things worth knowing:

- The API is only reachable through the UI container, which proxies `/api/*` and `/static/*`. The
  backend publishes no host port.
- `db` has a `pg_isready` healthcheck, `web` has one that actually queries the database, and the
  frontend waits for `web` to be *healthy* — the first page is server-rendered, so a frontend that
  starts before the database has migrated would serve an error page.
- **The schema migrates itself at startup.** `app/main.py` runs `alembic upgrade head` before
  serving, so a fresh directory and a database from M0/M1 both come up on the current schema. A
  failed migration stops the app instead of leaving it to fail at runtime.
- The image is about 0.28 GB and contains no TensorFlow.

### Make targets

```
make up         build and start the whole stack
make down       stop it (the data directory is left alone)
make logs       follow the logs
make dev        Postgres in Docker, backend and frontend on the host
make test       pytest against a throwaway Postgres it starts and removes itself
make lint       ruff + eslint
make typecheck  tsc --noEmit
make build      next build
make e2e        the Playwright smoke test against a running stack
make backup     database + managed files into data/backups/
make restore    restore the newest backup
```

## Local development

Backend (against the Compose Postgres, which is the target database):

```bash
make dev                                  # starts Postgres, then tells you the two commands
# or by hand:
docker compose up -d db                   # Postgres 16 on localhost:5432
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive
export DATA_DIR=./data
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

`DATABASE_URL` is required and must be a Postgres URL. Without it the backend stops at startup
and tells you so: SQLite used to be the default and it hid two Postgres-only bugs behind a second
code path.

### Migrations

Alembic owns the schema; `create_all` is not used anywhere. The app runs `alembic upgrade head`
itself at startup, so you only need these by hand when writing a migration:

```bash
alembic upgrade head                      # what startup does
alembic downgrade -1                      # step back
alembic revision --autogenerate -m "what changed"
alembic check                             # models and migrations agree
```

`alembic.ini` leaves `sqlalchemy.url` empty on purpose — `alembic/env.py` reads `DATABASE_URL`
and fails loudly when it is unset, so there is one place that decides which database is migrated.
Revision files are named `alembic/versions/<YYYYMMDD_HHMM>_<slug>.py`; the chain is linear.

### Moving an old SQLite database

```bash
export DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive
python scripts/migrate_sqlite_to_pg.py negarchive.db --dry-run   # look first
python scripts/migrate_sqlite_to_pg.py negarchive.db
```

It migrates the target schema, then copies cameras, lenses, film stocks, rolls and image assets,
keeping their ids (paths and bookmarks keep working), resolving each roll's gear names to the new
foreign keys and dropping the `"None"` strings the old form used to store. `faces` and `persons`
are left behind — that feature was deleted. The scan files are not touched. Keep the old
`negarchive.db` until you have checked the archive in the UI.

Tests (Postgres only; they are skipped when `DATABASE_URL` is unset, and refuse a non-Postgres
URL). They drop the schema and migrate from the first revision, so they exercise the migration
chain as well:

`make test` starts and removes that database for you, or do it by hand:

```bash
docker run -d --rm --name negarchive-test-db -p 55441:5432 \
  -e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive -e POSTGRES_DB=negarchive postgres:16
DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:55441/negarchive \
  .venv/bin/pytest tests -q
```

`DATA_DIR` defaults to a temporary directory during a test run, so the suite never writes an
upload or a preview into your working copy.

Linting is `ruff check .` for Python (config in `ruff.toml`) and `npm run lint` for the frontend
(`frontend/eslint.config.mjs`). Both run in CI, along with `tsc`, `next build`, the Playwright
smoke test and an Alembic up/down/up round trip — see `.github/workflows/ci.yml`.

Frontend:

```bash
cd frontend
echo "NEXT_PUBLIC_API_BASE=http://127.0.0.1:8010" > .env.local
npm ci --legacy-peer-deps
npm run dev            # http://localhost:3000
```

`NEXT_PUBLIC_API_BASE` is inlined into the client bundle **at build time**, so a production build
(`npm run build && npm run start`) needs it set for that build too. Leave it empty and the browser
talks to the same origin, which is what the Docker image does: the Next rewrites then proxy `/api`
and `/static` to the backend. Use `127.0.0.1` rather than `localhost`, so Node does not try `::1`.

End-to-end smoke test (needs a running backend and frontend, and Chromium once):

```bash
npx playwright install chromium
BASE_URL=http://127.0.0.1:3000 npm run e2e
```

It walks every route at desktop width and at 375px, creates a roll through the wizard, uploads
files, edits a frame number and a note in place, drives the viewer and the keyboard shortcuts,
checks pagination, the LAN footer and its QR code, the settings page, the manifest and the service
worker, toggles dark mode, and fails on any console error.
`SCREENSHOT_DIR=../screenshots npm run e2e` writes screenshots into a git-ignored folder (see
[Screenshots](#screenshots) — they show the machine they were taken on, so they are not committed).
It expects a populated archive; `scripts/seed_demo.py` makes one.

Environment variables:

| Variable | Where | Meaning |
|---|---|---|
| `DATA_DIR` | backend | **The one directory the archive lives in.** `./data` by default, `/data` in the container. Holds `postgres/`, `uploads/`, `catalog/`, `cache/`, `backups/` |
| `DATABASE_URL` | backend | **Required.** Postgres URL, e.g. `postgresql+psycopg2://negarchive:negarchive@db:5432/negarchive` (Compose). Anything else, or unset, stops the backend at startup |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | compose | the database credentials; change the password before the archive is on a network anyone else can see |
| `MAX_UPLOAD_MB` | backend | Largest accepted upload, default `512`. Over it the API answers 413 `file_too_large` |
| `UI_PORT` | compose, backend | the port the browser uses (default `8021`). The backend needs it too, to print the right URL |
| `NEGARCHIVE_PUBLIC_HOST` | backend | the host to advertise in the footer and the QR code. In Docker the container only sees its bridge address (172.x), which is useless to a phone, so set this to the host's LAN IP or name |
| `NEGARCHIVE_PASSWORD` | backend | optional single shared password. Empty (the default) means no login at all |
| `LIBRARY_ROOTS_ALLOW` | backend | `:`-separated folders NegArchive may link files from. **Empty by default, which switches import by reference off entirely** |
| `LIBRARY_HOST_DIR` | compose | the host folder mounted read-only at `/library` for the above |
| `WATCH_INTERVAL_SECONDS` | backend | seconds between watch-folder sweeps. **Unset means off**; the Compose stack sets `30`. `0` or `off` also disable it |
| `BACKUP_KEEP` | scripts | how many backup archives `scripts/backup.sh` keeps (default `7`) |
| `NEXT_PUBLIC_API_BASE` | frontend, browser | absolute API origin for local dev; empty in Docker so the browser uses same-origin `/api` and `/static` via the Next rewrites |
| `API_BASE` | frontend, server side | origin used for server-side fetches inside Docker (`http://web:8000`) |

## API

Base: `/api`. All responses are JSON, and every endpoint has a Pydantic request and response
model.

### Errors

One body, everywhere:

```json
{ "error": { "code": "duplicate_name",
             "message": "A camera named “Nikon F5” already exists.",
             "field": "name" } }
```

`field` names the input that caused it, or is `null` when the failure belongs to no single
input; `lib/api.ts` attaches the message to that field in the forms.

| Status | When |
|---|---|
| 400 | bad input the API parses itself: `invalid_json`, `invalid_title`, `invalid_name`, `invalid_date`, `invalid_date_range`, `invalid_number`, `invalid_kind`, `invalid_choice`, `invalid_type`, `invalid_ids`, `nothing_to_update`, `not_enough_images`, `invalid_zip` |
| 404 | `not_found` (any record), `unknown_roll`, `unknown_camera`, `unknown_lens`, `unknown_film_stock`, `file_missing` |
| 409 | `duplicate_name`, `gear_in_use` (a camera, lens or film stock rolls still refer to) |
| 413 | `file_too_large` — over `MAX_UPLOAD_MB` |
| 415 | `unsupported_file_type`, `unreadable_image` |
| 422 | `invalid_request` — the body has the wrong shape (Pydantic), with the offending `field` |

### Pagination and search

`GET /films` and `GET /images` take `limit` and `offset`. Without `limit` they answer with a bare
JSON array, exactly as before; with it they answer

```json
{ "items": [ … ], "total": 412, "limit": 24, "offset": 24, "has_more": true }
```

`X-Total-Count` carries the total either way, and `limit` is capped at 500. The roll list and the
frames page render their first page on the server from the query string — so `/?q=harbour` is a
link you can keep — and "Load more" the rest.

### Films

`GET /films`, `GET /films/{id}` → `{film, images, contact_sheets}`, `POST /films`,
`PUT /films/{id}`, `DELETE /films/{id}?keep_files=false`.

`GET /films` filters with `q` (every word must appear somewhere in the roll — title, notes,
serial, folder, building, or the camera, lens and film name), `camera_id`, `film_stock_id`, the
deprecated `camera` / `film_type` names, and `from` / `to`. A roll matches the date range when its
shooting range *overlaps* it, which is what "shot in August" means for a roll that ran from July
to September.

Fields: `id, title, camera_id, lens_id, film_stock_id, camera, lens, film_type, format, notes,
building, folder, archive_serial, start_date, end_date, created_at, image_count, cover_image_id,
cover_image_ids`.

**Gear is referenced by id.** Write `camera_id`, `lens_id`, `film_stock_id`; the `camera`, `lens`
and `film_type` names are still accepted (a name that matches a catalog entry is resolved to its
id, one that does not is kept as free text) and are always returned, taken from the catalog entry
so a rename shows up everywhere. `format` is one of `35mm`, `120`, `4x5`, `8x10`, `other`.
`image_count` and the (at most four) `cover_image_ids` let the roll list show a frame count and a
thumbnail strip without a request per roll.

Deleting a roll deletes its frame records **and their files**; `?keep_files=true` leaves the
files on disk.

### Images

`GET /images?film_id=&type=scan|contact_sheet&q=&unassigned=&storage_mode=&limit=&offset=`
(`unassigned=true` is the "not in a roll yet" pile the frames page shows; `q` searches the note and
the original filename), `GET /images/{id}`, `POST /images`,
`PUT /images/{id}` (`film_roll_id: null` unassigns the image from its roll),
`DELETE /images/{id}?keep_files=false`,
`POST /images/upload` (multipart: `file`, `type`, `film_roll_id?`, `frame_number?`, `notes?`,
`capture_date?`),
`POST /images/bulk_update` (`{ids, film_roll_id?, capture_date?, frame_number?}` — only the keys
you send are written),
`POST /images/bulk_delete` (`{ids, keep_files?}`),
`GET /images/{id}/preview?width=1200&render=auto|raw|positive` (JPEG; cached on disk under
`data/cache/` keyed by image id + width + rendering + the source file's mtime, so a re-scan or an
edit in NegPy invalidates it — `X-Preview-Cache: hit|miss` and `X-Preview-Render: raw|positive`),
`GET /images/{id}/download` (the original, named after `original_filename`).

Fields: `id, film_roll_id, type, path, url, original_filename, storage_mode, frame_number, notes,
capture_date, created_at`, plus M5's `capture_metadata, sidecar_path, negpy_edited_at, negpy_recipe,
negpy_summary, negpy_render`.

`original_filename` is the name the scanner gave the file; the stored name is a UUID. When the
client sends no `frame_number`, it is parsed from that name — an explicit `frame<n>` wins,
otherwise the last group of one to four digits does (`Roll12_007.tif`, `NEG-2024-011_007.jpg`,
`_Frame007`, `007.jpg`, `img_0007` all mean frame 7; `Roll12.tif` means nothing, because a number
glued to a word is part of the word). Frames are always listed in `frame_number NULLS LAST, id`
order.

`storage_mode` is `managed` (NegArchive owns the file and deletes it with the record) or `linked`
(the file belongs to somebody else and is never deleted — M3's import-by-reference). A linked
frame also carries `source_path` (where the original really is) and `content_hash`; its `url` is
`/api/images/{id}/download`, because the file is outside `/static` on purpose. Every managed
upload is hashed too, which is how an import knows the archive already has a file.

Uploads must be `jpg jpeg png tif tiff webp dng` or a camera raw (`arw nef cr2 cr3 raf orf rw2
pef` and the rest of LibRaw's list — the files NegPy's scan mode saves), by extension *and* by
their leading bytes, and
smaller than `MAX_UPLOAD_MB`. A bulk upload is all-or-nothing. Nothing under `/static/uploads` is
ever served as `text/html`.

### Per film

`POST /films/{id}/contact_sheet?columns=6&thumb_size=300` (laid out in frame order),
`POST /films/{id}/images/bulk` (multipart `files[]`), `POST /films/{id}/images/bulk_zip`
(multipart `file`; files inside the ZIP that are not images are skipped).

### Catalog

`GET|POST /cameras`, `GET|PUT|DELETE /cameras/{id}?force=false`, `POST /cameras/{id}/image`; same
for `/lenses` and `/filmstocks`. `PUT` returns the updated object.

Filmstock fields: `id, name, manufacturer, format, iso,
kind (black_and_white|color|slide|motion_picture), expired (boolean), expiration_date, image_path,
url`.

Deleting an entry that rolls still use answers 409 `gear_in_use` with the count. `?force=true`
deletes it anyway: the rolls' ids are set to NULL and they keep the name as plain text.

### Maintenance

`POST /seed` puts the starter cameras and film stocks back (startup only seeds while a catalog
table is empty, so a deleted entry stays deleted).

`POST /maintenance/sweep_orphans?apply=false` → `{orphan_files, missing_files, deleted_files,
bytes_reclaimed}`: files under `static/uploads` that no record points at, and records whose file
is missing from disk. A dry run unless `apply=true`, which deletes the orphan **files** only —
records are reported, never deleted.

### Library roots (import by reference)

`GET /library/roots` → `{roots, allowed_bases, enabled}`,
`POST /library/roots` (`{path, label?, watch?}`; the path must sit under `LIBRARY_ROOTS_ALLOW`),
`PUT /library/roots/{id}` (`{label?, watch?}`),
`DELETE /library/roots/{id}?forget_frames=false` (never touches a file),
`POST /library/roots/{id}/scan`, `POST /library/scan`.

### Backup and export

`GET /export` (streamed ZIP), `GET /export.json`, `GET /export/rolls.csv`,
`POST /import?dry_run=false` (multipart `file`), `GET /backups`.

### NegPy (M5)

`GET /negpy/status` → where the gear files and roll folders go, whether metadata ingest is on,
when the gear library was last written, the recommended export filename pattern, and how many
frames have been read or edited in NegPy.
`POST /negpy/gear/sync?dry_run=false` → writes `cameras.json`, `lenses.json`, `film_stocks.json`;
entries whose id does not start with `na-` are kept untouched.
`POST /negpy/rolls/{id}/handoff` (`{"mode": "link" | "copy"}`) → a folder of the roll's scans named
with the export preset, plus `presets/metadata/<serial>.json`. Originals are never moved.
`POST /negpy/ingest` (`{film_id?, image_ids?, all?, limit?}`) → re-reads files already in the
archive and fills blanks only; with no body it works through frames nothing has ever read.
`POST /negpy/edits/match` (`{film_id?, image_ids?, all?, limit?}`) → matches frames against NegPy's
`edits.db` by content hash, read-only; 404 `no_edits_db` when there is none to read.
`GET /negpy/lookup?hash=…&path=…` → which frame (and roll, and serial) a NegPy content hash is.

### System

`GET /health` (checks the database too), `GET /system/info`, `GET /system/qr.svg?url=`,
`POST /system/login` (`{password}`), `POST /system/logout`,
`GET|PUT /system/settings` — the allowlisted keys: `watch_enabled`, `serial_prefix`,
`public_base_url`, `label_spine_mm`, `label_sticker_mm` (M4), `negpy_ingest`, `negpy_create_gear`,
`negpy_user_dir`, `negpy_handoff_dir`, `negpy_handoff_mode` (M5). A folder setting outside the
allowed bases is a 403 `path_not_allowed`.

`/health`, `/system/info` and `/system/login` stay open when a password is set; everything else,
`/static` included, needs `Authorization: Bearer <token>` or the session cookie.

M3 error codes: `library_roots_disabled`, `path_not_allowed`, `unknown_path`, `not_a_directory`,
`duplicate_root` (403/404/409), `invalid_export` (400), `unknown_setting` (400),
`invalid_password` and `unauthorized` (401).

### Examples

```bash
curl -X POST http://localhost:8010/api/films -H 'Content-Type: application/json' \
  -d '{"title":"Roll 12","camera_id":1,"film_stock_id":4,"format":"35mm","start_date":"2024-07-01"}'
```

```bash
curl -X POST http://localhost:8010/api/films/1/images/bulk -F 'files=@Roll12_007.tif'   # frame 7
curl -X DELETE 'http://localhost:8010/api/images/12?keep_files=true'
curl -X POST http://localhost:8010/api/maintenance/sweep_orphans
```

```bash
# M5: a NegPy export and its sidecar, in one upload; the file says which frame it is
curl -X POST http://localhost:8010/api/films/1/images/bulk \
  -F 'files=@NEG-2024-0002_013_Kodak Gold 200.jpg' \
  -F 'files=@NEG-2024-0002_013_Kodak Gold 200.jpg.negpy'
curl -X POST http://localhost:8010/api/negpy/gear/sync
curl -X POST http://localhost:8010/api/negpy/rolls/1/handoff -H 'Content-Type: application/json' \
  -d '{"mode":"link"}'
```

## Import by reference and the watch folder

Scans are big and NegPy already has them on disk, so NegArchive can point at them instead of
copying them. A *linked* frame stores the path and a content hash and leaves the file exactly
where it is — it is never written to, moved or deleted, not even when you delete the frame.

It is **off until you say which folders are allowed**, because the API has no password by default
and "POST me any path" would otherwise turn the archive into a file server for the whole disk:

```bash
# .env
LIBRARY_HOST_DIR=/srv/scans          # the folder on the host
LIBRARY_ROOTS_ALLOW=/library         # where it is mounted in the container
```

Then in Settings, add `/library` and press Scan. The layout it expects is the one scanner software
produces anyway:

```
/library/
  2024-0007 Harbour/      → a roll titled "Harbour", serial 2024-0007
    harbour_001.tif       → frame 1
    harbour_002.tif       → frame 2
  Kyoto rain/             → a roll titled "Kyoto rain", no serial
```

Rescans are idempotent: scanning twice changes nothing, a file edited in place updates its hash,
and a file that *moved* is re-homed onto its existing record rather than imported again — so
reorganising your folders does not lose frame numbers or notes.

Tick **Watch** on a folder and a background poller sweeps it every `WATCH_INTERVAL_SECONDS`
(30 in the Compose stack; unset means the poller never starts): a new subfolder becomes a roll draft, a new file becomes a frame. It polls rather
than using filesystem events because the interesting case is a share on a NAS, where events either
do not exist or never reach the container. The toggle and the last-scan readout are in Settings.

## Backup and restore

Two different things, and they are not interchangeable.

**The operational backup** — what you run on a schedule:

```bash
make backup        # or: ./scripts/backup.sh
```

writes `data/backups/negarchive-<timestamp>.tar.gz` holding `database.sql` (a `pg_dump --clean
--if-exists`), `uploads/`, `catalog/` and a `MANIFEST.txt` that says what it is and how to put it
back, then prunes to the newest `BACKUP_KEEP` (default 7). It does **not** include `data/cache`
(rendered on demand), `data/postgres` (copying a live cluster is how you get a corrupt backup), or
files you imported by reference — those live in a folder you back up yourself.

To restore, step by step:

1. Have the stack running: `docker compose up -d`. The database is restored *through* it.
2. Run `./scripts/restore.sh` for the newest backup, or
   `./scripts/restore.sh negarchive-20260917-101500.tar.gz` for a particular one. Any path works
   too, so a file from a USB disk is fine.
3. Read the manifest it prints and answer `y`. (`FORCE=1` skips the question, for a scripted
   restore onto a fresh machine.) **This replaces the current archive.**
4. It stops `web`, loads `database.sql`, copies `uploads/` and `catalog/` back, clears the preview
   cache — its keys reference the old file timestamps — and starts `web` again.
5. Check it: `curl -s http://localhost:8021/api/films | head -c 400`, and compare the frame count
   in the UI against the manifest.

Restoring onto a *different* machine is the same, with one extra step first: create `.env` with
the same `POSTGRES_*` values, then `docker compose up -d db` before running the script.

**The format-independent export** — what you keep so the archive outlives this software:

```bash
curl -fL -o negarchive-export.zip http://localhost:8021/api/export
curl -fL -o rolls.csv             http://localhost:8021/api/export/rolls.csv
```

or the buttons in Settings. The ZIP holds `export.json` — every table as ordinary JSON, ISO dates,
no SQL dialect and no pickles — plus the managed files under `files/`, and a `README.txt`. Somebody
with a text editor can read it in 2031; any other program can import it. It streams, so a 300 GB
archive is not staged in memory first.

Importing one back:

```bash
curl -F file=@negarchive-export.zip 'http://localhost:8021/api/import?dry_run=true'   # look first
curl -F file=@negarchive-export.zip 'http://localhost:8021/api/import'
```

Import never overwrites. Gear is matched by name, rolls by archive serial (or title plus creation
time), frames by content hash; anything already here is skipped and counted, ids are remapped, and
library roots are ignored because they are absolute paths on somebody else's machine.

## At the shelf, offline

The UI is an installable PWA. Open it on a phone or tablet, "Add to Home Screen", and it behaves
like an app: its own icon, no browser chrome, and the system light/dark theme.

The point of it is narrow and worth stating: **you are standing at the shelf holding a binder and
you want to know what is on this roll.** So the service worker caches the app shell, the roll list
and the rolls you have actually opened, and a banner appears when the archive cannot be reached.
Uploading, editing and generating contact sheets need the server and say so.

Nothing that changes data is cached or replayed. There is no background sync queue on purpose: an
edit that silently lands three hours later is a good way to lose the link between paper and record.

The service worker is `frontend/public/sw.js` — about 150 lines, hand written, no dependency, no
build step. Read it; it is the kind of thing you want to be able to read.

**One catch, and it is the browsers', not ours: service workers need a secure context.**
`http://localhost` counts as secure, but `http://192.168.1.37:8021` does not, so on a phone over
plain HTTP on the LAN the worker will not register, the app will not install, and you get an
ordinary (online-only) web page. The UI degrades quietly rather than lying about it — the offline
banner still appears when the archive is unreachable, there is just nothing cached to fall back
on. To actually get the installable, offline version on a phone you need HTTPS in front of it:

- a reverse proxy with a certificate (Caddy will get one for a real domain by itself), or
- a certificate from your own CA — [mkcert](https://github.com/FiloSottile/mkcert) makes this
  about three commands — trusted on the devices you use, or
- an overlay network that terminates TLS for you, such as Tailscale.

Putting TLS in the Compose stack is not something NegArchive does for you today; it is a
[roadmap](docs/ROADMAP.md) item and an honest gap.

## On the network

The backend works out which addresses it is reachable on and prints them at startup:

```
INFO:     NegArchive data directory: /data
INFO:     NegArchive UI on this network: http://192.168.1.37:8021
INFO:     QR code for the phone: http://192.168.1.37:8021/api/system/qr.svg
```

The same address is in the UI footer with a QR code next to it — point a phone camera at it and
the archive opens. The QR is rendered server-side as SVG (`segno`), so it needs no JavaScript
library and works with no internet at all.

In Docker the container only sees its bridge address (172.x), which is useless to a phone. Set
`NEGARCHIVE_PUBLIC_HOST` to the host's LAN IP or hostname and everything above uses it.

`GET /api/system/info` is the machine-readable version: LAN addresses, the UI URL, the data
directory, the roll and frame counts, the watch state and whether a password is set. It stays open
even when one is, because a phone needs it *before* it can sign in.

## A shared password

There are no accounts. There is optionally **one** password for the whole archive:

```bash
# .env
NEGARCHIVE_PASSWORD=something-long
```

With it set, everything needs a token except `/api/health`, `/api/system/info` and the login
endpoint — `/static` included, because a photo archive whose pictures are readable without the
password is not protected at all. The UI shows a sign-in sheet, stores the token in a cookie, and
server-rendered pages forward it. The token is derived from the password, so updating the
container does not sign anyone out, and changing the password revokes every session.

What it is not: rate limiting, lockouts, per-user sessions, or anything you should expose to the
internet. It is a door latch for a network you mostly trust. Empty by default.

## The paper side (M4)

Every roll has a serial (`NEG-2024-0011`), a place in a storage tree (building → shelf → row →
binder → sleeve page, any depth) and a lifecycle (in camera → shot → at the lab → back → scanned →
sleeved). The tree lives under **Locations**; a binder gets numbered sleeve pages and files a roll
on its next free page.

**Codes.** Each roll and each location has a QR code (opens `/s/{serial}` or `/l/{id}` on a phone)
and a Code128 barcode (types the serial or `LOC-<id>` on a USB/Bluetooth scanner). Set
`public_base_url` under Settings so printed QR codes point at a stable address.

**Scanning.** A barcode scanner works from any page: scan a roll and it opens. The **Scan** page
is the console for sequences: choose *Move*, scan one or more rolls, scan the destination, done.
*Set status* and *Mark printed* work the same way. Print the command cards (`/print/commands`) and
the whole workflow is scans only. The phone camera scans QR codes too (needs HTTPS or localhost).

**Printouts** are plain A4 pages you print or save as PDF from the browser: the sleeve cover sheet
(its grid mirrors the strips on the page behind it), stickers (50 × 25 mm, 20 per sheet), index
cards (A6), binder spine labels, location labels, binder indexes and the whole tree.

**The print queue** lists rolls that never had a label, or moved since the last one was printed. It
is paged (50 at a time) because an archive that has never printed a label has its whole catalogue in
there, and it starts with **nothing selected**: marking a label printed freezes that roll's serial,
so a button offering to do it to every roll at once is not a good default. Select the ones you
printed — "Select these 50" does the page — then mark them. `?reason=never_printed` or
`moved_since_print` narrows it.

**Printing an ordinary page** of the app (the queue, a roll, a location) leaves the navigation, the
footer and the buttons off the paper, keeps a row or a card whole instead of slicing it across a
page break, and prints in the light palette even when the screen is dark.

## Working with NegPy (M5)

[NegPy](https://github.com/marcinz606/NegPy) converts negatives; NegArchive keeps track of them.
The two never call each other — NegPy has no CLI, no URL scheme and no importable API, and it is
GPL-3 where this is MIT — so everything below is **files**, in both directions. None of it needs
NegPy to be running, or even installed on the machine the archive runs on.

**A scan you export from NegPy already knows what it is.** On every upload (and on every file a
library root links), NegArchive reads the file's EXIF and the `negpy:` XMP namespace and fills in
what is still empty: the frame number, the capture date, the frame's notes, and the roll's camera,
lens and film if the catalog has them. `negpy:CaptureRoll` files a frame that arrived without a
roll into the roll whose serial — or, unambiguously, title — it names. **Ingest only ever fills a
blank.** Anything you typed wins, so it is safe to leave on, and it is on by default. Turn it off,
or let it add gear the catalog does not have yet, under **Settings → NegPy**.

**The filename is the metadata of last resort.** Set NegPy's export pattern to

```
{{ roll }}_{{ frame|pad(3) }}_{{ film }}
```

and a file that goes through a converter which strips EXIF still says which roll and frame it is.
NegArchive parses that shape strictly: `NEG-2024-0002_013_Kodak Gold 200.jpg` is frame 13, not
frame 200.

**Your gear, in NegPy's gear library.** *Settings → NegPy → Write gear for NegPy* writes
`cameras.json`, `lenses.json` and `film_stocks.json` in NegPy's own camelCase schema. Every entry
NegArchive owns has an id like `na-cam-3`, and **nothing else in those files is touched**: NegPy's
bundled cameras and anything you added by hand are read, kept and written back in place.

**"Open in NegPy"** on a roll prepares a folder named after the serial holding every scan (hard
links by default, so a 40 GB roll costs nothing), any `.negpy` sidecars, a `README.txt` with the
three steps, and a metadata preset at `presets/metadata/<serial>.json` carrying the roll's serial,
date and gear as the `na-…` ids above. Add the folder as a NegPy library root or Hot Folder, apply
the preset, and every frame comes out carrying the serial printed on the sleeve the negatives are
in. Nothing original is moved, renamed or changed.

**Sidecars.** A `.negpy` file next to a scan is kept: uploaded beside its image (single files or in
a ZIP), found next to a linked file, carried into an export and into a handoff, and deleted with
the frame. The viewer then shows an **Edited in NegPy** badge and a one-line summary of the recipe
— NegArchive stores the whole recipe but deliberately does not interpret it.

**No sidecars? Then `edits.db`.** NegPy keys its own edit database by the same content hash this
archive stores, so when both live on the same machine every scan that has been worked on can be
found without a single sidecar. NegArchive opens that database **read-only and immutable** — the
driver will not write, lock or create anything, a test asserts an `INSERT` fails, and another
fingerprints the file before and after a full match — and it is never required: no database, or one
whose tables are not the ones it knows, simply means "no extra information". Where a frame has both,
the sidecar wins, because it travels with the scan. *Settings → NegPy → Match NegPy's edits*, or
`POST /api/negpy/edits/match`.

**How it was developed.** A roll has `developer`, `development_dilution`, `push_pull` and
`development_time` — free text, because that is how it is written on the envelope — filled in from
`negpy:Developer` and friends when a scan says so, editable in the roll form, shown on the roll page
and in the roll CSV.

### Seeing the positive without storing a second file

A shelf of colour negatives is close to unbrowsable: every thumbnail is a dark orange rectangle.
NegArchive prints them on screen instead — and **stores nothing extra**. The rendering happens on
demand and lands in `data/cache/`, the same disposable cache every thumbnail already uses; the
archive still holds exactly one file per frame, and it is the scan.

What the render does, in the order a darkroom would: apply the recipe's crop and rotation, take the
log of the scan, normalize each channel between its own bounds (which is what defeats the orange
mask), meter the frame for an exposure anchor, put it through a paper-like transfer curve — grade,
midtone gamma, the zone densities, an asymmetric softplus toe and shoulder — and print it with
`I = 10⁻ᴰ` and black point compensation. The steps and their constants follow the pipeline NegPy
documents in [`docs/PIPELINE.md`](https://github.com/marcinz606/NegPy/blob/main/docs/PIPELINE.md);
where they are metered per frame, the calibration is NegArchive's own, because its axis is
per-frame and NegPy's is not.

If a frame has a NegPy edit, the render uses **its** numbers: the grade, the print exposure, the
toe and shoulder, the zone densities, the midtone snap, and the crop exactly.

**It is an approximation and says so.** NegPy's pipeline has nine stages; this has one. Dodging and
burning, contrast masks, paper profiles with their dye-coupling matrices, cast removal, crosstalk
unmix, flat-field, HDR merge, CLAHE, retouching, toning and ICC soft-proofing are not rendered —
and the viewer names them: *"Preview: 6 of 11 settings rendered · not rendered: cast_removal_strength,
lab.clahe_strength, local_masks, paper_profile…"*. For the real thing, export from NegPy into a
folder you have registered as a library root: those files are linked, not copied, so that costs no
second copy either.

**When it prints.** By default (`preview_render = auto`) a frame is printed when the archive *knows*
it is a negative — its roll names a negative film stock, or NegPy has an edit for it. A scan whose
film is unknown is left alone, because it might be a scan of a print, and turning somebody's
photograph inside out uninvited is worse than an orange thumbnail. Settings can force either way,
the frame viewer has a toggle (◑) that remembers your choice in that browser, and a contact sheet is
never inverted.

```bash
curl -s -o frame.jpg -D - 'http://localhost:8010/api/images/42/preview?width=1600&render=positive' | grep -i x-preview-render
```

**Where the files go.** With nothing configured, inside the archive's own data directory
(`data/negpy/user/gear`, `data/negpy/handoff`), so it works out of the box and is part of a backup.
Set `NEGPY_USER_DIR` (the same variable NegPy reads) and/or `NEGPY_EXPORT_DIR` to write straight
into NegPy's user directory instead. A path in Settings must sit inside one of those, inside
`NEGPY_DIRS_ALLOW`, inside `LIBRARY_ROOTS_ALLOW` or inside `data/negpy` — anything else is refused
with a 403, for the same reason library roots are: the API has no password by default.

**The content hash** NegArchive stores on every frame is NegPy's: SHA-256 of the file size plus a
1 MiB head, a 1 MiB tail and 16 × 256 KiB interior chunks, re-implemented from the written
specification in `app/services/hashing.py` (never imported — that would make this a derivative of
GPL code). So a row in NegPy's `edits.db` and a frame here can be matched:
`GET /api/negpy/lookup?hash=…` answers with the roll, the serial and the frame number.

**Endpoints:** `GET /api/negpy/status`, `POST /api/negpy/gear/sync[?dry_run=true]`,
`POST /api/negpy/rolls/{id}/handoff` (`{"mode": "link" | "copy"}`), `POST /api/negpy/ingest`
(re-read files already in the archive — the catch-up for everything imported before M5),
`POST /api/negpy/edits/match`, `GET /api/negpy/lookup?hash=…&path=…`.

**Contributing to NegPy** is a separate, optional question: two proposals (a physical-storage field
group, a headless export entry point) are drafted in
[docs/NEGPY_UPSTREAM.md](docs/NEGPY_UPSTREAM.md) and have deliberately **not** been filed — nothing
here depends on either of them.

## Working live in NegPy (M6)

M5 assumed NegArchive and NegPy were on one machine. They are not: the archive is a container on a
server, NegPy is a desktop app on a laptop. M6 closes that gap with a network share both can see.
The reasoning, the layout and the security notes are in [docs/NEGPY_LIVE.md](docs/NEGPY_LIVE.md);
this is what you do.

**Settings → Network share.** Type the NAS address, the share, and a user and password if it needs
one. *Test connection* is a TCP connect to port 445, so "the NAS is asleep" and "the password is
wrong" are told apart before anything is mounted. Then *Save and mount*.

**Then one button, “Set up live mode”.** It makes four folders on the share, registers two of them
as watched library roots, points NegPy's gear and presets at the share, and syncs the gear catalog:

```
rolls/          scans live here forever; NegArchive links them, NegPy edits them in place
exports/        what NegPy exports; watched too, so finished positives come back on their own
negpy-user/     gear/ and presets/metadata/ — NegArchive writes, NegPy reads
handoff/        a prepared roll, for the times you still want one
```

It creates nothing that exists and turns nothing off, so it is safe to run again.

**The Mac side is five steps — six if you camera-scan — printed in the page with your own paths and a copy button on each:**
mount the share in Finder, add `rolls/` as a NegPy library root, **turn on `.negpy` sidecars in
NegPy** (the one setting the whole thing depends on), symlink NegPy's `gear` and `presets/metadata`
onto the share, and set NegPy's export folder and filename pattern.

After that you just work. Edit a frame in NegPy, and within 30 seconds the archive shows it as
edited with a one-line summary of the recipe — because the sidecar lands next to the file the
archive linked, and the watch sweep compares its mtime.

**Camera scanning.** If you scan with a camera through NegPy's *Live View & Scan*, every roll page
has a "Scan with NegPy" card with the two things to paste: the share's `rolls/` folder as the
output, and the roll's serial as NegPy's roll name. NegPy then writes
`rolls/NEG-2026-0007/NEG-2026-0007_Frame001.ARW` and so on, and the next sweep files the raws onto
that very roll — linked, never copied — and marks it scanned. Raws (ARW, NEF, CR2/CR3, RAF, ORF,
RW2, PEF, DNG, …) are previewed through LibRaw and printed as positives like any other scan.

**What it costs.** Mounting a filesystem is privileged, so `docker-compose.yml` grants the `web`
service `CAP_SYS_ADMIN` and `CAP_DAC_READ_SEARCH` (opt-in, with a comment saying why). Both are
needed: the first is the `mount()` syscall, the second is one `mount.cifs` puts in its own permitted
set before it does anything else — with `SYS_ADMIN` alone it exits with `Unable to apply new
capability set.` and never reaches the NAS. **Set `NEGARCHIVE_PASSWORD` if you use
this** — the API has no login by default and these endpoints can mount filesystems. The SMB
password is kept in `$DATA_DIR/.smb/credentials` (mode 0600), never in the database and never in a
backup export.

**Endpoints:** `GET /api/smb/status`, `PUT /api/smb/config`, `POST /api/smb/test`,
`POST /api/smb/mount`, `POST /api/smb/unmount`, `DELETE /api/smb/credentials`,
`GET /api/smb/live`, `POST /api/smb/live`.

**Known limits:** one share, one editing machine, and NegPy converting big TIFFs over SMB is slower
than off local disk. Mounting itself is not covered by CI — it needs a NAS and a capability a
runner does not have — but the validation, the argv, the credentials file, the allow-lists and the
whole of live mode's wiring are (`tests/test_m6_smb.py`).

## Known issues

The full list with evidence and file references is [docs/REVIEW.md](docs/REVIEW.md). M2 closed
the data-integrity ones (R#7, R#9, R#10, R#11, R#14, R#15, R#16, R#17, R#18, R#21, R#23, R#24) and
M3 the rest of the offline ones (R#19 in part, R#20, R#26, R#29, R#30, R#31, R#33). What is left:

- **Security:** CORS is open, and the shared password (R#26) is one password with no rate
  limiting — a door latch for a network you mostly trust, not something to expose to the
  internet. It is off by default.
- **No TLS in the stack**, which is why the PWA does not install over the LAN: browsers only
  register a service worker in a secure context. See
  [At the shelf, offline](#at-the-shelf-offline) for the three ways round it.
- **Preview IO:** `GET /api/images/{id}/preview` still reads and encodes on the event loop
  (**R#19**); a big TIFF blocks other requests while it renders.
- **Deletion has no undo.** Deleting a roll deletes its scan files by default; the dialog offers
  "keep the files on disk", and `make backup` is the actual safety net.
- **Linked files are not backed up**, on purpose: they live in a folder you manage, and
  `scripts/backup.sh` says so in the manifest it writes.

## Next steps (short version)

Full checklist: [docs/ROADMAP.md](docs/ROADMAP.md).

1. **M0** *(done)* fix the Docker-breaking bugs, remove the legacy routers, add `.dockerignore`.
2. **M1** *(done)* UI rework around the roll as the unit of work: roll list with thumbnails,
   roll page as a workspace with inline editing, drag-and-drop upload, frame viewer, dialogs
   instead of form pages, mobile layout, dark mode.
3. **M2** *(done)* archive integrity: Postgres only with a migration script off SQLite, Alembic,
   original filenames and frame numbers parsed from them, foreign keys for gear, validation with
   real status codes, file lifecycle with an orphan sweep, upload allowlist, face detection
   deleted.
4. **M3** *(done)* offline-first: one Compose stack and one `data/` directory, pagination and
   server-side search, import by reference, watch folder, backup/restore and a format-independent
   export, an installable PWA, the LAN URL and QR code, an optional shared password, tests and CI.
5. **M4** *(done)* paper ↔ virtual: storage hierarchy, serial scheme, QR labels, printable
   contact and index sheets, strip/position, lifecycle, scanner console, print queue.
6. **M5** *(done)* NegPy: ingest its XMP and EXIF on upload and in link mode, the export filename
   preset, `.negpy` sidecars, gear sync into NegPy's `gear/*.json`, roll handoff with a metadata
   preset, a content hash compatible with NegPy's. See [Working with NegPy](#working-with-negpy-m5).
7. **M6** *(done)* the network share: the container mounts your NAS from Settings, and one button
   sets up the folders NegPy and the archive share — so you work in NegPy and the archive notices
   your edits on its own. See [Working live in NegPy](#working-live-in-negpy-m6).
8. **M7** Immich connector, optional: shared files via an external library, XMP sidecars, one
   album per roll with tags, "Open in Immich", people from Immich. NegArchive stays standalone.

## License

MIT. NegPy is GPL-3 and is deliberately not imported or bundled.

## Screenshots

Not in the repository, on purpose.

A screenshot of this application shows whatever the machine it ran on was called: the settings page
prints `DATA_DIRECTORY`, the NegPy dialog prints the folder it prepared, and the footer prints the
LAN address. On a developer's laptop those paths contain the account name, and a public repository
is a bad place for it. Screenshots that had been committed were removed from the working tree **and
from every commit in the history**; `screenshots/` is git-ignored so it cannot come back by
accident.

To make your own, run the archive with a neutral data directory and a neutral advertised host:

```bash
DATA_DIR=/tmp/negarchive-demo NEGARCHIVE_PUBLIC_HOST=archive.local make dev
cd frontend && SCREENSHOT_DIR=../screenshots npm run e2e      # the smoke test takes them
```

and **look at every image before adding one** — `git add -f screenshots/…` is deliberate for exactly
this reason. Anything showing a home directory, a hostname, a LAN address or a serial you would
rather not publish does not belong in a public repository.
