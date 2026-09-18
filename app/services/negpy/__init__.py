"""Everything NegArchive knows about NegPy, in one package (roadmap M5).

NegPy is GPL-3, NegArchive is MIT, and NegPy has no importable API anyway
(docs/NEGPY_INTEGRATION.md). So the two programs talk through **files only**:

* :mod:`~app.services.negpy.xmp` and :mod:`~app.services.negpy.metadata` read what
  NegPy wrote into an exported scan (EXIF plus the ``negpy:`` XMP namespace), so a
  file dropped on the upload zone arrives with its roll, frame, date and gear
  already filled in;
* :mod:`~app.services.negpy.naming` parses the recommended export filename pattern,
  which is the fallback when a converter strips the metadata;
* :mod:`~app.services.negpy.sidecar` reads the ``.negpy`` JSON sidecars NegPy can
  leave next to a source file, so the archive can say "edited in NegPy" and show
  what the recipe does;
* :mod:`~app.services.negpy.edits` reads NegPy's ``edits.db`` — read-only, keyed by
  the same content hash — for the archives whose owner never turned sidecars on;
* :mod:`~app.services.negpy.gear` writes NegArchive's cameras, lenses and film
  stocks into NegPy's ``gear/*.json`` schema, under ids prefixed ``na-``;
* :mod:`~app.services.negpy.handoff` prepares a roll folder plus a metadata preset
  so a roll can be opened in NegPy in two clicks;
* :mod:`~app.services.negpy.dirs` decides *where* those files may be written, and
  refuses everything else.

Not one line of NegPy source is imported, copied or vendored here. Where a
behaviour has to match (the sampled content hash in
:mod:`app.services.hashing`), the algorithm is re-implemented from its written
specification and that specification is the docstring.
"""

from . import dirs, edits, gear, handoff, metadata, naming, sidecar, xmp  # noqa: F401

__all__ = ["dirs", "edits", "gear", "handoff", "metadata", "naming", "sidecar", "xmp"]
