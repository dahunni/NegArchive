# NegArchive

A self-hosted archive for film photography: film rolls, their scans and contact sheets, the
cameras, lenses and film stocks they were shot with, and where the physical negatives live.
FastAPI JSON backend + Next.js frontend.

**Status: alpha, single user, run it on a trusted LAN only.** There is no authentication and CORS
is open. A full review with confirmed bugs is in [docs/REVIEW.md](docs/REVIEW.md); the task list is
in [docs/ROADMAP.md](docs/ROADMAP.md). Milestones M0 (the bugs that broke shipped workflows in
Docker) and M1 (the UI rework) are done; read the [Known issues](#known-issues) section before
deploying.

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
   phone at the shelf. SQLite still works today but is being dropped (see roadmap M2).
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

- Backend: FastAPI, SQLAlchemy 2, Postgres (target; SQLite still the fallback when
  `DATABASE_URL` is unset), Pillow + OpenCV for previews of TIFF and other non-web formats
- Frontend: Next.js 16 (app router), React 19, TypeScript, Tailwind 4, shadcn/ui (15 components,
  the rest were removed in M1), `next-themes` for dark mode, no web fonts and no analytics
- Storage: files under `static/uploads/{scans,contact_sheets}` and `static/catalog/*`; paths are
  stored in the database
- Dead code, still a dependency: DeepFace face detection. Nothing imports it at startup any
  more; whether it is revived or deleted is decided in roadmap M2.

## Project structure

```
app/                    FastAPI backend
  main.py               app, CORS, static mount, startup "migrations" and seed data
  db.py                 engine and session
  models.py             SQLAlchemy models (FilmRoll, ImageAsset, Camera, Lens, FilmStock, Person, Face)
  errors.py             structured {"error": {code, message}} bodies for validation failures
  schemas.py            Pydantic models (currently unused; M2 will wire them up)
  routers/api.py        the JSON API, everything under /api — the only router
  services/face.py      DeepFace helpers, currently unreachable (fate decided in M2)
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
tests/                  pytest suite, runs against Postgres (skipped without DATABASE_URL)
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
- The first build still downloads DeepFace and TensorFlow (about 2 GB) although nothing calls
  them; removing the dependency is a roadmap M2 decision. `DEEPFACE_ENABLED` defaults to `false`.

## Local development

Backend (against the Compose Postgres, which is the target database):

```bash
docker compose up -d db                   # Postgres 16 on localhost:5432
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -r requirements.txt        # or: grep -v deepface requirements.txt for a lean install
DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive \
DEEPFACE_ENABLED=false uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

Leaving `DATABASE_URL` unset falls back to `sqlite:///./negarchive.db`. Do not rely on it: two of
the confirmed bugs only appeared on Postgres, and SQLite support is scheduled for removal.

Tests (Postgres only; they are skipped when `DATABASE_URL` is unset):

```bash
docker run -d --rm --name negarchive-test-db -p 55433:5432 \
  -e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive -e POSTGRES_DB=negarchive postgres:16
DEEPFACE_ENABLED=false \
DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:55433/negarchive \
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
| `DATABASE_URL` | backend | Postgres URL, e.g. `postgresql+psycopg2://negarchive:negarchive@db:5432/negarchive` (Compose). Unset falls back to `sqlite:///./negarchive.db`, deprecated |
| `DEEPFACE_ENABLED` | backend | `true`/`false`; guards the DeepFace import in `services/face.py`, which nothing calls today |
| `FACE_MATCH_THRESHOLD` | backend | cosine threshold, unused in practice |
| `NEXT_PUBLIC_API_BASE` | frontend, browser | absolute API origin for local dev; empty in Docker so the browser uses same-origin `/api` and `/static` via the Next rewrites |
| `API_BASE` | frontend, server side | origin used for server-side fetches inside Docker (`http://web:8000`) |

## API

Base: `/api`. All responses are JSON.

The validation failures the UI can produce answer with a real 4xx and a structured body:

```json
{ "error": { "code": "duplicate_name", "message": "A camera named “Nikon F5” already exists." } }
```

Codes in use: `invalid_json`, `invalid_title`, `invalid_name`, `invalid_date`, `invalid_date_range`,
`invalid_number`, `invalid_kind`, `invalid_type`, `invalid_ids`, `nothing_to_update`,
`not_enough_images` (400), `duplicate_name` (409), `unknown_roll` (404). Everything else is
unchanged: "not found" on the read endpoints is still HTTP 200 with `{"error": "not_found"}`, and
other bad input is still a bare 500. Finishing that job is M2 in
[docs/ROADMAP.md](docs/ROADMAP.md).

Films: `GET /films`, `GET /films/{id}` → `{film, images, contact_sheets}`, `POST /films`,
`PUT /films/{id}`, `DELETE /films/{id}` (deletes image rows, not files).
Fields: `id, title, camera, lens, film_type, notes, building, folder, archive_serial, start_date,
end_date, created_at, image_count, cover_image_id, cover_image_ids`.
Camera, lens and film type are stored as **names**, not ids. `image_count` and the (at most four)
`cover_image_ids` let the roll list show a frame count and a thumbnail strip without a request per
roll; `cover_image_id` is the first of them.

Images: `GET /images?film_id=&type=scan|contact_sheet`, `GET /images/{id}`, `POST /images`,
`PUT /images/{id}` (`film_roll_id: null` unassigns the image from its roll),
`DELETE /images/{id}?delete_file=false`,
`POST /images/upload` (multipart: `file`, `type`, `film_roll_id?`, `frame_number?`, `notes?`,
`capture_date?`),
`POST /images/bulk_update` (`{ids, film_roll_id?, capture_date?, frame_number?}` — only the keys
you send are written; `film_roll_id: null` unassigns),
`POST /images/bulk_delete` (`{ids, delete_file}`),
`GET /images/{id}/preview?width=1200` (JPEG; cached on disk under `static/cache/` keyed by image id
+ width + the source file's mtime, so a re-scan invalidates it — `X-Preview-Cache: hit|miss`),
`GET /images/{id}/download` (original, as attachment).
Fields: `id, film_roll_id, type, path, url, frame_number, notes, capture_date, created_at`;
`film_roll_id` may be `null`. The original filename is **not** stored.

Per film: `POST /films/{id}/contact_sheet?columns=6&thumb_size=300`,
`POST /films/{id}/images/bulk` (multipart `files[]`), `POST /films/{id}/images/bulk_zip` (multipart `file`).

Catalog: `GET|POST /cameras`, `GET|PUT|DELETE /cameras/{id}`, `POST /cameras/{id}/image`; same
for `/lenses` and `/filmstocks`. Filmstock fields:
`id, name, iso, kind (black_and_white|color|slide|motion_picture), expired (boolean), expiration_date, image_path, url`.
`PUT` on a camera, lens or filmstock returns the updated object.

Examples:

```bash
curl -X POST http://localhost:8010/api/films -H 'Content-Type: application/json' \
  -d '{"title":"Roll 12","camera":"Nikon F5","film_type":"Fomapan 400","start_date":"2024-07-01"}'
```

```bash
curl -X POST http://localhost:8010/api/images/upload -F 'file=@scan.tif' -F 'type=scan' -F 'film_roll_id=1' -F 'frame_number=12'
```

## Known issues

The full list with evidence and file references is [docs/REVIEW.md](docs/REVIEW.md). The ones
that matter most:

- **Docker + Postgres:** deleting a film that has face rows fails on a foreign key.
- **Data loss:** original filenames are discarded on every upload path (files are renamed to a
  UUID, frame numbers from bulk import are lost). Deleting a film or image leaves its files on
  disk forever. Renaming or deleting a camera, lens or film stock silently orphans every roll
  that used it.
- **Crashes:** the inputs the UI produces are validated (see the API section), but other bad
  input still returns a bare HTTP 500, and every endpoint is still unvalidated below that.
- **Wrong data:** seed cameras and film stocks come back on every restart; "not found" is an
  HTTP 200 with `{"error": "not_found"}`.
- **Security:** any file type is accepted and served back from `/static`, including HTML
  (stored XSS on the LAN). No size limits. No auth.
- **Offline:** DeepFace/TensorFlow are still hard requirements although the feature is dead, so
  the backend image is about 2 GB. (The frontend no longer loads analytics or web fonts and
  builds without internet.)

## Next steps (short version)

Full checklist: [docs/ROADMAP.md](docs/ROADMAP.md).

1. **M0** *(done)* fix the Docker-breaking bugs, remove the legacy routers, add `.dockerignore`.
2. **M1** *(done)* UI rework around the roll as the unit of work: roll list with thumbnails,
   roll page as a workspace with inline editing, drag-and-drop upload, frame viewer, dialogs
   instead of form pages, mobile layout, dark mode.
3. **M2** archive integrity: Postgres only (drop SQLite, migration script for existing DBs),
   keep original filenames and parse frame numbers, foreign keys for gear, Alembic, validation
   with real status codes, file lifecycle, upload allowlist, decide the fate of face detection.
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
