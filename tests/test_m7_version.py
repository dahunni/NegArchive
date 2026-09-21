"""The version on screen and the changelog behind it (docs/ROADMAP.md, M7).

Three files carry the version — ``app/version.py``, the top of ``CHANGELOG.md``
and ``frontend/package.json`` — and the first test here is the one that keeps
them from drifting apart. The rest covers the parser and the endpoint.
"""

import json
from pathlib import Path

from app import version
from app.services import changelog

ROOT = Path(__file__).resolve().parent.parent


def test_the_three_version_numbers_agree():
    package = json.loads((ROOT / "frontend" / "package.json").read_text())
    assert package["version"] == version.__version__
    top = changelog.entries()[0]
    assert top["version"] == version.__version__, "CHANGELOG.md needs an entry for the current version"
    assert top["date"], "the top changelog entry needs a date"


def test_the_parser_reads_the_keep_a_changelog_shape():
    entries = changelog.parse(
        """# Changelog

Some preamble that mentions ## headings in prose.

## [0.10.0] - 2026-09-21

### Added
- One thing, and it
  wraps onto a second line.
- Two

### Fixed
- Three

## [0.9.1] - 2026-09-21
- A bullet with no section

## Unreleased
"""
    )
    assert [e["version"] for e in entries] == ["0.10.0", "0.9.1", "Unreleased"]
    assert entries[0]["date"] == "2026-09-21"
    assert [s["title"] for s in entries[0]["sections"]] == ["Added", "Fixed"]
    assert entries[0]["sections"][0]["items"] == ["One thing, and it wraps onto a second line.", "Two"]
    assert entries[1]["sections"] == [{"title": "Changes", "items": ["A bullet with no section"]}]
    assert entries[2] == {"version": "Unreleased", "date": None, "sections": []}


def test_versions_compare_numerically_not_alphabetically():
    key = changelog.version_key
    assert key("0.10.0") > key("0.9.1")
    assert key("v0.10.0") == key("0.10.0")
    assert key("1.0.0-rc1") < key("1.0.0")
    assert key("garbage") < key("0.0.1")


def test_since_trims_to_the_releases_you_skipped():
    entries = [{"version": v, "date": None, "sections": []} for v in ("0.10.0", "0.9.1", "0.9.0")]
    assert [e["version"] for e in changelog.since(entries, "0.9.0")] == ["0.10.0", "0.9.1"]
    assert [e["version"] for e in changelog.since(entries, "0.10.0")] == []
    assert len(changelog.since(entries, None)) == 3


def test_a_missing_changelog_is_an_empty_list(tmp_path):
    assert changelog.entries(tmp_path / "nope.md") == []


def test_the_version_endpoint_reports_the_build_and_the_changelog(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_GIT_SHA", "0123456789abcdef0123")
    monkeypatch.setenv("NEGARCHIVE_BUILD_DATE", "2026-09-21T09:00:00Z")
    body = client.get("/api/system/version").json()
    assert body["app"] == "NegArchive"
    assert body["version"] == version.__version__
    assert body["git_sha"] == "0123456789ab"
    assert body["built_at"] == "2026-09-21T09:00:00Z"
    assert body["changelog"][0]["version"] == version.__version__
    assert body["changelog_total"] == len(body["changelog"])
    assert body["release_url"].endswith(f"/v{version.__version__}")

    # `since` the release before this one leaves exactly this one. Taken from the
    # file rather than written down, so a release does not have to edit this test.
    previous = body["changelog"][1]["version"]
    trimmed = client.get("/api/system/version", params={"since": previous}).json()
    assert [e["version"] for e in trimmed["changelog"]] == [version.__version__]
    assert trimmed["changelog_total"] == body["changelog_total"]


def test_a_source_checkout_has_no_build_metadata(client, monkeypatch):
    monkeypatch.delenv("NEGARCHIVE_GIT_SHA", raising=False)
    monkeypatch.delenv("NEGARCHIVE_BUILD_DATE", raising=False)
    body = client.get("/api/system/version").json()
    assert body["git_sha"] is None
    assert body["built_at"] is None


def test_the_version_is_behind_the_password(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "hunter2")
    assert client.get("/api/system/version").status_code == 401
    assert client.get("/api/system/info").status_code == 200  # still open, as documented
