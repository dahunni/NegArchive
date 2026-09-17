# NegArchive code review (2026-09-17)

Scope: every file in `app/`, `frontend/` (excluding generated `components/ui/*`), Docker and config.
Method: read all code; booted the backend on Python 3.11 against SQLite **and** Postgres 16 and
exercised the API with a probe script; ran `tsc --noEmit` (0 errors) and `next build` (succeeds).
"Confirmed" below means reproduced by running it, "By reading" means the defect is evident from
the code but was not executed.

Severity: **P0** breaks a shipped workflow · **P1** wrong data or data loss · **P2** robustness/UX ·
**P3** hygiene.

## P0 — broken in the Docker deployment

| # | Finding | Where | Evidence |
|---|---------|-------|----------|
| 1 | **Creating or editing a filmstock from the UI fails on Postgres.** The form sends `expired: true/false`; the column is `Integer`; the API passes it through unchanged. Postgres rejects boolean→integer. Works on SQLite only, so it is invisible in local dev. | `frontend/components/filmstock-form.tsx:67`, `app/models.py:40`, `app/routers/api.py:628,657-659` | Confirmed: `psycopg2.errors.DatatypeMismatch: column "expired" is of type integer but expression is of type boolean` |
| 2 | **Catalog images (camera/lens/filmstock pictures) never load in Docker.** Two components build the `<img>` URL from `NEXT_PUBLIC_API_BASE \|\| "http://localhost:8010"`; compose sets that variable to `""`, so browsers request `localhost:8010` on the viewer's machine. Even with a same-origin URL it would 404: the Next rewrite only proxies `/api/*`, not `/static/*`, and the `web` service publishes no port. | `frontend/components/catalog-list.tsx:20,70`, `frontend/components/filmstocks-list.tsx:20,62-67`, `frontend/next.config.mjs:27-32`, `docker-compose.yml` | By reading (deterministic from config) |
| 3 | **"Generate Contact Sheet" is broken in Docker.** `createContactSheet` is the one client call that uses `INTERNAL_API_BASE`, which in the browser resolves to `localhost:8010`. | `frontend/lib/api.ts:4-7,152` | By reading |
| 4 | **Six legacy HTML routers are still mounted but their templates were deleted.** `GET /films`, `/cameras`, `/lenses`, `/filmstocks`, `/search`, `/images/upload` all return 500, and they add 20+ dead paths to the OpenAPI schema. `images.py` also imports the face service, which imports DeepFace/TensorFlow at startup when `DEEPFACE_ENABLED=true` (the compose default). | `app/main.py:10,110-114,117`, `app/routers/{films,images,search,cameras,filmstocks,lenses}.py`, `app/routers/images.py:11` | Confirmed: `GET /films` → 500 (`TemplateNotFound`) |
| 5 | **Uploading an image without a film → 500.** The upload form offers "None" for film and the README calls `film_roll_id` optional, but the column is `NOT NULL` (`Mapped[int]` without `Optional`). | `app/models.py:86`, `app/routers/api.py:336`, `frontend/components/image-upload-form.tsx:156`, `README.md` | Confirmed on SQLite and Postgres: `NOT NULL constraint failed: image_assets.film_roll_id` |
| 6 | **Uploading a new catalog image while *editing* a lens or filmstock fails.** `PUT /api/lenses/{id}` and `PUT /api/filmstocks/{id}` return only `{"ok": true}`; the forms then call `uploadLensImage(savedItem.id)` with `undefined` → `POST /api/lenses/undefined/image` → 422. Cameras work because their PUT returns the object. | `app/routers/api.py:663,735`, `frontend/components/catalog-form.tsx:57-59,73-75`, `frontend/components/filmstock-form.tsx:74,80` | By reading |

## P1 — wrong data or data loss

| # | Finding | Where | Evidence |
|---|---------|-------|----------|
| 7 | **Original filenames are thrown away on every upload path.** Only the extension survives; files are renamed to a UUID. Bulk and ZIP imports also set `frame_number = None`. For an archive the scanner filename (`Roll12_007.tif`) is the only link between a physical frame and its file, and sort order is lost. | `app/routers/api.py:348-350,448-450,503-505` | Confirmed: uploaded `Roll12_007.jpg` stored as `c62a…d9d.jpg`, no record of the name |
| 8 | **The literal string `"None"` is saved as camera, lens and film type.** The film form initialises the selects with `"None"` and submits verbatim; the API stores it. Lists then show "None" instead of "—". | `frontend/components/film-form.tsx:41-43,94,101`, `app/routers/api.py:101-103` | Confirmed: `POST /api/films {"camera":"None"}` → stored `"None"` |
| 9 | **Deleting a film or image never deletes files.** Film delete removes DB rows only; the image edit form hard-codes `deleteImage(id, false)`. Disk usage only grows and there is no orphan sweep. The delete dialog text also promises more than it does. | `app/routers/api.py:138-141`, `frontend/components/image-edit-form.tsx:85`, `frontend/components/films-list.tsx:121` | Confirmed: after `DELETE /api/films/1` all scan files remain |
| 10 | **Deleting a film whose images have face rows fails on Postgres.** Bulk `query.delete()` bypasses the ORM cascade; `faces.image_id` FK is violated. (Only reachable once face detection is wired up.) | `app/routers/api.py:139`, `app/models.py:95,112` | Confirmed: `ForeignKeyViolation: faces_image_id_fkey` |
| 11 | **Seed data resurrects on every restart.** Deleting Nikon F5, Minolta XG9, Kodak Gold 200 or the Fomapans is undone at the next boot. | `app/main.py:72-94` | Confirmed |
| 12 | **An image cannot be unassigned from a film.** `PUT /api/images/{id}` ignores `film_roll_id: null` (falsy check), while the edit form offers "None". Schema also forbids NULL (see #5). | `app/routers/api.py:297-298`, `frontend/components/image-edit-form.tsx:59` | Confirmed: PUT with `null` returns unchanged record |
| 13 | **`url` becomes wrong after changing an image's type.** `image_to_dict` derives the public URL from the *current* type plus the file's basename, but the file stays in the folder it was uploaded to. Preview/download still work because they use `path`. | `app/routers/api.py:40-44` | By reading |
| 14 | **Catalog references are by name, not by id.** Films store `camera`, `lens`, `film_type` as free strings. Renaming or deleting a catalog item silently orphans every film that used it; there is no cascade, no warning, no backfill. | `app/models.py:62-65` | By reading |
| 15 | **Face detection is dead code, but its dependencies are shipped.** `process_image` is only called from the broken legacy route; the JSON upload never runs it; there is no faces/persons API. Inside it, every face gets the *same* embedding (`rep[0]` reused per face), and on SQLite `embedding` is stored as `Text` so `.get("v")` would raise. Meanwhile `deepface`+TensorFlow are hard requirements (~2 GB image, slow cold start) and `DEEPFACE_ENABLED=true` in compose. | `app/services/face.py:36-48,63,73`, `app/models.py:119`, `app/routers/images.py:77`, `requirements.txt:10`, `docker-compose.yml:21` | By reading |

## P2 — robustness, security, performance, UX

| # | Finding | Where | Evidence |
|---|---------|-------|----------|
| 16 | **No input validation anywhere; every bad input is a bare 500.** Handlers call `request.json()` and `date.fromisoformat()` directly. Invalid date, empty body, non-numeric frame number, duplicate catalog name, missing camera name, unknown film kind all crash. `schemas.py` defines Pydantic models that nothing uses. | `app/routers/api.py:97-110,121-128,302,541,623`, `app/schemas.py` | Confirmed for each case listed |
| 17 | **"Not found" is HTTP 200 with `{"error":"not_found"}`.** The frontend's `res.ok` checks therefore never fire; edit pages happily render forms for records that do not exist and the film detail page needs an `as any` workaround. | `app/routers/api.py:75,120,137,…`, `frontend/app/films/[id]/page.tsx:22`, `frontend/app/*/[id]/edit/page.tsx` | Confirmed |
| 18 | **Any file type is accepted and then served as-is from `/static` → stored XSS.** Uploaded `evil.html` is served with `text/html`. No MIME sniff, no extension allowlist (the ZIP path has one; the single/bulk paths do not), no size limit. | `app/routers/api.py:348-353,448-453,576-581` | Confirmed: `GET /static/uploads/scans/….html` returned the script |
| 19 | **Preview endpoint re-decodes the full-resolution file on every request.** No thumbnail cache; a film page with 36 TIFF scans decodes 36 TIFFs per view. Also sets Pillow's global `LOAD_TRUNCATED_IMAGES` and does blocking file IO inside `async` handlers. | `app/routers/api.py:173-256,352-353` | By reading |
| 20 | **No pagination.** `/api/images` returns every image; the Search page downloads all films, images and filmstocks and filters in the browser. | `app/routers/api.py:145-162`, `frontend/app/search/page.tsx:6` | By reading |
| 21 | **Filmstock "kind" UX.** The select only lists kinds already in use (so `slide` and `motion_picture` are unreachable on a fresh install), and when the catalog is empty the field becomes free text, which the enum rejects with a 500. | `frontend/components/filmstock-form.tsx:36-40,137-158`, `app/routers/api.py:623` | Confirmed: `'Color Negative' is not a valid FilmKind` |
| 22 | **Stray "0" rendered on every non-expired filmstock card.** `{filmstock.expired && <Badge/>}` with `expired === 0` renders the number. The TS type says `boolean`, the API returns `0/1`. | `frontend/components/filmstocks-list.tsx:84`, `frontend/lib/api.ts:69` | By reading (React semantics) |
| 23 | **Schema management is ad hoc.** Column additions are `ALTER TABLE` in a startup hook inside a blanket `try/except: pass`; `create_all` never adds columns; no Alembic. A failed migration is silent. `@app.on_event("startup")` is deprecated. | `app/main.py:24-70` | By reading |
| 24 | **Frame ordering.** Film detail and contact-sheet inputs sort by `id`; only the contact sheet honours `frame_number`. Images show "Frame unknown" after bulk import (see #7). | `app/routers/api.py:80,87,378` | By reading |
| 25 | **Docker build context is the whole repo.** No `.dockerignore`, so `frontend/node_modules`, `.next`, `.git`, screenshots go into the backend image and every build. `depends_on` has no healthcheck; compose `version:` key is obsolete. README documents ports 8000/3000 but compose exposes the UI on **8021** and does not publish the API at all. | `Dockerfile:18`, `docker-compose.yml`, `README.md` | Confirmed (no `.dockerignore` present) |
| 26 | **No auth, CORS `*`.** Fine on a trusted LAN, but nothing documents that the app must not be exposed. | `app/main.py:15-21` | By reading |

## P3 — hygiene and offline-readiness

| # | Finding | Where |
|---|---------|-------|
| 27 | `@vercel/analytics` is loaded on every page and phones home; wrong for an offline archive. | `frontend/app/layout.tsx:4,47` |
| 28 | Three Google font families are fetched at build time (build needs internet) and then never applied. | `frontend/app/layout.tsx:7-12,44` |
| 29 | `"latest"` version specifiers (`react-checkbox`, `react-label`, `react-tabs`, `@vercel/analytics`) make builds non-reproducible; stale 92-byte `pnpm-lock.yaml` beside `package-lock.json`; package name is `my-v0-project`. | `frontend/package.json`, `frontend/pnpm-lock.yaml` |
| 30 | `typescript.ignoreBuildErrors: true` hides regressions; `tsc` is currently clean, so it can be switched off now. | `frontend/next.config.mjs:6-8` |
| 31 | README does not state the Python floor. `models.py` uses `str \| None` annotations → Python ≥ 3.10; this Mac's system Python is 3.9. | `app/models.py`, `README.md` |
| 32 | Dead files: `static/css/style.css`, duplicate `frontend/styles/globals.css` (identical to `app/globals.css`), unused `app/schemas.py`, `Jinja2` requirement. | — |
| 33 | No tests, no CI, no linter for either half. | — |
| 34 | README lists screenshots 01–07; 08 exists. | `README.md`, `screenshots/` |

## What is in good shape

- The JSON API surface is small and easy to reason about; the Next.js pages are thin and consistent.
- `tsc --noEmit` passes with zero errors and `next build` succeeds on Node 24 / Next 16.
- The preview endpoint's Pillow → OpenCV → original fallback chain handles 16-bit and grayscale TIFFs.
- The SSR/CSR API-base split (`API_BASE` vs `NEXT_PUBLIC_API_BASE`) plus the `/api` rewrite is the
  right shape for a single-port deployment; it just is not applied consistently (#2, #3).
- ZIP import is not vulnerable to zip-slip (Python's `extractall` strips `..` components).
