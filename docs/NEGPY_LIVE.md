# Working live in NegPy (M6)

M5 made NegArchive and NegPy exchange files ([NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md)). It
assumed both were on one machine. They are not: NegArchive is a container on a server, NegPy is a
desktop app on a laptop. This is how that gap is closed.

**The short version.** Put the scans on a network share. Mount it in the container from Settings,
mount it on the Mac in Finder, and point NegPy at it. Then work in NegPy normally — the archive
notices your edits by itself, within 30 seconds.

## Why a share, and not something cleverer

The live behaviour everyone actually wants is: *edit a frame in NegPy, see it marked as edited in
the archive, with the recipe.* That behaviour already exists in the code, and it is one function:

```python
# app/services/importer.py
def _refresh_sidecar(image: ImageAsset) -> bool:
    source = image.source_path or image.path
    found = negpy_sidecar.find(source)
```

It looks for a `.negpy` file **beside the frame's own `source_path`**, compares its mtime against
what the frame recorded, and attaches the recipe if it moved. The watcher calls it for every known
frame on every sweep. So the whole of "live" reduces to one requirement: *the path NegArchive
linked must be the path NegPy edits.* A share is the simplest thing that makes that true.

Three consequences worth stating, because they rule out the obvious alternatives:

- **Live mode uses import by reference, not the roll handoff.** A handoff folder holds *hard links*
  to managed uploads, and a sidecar written next to a hard link is not next to the frame's
  `source_path`. The handoff is still there for carrying a roll to another machine; it is not the
  live path.
- **NegPy's `edits.db` stays on the laptop.** Sidecars carry the same information and travel with
  the file. A SQLite database on an SMB share, written by a desktop app, is the textbook corruption
  case — so the mount uses `nobrl` and live mode never asks you to move `edits.db`.
- **Nothing was invented upstream.** No NegPy code is imported, no plugin, no CLI. It reads a
  folder and writes sidecars because that is what it already does.

## What the container does

`app/services/smb.py` is the only place that runs `mount`. It needs two things from the deployment,
both of which the Settings card checks for and explains if they are missing:

| Needs | Where it comes from |
|---|---|
| `mount.cifs` | `cifs-utils`, in the image since M6 |
| `CAP_SYS_ADMIN` | `cap_add: [SYS_ADMIN, DAC_READ_SEARCH]` on the `web` service, plus `security_opt: [apparmor:unconfined]` on Debian/Ubuntu hosts |
| `CAP_DAC_READ_SEARCH` | the same `cap_add` line — see below |

Mounting a filesystem is privileged and no userspace trick changes that. The capabilities are opt-in
in `docker-compose.yml` rather than hidden in the image, with a comment saying what they cost.

`CAP_DAC_READ_SEARCH` is the one nobody expects. `mount.cifs` starts by clearing its own capability
set and re-adding the three it wants (`SYS_ADMIN`, `DAC_OVERRIDE`, `DAC_READ_SEARCH`), and no
process may *add* a capability it does not already hold. Docker's default set has `DAC_OVERRIDE`
but not `DAC_READ_SEARCH`, so a container with `cap_add: [SYS_ADMIN]` alone fails on
`mount.cifs`'s first line with:

```
Unable to apply new capability set.
```

That happens before any network traffic, which is why the message says nothing about the NAS.

**Set `NEGARCHIVE_PASSWORD` if you turn this on.** The API has no login by default, and these
endpoints can mount filesystems.

### Where the SMB password lives

Not in the database, and not in an export. The settings table is exported by `/api/export`, and an
export carrying the NAS password is a copy of that password on every machine the archive is ever
restored to. It is written to `$DATA_DIR/.smb/credentials` with mode `0600` in a `0700` directory —
which is the file `mount.cifs` reads — and `/api/smb/status` never returns it.

That is also why the password is not passed as `-o password=…`: a password on a command line is in
the process table.

### What is validated, and why

A mount option string is a comma-separated list, so **a comma in a share name is an injection**:
`photo,credentials=/etc/shadow` would end the share and begin an option. Every field that reaches
the command line is checked against a pattern first, the argv is built as a list (never a shell
string), and credentials may not contain a newline, because `mount.cifs` parses its credentials
file line by line. `tests/test_m6_smb.py` asserts each of those refusals.

### A mounted share is a place files may live — while it is mounted

`importer.allowed_bases()` and `negpy/dirs.allowed_bases()` both add the mount point, but only when
`smb.is_mounted()` says so, read fresh from `/proc/self/mounts` rather than remembered. An
unmounted mount point is an empty directory, and a library root registered inside one would import
nothing and look like a broken feature.

A sweep over an unmounted share is harmless either way: `scan_root` never deletes a frame, so a NAS
that is asleep costs you a no-op, not your links.

## The layout live mode makes

One button in Settings (`POST /api/share/setup`, and the older `POST /api/smb/live`) creates this
on the share and wires it up:

```
inbox/          what NegPy exports; taken into the archive and deleted (app/services/inbox.py)
rolls/          scans live here forever; NegArchive links them, NegPy edits them in place
negpy-user/     gear/ and presets/metadata/ — NegArchive writes, NegPy reads
handoff/        a prepared roll, for the times you still want one
```

It registers `rolls/` as a watched library root (the inbox is not a root: it is emptied, not
indexed), points `negpy_user_dir` and `negpy_handoff_dir` at the share, turns the watcher on, and
syncs the gear catalog. It creates nothing that exists and turns nothing off, so running it twice
reports that there was nothing to do.

## The five steps on the Mac (and a sixth for camera scanning)

These are shown in Settings with the real paths filled in and a copy button on each, computed from
the share you saved — `/Volumes/<share>/<folder>/rolls` is what Finder will have mounted.

1. **Mount the same share.** Finder, ⌘K, `smb://nas.local/photo`.
2. **Point NegPy at the scans.** Add `/Volumes/photo/film/rolls` as a library root.
3. **Turn on sidecars in NegPy** — write `.negpy` files next to the originals. *This is the one
   setting the whole thing depends on.* Without it an edit never leaves the laptop.
4. **Share NegPy's gear and presets**, so the catalog and the roll presets appear in NegPy:
   ```bash
   ln -sfn "/Volumes/photo/film/negpy-user/gear" ~/.negpy/gear
   mkdir -p ~/.negpy/presets && ln -sfn "/Volumes/photo/film/negpy-user/presets/metadata" ~/.negpy/presets/metadata
   ```
   Symlinks rather than relocating `NEGPY_USER_DIR` wholesale, so `edits.db` stays on local disk.
5. **Send exports back.** Set NegPy's output folder to `.../inbox` and its filename pattern to
   `{{ roll }}_{{ frame|pad(3) }}_{{ film }}`, so finished positives file themselves onto the right
   roll ([NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md) explains why that pattern is parsed strictly).

## The archive's own share (M6.2, M6.3)

**Live mode runs on a share the stack serves itself.** Everything further down about mounting a
NAS *into* the archive is the older, now optional route (Settings → *Advanced*; its Compose
capability lines are commented out by default). The `smb` service in `docker-compose.yml` exports
`./data/share`, and `app/services/share.py` owns its layout and its address:

| On the share | What happens there |
|---|---|
| `inbox/` | NegPy's exports land here and are taken into the archive and deleted (`app/services/inbox.py`) |
| `rolls/` | camera scans, a folder per roll named after its serial; linked, edited in place |
| `negpy-user/` | `gear/` and `presets/metadata/` — the archive writes, NegPy reads |
| `handoff/` | a prepared roll, when you want one |

Setting it up is one button — Settings → *The share* → **Set up** (`POST /api/share/setup`,
`livemode.apply`): it makes the layout, watches `rolls/`, points `negpy_user_dir` and
`negpy_handoff_dir` at the share, turns the watcher on and syncs the gear. Idempotent. The Mac
steps on the same card use the share's own paths (`/Volumes/negarchive/…`).

**Two addresses (M6.3).** Settings → *This machine* has *Address for links* (`public_base_url`:
an IP, a name, or a full URL such as `https://archive.example.com` when a proxy answers for the
archive — used by the footer, the QR code and printed labels) and *Address for the share*
(`share_host`: what Finder connects to — the box itself, never the proxy). Each is optional; the
share borrows the links' hostname when it has none of its own, and both fall back to the LAN
addresses the container can see. `NEGARCHIVE_PUBLIC_HOST` and `SHARE_HOST` set the same from the
environment.

**Permissions.** Samba writes as its own user and the API runs as root, so `share.ensure_layout()`
makes the layout world-writable. It is a letterbox on a home LAN; the archive's own copies of
everything live elsewhere under `DATA_DIR`.

The inbox on it:

1. Finder → Go → Connect to Server: `smb://<your server>/negarchive`, user and password from `.env`
   (`SHARE_USER` / `SHARE_PASSWORD`, `negarchive` / `negarchive` until you change them).
2. NegPy → Export: output folder `/Volumes/negarchive/inbox`, filename pattern
   `{{ roll }}_{{ frame|pad(3) }}_{{ film }}`.
3. Export.

On the next sweep (`WATCH_INTERVAL_SECONDS`, or *Import now*) `app/services/inbox.py` takes each
finished file **into** the archive exactly as an upload would — copied into managed storage,
hashed, EXIF and `negpy:` XMP read — files it on the roll (a subfolder named after a roll's serial
or title wins; otherwise `negpy:CaptureRoll` or the export filename; otherwise the frame waits
unassigned on the Frames page — the inbox never creates a roll), marks it *already a positive*,
commits, and **deletes it from the inbox**. The folder is a letterbox: it never fills up.

What stays, and why: a file still being written (younger than ten seconds) waits for the next
sweep; a file the archive cannot take — not an image, truncated, too large — stays and is named on
the card; a file whose bytes the archive already holds is removed and counted as a duplicate.
Emptied subfolders and macOS's `._` twins are cleared. The share is a plain container on one port,
so nothing privileged is involved; if the host already runs an SMB server, set `SHARE_PORT`.

Exports uploaded through the browser are handled the same way: a NegPy export is recognised by its
XMP, the roll's upload box has a "These are finished positives" checkbox, and every frame has a
*Shown as* choice in the viewer.

## Scanning straight into the archive (M6.1)

NegPy's *Live View & Scan* photographs the negative with a tethered camera and saves **the camera's
own raw, untouched** — `<output>/<roll name>/<roll name>_Frame001.ARW`, then `_Frame002.ARW`, and so
on. No conversion, no sidecar, no metadata: in that workflow the raw *is* the scan, and the archive
treats it as one.

Two strings make it land on the right roll, and every roll page shows them with a copy button
("Scan with NegPy"):

| In NegPy | Value | Why |
|---|---|---|
| Output folder | `/Volumes/<share>/…/rolls` — the share's `rolls/` folder | it is a watched root, so the sweep sees the new folder |
| Roll name | the roll's archive serial, e.g. `NEG-2026-0007` | the importer adopts a folder carrying the serial of a roll that has no folder yet |

What happens on the next sweep (`WATCH_INTERVAL_SECONDS`, 30 in the Compose stack — or "Check now"
on the roll page):

1. `rolls/NEG-2026-0007/` is found. `parse_folder_name` reads the serial; `_roll_for_folder`
   finds the roll that already carries it and, because that roll has no `source_dir` yet, **adopts**
   it instead of creating a draft beside it. Title, film, camera, lens and location stay as they were.
2. Each `NEG-2026-0007_Frame00N.ARW` is linked — never copied — as frame *N* (the explicit
   `Frame` rule in `frame_number_from_filename`), with its content hash.
3. The first frame marks the roll **scanned** (`lifecycle.touch_scanned`).
4. Previews come through LibRaw (`app/services/rawdecode.py`): the camera's embedded JPEG when
   served raw, a linear demosaic through the print renderer when printed. A roll whose film stock
   is a negative is printed as a positive, exactly as an uploaded TIFF would be.
5. Editing a frame in NegPy afterwards writes `NEG-2026-0007_Frame00N.ARW.negpy` beside it, and the
   same sweep attaches the recipe — nothing about M5 changes because the file is a raw.

The guard rails, and why they are where they are:

- **A roll that already has a folder is never hijacked.** A second folder with the same serial gets
  a fresh serial of its own, as M4 always did: two folders are not one roll. The roll page says so
  when a roll is already linked elsewhere.
- **NegPy's default roll name still works.** A folder called `Roll001` has no serial and becomes a
  draft roll titled `Roll001`, as any other folder would. The workflow above is an offer, not a
  requirement.
- **Trichrome sessions** (RGB scanlight) write three raws plus a merged 16-bit TIFF into the same
  folder; all four are accepted today and all four appear as frames. Hiding the triplet behind the
  merge is on the roadmap.

## What this does not do

- **One share.** A second share is a second deployment decision; those live in the environment.
- **One editing machine.** Two people editing the same folder in NegPy at once is not something
  this has been tested for, and NegPy's own sidecar write path has not been read closely enough to
  promise it is safe.
- **Speed.** NegPy converts big TIFFs over SMB. The bytes cross the wire once per open, and NegPy's
  cache is local, but it is slower than local disk and always will be.
- **Mounting is not tested in CI.** It needs a NAS and a capability that a CI runner does not have.
  What *is* tested is everything that decides what gets mounted — the validation, the argv, the
  credentials file, the allow-lists, and the whole of live mode's wiring against a real directory.
