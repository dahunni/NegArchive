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

---

## M0 — Stop the bleeding (bugs that break shipped workflows)

- [ ] Fix filmstock create/update on Postgres: change `expired` to a Boolean column via the first
      Alembic migration (see M2), or coerce to int in the API as a stopgap. **R#1**
- [ ] Proxy `/static/*` through Next (add a rewrite) and make *every* browser URL go through one
      helper in `lib/api.ts`; delete the two local `API_BASE` constants. **R#2, R#3**
- [ ] Remove the six legacy HTML routers and `Jinja2`; keep only `routers/api.py`. **R#4**
- [ ] Make `image_assets.film_roll_id` nullable (migration) or make the UI require a film. **R#5, R#12**
- [ ] Return the full object from `PUT /api/lenses/{id}` and `PUT /api/filmstocks/{id}`. **R#6**
- [ ] Map the "None" select value to `null` in `film-form.tsx` before submit; also add a one-off
      data fix that nulls existing `"None"` strings. **R#8**
- [ ] Add `.dockerignore`; fix README ports; add a Postgres healthcheck to `depends_on`. **R#25**
- [ ] Render `expired` as boolean in the API and fix the `{0 && …}` render. **R#22**

## M1 — UI rework (high priority)

The current UI is a generic CRUD scaffold (one table or card grid per entity, a separate page
for every form, icon-only actions, no thumbnails on the roll list, no lightbox, no drag-and-drop,
navigation that overflows on phones). Rework it around the real workflow: **a roll is the unit of
work**, and most sessions are "new roll → dump scans → number and annotate frames → find it later".

- [ ] **Information architecture**: Rolls as the home page with thumbnail strip, film, camera,
      date range, frame count and storage location per row; catalog (cameras, lenses, film stocks)
      demoted to a single "Gear" section; Search folded into the roll list as filters, not a page.
- [ ] **Roll page as a workspace**: contact sheet on top, frames in a grid with frame number and
      date visible, inline edit of frame number and notes, keyboard navigation, multi-select for
      bulk delete / reassign / set date, drag-and-drop upload zone that accepts files and ZIPs.
- [ ] **Lightbox / frame viewer** with previous/next, zoom, download, and the metadata panel beside
      it instead of a separate detail page and a separate edit page.
- [ ] **Forms as dialogs or side panels** with proper validation messages from the API, not
      "Failed to save"; keep the user on the page after saving.
- [ ] **New roll wizard**: title, gear, film, dates, storage location, then straight into the
      upload zone; remember the last used camera and film.
- [ ] **Mobile / tablet layout**: collapsible navigation, one-column roll list, touch-sized targets;
      this is the "at the shelf" view for M4's QR lookup.
- [ ] **Consistent empty, loading and error states**; skeletons for lists; toasts only for
      background results.
- [ ] **Visual pass**: dark mode toggle (the theme provider already exists), typography scale,
      real thumbnails everywhere (needs the M3 thumbnail cache), image aspect ratio preserved
      instead of square crops for 35mm frames.
- [ ] Remove unused shadcn components from `components/ui` after the rework; keep the bundle lean.

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
      **R#16, R#17**
- [ ] File lifecycle: delete files with records (with a "keep files" option), an orphan sweep
      endpoint, and a `delete_file` checkbox in the UI. **R#9**
- [ ] Extension + MIME allowlist (`jpg jpeg png tif tiff webp dng`), size limit, never serve
      uploads as `text/html`. **R#18**
- [ ] Faces: either delete `services/face.py`, `Face`, `Person` and the DeepFace requirement, or
      wire it in behind an optional extra with a background job. Decide; do not keep dead 2 GB. **R#10, R#15**
- [ ] Filmstock `kind` select lists the enum, not "kinds already used". Add `manufacturer`,
      `format` (35mm/120/4x5…) to filmstocks; add `format` to rolls. **R#21** (also needed for NegPy gear sync)

## M3 — Offline-first and easy local use

- [ ] Remove `@vercel/analytics` and the Google font loaders; use a system font stack. **R#27, R#28**
- [ ] Pin every `"latest"` dependency; delete `pnpm-lock.yaml`; rename the package; turn
      `ignoreBuildErrors` off. **R#29, R#30**
- [ ] One Compose stack for everyone: Postgres + backend + frontend, with a single bind-mounted
      `data/` directory holding the Postgres data dir and `uploads/`, a Postgres healthcheck, and
      `.env` for the password. Document `DATA_DIR`. One command: `docker compose up`.
- [ ] `make dev` / `uv run` scripts so local dev is `uv sync && make dev` (Python 3.11 pinned via
      `.python-version`). **R#31**
- [ ] Disk thumbnail cache for `/preview` (`data/cache/<image_id>_<width>.jpg`, invalidated on
      file change) and async file IO. **R#19**
- [ ] Pagination on `/api/images` and server-side search (`q`, `film_id`, `camera_id`, date range). **R#20**
- [ ] **Import by reference ("link mode")**: register a folder tree (roll = subfolder) without
      copying files; NegArchive stores the path and hash. Lets NegPy library roots and NegArchive
      share one copy of every scan.
- [ ] **Watch folder**: poll a scanner output directory; new subfolder → new roll draft; new file
      → new frame. (Same idea as NegPy's Hot Folder, but headless.)
- [ ] **Backup / restore**: a `backup` script that runs `pg_dump` and zips it with `uploads/`;
      `GET /api/export` → zip of a JSON dump of all tables plus files (format-independent, for
      longevity); `POST /api/import`. Also a CSV dump of rolls for spreadsheets. Document the restore.
- [ ] PWA manifest + service worker so the UI installs on phone/tablet and the shell loads with the
      backend unreachable (read-only cached lists, queued uploads later).
- [ ] LAN discoverability: print the LAN URL and a QR code at startup and in the UI footer.
- [ ] Optional single shared password (env var) for when the LAN is not trusted. **R#26**
- [ ] Tests: pytest against Postgres (testcontainers or a Compose service; the probe script in
      the review is a starting point), Playwright smoke test for the 6 main pages, GitHub Actions
      with a Postgres service container. **R#33**

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

## M6 — Nice to have

- [ ] Map view from NegPy GPS/city metadata.
- [ ] Per-frame ratings/keep-reject imported from NegPy `file_marks`.
- [ ] Multi-user with roles (only if the archive ever leaves the LAN).
- [ ] Face/person tagging revived as an optional, on-demand job.
