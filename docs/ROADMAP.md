# NegArchive roadmap, tasks and todos

Status: alpha, single-user, LAN-only. This file is the working task list. Numbers like **R#7**
refer to findings in [REVIEW.md](REVIEW.md). Checkboxes are the todo state.

Guiding decisions (see [NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md) for the reasoning):

1. **NegArchive is the system of record for the physical archive**: rolls, frames, storage
   location, catalog. NegPy stays the processing tool. Integration is file-based (JSON, XMP,
   sidecars), never by importing NegPy code, so NegArchive stays MIT.
2. **Offline-first, Postgres-only**: no network calls at runtime, one Compose stack that includes
   Postgres, one command to run, everything exportable as plain files. SQLite is dropped as a
   supported database; it hid the Postgres bugs (R#1, R#10) and forces two code paths.
3. **Never lose the link to the paper**: original filenames, frame numbers, serials and
   storage locations are first-class and printable.
4. **Immich is the optional photo layer, NegArchive is the film layer.** Immich (external
   libraries, XMP sidecars, REST API) can own thumbnails, faces and people, map, mobile backup and
   sharing. NegArchive owns rolls, frames, gear, storage location, serials, labels, contact sheets
   and unscanned rolls, and must keep working without Immich. See M6.

---

## M0 — Stop the bleeding (bugs that break shipped workflows)

- [x] Fix filmstock create/update on Postgres: `expired` is now a Boolean column, migrated in the
      startup hook (Alembic still to come in M2), and the API coerces whatever the client sends. **R#1**
- [x] Proxy `/static/*` through Next (add a rewrite) and make *every* browser URL go through one
      helper in `lib/api.ts`; delete the two local `API_BASE` constants. **R#2, R#3**
- [x] Remove the six legacy HTML routers and `Jinja2`; keep only `routers/api.py`. **R#4**
- [x] Make `image_assets.film_roll_id` nullable (startup `DROP NOT NULL` on Postgres) and let
      `PUT /api/images/{id}` unassign a frame with `film_roll_id: null`. **R#5, R#12**
- [x] Return the full object from `PUT /api/lenses/{id}` and `PUT /api/filmstocks/{id}`. **R#6**
- [x] Map the "None" select value to `null` in `film-form.tsx` before submit; also add a one-off
      data fix that nulls existing `"None"` strings. **R#8**
- [x] Add `.dockerignore` (backend and frontend); README ports already matched compose; add a
      Postgres healthcheck with `depends_on: condition: service_healthy`; drop the obsolete
      compose `version:` key. **R#25**
- [x] Render `expired` as boolean in the API and fix the `{0 && …}` render. **R#22**

## M1 — UI rework (high priority) *(done)*

The UI used to be a generic CRUD scaffold (one table or card grid per entity, a separate page
for every form, icon-only actions, no thumbnails on the roll list, no lightbox, no drag-and-drop,
navigation that overflowed on phones). It is now built around the real workflow: **a roll is the
unit of work**, and most sessions are "new roll → dump scans → number and annotate frames → find
it later".

**Stack constraint: the rework stays on Next.js.** App router, React 19, TypeScript, Tailwind 4
and shadcn/ui as today; no framework switch, no separate SPA. Server components keep fetching
through `lib/api.ts`, interactive parts are client components, and the `/api` and `/static`
rewrites remain the only way the browser reaches the backend.

- [x] **Information architecture**: Rolls are the home page (`/`, with `/films` kept working),
      each row a thumbnail strip, film, camera, date range, frame count and storage location;
      cameras, lenses and film stocks are one "Gear" section with tabs (`/cameras`, `/lenses`,
      `/filmstocks` redirect into it); Search is the filter bar above the roll list (text, camera,
      film, date range) and `/search?q=` redirects to `/?q=`.
- [x] **Roll page as a workspace**: contact sheet on top, frames in a grid with frame number and
      date visible, inline edit of frame number and notes, keyboard navigation (arrows, Enter,
      Space, Escape), multi-select with bulk delete / reassign / set date, drag-and-drop upload
      zone for many files and ZIPs with per-file progress.
- [x] **Lightbox / frame viewer** with previous/next (buttons and arrow keys), zoom, download and
      the metadata panel beside the image. It replaced both the image detail page and the image
      edit page; `/images/{id}` opens the viewer, `/images/{id}/edit` redirects to it.
- [x] **Forms as dialogs or side panels** (`Dialog` for the wizard and the gear forms, `Sheet` for
      the roll editor) with the API's own validation message on the field that caused it; saving
      keeps the user where they were and calls `router.refresh()`.
- [x] **New roll wizard**: title and dates → gear and film → storage, then straight into the upload
      zone; the last camera, lens and film are remembered in `localStorage`.
- [x] **Mobile / tablet layout**: navigation collapses into a Sheet, one-column roll list, 44px
      targets; tested at 375px (no horizontal scrolling on any route).
- [x] **Consistent empty, loading and error states**: one `EmptyState` and one `ErrorState`,
      `loading.tsx` skeletons that mirror each layout, `error.tsx` per section; toasts only report
      background results (uploads, bulk actions, deletes).
- [x] **Visual pass**: dark mode toggle on the existing `next-themes` provider
      (`attribute="class"`), a four-step typography scale, real thumbnails everywhere (the
      thumbnail cache was pulled forward from M3), and 3:2 `object-contain` cells so 35mm frames
      are never square-cropped.
- [x] Removed 42 unused shadcn components from `components/ui` (15 left) and the 31 dependencies
      that only they imported, including `@vercel/analytics` and the Google font loaders.

## M2 — Archive integrity (data model)

- [ ] **Postgres only.** Make `DATABASE_URL` required (no SQLite fallback), remove the SQLite
      branches (`check_same_thread`, the `Text` variant on `Face.embedding`), use native
      `JSONB`/`Boolean`/`Date` types, and run every migration and test against Postgres 16.
      Local dev = `docker compose up db` plus uvicorn on the host. Ship a one-off
      `scripts/migrate_sqlite_to_pg.py` for existing `negarchive.db` files.
- [ ] Store `original_filename` on every upload; parse `frame_number` from it
      (`Roll12_007.tif`, `_Frame007`, `007.jpg`, NegPy's `{roll}_{frame}` pattern). Sort by
      frame everywhere. **R#7, R#24**
- [ ] Replace name-based references with foreign keys: `film_rolls.camera_id`, `lens_id`,
      `film_stock_id` (keep the string columns during migration, backfill by name). **R#14**
- [ ] Introduce Alembic (Postgres dialect, autogenerate checked in CI); move the startup
      `ALTER TABLE` hacks into migrations; drop the seed-on-startup (seed only when the table is
      empty, or via `POST /api/seed`). **R#11, R#23**
- [ ] Pydantic request/response models for every endpoint (the unused `schemas.py` is the start);
      proper 404/400/409 status codes; structured error body `{ "error": { code, message } }`.
      *(M1 added that body and real 4xx codes for the cases its forms hit — see `app/errors.py`.
      Every other endpoint, and "not found", still answers the old way.)* **R#16, R#17**
- [ ] File lifecycle: delete files with records (with a "keep files" option), an orphan sweep
      endpoint, and a `delete_file` checkbox in the UI. **R#9**
- [ ] Extension + MIME allowlist (`jpg jpeg png tif tiff webp dng`), size limit, never serve
      uploads as `text/html`. **R#18**
- [ ] Faces: delete `services/face.py`, the `Face` and `Person` models and the `deepface`,
      `scikit-learn` and `opencv` requirements if nothing else needs them. People detection comes
      from Immich (M6), not from this codebase. **R#10, R#15**
- [ ] Filmstock `kind` select lists the enum, not "kinds already used". Add `manufacturer`,
      `format` (35mm/120/4x5…) to filmstocks; add `format` to rolls. **R#21** (also needed for NegPy gear sync)

## M3 — Offline-first and easy local use

- [x] Remove `@vercel/analytics` and the Google font loaders; use a system font stack. **R#27, R#28**
      *(done in M1: they were in the way of the layout rework)*
- [ ] Pin the remaining `"latest"` dependencies (4 of 5 went with the unused components in M1);
      delete `pnpm-lock.yaml`; rename the package; turn `ignoreBuildErrors` off. **R#29, R#30**
- [ ] One Compose stack for everyone: Postgres + backend + frontend, with a single bind-mounted
      `data/` directory holding the Postgres data dir and `uploads/`, a Postgres healthcheck, and
      `.env` for the password. Document `DATA_DIR`. One command: `docker compose up`.
- [ ] `make dev` / `uv run` scripts so local dev is `uv sync && make dev` (Python 3.11 pinned via
      `.python-version`). **R#31**
- [x] Disk thumbnail cache for `/preview`, keyed by image id + width + source mtime under
      `static/cache/`. *(pulled forward into M1: the frame grid needs it. It moves to `data/cache/`
      with the single-`DATA_DIR` compose stack above; async file IO is still open.)* **R#19**
- [ ] Pagination on `/api/images` and server-side search (`q`, `film_id`, `camera_id`, date range). **R#20**
- [ ] **Import by reference ("link mode")**: register a folder tree (roll = subfolder) without
      copying files; NegArchive stores the path and hash. Lets NegPy library roots, an Immich
      external library and NegArchive share one copy of every scan. Store `original_filename`,
      `source_path`, `content_hash` and `storage_mode` (`managed` | `linked`) per image.
- [ ] **Watch folder**: poll a scanner output directory; new subfolder → new roll draft; new file
      → new frame. (Same idea as NegPy's Hot Folder, but headless.)
- [ ] **Backup / restore**: a `backup` script that runs `pg_dump` and zips it with `uploads/`;
      `GET /api/export` → zip of a JSON dump of all tables plus files (format-independent, for
      longevity); `POST /api/import`. Also a CSV dump of rolls for spreadsheets. Document the restore.
- [ ] PWA manifest + service worker so the UI installs on phone/tablet and the shell loads with the
      backend unreachable (read-only cached lists). Scope: the "at the shelf" lookup, not a photo
      app; mobile photo backup and browsing are Immich's job.
- [ ] LAN discoverability: print the LAN URL and a QR code at startup and in the UI footer.
- [ ] Optional single shared password (env var) for when the LAN is not trusted. **R#26**
- [ ] Tests: pytest against Postgres (testcontainers or a Compose service; the probe script in
      the review is a starting point) and GitHub Actions with a Postgres service container.
      *(The Playwright smoke test landed in M1: `frontend/e2e/smoke.mjs`, `npm run e2e`.)* **R#33**

## M4 — Paper ↔ virtual (physical archive features)

- [ ] **Storage hierarchy** instead of two free-text fields: `Location` (building/room) →
      `Container` (binder/box, with a printable label) → `Sleeve` (page, with slots) → strip and
      position. A roll lives in one container/sleeve; a "Where is it?" panel on the roll page.
- [ ] **Archive serial scheme** with auto-numbering (`YYYY-NNNN` or a configurable prefix),
      unique, shown everywhere, searchable, encoded in every QR.
- [ ] **Label printing**: PDF for sleeve/binder/box labels (Avery/Brother sizes) with serial,
      title, date range, film, and a QR to `/films/{id}` (or `/s/{serial}` short route).
- [ ] **Printable contact sheet / index print**: extend the existing generator with frame numbers,
      serial, date, camera/film, and the QR; A4/Letter layout; PDF output.
- [ ] **Binder index sheet**: a printable table of contents per container.
- [ ] **Strip / position from frame number**: derive "strip 3, frame 2" (configurable frames per
      strip: 6 for 35mm, 3–4 for 120) and show it on the image page and in the grid.
- [ ] **Paper twin capture**: mobile-friendly page to photograph the physical contact print or the
      sleeve and attach it as `contact_sheet` (or a new `paper_scan` type) with an OCR/handwritten
      notes field.
- [ ] **Scan a QR to open the record**: `/s/{serial}` route; camera-based QR reader in the PWA
      for quick lookups at the shelf.
- [ ] **Darkroom prints as assets**: a `print` asset type with paper stock, size, grade/filter,
      exposure notes, and its own storage location; link to the source frame.
- [ ] **Loan / status log** per roll and per print: on shelf, lent to, at the lab, missing.
- [ ] **Roll lifecycle**: `loaded → shot → developed → scanned → archived` with dates
      (development date, lab, process) so unscanned rolls are visible in the archive too.

## M5 — NegPy integration (file-based, no NegPy code in NegArchive)

See [NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md) for formats and field mappings.

- [ ] **Ingest NegPy exports**: read EXIF (`Make`, `Model`, `LensModel`, `ISOSpeedRatings`,
      `DateTimeOriginal`) and the XMP `negpy:` namespace (`CaptureRoll`, `CaptureFrame`,
      `CaptureFilmStock`, …) on upload; match `CaptureRoll` to `archive_serial` or title; fill
      frame number, capture date, camera/lens/film automatically.
- [ ] **Gear sync (NegArchive → NegPy)**: write `cameras.json`, `lenses.json`, `film_stocks.json`
      in NegPy's camelCase schema into a target `gear/` directory (env `NEGPY_USER_DIR` or a path
      setting); stable ids `na-cam-<id>`; merge-safe (never overwrite ids not ours).
- [ ] **Roll handoff (NegArchive → NegPy)**: "Open in NegPy" prepares a roll folder (copy or link)
      plus a metadata preset JSON under `presets/metadata/<serial>.json` prefilled with camera,
      lens, film, `capture_roll = serial`, capture date; the user adds the folder as a NegPy
      library root or Hot Folder.
- [ ] **Sidecar awareness**: accept `.negpy` sidecars on upload and in link mode; show
      "edited in NegPy" and the recipe summary on the image page; keep sidecars next to files on
      export/backup.
- [ ] **Content hash compatible with NegPy** (reimplemented, documented algorithm: SHA-256 of
      size + 1 MiB head + 1 MiB tail + 16 × 256 KiB interior chunks) so a NegArchive record can
      be looked up in `edits.db` when both run on the same machine. Do not import NegPy code.
- [ ] **Filename preset**: publish a recommended NegPy export preset
      `{{ roll }}_{{ frame|pad(3) }}_{{ film }}` and parse it on import.
- [ ] **Upstream proposals to NegPy** (separate, optional, GPL): a physical-storage field group in
      `MetadataConfig` (building/container/sleeve/serial → XMP), and a headless export entry point.
      Frame both as "external sync", because NegPy's library deliberately has no index database.

## M6 — Immich connector (optional photo layer)

Immich stays optional: every feature below is behind an "Immich" settings section (base URL +
API key) and NegArchive works fully without it. Two services, two databases; never share
Immich's Postgres.

- [ ] **Shared files, not copies**: document pointing an Immich external library at NegArchive's
      uploads folder (or the M3 linked folders). Read-write mount so Immich can write sidecars.
- [ ] **XMP sidecars from NegArchive**: write `<file>.xmp` next to every frame with capture date,
      roll serial, frame number, camera, lens, film (same fields NegPy writes, so a NegPy export
      and a NegArchive frame look identical to Immich). Re-written on edit. This is also the
      sidecar work M5 needs.
- [ ] **Roll ↔ album sync** through the Immich API: one album per roll named by serial + title,
      tags `roll:<serial>`, `film:<name>`, `camera:<name>`, `lens:<name>`; store the Immich asset
      id on each frame (`image_assets.immich_asset_id`) after matching by path or content hash.
- [ ] **"Open in Immich"** on frames and rolls; "Open in NegArchive" the other way via the roll
      tag or album description link.
- [ ] **People from Immich**: read faces/people per asset from the API and expose a person filter
      in NegArchive; replaces the deleted DeepFace code.
- [ ] **Conflict rule**: NegArchive is authoritative for roll, frame, gear and date; Immich is
      authoritative for people, favourites and ratings. Never overwrite the other side's fields.
      Note the known Immich issue where in-app edits stop external XMP changes being re-read.
- [ ] Later, optional: an Immich workflow plugin (Wasm, alpha) that files a newly added asset into
      the right album by parsing the NegPy/NegArchive XMP, so the connector also runs inside Immich.

## M7 — Nice to have

- [ ] Map view from NegPy GPS/city metadata (or from Immich).
- [ ] Per-frame ratings/keep-reject imported from NegPy `file_marks`.
- [ ] Multi-user with roles (only if the archive ever leaves the LAN).
