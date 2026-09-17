# NegArchive

A self-hosted archive for film photography: film rolls, their scans and contact sheets, the
cameras, lenses and film stocks they were shot with, and where the physical negatives live.
FastAPI JSON backend + Next.js frontend.

**Status: alpha, single user, run it on a trusted LAN only.** There is no authentication and CORS
is open. A full review with confirmed bugs is in [docs/REVIEW.md](docs/REVIEW.md); the task list is
in [docs/ROADMAP.md](docs/ROADMAP.md). Read the [Known issues](#known-issues) section before
deploying, several shipped workflows are currently broken.

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

## Stack

- Backend: FastAPI, SQLAlchemy 2, Postgres (target; SQLite still the fallback when
  `DATABASE_URL` is unset), Pillow + OpenCV for previews of TIFF and other non-web formats
- Frontend: Next.js 16, React 19, TypeScript, Tailwind 4, shadcn/ui
- Storage: files under `static/uploads/{scans,contact_sheets}` and `static/catalog/*`; paths are
  stored in the database
- Optional, currently dead code: DeepFace face detection (see Known issues)

## Project structure

```
app/                    FastAPI backend
  main.py               app, CORS, static mount, startup "migrations" and seed data
  db.py                 engine and session
  models.py             SQLAlchemy models (FilmRoll, ImageAsset, Camera, Lens, FilmStock, Person, Face)
  schemas.py            Pydantic models (currently unused)
  routers/api.py        the JSON API, everything under /api
  routers/{films,images,search,cameras,filmstocks,lenses}.py
                        legacy HTML routes whose templates were removed; they 500 (to be deleted)
  services/face.py      DeepFace helpers, only reachable from the legacy routes
frontend/               Next.js app (app router)
  app/                  pages: films, images, cameras, lenses, filmstocks, search
  components/           forms, lists, grids; components/ui is shadcn
  lib/api.ts            typed fetch helpers and API base handling
docs/                   REVIEW.md, ROADMAP.md, NEGPY_INTEGRATION.md
static/                 served at /static; uploads are git-ignored
Dockerfile, docker-compose.yml, frontend/Dockerfile
```

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
- The first build downloads DeepFace and TensorFlow (about 2 GB) although nothing calls them.
  Set `DEEPFACE_ENABLED=false` in `docker-compose.yml` to at least skip importing them at startup.

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
the confirmed bugs only appear on Postgres, and SQLite support is scheduled for removal.

Frontend:

```bash
cd frontend
echo "NEXT_PUBLIC_API_BASE=http://localhost:8010" > .env.local
npm ci --legacy-peer-deps
npm run dev            # http://localhost:3000
```

Environment variables:

| Variable | Where | Meaning |
|---|---|---|
| `DATABASE_URL` | backend | Postgres URL, e.g. `postgresql+psycopg2://negarchive:negarchive@db:5432/negarchive` (Compose). Unset falls back to `sqlite:///./negarchive.db`, deprecated |
| `DEEPFACE_ENABLED` | backend | `true`/`false`; only affects an import at startup today |
| `FACE_MATCH_THRESHOLD` | backend | cosine threshold, unused in practice |
| `NEXT_PUBLIC_API_BASE` | frontend, browser | absolute API origin for local dev; empty in Docker so the browser uses same-origin `/api` via the Next rewrite |
| `API_BASE` | frontend, server side | origin used for server-side fetches inside Docker (`http://web:8000`) |

## API

Base: `/api`. All responses are JSON. Today "not found" is returned as HTTP 200 with
`{"error": "not_found"}` and validation failures as HTTP 500; fixing that is the first item in
[docs/ROADMAP.md](docs/ROADMAP.md).

Films: `GET /films`, `GET /films/{id}` → `{film, images, contact_sheets}`, `POST /films`,
`PUT /films/{id}`, `DELETE /films/{id}` (deletes image rows, not files).
Fields: `id, title, camera, lens, film_type, notes, building, folder, archive_serial, start_date, end_date, created_at`.
Camera, lens and film type are stored as **names**, not ids.

Images: `GET /images?film_id=&type=scan|contact_sheet`, `GET /images/{id}`, `POST /images`,
`PUT /images/{id}`, `DELETE /images/{id}?delete_file=false`,
`POST /images/upload` (multipart: `file`, `type`, `film_roll_id` **required** in practice,
`frame_number?`, `notes?`, `capture_date?`),
`GET /images/{id}/preview?width=1200` (JPEG, re-encoded on every request),
`GET /images/{id}/download` (original, as attachment).
Fields: `id, film_roll_id, type, path, url, frame_number, notes, capture_date, created_at`.
The original filename is **not** stored.

Per film: `POST /films/{id}/contact_sheet?columns=6&thumb_size=300`,
`POST /films/{id}/images/bulk` (multipart `files[]`), `POST /films/{id}/images/bulk_zip` (multipart `file`).

Catalog: `GET|POST /cameras`, `GET|PUT|DELETE /cameras/{id}`, `POST /cameras/{id}/image`; same
for `/lenses` and `/filmstocks`. Filmstock fields:
`id, name, iso, kind (black_and_white|color|slide|motion_picture), expired (0|1), expiration_date, image_path, url`.

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

- **Docker + Postgres:** creating or editing a filmstock from the UI fails (boolean sent to an
  integer column). Catalog images and "Generate Contact Sheet" point at `localhost:8010` in the
  browser and never load. Deleting a film that has face rows fails on a foreign key.
- **Data loss:** original filenames are discarded on every upload path (files are renamed to a
  UUID, frame numbers from bulk import are lost). Deleting a film or image leaves its files on
  disk forever. Renaming or deleting a camera, lens or film stock silently orphans every roll
  that used it.
- **Crashes:** upload without a film, invalid dates, non-numeric frame numbers, duplicate
  catalog names, empty request bodies and unknown film kinds all return a bare HTTP 500. The six
  legacy HTML routes (`/films`, `/cameras`, …) always 500.
- **Wrong data:** the film form stores the literal string `"None"` for camera/lens/film type;
  images cannot be unassigned from a film; seed cameras and film stocks come back on every restart;
  every non-expired filmstock card shows a stray `0`.
- **Security:** any file type is accepted and served back from `/static`, including HTML
  (stored XSS on the LAN). No size limits. No auth.
- **Offline:** the UI loads `@vercel/analytics` and Google fonts; the frontend build needs
  internet for the fonts. DeepFace/TensorFlow are hard requirements although the feature is dead.

## Next steps (short version)

Full checklist: [docs/ROADMAP.md](docs/ROADMAP.md).

1. **M0** fix the Docker-breaking bugs, remove the legacy routers, add `.dockerignore`.
2. **M1** complete UI rework around the roll as the unit of work: roll list with thumbnails,
   roll page as a workspace with inline editing, drag-and-drop upload, lightbox, dialogs instead
   of form pages, mobile layout.
3. **M2** archive integrity: Postgres only (drop SQLite, migration script for existing DBs),
   keep original filenames and parse frame numbers, foreign keys for gear, Alembic, validation
   with real status codes, file lifecycle, upload allowlist, decide the fate of face detection.
4. **M3** offline-first: drop analytics/fonts, single Postgres compose stack, thumbnail cache, pagination,
   import-by-reference, watch folder, backup/restore, PWA, LAN QR, tests + CI.
5. **M4** paper ↔ virtual: storage hierarchy, serial scheme, QR labels, printable contact and
   index sheets, strip/position, paper-twin capture, prints and loans.
6. **M5** NegPy: ingest its XMP on upload, write its gear JSON, roll handoff with a metadata
   preset, sidecar awareness, compatible content hash.

## License

MIT. NegPy is GPL-3 and is deliberately not imported or bundled.

## Screenshots

![Screenshot 01](screenshots/screenshot-01.png)
![Screenshot 02](screenshots/screenshot-02.png)
![Screenshot 03](screenshots/screenshot-03.png)
![Screenshot 04](screenshots/screenshot-04.png)
![Screenshot 05](screenshots/screenshot-05.png)
![Screenshot 06](screenshots/screenshot-06.png)
![Screenshot 07](screenshots/screenshot-07.png)
![Screenshot 08](screenshots/screenshot-08.png)
