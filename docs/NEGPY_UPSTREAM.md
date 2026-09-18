# Two proposals for NegPy — drafts, not yet filed

Roadmap M5's last open item. These are **optional contributions to
[NegPy](https://github.com/marcinz606/NegPy)** (GPL-3), written here so they can be
reviewed before anything is sent, and so that NegArchive's side of each one is already
decided if either lands.

**Nothing in NegArchive depends on them.** M5 works today against NegPy 0.59 exactly as
it ships: XMP and EXIF on export, `.negpy` sidecars, `gear/*.json`, filename templating,
`edits.db`. If both proposals are declined, nothing here has to change — which is the
test each of them has to pass before it is worth anybody's time.

Neither has been filed. Filing means opening an issue or a pull request on somebody
else's project under their name, so that is the owner's call, not the archive's.
[docs/NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md) has the background; NegPy's
contribution gate (Python 3.13, ruff + ty + pytest, frozen-dataclass configs with
migrations, docs in the same change, UI factories only) is the bar a PR would have to
clear.

---

## Proposal 1 — a "Physical storage" field group in `MetadataConfig`

### What

Four optional string fields on the per-frame metadata NegPy already keeps
(`negpy/features/metadata/models.py`), flowing into the XMP writer
(`negpy/features/metadata/xmp.py`) and the filename context
(`negpy/services/export/templating.py`):

| Field | XMP property | Example |
|---|---|---|
| `archive_serial` | `negpy:ArchiveSerial` | `NEG-2024-0011` |
| `archive_container` | `negpy:ArchiveContainer` | `Archive A / Shelf 2 / Binder 03` |
| `archive_sleeve` | `negpy:ArchiveSleeve` | `Page 12` |
| `archive_position` | `negpy:ArchivePosition` | `Strip 3 · 2` |

Plus `{{ archive_serial }}` in the filename template, so an export can be named after
the physical negative it came from.

### Why it is capture provenance, not an index

NegPy's maintainer has documented the decision that the library has **no index
database**: "roots are folders on disk, and a search is a walk"
(`negpy/services/assets/library.py`). A catalog of rolls, sleeves and buildings is
exactly the thing that decision rules out, and this proposal must not smuggle one in.

So the framing matters, and it is honest: these are **four strings the photographer
types, stored with the frame, written into the file on export**. NegPy does not index
them, search them, validate them or reconcile them. They sit beside `capture_roll` and
`capture_frame`, which are already exactly that — provenance about where the image came
from — and they go into the XMP for whatever reads it later. The archive that *does*
index them is somebody else's program.

If that framing is not accepted, the feature is not worth arguing for: the serial
already travels in `negpy:CaptureRoll`, which NegPy has today.

### What NegArchive would do with it

`app/services/negpy/metadata.py` reads the four properties next to `CaptureRoll` and
uses them as a **cross-check, never as an instruction**: a scan whose `ArchiveSerial`
names a different roll than the one it is being uploaded into is reported, not moved,
and a container that does not match the roll's current location is shown as a
discrepancy on the roll page — which is the same thing M4's location browser already
does for a sleeve whose contents disagree with the database. Ingest's rule does not
change: it fills blanks and never overwrites.

The mapping to M4's model, decided in advance:

| XMP | NegArchive |
|---|---|
| `negpy:ArchiveSerial` | `film_rolls.archive_serial` |
| `negpy:ArchiveContainer` | the location path of the sleeve's parent chain |
| `negpy:ArchiveSleeve` | the `sleeve` node itself |
| `negpy:ArchivePosition` | derived from `film_rolls.strips` (`services/strips.py`) |

### Sketch

```python
# negpy/features/metadata/models.py
@dataclass(frozen=True)
class MetadataConfig:
    ...
    archive_serial: str = ""
    archive_container: str = ""
    archive_sleeve: str = ""
    archive_position: str = ""

# negpy/features/metadata/xmp.py
ARCHIVE_PROPERTIES = {
    "ArchiveSerial": "archive_serial",
    "ArchiveContainer": "archive_container",
    "ArchiveSleeve": "archive_sleeve",
    "ArchivePosition": "archive_position",
}
```

with a config migration (NegPy versions its frozen dataclasses), the four fields in a
"Physical storage" card in the metadata panel built through the existing UI factories,
`{{ archive_serial }}` registered in the templating context, and a round-trip test that
writes and reads the XMP back.

---

## Proposal 2 — a headless export entry point

### What

```
python -m negpy export --preset <name> --output <dir> <files or folders>…
```

built from the pieces that are already Qt-free: `LoaderFactory` → `ImageProcessor` →
`encoders` → `embed_metadata`. No new conversion code; an entry point onto the code
that exists, plus `[project.scripts]` so it is a command after an install.

### Why

NegPy's only entry point is `desktop.py`, which means every kind of automation — a
watch folder that converts overnight, a re-export of a whole binder after a recipe
change, a CI check on NegPy's own output — needs a person clicking. A CLI is also the
cheapest possible integration surface for *any* other program, not just this one.

It is a real cost to the maintainer, though: a second entry point is a second thing to
keep working, and the import graph has to stay clean enough that the CLI does not drag
in PyQt6 and wgpu. That is the actual work, and the proposal should say so rather than
pretend it is a hundred lines.

### What NegArchive would do with it

Nothing automatically, and this is worth being explicit about: **NegArchive would not
call it from the server.** Running a converter inside a web request is how a photo
archive becomes a machine that is busy for twenty minutes and cannot answer. What a CLI
would enable is the last manual step of the handoff — "Open in NegPy" prepares a folder
and a preset today, and with a CLI the owner could run one documented command over that
folder instead of clicking through NegPy — and NegArchive would ship that command in
the handoff's `README.txt`, nothing more.

---

## If you want to file these

1. Read them against NegPy's current `main`; this was written against 0.59.0, and both
   sketches name files that may have moved.
2. Open them as **issues first**, not pull requests. Both touch design decisions the
   maintainer has already made deliberately, and a PR that argues with a documented
   decision is a worse way to ask than a paragraph that acknowledges it.
3. Keep them separate. They share nothing but a motivation, and one being declined
   should not take the other with it.
