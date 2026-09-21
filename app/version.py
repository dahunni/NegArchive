"""The one place the version number lives.

Bumped by hand with every release, together with the top entry of
``CHANGELOG.md`` and ``frontend/package.json``; ``tests/test_m7_version.py``
fails when the three disagree. The git SHA and the build date are not known
here — the published image bakes them in as ``NEGARCHIVE_GIT_SHA`` and
``NEGARCHIVE_BUILD_DATE`` (Dockerfile, ``.github/workflows/publish.yml``), and a
checkout run from source simply has none.
"""

from __future__ import annotations

import os

__version__ = "0.10.0"


def git_sha() -> str | None:
    """The commit the running image was built from, short form, or None."""
    value = (os.getenv("NEGARCHIVE_GIT_SHA") or "").strip()
    return value[:12] or None


def build_date() -> str | None:
    """When the running image was built (ISO 8601), or None."""
    value = (os.getenv("NEGARCHIVE_BUILD_DATE") or "").strip()
    return value or None
