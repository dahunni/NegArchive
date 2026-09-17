"""The sampled content hash (docs/ROADMAP.md, M3; the algorithm is in app/services/hashing.py).

These are the properties the rest of M3 relies on: import-by-reference uses the
hash to re-home a file that moved, and `POST /api/import` uses it to decide that
a frame is already in the archive. If the hash is not stable across copies, or
not sensitive to a changed byte in the middle of a big file, both break quietly.

The interesting cases are all about size, because the algorithm samples rather
than reading everything: a file below 1 MiB is hashed whole, one between 1 and
2 MiB has a head and a tail but no interior, and only above that do the 16
interior chunks appear.
"""

import os

from app.services.hashing import (
    HEAD_TAIL_BYTES,
    INTERIOR_CHUNK_BYTES,
    content_hash,
    safe_content_hash,
)

MIB = 1024 * 1024


def write(tmp_path, name: str, data: bytes) -> str:
    target = tmp_path / name
    target.write_bytes(data)
    return str(target)


def pattern(size: int, seed: int = 0) -> bytes:
    """Deterministic, non-repeating-ish bytes; cheap for multi-MiB files."""
    return bytes(((index * 31 + seed) % 251) for index in range(size))


def test_hash_is_deterministic_and_64_hex_characters(tmp_path):
    path = write(tmp_path, "a.tif", pattern(5000))
    digest = content_hash(path)
    assert digest == content_hash(path)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_a_copy_has_the_same_hash(tmp_path):
    original = write(tmp_path, "a.tif", pattern(3 * MIB))
    copy = write(tmp_path, "b.tif", (tmp_path / "a.tif").read_bytes())
    assert content_hash(original) == content_hash(copy)


def test_size_alone_changes_the_hash(tmp_path):
    """The size goes into the digest first, so two files cannot collide on it."""
    short = write(tmp_path, "short.tif", b"x" * 1000)
    long = write(tmp_path, "long.tif", b"x" * 1001)
    assert content_hash(short) != content_hash(long)


def test_a_changed_byte_in_the_head_changes_the_hash(tmp_path):
    data = bytearray(pattern(4 * MIB))
    first = write(tmp_path, "one.tif", bytes(data))
    data[10] ^= 0xFF
    second = write(tmp_path, "two.tif", bytes(data))
    assert content_hash(first) != content_hash(second)


def test_a_changed_byte_in_the_tail_changes_the_hash(tmp_path):
    data = bytearray(pattern(4 * MIB))
    first = write(tmp_path, "one.tif", bytes(data))
    data[-20] ^= 0xFF
    second = write(tmp_path, "two.tif", bytes(data))
    assert content_hash(first) != content_hash(second)


def test_a_changed_byte_in_a_sampled_interior_chunk_changes_the_hash(tmp_path):
    """Chunk 0 starts exactly at 1 MiB, so this byte is definitely sampled."""
    data = bytearray(pattern(8 * MIB))
    first = write(tmp_path, "one.tif", bytes(data))
    data[HEAD_TAIL_BYTES + 5] ^= 0xFF
    second = write(tmp_path, "two.tif", bytes(data))
    assert content_hash(first) != content_hash(second)


def test_an_unsampled_byte_is_not_read(tmp_path):
    """Sampling is the point: a huge file is not read end to end.

    This documents the trade-off rather than complaining about it — two files
    that differ only in a gap between two interior chunks hash the same, which is
    acceptable for identifying scans and is why the size is mixed in as well.
    """
    size = 40 * MIB
    data = bytearray(pattern(size))
    first = write(tmp_path, "one.tif", bytes(data))
    # Just past the end of interior chunk 0, which covers [1 MiB, 1 MiB + 256 KiB).
    gap = HEAD_TAIL_BYTES + INTERIOR_CHUNK_BYTES + 1024
    data[gap] ^= 0xFF
    second = write(tmp_path, "two.tif", bytes(data))
    assert content_hash(first) == content_hash(second)


def test_empty_file_hashes(tmp_path):
    assert len(content_hash(write(tmp_path, "empty.tif", b""))) == 64


def test_small_file_has_no_interior_chunks(tmp_path):
    """Below 2 MiB the interior is empty; the call must still work."""
    for size in (0, 1, MIB - 1, MIB, MIB + 1, 2 * MIB):
        assert len(content_hash(write(tmp_path, f"s{size}.tif", pattern(size)))) == 64


def test_safe_content_hash_returns_none_for_an_unreadable_file(tmp_path):
    assert safe_content_hash(str(tmp_path / "does-not-exist.tif")) is None


def test_reading_cost_is_bounded(tmp_path, monkeypatch):
    """A 40 MiB file must cost ~6 MiB of reads, not 40."""
    path = write(tmp_path, "big.tif", pattern(40 * MIB))
    read_bytes = {"total": 0}
    real_open = os.fdopen  # noqa: F841 - kept for clarity about what is not patched

    import builtins

    original = builtins.open

    class Counting:
        def __init__(self, handle):
            self._handle = handle

        def read(self, *args):
            data = self._handle.read(*args)
            read_bytes["total"] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def patched(file, mode="r", *args, **kwargs):
        handle = original(file, mode, *args, **kwargs)
        if "b" in mode and str(file) == path:
            return Counting(handle)
        return handle

    monkeypatch.setattr(builtins, "open", patched)
    content_hash(path)
    monkeypatch.undo()

    # 1 MiB head + 1 MiB tail + 16 × 256 KiB = 6 MiB.
    assert read_bytes["total"] <= 7 * MIB, read_bytes
