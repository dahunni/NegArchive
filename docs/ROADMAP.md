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

## M2 — Archive integrity (data model) *(done)*

The data model is the archive's memory, and it was leaking: filenames were thrown away on
upload, gear was referenced by a string that a rename silently broke, deleting a roll left its
files on disk forever, the schema was maintained by guarded `ALTER TABLE`s in a startup hook,
and "not found" was an HTTP 200. All of that is fixed here.

- [x] **Postgres only.** `DATABASE_URL` is required and must be a Postgres URL — the backend
      stops at startup with an explanation otherwise. The SQLite branches
      (`check_same_thread`, the `Text` variant on the JSON column) are gone, the columns are
      native `Boolean`/`Date`, and the tests refuse a non-Postgres URL. Local dev is
      `docker compose up -d db` plus uvicorn on the host.
      `scripts/migrate_sqlite_to_pg.py` copies an existing `negarchive.db` across, keeping ids
      and resolving gear names to the new foreign keys.
- [x] `original_filename` is stored on every upload path (single, bulk, ZIP) and `frame_number`
      is parsed from it when the client sends none (`Roll12_007.tif`, `NEG-2024-011_007.jpg`,
      `_Frame007`, `007.jpg`, `img_0007`, NegPy's `{roll}_{frame}`). Frames sort by
      `frame_number NULLS LAST, id` everywhere, including the contact sheet's input, and the
      filename is in the API, in the viewer's panel and on the download. **R#7, R#24**
- [x] Gear is referenced by id: `film_rolls.camera_id`, `lens_id`, `film_stock_id`, nullable,
      `ON DELETE SET NULL`, backfilled from the name columns in the migration. The string
      columns stay for one release and now mirror the catalog entry's current name, so a
      rename reaches every roll. The API takes ids or names; deleting gear that is still in
      use is a 409 with the count unless `?force=true`. **R#14**
- [x] Alembic owns the schema: `0001_baseline` reproduces the pre-M2 schema (and no-ops on a
      database that already has it), `0002_m2_archive_integrity` carries the changes above.
      `app/main.py` runs `alembic upgrade head` at startup instead of the `ALTER TABLE` hook,
      and `create_all` is gone. Seeding only happens while a catalog table is empty, or on
      `POST /api/seed`, so a deleted Nikon F5 stays deleted. **R#11, R#23**
- [x] Pydantic request and response models for every endpoint, real status codes
      (404 missing, 400/422 invalid, 409 duplicate or in use, 413 too large, 415 wrong type)
      and one error body everywhere: `{"error": {"code", "message", "field"}}`. `lib/api.ts`
      puts the message on the field the API named. **R#16, R#17**
- [x] File lifecycle: deleting an image or a roll deletes the managed files too, with
      `?keep_files=true` (and a checkbox in every delete dialog) to opt out;
      `POST /api/maintenance/sweep_orphans` lists files with no record and records with no
      file, dry run unless `?apply=true`. A `storage_mode = 'linked'` row is never deleted —
      the column ships here so M3's import-by-reference can rely on it. **R#9**
- [x] Uploads are limited to `jpg jpeg png tif tiff webp dng` by extension *and* by a
      magic-byte sniff, with a configurable `MAX_UPLOAD_MB` (default 512); nothing under
      `/static/uploads` can come back as `text/html`, and everything is `nosniff`. **R#18**
- [x] Faces are gone: `services/face.py`, the `Face` and `Person` models and their tables, and
      the `deepface` and `scikit-learn` requirements. `opencv-python-headless` stays, the
      preview fallback still decodes 16-bit TIFFs with it. The backend image went from about
      2 GB to 0.28 GB. People detection comes from Immich (M6). **R#10, R#15**
- [x] The filmstock `kind` select lists the enum; film stocks gained `manufacturer` and
      `format`, rolls gained `format` (`35mm`, `120`, `4x5`, `8x10`, `other`). **R#21**

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

Specification with the owner's decisions: [M4_PAPER.md](M4_PAPER.md). Depends on M2 and M3.

- [ ] **Serial** `NEG-YYYY-NNN`: auto-assigned, unique, immutable once printed, backfill for
      existing rolls, `/s/{serial}` route, `serial:` search prefix, `/` focuses search.
- [ ] **Location tree**: `locations` (building/room/shelf/row/box/binder/envelope/sleeve),
      `sleeve_layouts` (PrintFile 7×6 default, 7×5, 120 variants), `film_rolls.location_id` +
      `strips` override, `location_moves` history; migrate `building`/`folder` into nodes and drop
      them. Binder extras (capacity, page order, missing pages), sleeve holds exactly one roll.
- [ ] **Strip / position** from the roll's strips: on frame cards, in the viewer, and as the
      contact sheet grid.
- [ ] **Roll lifecycle** loaded → shot → at lab → back → scanned → sleeved with timestamps,
      "Load film" on a camera, automatic `scanned`/`sleeved`, home page work lists (in cameras, at
      the lab, to scan, to sleeve), status filter.
- [ ] **Codes**: `GET /api/codes/qr` and `/api/codes/code128` as SVG; QR = `{PUBLIC_BASE_URL}/s/{serial}`,
      Code128 = bare serial.
- [ ] **Printouts** as print-optimised pages with cut marks (browser "Save as PDF"): sleeve cover
      sheet (A4, grid mirrors the sleeve, frame numbers, header with all metadata + QR + Code128),
      binder spine label (50×200, 4/A4), small roll sticker (50×25, 20/A4), binder index, roll
      index card (A6, 4/A4), location tree sheet. One `print.css`; label sizes are settings.
- [ ] **Print queue**: rolls never printed or moved since last print; batch print; `label_printed_at`.
- [ ] **Scan page** in the PWA (QR + Code128 via `BarcodeDetector`, `jsQR` fallback) and a
      **location browser** with counts, page order, discrepancies and per-node QR.
- [ ] **Move roll** action (single and bulk) with next-free-page suggestion.
- [ ] Tests for serial allocation, strip math, location constraints, lifecycle transitions; a
      Playwright check that each printout renders at its paper size.

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

- [ ] Paper twin: photograph the DM index print or sleeve page as the roll's contact sheet.
- [ ] Darkroom prints as assets with paper, size, location; loan / status log.
- [ ] German printouts.
- [ ] Map view from NegPy GPS/city metadata (or from Immich).
- [ ] Per-frame ratings/keep-reject imported from NegPy `file_marks`.
- [ ] Multi-user with roles (only if the archive ever leaves the LAN).
