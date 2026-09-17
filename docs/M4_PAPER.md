# M4 — Paper ↔ virtual: specification

Decided with the owner on 2026-09-17. This is the reference for the M4 checklist in
[ROADMAP.md](ROADMAP.md). Depends on M2 (gear foreign keys, validation, Alembic) and M3
(settings table, PWA shell, `PUBLIC_BASE_URL`, QR generation via `segno`).

## Facts about the real archive

- 35mm only, strips of 6, one roll per sleeve page. PrintFile pages are the target (7 rows × 6).
  Some older sleeves hold only 5 per row, so a few rolls have one strip doubled up; the owner is
  switching back to PrintFile but the old pages stay as they are.
- Rolls come back from the lab (DM: cheap development plus prints) as an envelope with cut strips
  and prints. **Prints are ignored** by the app. The envelope is only a temporary container until
  the strips are sleeved.
- Physical layout the owner wants to browse: **building → shelf → row → binder → sleeve**, with
  binders and sleeves as the two node kinds that carry extra behaviour.
- Printing is on a normal printer, plain A4 paper, cut by hand. No adhesive label stock.
- Lookup at the shelf: QR scanned with the phone; at the PC: a 1D barcode scanner typing the
  serial. Also typing the serial and browsing by location.
- Full roll lifecycle: loaded → shot → at lab → back → scanned → sleeved, with dates.
- Language of printouts: English.

## Serial

`NEG-YYYY-NNN`: fixed prefix (configurable, default `NEG`), four-digit year, per-year counter
padded to three digits (grows to four automatically). Assigned when a roll is created, unique,
immutable once a label has been printed (the API refuses changes with 409 unless `?force=true`).
Existing rolls without a serial get one from a backfill command in creation order.

- `GET /s/{serial}` (frontend route) opens the roll; `GET /api/rolls/by-serial/{serial}`.
- QR content: `{PUBLIC_BASE_URL}/s/{serial}` so a phone camera opens the roll. The in-app
  scanner and the search box also accept a bare serial or that URL.
- Code128 content: the bare serial, so a USB/Bluetooth barcode scanner typing into the focused
  search box opens the roll with Enter. Global shortcut `/` focuses search from any page.

## Location model

One tree table, any depth:

```
locations(id, parent_id, kind, name, code, sort_order, notes,
          sleeve_layout_id NULL, capacity NULL, created_at)
kind ∈ { building, room, shelf, row, box, binder, envelope, sleeve, other }
```

- `code` is the short printable identifier (`A`, `S2`, `R1`, `B03`, `P12`); the full **path
  string** (`Archive A / Shelf 2 / Row 1 / Binder 03 / Page 12`) is derived and shown on every
  label and printout.
- **Binder** extras: capacity in pages, ordered child sleeves (page numbers), spine label,
  index printout, year range and serial range derived from its rolls, "what is missing"
  (pages whose roll is not `sleeved`).
- **Sleeve** extras: a `sleeve_layout` (rows × frames per row), holds **one roll**; page number =
  `sort_order` inside the binder. Moving a roll to a sleeve that already holds one is refused.
- **Envelope / box**: hold several rolls loosely (no page geometry); the DM envelope is an
  `envelope` created automatically when a roll goes to `back` and dissolved when it is sleeved.

```
sleeve_layouts(id, name, rows, frames_per_row, film_format)
seed: "PrintFile 35-7B" 7×6 (default), "5 per row" 7×5, "120 (3 per row)" 4×3, "120 (4 per row)" 3×4
```

Roll fields added: `location_id` (FK → locations, nullable), `strips` (JSON list of strip
lengths overriding the layout, e.g. `[5,5,5,5,5,5,6]` for a doubled-up roll; null = layout
default), `label_printed_at`.

`location_moves(id, roll_id, from_location_id, to_location_id, moved_at, note)` is appended on
every move; the roll page shows the history.

The old free-text `building`, `folder` and `archive_serial` columns: `archive_serial` becomes the
serial (validated to the pattern, or backfilled), `building`/`folder` are migrated into a
`building` node and a `binder` node under it by name where possible, then dropped.

## Strip and position

For a roll with strips `[6,6,6,6,6,6]` frame 14 is strip 3, position 2. Shown on the frame
card, in the viewer side panel ("Strip 3 · Pos 2 · Page 12 · Binder 03") and as the row/column
of the contact sheet grid. Frames without a number are listed after the grid, not placed.

## Roll lifecycle

`status ∈ { loaded, shot, at_lab, back, scanned, sleeved }` with one timestamp per step
(`loaded_at, shot_at, lab_sent_at, lab_back_at, scanned_at, sleeved_at`) and a `loaded_camera_id`.

- Creating a roll from the camera's "Load film" action sets `loaded` and blocks loading a second
  roll into the same camera until it is `shot`.
- `scanned` is set automatically on the first scan upload or link; `sleeved` on the first move
  into a `sleeve` node. Every step can be set by hand; steps can be skipped.
- Work lists on the home page: **In cameras**, **At the lab**, **To scan**, **To sleeve**. Rolls
  list filter by status. Unscanned rolls stay visible everywhere (they were invisible before M1).

## Printouts (A4, plain paper, English)

All printouts are print-optimised Next.js pages (`@media print`, exact mm sizes, cut marks) so
the browser's "Save as PDF" is the PDF export; no server-side PDF library. QR and Code128 are
SVGs from `GET /api/codes/qr?text=` and `GET /api/codes/code128?text=` (`segno`,
`python-barcode`). Every printout is reachable from a **Print** menu on its object and from a
**Print queue** page that collects rolls with `label_printed_at IS NULL` or moved since the last
print.

1. **Sleeve cover sheet** (A4 portrait, one per roll): the sheet that sits in front of the
   sleeve page. Header: serial (large), title, shoot dates, camera, lens, film, ISO, location path,
   status, notes (three lines), QR (URL) and Code128 (serial). Body: a grid that **mirrors the
   sleeve** using the roll's strips (rows = strips, cells = frames), each cell a thumbnail with the
   frame number under it, empty dashed cells for frames without a scan, so the paper lines up with
   the negatives behind it. Footer: printed date, app URL.
2. **Binder spine label** (50 × 200 mm, four per A4 with cut lines): binder code and name,
   location path above it, year range, number of rolls, serial range, QR to the binder page.
3. **Small roll sticker** (50 × 25 mm, 20 per A4 with cut lines): serial, title (truncated),
   date, film, Code128 and a small QR. For envelopes and loose sleeves.
4. **Binder index** (A4, as many pages as needed): table of pages → serial, title, dates, film,
   camera, status, frame count; missing pages flagged. Header with binder path and QR.
5. **Roll index card** (A6, four per A4): metadata, location path, status timeline, QR +
   Code128, mini contact sheet (all frames, no numbers).
6. **Location tree printout** (A4): the whole hierarchy with codes, for the shelf door.

Layout constants (frame cell size, margins, fonts) live in one `print.css`; sizes for the spine
label and sticker are settings so other paper can be used later.

## Lookup and browse

- **Scan page** in the PWA: camera view using `BarcodeDetector` where available (QR + Code128),
  `jsQR` fallback; result opens `/s/{serial}` or the location page for a location QR. Manual
  entry field underneath.
- **Location browser** `/locations`: tree with counts, click into a binder to see its pages in
  order with the roll's cover thumbnail, serial and status; empty pages and "roll says sleeved
  here but another roll claims the page" discrepancies are highlighted. Each node has a QR.
- **Move roll** action (roll page and bulk bar): pick a target sleeve (next free page in a binder
  is the default suggestion), writes a `location_moves` row, marks the roll for reprint.
- Search understands `serial:`, `status:`, `location:` prefixes in addition to free text.

## Out of scope for M4 (moved to M7)

- Photographing the DM index print as a "paper twin" (owner ignores prints for now).
- Darkroom prints as assets and loan tracking.
- German printouts (English is fine).

## Acceptance

- A new roll gets `NEG-2026-001`; its cover sheet prints on A4 with a 6 × 6 grid matching a
  PrintFile page; scanning the QR with a phone opens the roll; a Code128 scanner typing the serial
  into the search box opens it on the PC.
- A roll with strips `[5,5,5,5,5,5,6]` prints a 7-row sheet and the viewer shows strip/position
  from that layout.
- Browsing Archive A → Shelf 2 → Row 1 → Binder 03 lists pages 1–n with the right rolls and
  flags the missing page.
- The home page shows rolls in cameras, at the lab, to scan and to sleeve.
