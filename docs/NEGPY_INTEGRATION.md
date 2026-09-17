# NegPy ↔ NegArchive integration

Findings from reading NegPy `0.59.0` source (github.com/marcinz606/NegPy, GPL-3.0,
Python ≥ 3.13, PyQt6 + WebGPU). Paths are NegPy repo paths.

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
| `negpy:Developer`, `DevelopmentDilution`, `PushPull`, `DevelopmentTime` | roll `notes` now; dedicated process fields later |
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

## Optional upstream proposals (GPL contributions to NegPy)

Only if the owner wants to contribute; NegArchive must not depend on them.

1. A "Physical storage" card in the Metadata panel (`container`, `sleeve`, `archive_serial`)
   flowing into `negpy:` XMP and the filename context. Framed as capture provenance, not an index.
2. A headless export entry point (`python -m negpy export --preset X folder/`) built from the
   Qt-free pieces (`LoaderFactory` → `ImageProcessor` → `encoders` → `embed_metadata`).
