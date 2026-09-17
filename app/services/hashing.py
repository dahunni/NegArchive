"""A sampled SHA-256 that identifies a scan without reading all of it.

Roadmap M3/M5. A 16-bit 4000 dpi TIFF is 200–400 MB; hashing whole rolls on every
rescan would make the watch folder unusable. This reads at most 6 MiB per file
regardless of size, which is enough to tell scans apart in practice and is stable
across copies, moves and renames — so a file that moved between two scans can be
re-homed instead of being imported twice.

**The algorithm** (this docstring is the specification; NegPy is GPL-3 and is
deliberately not imported — see docs/NEGPY_INTEGRATION.md):

``sha256`` over, in this exact order,

1. the file size in bytes, as ASCII decimal digits, no separator;
2. the first 1 MiB of the file (the whole file if it is smaller);
3. the last 1 MiB of the file, only when the file is larger than 1 MiB;
4. 16 interior chunks of 256 KiB each, taken from the region between the head and
   the tail. With ``interior = [1 MiB, size - 1 MiB)`` and
   ``n = len(interior)``, chunk ``i`` starts at ``1 MiB + (n * i) // 16`` and is
   truncated so it never runs past the end of the interior. When the interior is
   empty (files up to 2 MiB) no interior chunk is read at all.

Because step 1 mixes in the size, two different files have to collide on both the
size and every sampled byte to collide at all.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

#: Bytes read from the start, and from the end, of the file.
HEAD_TAIL_BYTES = 1024 * 1024
#: Number of interior samples.
INTERIOR_CHUNKS = 16
#: Size of each interior sample.
INTERIOR_CHUNK_BYTES = 256 * 1024


def _read_at(handle: BinaryIO, offset: int, length: int) -> bytes:
    if length <= 0:
        return b""
    handle.seek(offset)
    return handle.read(length)


def hash_stream(handle: BinaryIO, size: int) -> str:
    """The sampled hash of an already-open binary file of known size."""
    digest = hashlib.sha256()
    digest.update(str(int(size)).encode("ascii"))

    digest.update(_read_at(handle, 0, min(HEAD_TAIL_BYTES, size)))

    if size > HEAD_TAIL_BYTES:
        digest.update(_read_at(handle, size - HEAD_TAIL_BYTES, HEAD_TAIL_BYTES))

    interior_start = HEAD_TAIL_BYTES
    interior_end = max(interior_start, size - HEAD_TAIL_BYTES)
    interior_length = interior_end - interior_start
    if interior_length > 0:
        for index in range(INTERIOR_CHUNKS):
            offset = interior_start + (interior_length * index) // INTERIOR_CHUNKS
            length = min(INTERIOR_CHUNK_BYTES, interior_end - offset)
            digest.update(_read_at(handle, offset, length))

    return digest.hexdigest()


def content_hash(path: str | os.PathLike[str]) -> str:
    """The sampled hash of the file at ``path``.

    Raises ``OSError`` if the file cannot be read; callers that import whole trees
    are expected to catch it and skip the file.
    """
    target = Path(path)
    size = target.stat().st_size
    with target.open("rb") as handle:
        return hash_stream(handle, size)


def safe_content_hash(path: str | os.PathLike[str]) -> str | None:
    """:func:`content_hash`, or ``None`` when the file is unreadable."""
    try:
        return content_hash(path)
    except OSError:
        return None
