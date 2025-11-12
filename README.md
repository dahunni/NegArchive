# NegArchive

FastAPI + Next.js app for archiving film negatives and scans. Includes full CRUD for films, images, cameras, lenses, and filmstocks; local file uploads; optional CPU-only face detection; and a modern React frontend for management and search.

## Stack

- Backend: FastAPI (JSON API only), SQLAlchemy, SQLite (local) or Postgres (Docker)
- Frontend: Next.js, TypeScript, Tailwind/Shadcn UI
- Image storage: Local `static/uploads` (scans/contact sheets) and `static/catalog/*`
- Optional AI: DeepFace for face detection and embedding (CPU)

## Project Structure

```
app/                # FastAPI backend
  main.py           # App, CORS, static, routers
  db.py             # DB session and engine setup
  models.py         # SQLAlchemy models
  routers/          # JSON API routers
    api.py          # Core JSON API (films, images, cameras, lenses, filmstocks)
    films.py        # Legacy HTML routes (deprecated; Next.js handles UI)
    images.py       # Legacy HTML routes (deprecated)
    search.py       # Legacy HTML routes (deprecated)
frontend/           # Next.js app (client UI)
  app/              # App router pages
  components/       # UI components
  lib/api.ts        # Frontend fetch helpers
static/             # Public static assets and uploaded files
docker-compose.yml  # Postgres + uvicorn service
```

Note: Legacy Jinja templates have been removed. The frontend UI is served solely by the Next.js application.

## Quick Start (Docker Compose)

This starts Postgres and the backend API on port `8000`.

```
docker compose up --build
```

- API base: `http://localhost:8000/api`
- Uploaded files are under `/app/static/` in the container. Mount a volume for persistence if needed.

## Local Development

### Backend (FastAPI)

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

- Backend dev URL: `http://localhost:8010`
- API base: `http://localhost:8010/api`
- Database defaults to `sqlite:///./negarchive.db` unless `DATABASE_URL` is set.

Environment variables:
- `DATABASE_URL`: e.g. `postgresql+psycopg2://negarchive:negarchive@db:5432/negarchive`
- `DEEPFACE_ENABLED`: `true`/`false` (default `true` in Docker)
- `FACE_MATCH_THRESHOLD`: cosine similarity threshold (default `0.7`)

### Frontend (Next.js)

```
cd frontend
echo "NEXT_PUBLIC_API_BASE=http://localhost:8010" > .env.local
npm install --legacy-peer-deps
npm run dev
```

- Frontend dev URL: `http://localhost:3000`
- The frontend reads the backend API base from `NEXT_PUBLIC_API_BASE`.
- Remote images are allowed from `localhost:8010` via `next.config.mjs`.

### Image Preview and Download

- `GET /api/images/{id}/preview` streams a JPEG preview for TIFFs and other non-web formats. Uses Pillow first, then OpenCV fallback for 16-bit or grayscale TIFFs.
- `GET /api/images/{id}/download` serves the original file with `Content-Disposition: attachment` for reliable browser downloads.

## API Reference (JSON)

Base: `http://localhost:{8000|8010}/api`

### Films
- `GET /api/films` → `Film[]`
- `GET /api/films/{id}` → `{ film: Film, images: Image[] }`
- `POST /api/films` → `{ ok: true, film: Film }`
- `PUT /api/films/{id}` → `{ ok: true, film?: Film }`
- `DELETE /api/films/{id}` → `{ ok: true }`

Film fields:
`id, title, camera, lens, film_type, notes, building, folder, archive_serial, start_date, end_date, created_at`

### Images
- `GET /api/images` → `Image[]`
- `GET /api/images?film_id={id}` → `Image[]`
- `GET /api/images/{id}` → `Image`
- `POST /api/images` → `{ ok: true, image: Image }`
- `PUT /api/images/{id}` → `{ ok: true, image: Image }`
- `DELETE /api/images/{id}?delete_file={bool}` → `{ ok: true }`
- `POST /api/images/upload` (multipart form) → `Image`

Upload fields:
`file`, `type` (`scan`|`contact_sheet`), `film_roll_id?`, `frame_number?`, `notes?`, `capture_date?`

Image fields:
`id, film_roll_id, type, path, url, frame_number, notes, capture_date, created_at`
`url` points to a public path under `/static/uploads/{scans|contact_sheets}/...`

### Catalog: Cameras
- `GET /api/cameras` → `Camera[]`
- `GET /api/cameras/{id}` → `Camera`
- `POST /api/cameras` → `{ ok: true, camera: Camera }`
- `PUT /api/cameras/{id}` → `{ ok: true }`
- `DELETE /api/cameras/{id}` → `{ ok: true }`
- `POST /api/cameras/{id}/image` (multipart form) → `{ ok: true, camera: Camera }`

Camera fields: `id, name, mount, image_path, url, notes`

### Catalog: Lenses
- `GET /api/lenses` → `Lens[]`
- `GET /api/lenses/{id}` → `Lens`
- `POST /api/lenses` → `{ ok: true, lens: Lens }`
- `PUT /api/lenses/{id}` → `{ ok: true }`
- `DELETE /api/lenses/{id}` → `{ ok: true }`
- `POST /api/lenses/{id}/image` (multipart form) → `{ ok: true, lens: Lens }`

Lens fields: `id, name, mount, image_path, url, notes`

### Catalog: Filmstocks
- `GET /api/filmstocks` → `Filmstock[]`
- `GET /api/filmstocks/{id}` → `Filmstock`
- `POST /api/filmstocks` → `{ ok: true, filmstock: Filmstock }`
- `PUT /api/filmstocks/{id}` → `{ ok: true }`
- `DELETE /api/filmstocks/{id}` → `{ ok: true }`
- `POST /api/filmstocks/{id}/image` (multipart form) → `{ ok: true, filmstock: Filmstock }`

Filmstock fields: `id, name, iso, kind, expired, expiration_date, image_path, url`

## Image URLs in the Frontend

- For catalog items and images, the backend includes a `url` with a leading `/`.
- The frontend resolves absolute URLs via `${NEXT_PUBLIC_API_BASE}${url}` and uses `next/image` with remote patterns configured.

## Quick API Examples

Create a film:
```
curl -X POST http://localhost:8010/api/films \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Test Roll",
    "camera": "Nikon F5",
    "lens": "50mm f/1.8",
    "film_type": "HP5+",
    "start_date": "2024-07-01",
    "end_date": "2024-07-15"
  }'
```

Upload a scan:
```
curl -X POST http://localhost:8010/api/images/upload \
  -F 'file=@/path/to/scan.jpg' \
  -F 'type=scan' \
  -F 'film_roll_id=1' \
  -F 'frame_number=12'
```

Upload a filmstock image:
```
curl -X POST http://localhost:8010/api/filmstocks/1/image \
  -F 'file=@/path/to/stock.jpg'
```

## Known Notes

- The frontend currently installs with `--legacy-peer-deps` to accommodate packages that have not yet declared compatibility with React 19.
- CORS is open in development. Tighten allowed origins for production.
- User-generated uploads (`static/uploads/`) are ignored by git.

## License

Apache-2.0 or MIT — choose what you prefer for open-source distribution.