# NegPy ↔ NegArchive integration

Findings from reading NegPy `0.59.0` source (github.com/marcinz606/NegPy, GPL-3.0,
Python ≥ 3.13, PyQt6 + WebGPU). Paths are NegPy repo paths.

> **This document assumes both programs can see the same files.** They usually cannot — NegArchive
> is a container on a server and NegPy is a desktop app on a laptop. [NEGPY_LIVE.md](NEGPY_LIVE.md)
> (M6) is how that is closed: a network share the container mounts from Settings, and a one-button
> setup that makes the exchange below happen by itself.

## What NegPy is and is not

| NegPy has | NegPy does not have |
|-----------|---------------------|
| Gear library (cameras, lenses, film stocks, dev processes, scan setups) as **JSON files** under `<user dir>/gear/` (`negpy/services/assets/gear.py`), bundled defaults in repo `gear/` | A **CLI**, `__main__`, `[project.scripts]`, or any headless batch converter (`desktop.py` is the only entry point) |
| Per-frame metadata (`MetadataConfig`, `negpy/features/metadata/models.py`) incl. **`capture_roll`, `capture_frame`**, capture date, GPS/city/state/country | A **plugin system, HTTP/IPC, URL scheme** or importable API meant for third parties |
| Edits in `<user dir>/edits.db`, table `file_settings(file_hash, settings_json, file_path)`; optional **`.negpy` JSON sidecars** next to sources (`negpy/services/assets/sidecar.py`) | A **physical storage location** field (building / binder / sleeve / serial) |
| **XMP on export** in namespace `https://negpy.app/ns/1.0/` (`negpy:CaptureRoll`, `CaptureFrame`, `CaptureFilmStock`, `CaptureCameraMake/Model`, `CaptureLensMake/Model`, `Developer`, …) plus standard EXIF `Make`, `Model`, `LensModel`, `ISOSpeedRatings`, `DateTimeOriginal`, GPS (`negpy/features/metadata/writer.py`, `xmp.py`) | A **roll/catalog index database**. Its library is "the filesystem: roots are folders on disk, and a search is a walk. There is no index database." (`negpy/services/assets/library.py`) |
| Filename templating with `{{ roll }}`, `{{ frame\|pad(3) }}`, `{{ film }}`, `{{ camera }}`, `{{ capture_date }}` (`negpy/services/export/templating.py`, `docs/TEMPLATING.md`) | PyPI distribution (releases are AppImage/DMG/EXE via PyInstaller) |
| Hot Folder (GUI poll of a directory for new files), `NEGPY_USER_DIR` env var to relocate all data | Import/export UI for the gear library (the JSON files *are* the interface) |
| Contact sheet export with TOML layouts (`negpy/services/export/contact_sheet.py`) | |
| Content hash: SHA-256 of decimal size + first 1 MiB + last 1 MiB + 16 evenly spaced 256 KiB interior chunks (`negpy/kernel/image/logic.py::calculate_file_hash`) | |

## Which direction?

**NegArchive consumes and feeds NegPy through files. Do not build the archive into NegPy, and do
not embed NegPy in NegArchive.**

Reasons:

- NegPy's maintainer documents the decision that the library has no index database. A catalog of
  rolls, sleeves and buildings is exactly that, so a PR adding it works against the design and
  would have to pass a strict contribution gate (Python 3.13, ruff + ty + pytest, frozen-dataclass
  configs with migrations, docs in the same change, UI factories only).
- NegPy has no headless entry point, so "run NegPy from the web app" means new upstream code and a
  server with Qt, wgpu, numba, rawpy and opencv installed.
- Licensing: NegPy is GPL-3, NegArchive is MIT. Exchanging files keeps them separate works.
  Importing even one NegPy module (for example the hash function) would make NegArchive a
  derivative. Reimplement the ~30-line hash instead.
- Everything NegArchive needs is already externalised by NegPy: gear as JSON, metadata as XMP/EXIF
  in every export, edits as `.negpy` sidecars, roll/frame in filenames.

## Field mapping

### Gear: NegArchive → NegPy `gear/*.json` (camelCase on disk)

| NegArchive | NegPy `cameras.json` | Note |
|---|---|---|
| `id` | `id` = `na-cam-<id>` | prefix keeps our ids out of NegPy's bundled `cam-…` space |
| `name` | `displayName`; split into `make` + `model` on first space if unambiguous | |
| `mount` | — | NegPy has no mount field; put it in `notes` |
| `notes` | `notes` | |

| NegArchive | NegPy `lenses.json` |
|---|---|
| `id` | `id` = `na-lens-<id>` |
| `name` | `displayName`, `lensModel` |
| `mount` | → `notes` (no field) |
| — | `focalLength`, `maxAperture`: parse from name (`50mm f/1.8`) when possible |

| NegArchive | NegPy `film_stocks.json` |
|---|---|
| `id` | `id` = `na-film-<id>` |
| `name` | `displayName`; `manufacturer` + `stockName` need new NegArchive fields (M2) |
| `iso` | `iso` |
| `kind` `color` / `black_and_white` / `slide` / `motion_picture` | `colorType` `ColorNegative` / `B&W Negative` / `ColorSlide` / `Other` |
| — | `format` (`35mm`, `120`, …): new NegArchive field (M2) |

Write only our own ids; never rewrite entries whose id does not start with `na-`. NegPy reloads on
file mtime change; bundled entries win on id collision, which our prefix avoids.

### Frame metadata: NegPy export → NegArchive upload

| NegPy XMP / EXIF | NegArchive |
|---|---|
| `negpy:CaptureRoll` | match against `film_rolls.archive_serial`, then `title` |
| `negpy:CaptureFrame` | `image_assets.frame_number` |
| EXIF `DateTimeOriginal` / `photoshop:DateCreated` | `capture_date` |
| EXIF `Make` + `Model` / `negpy:CaptureCameraMake/Model` | camera (by name, later by id) |
| EXIF `LensModel` / `negpy:CaptureLensModel` | lens |
| `negpy:CaptureFilmStock` + `CaptureFilmManufacturer` | film stock |
| `negpy:Developer`, `DevelopmentDilution`, `PushPull`, `DevelopmentTime` | `film_rolls.developer`, `development_dilution`, `push_pull`, `development_time` (0006) |
| `negpy:Notes` | image `notes` |

XMP lives in JPEG APP1 (`http://ns.adobe.com/xap/1.0/`), TIFF tag 700, PNG `iTXt`, WebP `XMP `
chunk. Pillow exposes it via `Image.info["xmp"]` / `getxmp()`; parse the `negpy` namespace with
`xml.etree`.

### Roll handoff: NegArchive → NegPy

1. Create `<export>/<serial>/` with the roll's scans (copy, or hard-link in link mode) plus any
   `.negpy` sidecars.
2. Write `<NEGPY_USER_DIR>/presets/metadata/<serial>.json` with `camera_id`, `lens_id`,
   `film_stock_id` (our `na-…` ids), `capture_roll = serial`, `capture_date`, `film_iso`.
3. The user adds the folder as a library root or Hot Folder in NegPy and applies the preset.

Recommended NegPy export preset for round-tripping: `filename_pattern =
"{{ roll }}_{{ frame|pad(3) }}_{{ film }}"`, JPEG + TIFF, output to a folder NegArchive watches.

## What M5 actually ships

All of it is in `app/services/negpy/` and `app/routers/negpy.py`; the tests are
`tests/test_m5_negpy.py`. Nothing imports, copies or vendors NegPy.

| Direction | What | Where |
|---|---|---|
| NegPy → NegArchive | EXIF + `negpy:` XMP read on **every** upload path and on every file link mode touches; blanks filled, nothing overwritten | `negpy/xmp.py`, `negpy/metadata.py` |
| NegPy → NegArchive | `.negpy` sidecars: accepted beside a scan in a bulk upload or a ZIP, found next to a linked file, re-read when their mtime moves, shown as "Edited in NegPy" plus a one-line summary | `negpy/sidecar.py` |
| NegPy → NegArchive | the export filename preset, parsed **before** the looser scanner rule | `negpy/naming.py` |
| NegArchive → NegPy | `gear/cameras.json`, `lenses.json`, `film_stocks.json`, merge-safe on the `na-` id prefix, written atomically | `negpy/gear.py` |
| NegArchive → NegPy | a roll folder of hard links named with the preset, plus `presets/metadata/<serial>.json` | `negpy/handoff.py` |
| NegPy → NegArchive | `edits.db` read **read-only and immutable**, matched by content hash, for archives with no sidecars | `negpy/edits.py` |
| both | the sampled content hash, so `edits.db` and a frame here can be matched (`GET /api/negpy/lookup?hash=…`) | `app/services/hashing.py` |

Four decisions worth keeping in mind when this is extended:

1. **Ingest fills blanks, never overwrites.** That single rule is what makes it safe to run
   automatically on every upload, and it is why a re-ingest is a no-op. The archive is the system
   of record for the physical roll; a file may inform it and may not correct it.
2. **Gear is matched, not invented** (unless `negpy_create_gear` is on). EXIF spellings —
   "NIKON CORPORATION NIKON F5" — would otherwise fill the Gear page with near-duplicates of
   entries somebody curated.
3. **The recipe is reported, not interpreted.** NegArchive stores the parsed sidecar whole and
   summarises only keys whose meaning is obvious from their name. Rendering somebody else's edit
   badly is worse than not rendering it at all, and NegPy's settings will keep changing.
4. **XMP is parsed defensively.** Pillow's `getxmp()` needs `defusedxml`, and `xml.etree` is
   documented as vulnerable to entity expansion. A packet declaring a DTD or an entity, or one
   over 4 MiB, is refused before the parser sees it. Files come off a scanner's SMB share; they are
   data, not instructions.

### The filename preset, and why it is parsed strictly

Publish `filename_pattern = "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"` in NegPy and a file
survives a converter that strips EXIF and XMP. But the film name usually ends in the ISO, so
M2's "last number in the name wins" rule reads `NEG-2024-0002_013_Kodak Gold 200.jpg` as frame
**200** — and files every frame of the roll as 200. `frame_number_from_filename` therefore tries
the whole-name preset shape before that rule. A name that does not match the preset is left to the
loose rule exactly as before.

Shape alone turned out not to be enough (found on a live archive, 2026-09-21). NegPy renders
`{{ roll }}` through a slug step, so the serial's hyphens come back as the preset's own
separator: `NEG-2026-0001` leaves as `NEG_2026_0001_001.jpg`. Read by shape that is roll `NEG`,
frame **2026**, film `0001_001` — and the whole roll is filed under the year. So the film part
must contain a **letter**; no film stock is called `0001_001`, the candidate is dropped, and the
name falls through to the `<roll>_<frame>` rule, which reads it correctly. Both spellings of a
serial mean the same roll (`serials.find_by_serial_loose`), padding included.

### Where the scanner writes, and the roll it lands on

NegPy's scan mode writes `<output>/<roll name>/<roll name>_Frame001.ARW`. Told to name the roll
after the archive's serial, that folder is the roll (M6.1) — the frames land on the record that
already knows the camera, the film and where the negatives are filed.

Pointed **straight at the watch folder**, though, there is no subfolder: the files land loose in
`/mnt/share/rolls`. The importer used to read only folder names, so it invented a roll called
"rolls" with a serial of its own and left the real roll empty beside it — one roll, in the
archive twice. The roll's name was in every *file* name the whole time, so when a folder's own
name says nothing about a serial, the filenames are read instead, and a file naming a roll the
archive already has goes to that roll (`importer._rolls_for_files`). Two guards keep it quiet:
the serial has to resolve to a roll that exists, so a camera's `IMG_2026_0001_0007.jpg` matches
nothing; and a folder that *does* name a serial keeps M6.1's behaviour, being the more
deliberate statement of the two. The watch folder is never claimed as one roll's `source_dir` —
the next roll scanned into it has to be free to find its own record.

A file that *moves* into a serial-named place is re-filed onto that roll. Re-homing used to fill
in `film_roll_id` only when it was empty, so tidying a misfiled roll into the right folder by
hand changed nothing — which is exactly how the live archive stayed wrong after its owner had
already fixed the folders. A move between two ordinary folders still leaves the roll alone: only
a serial re-files a frame.

An archive that already has the damage is repaired by `scripts/repair_misfiled_rolls.py` (dry
run by default), or one roll at a time in the UI with *Renumber → "Read the filenames again"*.

### Two files per frame, and which one goes on paper

After a round trip a frame has both the raw negative the scanner made and the positive NegPy
exported from it. Both are `type=scan` on the same roll with the same frame number — duplicates
per number are legitimate in this archive, and the roll page shows both.

Everywhere that can only show *one* image per frame, the positive wins: the sleeve grid, cover
sheets, index cards, roll stickers and the roll list's cover strip. Thirty-six orange negatives
say nothing about a roll, and before this the raw won every time for the accidental reason that
it had the lower id. The rule is `strips.better_for_paper` — a finished positive beats one that
is not, the newest export beats an older one, and with no positive anywhere the old rule stands
(first in display order). `roll_summaries` and `/api/films/{id}/layout` apply it server-side;
the print pages' loader (`frontend/components/print/data.ts`, `onePerFrame`) applies the same
rule to the thumbnail strips, so 36 thumbnails mean 36 frames rather than the first 18 twice.

### Reading `edits.db`

NegPy keeps every edit in `<user dir>/edits.db`, table `file_settings(file_hash,
settings_json, file_path)`, keyed by the **content hash** of the source file rather than by its
path. NegArchive computes the same hash for every frame, so on one machine the two can be
matched exactly — which is the whole point of re-implementing the hash faithfully.

Three rules in `app/services/negpy/edits.py`, and none of them is negotiable:

1. **Read-only, always.** `sqlite3.connect("file:…?mode=ro&immutable=1", uri=True)`: the driver
   will not write, will not create the file, takes no locks and leaves any WAL or journal alone,
   so a NegPy that happens to be running is not disturbed. A test asserts an `INSERT` raises, and
   another fingerprints the file before and after a full match.
2. **Never required.** No database, an unreadable one, a schema this does not recognise — all mean
   "no extra information", never an error. The table and the three columns are *sniffed* from
   `sqlite_master` and `PRAGMA table_info`, so a rename upstream degrades instead of breaking.
3. **A sidecar wins.** A `.negpy` file travels with the scan; edits.db is one machine's private
   state. Where both exist the sidecar is what the archive records, and the stored recipe says
   which it was (`source: "sidecar" | "edits.db"`).

Reading somebody's data file is not linking against their program, so this stays MIT-clean — the
schema above is treated as an observation that may be wrong, not as an interface that must hold.

### Printing the negative for the preview

`app/services/preview.py` renders a scan as a positive on demand, into the disposable preview
cache — the archive stores one file per frame, and it is the scan. `app/services/negpy/recipe.py`
maps an edit's tone controls and geometry onto that renderer.

What is rendered, and where it comes from:

| Stage | Source |
|---|---|
| crop, rotation, flips | the recipe, applied exactly |
| log conversion, per-channel percentile bounds, polarity | PIPELINE.md §2 |
| exposure anchor metered off the frame (Auto Density) | §3 helper, our calibration |
| grade as ISO-R, matched to the frame's textural range (Auto Grade) | §3 helper, our calibration |
| print exposure in stops, per-channel offsets | the recipe |
| midtone S-curve, zone densities, split grade | §3, with their constants |
| softplus toe and shoulder, `D_min` 0.06, `D_max` 2.3 | §3, with their constants |
| `I = 10⁻ᴰ`, black point compensation, Adobe RGB TRC | §3 output |

What is **not** rendered, and is reported by name in the viewer: flat-field, sensor crosstalk
unmix, HDR merge, cast removal, dye-coupling paper profiles, hue trim, dodge and burn, local grade,
contrast masks, CLAHE, retouching, Lab mode, alt processes, toning, finish, ICC soft-proofing.

Two calibration constants are **ours, not NegPy's**, and the module says so: their Auto Density and
Auto Grade are metered on a linear raw decode against fixed bounds, while this renderer's axis is
normalized per frame, so a picture occupying the lower third of the axis printed far too bright
with their numbers. Measured against a reference photograph put through a synthetic film gamma and
orange mask: their constants give an RMS error of 54 on a 0–255 scale, ours give 25.

The faithful render is NegPy's own and stays NegPy's: export into a folder registered as a library
root (linked, not copied), or see proposal 3 in [NEGPY_UPSTREAM.md](NEGPY_UPSTREAM.md).

### Where NegArchive writes

| | Default | Override |
|---|---|---|
| NegPy user directory (`gear/`, `presets/`) | `DATA_DIR/negpy/user` | `NEGPY_USER_DIR`, or the `negpy_user_dir` setting |
| Prepared roll folders | `DATA_DIR/negpy/handoff` | `NEGPY_EXPORT_DIR`, or the `negpy_handoff_dir` setting |

A path chosen in the UI must resolve inside `DATA_DIR/negpy`, `NEGPY_USER_DIR`, `NEGPY_EXPORT_DIR`,
`NEGPY_DIRS_ALLOW` or `LIBRARY_ROOTS_ALLOW`; anything else is a 403. Same rule as M3's library
roots, same reason: the API has no password by default, and "POST me a path and I will write files
into it" is not something to offer a LAN.

## Optional upstream proposals (GPL contributions to NegPy)

Only if the owner wants to contribute; NegArchive must not depend on them.

1. A "Physical storage" card in the Metadata panel (`container`, `sleeve`, `archive_serial`)
   flowing into `negpy:` XMP and the filename context. Framed as capture provenance, not an index.
2. A headless export entry point (`python -m negpy export --preset X folder/`) built from the
   Qt-free pieces (`LoaderFactory` → `ImageProcessor` → `encoders` → `embed_metadata`).

Both are now drafted in full, with the NegArchive side of each decided in advance, in
[NEGPY_UPSTREAM.md](NEGPY_UPSTREAM.md) — **not filed**, because opening an issue or a PR on
somebody else's project is the owner's call.

Neither has been proposed upstream yet, and **NegArchive must keep working if neither ever lands**
— which is the whole point of M5 being files. If the first one does land, the mapping is already
decided: `container`/`sleeve`/`archive_serial` are what M4's location tree calls a node's path, the
sleeve node and `film_rolls.archive_serial`, and NegArchive would read them back out of
`negpy:` XMP in `negpy/metadata.py` next to `CaptureRoll`. Until then the serial travels in
`negpy:CaptureRoll`, which NegPy already has, and in the filename.
