# NegArchive

A self-hosted archive for film photography: film rolls, their scans and contact sheets, the
cameras, lenses and film stocks they were shot with, and where the physical negatives live.
FastAPI JSON backend + Next.js frontend.

**Status: alpha, single user, run it on a trusted LAN only.** There is no authentication and CORS
is open. A full review with confirmed bugs is in [docs/REVIEW.md](docs/REVIEW.md); the task list is
in [docs/ROADMAP.md](docs/ROADMAP.md). Milestones M0 (the bugs that broke shipped workflows in
Docker), M1 (the UI rework) and M2 (archive integrity: Postgres only, Alembic, original
filenames, gear foreign keys, validation, file lifecycle) are done; read the
[Known issues](#known-issues) section before deploying.

## Where this is going

Three goals drive the roadmap (details and reasoning in [docs/ROADMAP.md](docs/ROADMAP.md)):

1. **NegArchive is the system of record for the physical archive.** Rolls, frames, serials,
   storage locations and the gear catalog live here. [NegPy](https://github.com/marcinz606/NegPy)
   stays the negative-conversion tool; the two exchange files (gear JSON, XMP metadata, `.negpy`
   sidecars, filenames), never code. See [docs/NEGPY_INTEGRATION.md](docs/NEGPY_INTEGRATION.md)
   for why, and for the field mappings.
2. **Offline-first, on Postgres.** No runtime network calls, one Compose stack that includes
   Postgres, one command to run, everything exportable as plain files, import-by-reference so
   scans are not duplicated, a watch folder for scanner output, and an installable PWA for the
   phone at the shelf. Postgres is the only supported database since M2; see
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
- The layout works down to 375px: the navigation collapses into a drawer and the roll list becomes
  one column. There is a light/dark toggle in the header.

## Stack

- Backend: FastAPI, SQLAlchemy 2, **Postgres 16 (required — there is no SQLite fallback)**,
  Alembic for the schema, Pillow + OpenCV for previews of TIFF and other non-web formats
- Frontend: Next.js 16 (app router), React 19, TypeScript, Tailwind 4, shadcn/ui (15 components,
  the rest were removed in M1), `next-themes` for dark mode, no web fonts and no analytics
- Storage: files under `static/uploads/{scans,contact_sheets}` and `static/catalog/*`; the path,
  the name the scanner gave the file and whether NegArchive owns it are stored in the database
- Face detection was deleted in M2: no DeepFace, no TensorFlow, no scikit-learn. People come
  from Immich in M6. The backend image is about 0.28 GB instead of 2 GB.

## Project structure

```
app/                    FastAPI backend
  main.py               app, CORS, safe static mount, `alembic upgrade head` at startup, seeding
  db.py                 engine and session; DATABASE_URL is required and must be Postgres
  models.py             SQLAlchemy models (FilmRoll, ImageAsset, Camera, Lens, FilmStock)
  errors.py             the {"error": {code, message, field}} body and the input parsers
  schemas.py            Pydantic request and response models for every endpoint
  seed.py               the starter catalog, added only when a table is empty
  routers/api.py        the JSON API, everything under /api — the only router
alembic/                the schema: versions/<YYYYMMDD_HHMM>_<slug>.py, env.py reads DATABASE_URL
alembic.ini             `sqlalchemy.url` deliberately empty
scripts/                migrate_sqlite_to_pg.py, the one-way door off SQLite
frontend/               Next.js app (app router)
  app/                  page.tsx (rolls), films/[id] (roll workspace), images, images/[id]
                        (frame viewer), gear; a loading.tsx and error.tsx beside each
  components/           app-shell, roll-browser, roll-wizard, roll-edit-sheet, roll-workspace,
                        frame-grid, frame-viewer, upload-zone, gear-section, gear-dialog,
                        empty/error states and skeletons; components/ui is shadcn
  lib/api.ts            typed fetch helpers, API base handling, ApiError
  lib/format.ts         date range, storage and frame-label formatting
  e2e/smoke.mjs         Playwright smoke test (`npm run e2e`)
  next.config.mjs       the /api and /static rewrites, and the M1 route redirects
tests/                  pytest suite, Postgres only (skipped without DATABASE_URL); test_m2_*
                        cover the migrations, filenames, gear ids, validation and files
docs/                   REVIEW.md, ROADMAP.md, NEGPY_INTEGRATION.md
static/                 served at /static; uploads and cache/ are git-ignored
Dockerfile, docker-compose.yml, frontend/Dockerfile
```

Routes that moved in M1 still work — `/films`, `/cameras`, `/lenses`, `/filmstocks`, `/search`,
`/films/new`, `/films/{id}/edit`, `/images/upload` and `/images/{id}/edit` all redirect (HTTP 307)
to their new home.

## Requirements

- Python **3.10 or newer** (the models use `str | None` annotations; 3.11 is what Docker uses).
  macOS ships 3.9, so use `uv venv --python 3.11` or Homebrew.
- Node 20+ for the frontend (built and type-checked on Node 24, Next 16).
- Docker + Compose for the containerised setup.

## Run with Docker Compose

```bash
docker compose up --build
```

- UI: `http://localhost:8021` (not 3000; see `docker-compose.yml`)
- API: only reachable through the UI container, which proxies `/api/*` to the backend service.
  The backend publishes no host port.
- Postgres data lives in the `pgdata` volume; uploads and catalog images are bind-mounted from
  `./static/uploads` and `./static/catalog`.
- The backend waits for the database: `db` has a `pg_isready` healthcheck and `web` depends on
  `service_healthy`.
- **The schema migrates itself at startup.** `app/main.py` runs `alembic upgrade head` before
  serving, so a fresh volume and a database from M0/M1 both come up on the current schema. A
  failed migration stops the app instead of leaving it to fail at runtime.
- The image is about 0.28 GB and contains no TensorFlow.

## Local development

Backend (against the Compose Postgres, which is the target database):

```bash
docker compose up -d db                   # Postgres 16 on localhost:5432
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive
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

```bash
docker run -d --rm --name negarchive-test-db -p 55440:5432 \
  -e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive -e POSTGRES_DB=negarchive postgres:16
DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:55440/negarchive \
  .venv/bin/python -m pytest tests -q
```

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
toggles dark mode and fails on any console error. `SCREENSHOT_DIR=../screenshots npm run e2e`
refreshes the screenshots below.

Environment variables:

| Variable | Where | Meaning |
|---|---|---|
| `DATABASE_URL` | backend | **Required.** Postgres URL, e.g. `postgresql+psycopg2://negarchive:negarchive@db:5432/negarchive` (Compose). Anything else, or unset, stops the backend at startup |
| `MAX_UPLOAD_MB` | backend | Largest accepted upload, default `512`. Over it the API answers 413 `file_too_large` |
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

### Films

`GET /films`, `GET /films/{id}` → `{film, images, contact_sheets}`, `POST /films`,
`PUT /films/{id}`, `DELETE /films/{id}?keep_files=false`.

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

`GET /images?film_id=&type=scan|contact_sheet`, `GET /images/{id}`, `POST /images`,
`PUT /images/{id}` (`film_roll_id: null` unassigns the image from its roll),
`DELETE /images/{id}?keep_files=false`,
`POST /images/upload` (multipart: `file`, `type`, `film_roll_id?`, `frame_number?`, `notes?`,
`capture_date?`),
`POST /images/bulk_update` (`{ids, film_roll_id?, capture_date?, frame_number?}` — only the keys
you send are written),
`POST /images/bulk_delete` (`{ids, keep_files?}`),
`GET /images/{id}/preview?width=1200` (JPEG; cached on disk under `static/cache/` keyed by image id
+ width + the source file's mtime, so a re-scan invalidates it — `X-Preview-Cache: hit|miss`),
`GET /images/{id}/download` (the original, named after `original_filename`).

Fields: `id, film_roll_id, type, path, url, original_filename, storage_mode, frame_number, notes,
capture_date, created_at`.

`original_filename` is the name the scanner gave the file; the stored name is a UUID. When the
client sends no `frame_number`, it is parsed from that name — an explicit `frame<n>` wins,
otherwise the last group of one to four digits does (`Roll12_007.tif`, `NEG-2024-011_007.jpg`,
`_Frame007`, `007.jpg`, `img_0007` all mean frame 7; `Roll12.tif` means nothing, because a number
glued to a word is part of the word). Frames are always listed in `frame_number NULLS LAST, id`
order.

`storage_mode` is `managed` (NegArchive owns the file and deletes it with the record) or `linked`
(the file belongs to somebody else and is never deleted — M3's import-by-reference).

Uploads must be `jpg jpeg png tif tiff webp dng`, by extension *and* by their leading bytes, and
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

## Known issues

The full list with evidence and file references is [docs/REVIEW.md](docs/REVIEW.md). M2 closed
the data-integrity ones (R#7, R#9, R#10, R#11, R#14, R#15, R#16, R#17, R#18, R#21, R#23, R#24).
What is left:

- **Security:** no authentication and CORS is open — do not expose this outside a trusted LAN
  (R#26). Uploads are now limited by type and size and are never served as HTML.
- **Performance:** `/api/images` is unpaginated and the roll list filters in the browser
  (R#20, roadmap M3).
- **Offline/setup:** the Compose stack still uses separate volumes and no `.env`; one
  bind-mounted `data/` directory is roadmap M3. Some frontend dependencies are still pinned to
  `"latest"` (R#29) and `typescript.ignoreBuildErrors` is still on (R#30).
- **Backups:** there is no export/restore yet (roadmap M3). Deleting a roll now deletes its
  scan files by default — the dialog offers "keep the files on disk", but there is no undo.

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
4. **M3** offline-first: drop analytics/fonts, single Postgres compose stack, thumbnail cache, pagination,
   import-by-reference, watch folder, backup/restore, PWA, LAN QR, tests + CI.
5. **M4** paper ↔ virtual: storage hierarchy, serial scheme, QR labels, printable contact and
   index sheets, strip/position, paper-twin capture, prints and loans.
6. **M5** NegPy: ingest its XMP on upload, write its gear JSON, roll handoff with a metadata
   preset, sidecar awareness, compatible content hash.
7. **M6** Immich connector, optional: shared files via an external library, XMP sidecars, one
   album per roll with tags, "Open in Immich", people from Immich. NegArchive stays standalone.

## License

MIT. NegPy is GPL-3 and is deliberately not imported or bundled.

## Screenshots

Taken by the smoke test against a seeded archive.

The roll list, the home page:

![The roll list](screenshots/screenshot-01.png)

A roll as a workspace — contact sheet, drop zone, frame grid:

![A roll workspace](screenshots/screenshot-02.png)

The frame viewer, with the metadata panel beside the image:

![The frame viewer](screenshots/screenshot-03.png)

At 375px: the roll list and a roll workspace.

![The roll list at 375px](screenshots/screenshot-04.png)
![A roll workspace at 375px](screenshots/screenshot-05.png)

The new-roll wizard, the gear catalog, and the frames page in dark mode:

![The new roll wizard](screenshots/screenshot-06.png)
![The gear catalog](screenshots/screenshot-07.png)
![Frames in dark mode](screenshots/screenshot-08.png)
