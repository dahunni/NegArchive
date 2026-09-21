# Changelog

Every release, newest first. The archive reads this file itself: `GET /api/system/version`
serves it, the footer shows the version, and the first visit after an update opens the entries
you have not seen yet. Keep the format — `## [version] - YYYY-MM-DD`, then `### Added`,
`### Changed`, `### Fixed` or `### Removed` with one `-` bullet per line — because that is what
`app/services/changelog.py` parses.

## [0.11.1] - 2026-09-21

### Fixed
- **The sleeve cover sheet uses the whole page, and an upright frame is no longer a
  thumbnail.** Every cell on the sheet was locked to a landscape 3:2 box, so a frame shot
  upright was drawn at less than half the width of the one beside it, matted against
  near-black — on a roll where half the frames are portrait it read as a picture that had
  failed to load. The strips now take the height the header leaves instead of stopping a third
  of the way up the A4, a cell grows to square, and the matting is the paper rather than a
  black bar. An upright frame comes off the printer at a little over twice the area.
- A sleeve cell asks for a preview wide enough to print it. The width was fixed at 480 px,
  which is right for a 35mm roll at six frames to a strip and soft on a 120 roll at three,
  whose cells are twice as wide; it now follows the cell.

## [0.11.0] - 2026-09-21

### Changed
- **A NegPy export is a rendition of a frame, not a second frame.** A roll that has been
  through NegPy holds two files per frame — the raw negative the scanner made and the positive
  NegPy exported from it — and the archive was counting both. A 33-frame roll listed 66, every
  frame appeared twice in every grid, and re-exporting added a third file rather than replacing
  the second. The negative is now *the frame* and the export hangs off it: one frame, counted
  once, everywhere. The export keeps its own file, hash, filename and download link, and the
  roll page's contrast button switches between them — "NegPy's export" and "the negative as
  scanned".
- **A frame shows the export where there is one.** The positive view used to be this backend's
  approximation of NegPy's tone controls in every case. It still is when there is nothing
  better, and still says so — but a real export beats an approximation of one, and that is what
  cover sheets, index cards, the sleeve grid, the roll list and the viewer now show.
- **Re-exporting a frame replaces its export.** The newest export becomes the frame's
  rendition, the previous record is retired and its file deleted — only ever a file NegArchive
  owns; a linked file on your share is unlinked, never touched. Notes typed on the old export
  are carried forward.
- Searching, renumbering, contact sheets and the handoff to NegPy all see frames, not files.
  Handing NegPy back its own exports would have had it converting a positive a second time.

### Added
- `derived_from_id` on a frame's file, and `rendition` on every frame the API answers with.
  `GET /api/images?type=scan&renditions=true` lists the exports too, for a maintenance sweep.
- `scripts/repair_negpy_archive.py` (was `repair_misfiled_rolls.py`) gains a third pass that
  pairs the exports an existing archive already holds with their negatives. Its dry run now
  does the whole repair and rolls it back, so the preview is the real thing rather than a guess
  at what each pass would find.

## [0.10.1] - 2026-09-21

### Fixed
- **A roll exported from NegPy no longer arrives as 33 copies of frame 2026.** NegPy's export
  templating slugs the roll name, so the serial `NEG-2026-0001` comes back in the filename as
  `NEG_2026_0001_001.jpg` — and the preset parser, which reads `<roll>_<frame>_<film>` by shape,
  took the year for the frame and `0001_001` for the film. A part of the name only counts as a
  film now if it has a letter in it, so the name falls through to the `<roll>_<frame>` rule and
  the frame is 1. *Renumber → "Read the filenames again"* fixes a roll that already came in
  wrong, one roll at a time, with the plan on screen.
- **A scanner pointed straight at the watch folder no longer puts the roll in the archive
  twice.** NegPy's scan mode, writing `NEG-2026-0001_Frame001.ARW` into the watch folder with no
  subfolder around it, made the archive invent a roll named after the *folder* — "rolls" — while
  the real roll sat beside it, empty. When a folder's own name says nothing about a serial, the
  filenames are read instead, and a file naming a roll the archive already has goes to that
  roll. Two rolls loose in one folder now stay two rolls; a file naming nothing known still goes
  to the folder's roll, as before. The watch folder itself is never claimed as one roll's folder.
- A serial matches whichever way it is spelled: `NEG_2026_0001`, `NEG-2026-0001` and
  `NEG-2026-1` are one roll, so a folder or file that lost its padding or its hyphens still
  finds the record it belongs to.
- **Filing scans into the right folder now sticks.** Moving a file under a folder named with a
  roll's serial puts the frame on that roll. Re-homing a moved file only ever filled in an
  *empty* roll before, so tidying a misfiled roll into the right folder by hand changed nothing
  and the archive stayed wrong. A move between two ordinary folders still leaves the roll alone
  — only a serial re-files a frame.
- **Anything printed shows the positive, not the negative.** A roll scanned through NegPy has
  two files per frame — the raw negative and the positive exported from it — and cover sheets,
  index cards, the sleeve grid and the roll list's thumbnails were all showing the raw, because
  it happened to arrive first. They show the exported positive where there is one, one image
  per frame, so 36 thumbnails mean 36 frames. Both files stay in the archive and the roll page
  still shows both. A roll with no positives looks exactly as it did.
- A negative whose positive is standing in for it on the sleeve grid is no longer listed under
  "not on the sleeve grid" — which had been saying it about every frame of a NegPy roll.

### Added
- `scripts/repair_misfiled_rolls.py` puts an archive that already has the damage back together:
  it moves frames onto the roll their filenames name, removes the invented roll it leaves empty
  (never one you have typed anything into), and re-reads every frame number from its filename.
  A dry run by default; `--apply` writes.

## [0.10.0] - 2026-09-21

### Added
- **Search everything from anywhere.** `⌘K` (or `Ctrl+K`, or the search button in the header)
  opens a palette that finds rolls, frames, cameras, lenses, film stocks and storage locations in
  one go, ranked by how well they match, with the arrow keys and `Enter` to open a result.
- **Better matching.** A search finds a roll by anything on it or in it: title, notes, serial,
  folder, building, gear, film, developer, the year it was shot, where it is filed, and the
  notes and filenames of its frames. Small typos are forgiven (`harbor` finds "Harbour"), and
  `camera:`, `lens:`, `film:`, `year:`, `status:`, `location:` and `serial:` narrow a search to
  one field. The filter bar on the roll list uses the same matching.
- **The version on screen.** The footer shows which NegArchive is running; Settings → About has
  the build details and this changelog.
- **What's new after an update.** The first page load after `docker compose pull` opens the
  changelog entries you have not seen yet, and says when the page you have open was built for
  an older version than the archive, so a reload is one click away.
- **Renumber the frames of a roll in one go.** *Renumber* on the roll page (or on a selection
  in the bulk bar) numbers the frames in their current order from any start, reverses the
  order for a roll scanned tail first, shifts every number for a scanner that counted from 0,
  or reads the numbers out of the filenames again. The dialog shows every old → new number,
  and warns about duplicates, before anything is written.

### Changed
- The frames page takes `?q=` in the URL, so "all frames matching …" from the palette is a link.
- The service worker no longer caches the version endpoint, so an update is noticed straight
  away rather than after the cache expires.

## [0.9.1] - 2026-09-21

### Fixed
- The 2026-09-20 review: a hundred small things across the API, the UI and the printouts, fixed
  in one release. The write-up is in `docs/REVIEW.md`.

## [0.9.0] - 2026-09-20

### Added
- Live mode on the archive's own share: NegPy on a laptop and NegArchive on the server work in
  the same folder, and an edit in NegPy shows up in the archive on its own.
- Two address overrides, one for the links and QR codes the archive prints and one for the
  share it serves, for a box that is reached through a different name than it sees itself.

## [0.8.0] - 2026-09-20

### Added
- The archive serves its own network share, so a scanner or NegPy can drop files straight
  into it, and the inbox folder empties itself into rolls.

## [0.7.1] - 2026-09-20

### Fixed
- A frame that is already a positive — a NegPy export, a scan of a print — is shown as it is
  and never printed a second time.
- The published images are built on native runners per architecture, so the arm64 build no
  longer hangs under emulation.

## [0.7.0] - 2026-09-20

### Added
- Camera scanning with NegPy: the raws from NegPy's scan mode go straight into the archive,
  previews are rendered from the raw, and the share mounts on the archive side.

## [0.6.0] - 2026-09-18

### Added
- The network share (M6): mount the folder NegPy works in, watch it, and import by reference.
