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
| `CAP_SYS_ADMIN` | `cap_add: [SYS_ADMIN]` on the `web` service, plus `security_opt: [apparmor:unconfined]` on Debian/Ubuntu hosts |

Mounting a filesystem is privileged and no userspace trick changes that. The capability is opt-in
in `docker-compose.yml` rather than hidden in the image, with a comment saying what it costs.

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

One button in Settings (`POST /api/smb/live`) creates this on the share and wires it up:

```
rolls/          scans live here forever; NegArchive links them, NegPy edits them in place
exports/        what NegPy exports; watched too, so finished positives come back on their own
negpy-user/     gear/ and presets/metadata/ — NegArchive writes, NegPy reads
handoff/        a prepared roll, for the times you still want one
```

It registers `rolls/` and `exports/` as watched library roots, points `negpy_user_dir` and
`negpy_handoff_dir` at the share, turns the watcher on, and syncs the gear catalog. It creates
nothing that exists and turns nothing off, so running it twice reports that there was nothing to
do.

## The five steps on the Mac

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
5. **Send exports back.** Set NegPy's output folder to `.../exports` and its filename pattern to
   `{{ roll }}_{{ frame|pad(3) }}_{{ film }}`, so finished positives file themselves onto the right
   roll ([NEGPY_INTEGRATION.md](NEGPY_INTEGRATION.md) explains why that pattern is parsed strictly).

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
