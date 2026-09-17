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

## M3 — Offline-first and easy local use *(done)*

- [x] Remove `@vercel/analytics` and the Google font loaders; use a system font stack. **R#27, R#28**
      *(done in M1: they were in the way of the layout rework)*
- [x] Pin the remaining `"latest"` dependencies (4 of 5 went with the unused components in M1);
      delete `pnpm-lock.yaml`; rename the package to `negarchive-frontend`; turn
      `ignoreBuildErrors` off. `middlewareClientMaxBodySize` turned out to be set at the top
      level, where Next ignores it — bulk uploads were still capped at the 10 MB default. It is
      now `experimental.proxyClientMaxBodySize`, which is the Next 16 spelling. **R#29, R#30**
- [x] One Compose stack for everyone: Postgres + backend + frontend, a single bind-mounted
      `./data/` holding `postgres/`, `uploads/`, `catalog/`, `cache/` and `backups/`, healthchecks
      on `db` and `web`, the frontend waiting for `web` to be *healthy*, and `.env.example` with
      every variable. No named volumes: a volume you cannot see is one you forget to back up.
      One command: `docker compose up`.
- [x] `make up` / `make dev` / `make test` / `make backup` (plus `lint`, `typecheck`, `build`,
      `e2e`, `restore`); `make test` starts and removes its own throwaway Postgres. Python 3.11
      pinned via `.python-version`. **R#31**
- [x] Disk thumbnail cache for `/preview`, keyed by image id + width + source mtime. *(pulled
      forward into M1; M3 moved it under `DATA_DIR` with everything else. Async file IO is still
      open.)* **R#19**
- [x] Pagination and server-side search on `/api/films` (`q`, `camera_id`, `film_stock_id`,
      `from`, `to`, `limit`, `offset`) and `/api/images` (`film_id`, `type`, `q`, `unassigned`,
      `storage_mode`, `limit`, `offset`). Without `limit` both still answer with a bare array, so
      nothing written against M0/M1 breaks; with it they answer `{items, total, limit, offset,
      has_more}`. The roll list and the frames page render their first page on the server from the
      query string and "Load more" the rest. **R#20**
- [x] **Import by reference ("link mode")**: `POST /api/library/roots` registers a folder
      (validated against `LIBRARY_ROOTS_ALLOW`, empty by default so the feature is off), and a
      scan turns each subfolder into a roll draft and each file into a frame with
      `storage_mode='linked'`, `source_path`, `content_hash`, `original_filename` and a parsed
      frame number. Rescans are idempotent by path, a moved file is re-homed by hash, previews and
      downloads work, and nothing linked is ever written to or deleted.
- [x] **Watch folder**: an asyncio poller over the roots marked `watch`, every
      `WATCH_INTERVAL_SECONDS` (default 30, off when unset), with a toggle and a last-scan readout
      in Settings. Polling rather than inotify, because the interesting case is an SMB share.
- [x] **Backup / restore**: `scripts/backup.sh` (`pg_dump` + the managed files + a MANIFEST, into
      `data/backups/`, pruned to `BACKUP_KEEP`) and `scripts/restore.sh`; `GET /api/export` streams
      a ZIP of `export.json` (every table as plain JSON) plus the managed files; `POST /api/import`
      merges one back with a dry-run flag, id remapping and skip-by-content-hash;
      `GET /api/export/rolls.csv`. Restore is documented step by step in the README.
- [x] PWA manifest, generated icons and a hand-written service worker (no dependency): the shell,
      the roll list and the rolls you have visited are cached and readable offline, with an
      "offline" banner. Nothing that changes data is cached or replayed. Scope: the "at the shelf"
      lookup, not a photo app; mobile photo backup and browsing are Immich's job.
- [x] LAN discoverability: `GET /api/system/info` reports the LAN addresses and the UI URL, the
      backend logs them at startup, and the footer shows the URL with a QR code rendered
      server-side as SVG (`segno`). `NEGARCHIVE_PUBLIC_HOST` overrides the guess in Docker, where
      the container only sees its bridge address.
- [x] Optional single shared password, `NEGARCHIVE_PASSWORD`. Off by default; when set, everything
      but `/api/health`, `/api/system/info` and the login endpoint needs a token — `/static`
      included. The token is derived from the password, so a restart is not a logout. **R#26**
- [x] Tests: `tests/test_m3_*.py` against Postgres (86 new, 128 in total), and
      `.github/workflows/ci.yml` with a Postgres service container — ruff, an Alembic
      up/down/up round trip, pytest, eslint, `tsc`, `next build` and the Playwright smoke test,
      which now covers the PWA, the LAN footer, the settings page and pagination. **R#33**

Left for later, deliberately:

- Alembic autogenerate is **not** checked in CI (the roadmap asks for it under M2, which owns the
  baseline); CI runs the migrations up, down and up again instead.
- The service worker has no background sync queue, and should not have one: an edit that silently
  lands hours later is a good way to lose the link between paper and record.
- `GET /api/images/{id}/preview` still does blocking file IO on the event loop (**R#19**).

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
