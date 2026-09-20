"""The archive's own share, live mode on it, and the two address overrides (M6.3).

Live mode used to need a NAS mounted into the container; now it wires up the
folder the stack serves itself, so these tests point ``SHARE_DIR`` at a
temporary directory and nothing has to pretend to be mounted.
"""

from __future__ import annotations

import os

import pytest

from app.models import LibraryRoot
from app.services import livemode, network, settings_store, share


@pytest.fixture
def db_session(client):
    """A session against the migrated test database (``client`` runs the migrations
    and the seed; live mode needs the seeded gear to have something to sync)."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def served(tmp_path, monkeypatch):
    base = tmp_path / "share"
    monkeypatch.setenv(share.SHARE_DIR_ENV, str(base))
    return base


@pytest.fixture
def clean_settings(db_session):
    """Live mode flips settings; put them back so other tests see the defaults."""
    yield
    for key in ("negpy_user_dir", "negpy_handoff_dir", "share_host", "public_base_url"):
        settings_store.set_value(db_session, key, "")
    db_session.commit()


# --- the layout ---------------------------------------------------------------------


def test_the_layout_is_made_and_open_to_the_shares_user(served):
    base = share.ensure_layout()
    assert base == served.resolve() or base == served
    for name in share.LAYOUT:
        folder = base / name
        assert folder.is_dir(), name
        assert (folder.stat().st_mode & 0o777) == 0o777, f"{name} is not writable by the Samba user"


def test_the_share_is_always_a_place_files_may_live(served):
    from app.services import importer
    from app.services.negpy import dirs

    share.ensure_layout()
    assert share.base() in importer.allowed_bases()
    assert dirs.is_allowed(share.folder(share.USER_DIR))


# --- live mode ----------------------------------------------------------------------


def test_live_mode_wires_up_the_served_share(db_session, served, clean_settings):
    report = livemode.apply(db_session)

    for name in share.LAYOUT:
        assert (served / name).is_dir(), f"{name} was not created"

    # rolls/ is watched, or the sidecar loop never runs. The inbox is not a root:
    # it is emptied, not indexed.
    roots = {r.path: r for r in db_session.query(LibraryRoot).all()}
    assert str(served / share.ROLLS_DIR) in roots
    assert roots[str(served / share.ROLLS_DIR)].watch is True
    assert str(served / share.INBOX_DIR) not in roots

    # NegPy's gear and presets go on the share, where the laptop can see them.
    assert settings_store.get(db_session, "negpy_user_dir") == str(served / share.USER_DIR)
    assert settings_store.get(db_session, "negpy_handoff_dir") == str(served / share.HANDOFF_DIR)
    assert settings_store.get(db_session, "watch_enabled") is True
    assert report.changed is True
    assert (served / share.USER_DIR / "gear" / "cameras.json").is_file()

    # And the Mac side is spelled out with the share's own paths.
    steps = report.to_dict()["client"]
    assert steps["rolls"] == "/Volumes/negarchive/rolls"
    assert steps["inbox"] == "/Volumes/negarchive/inbox"
    assert steps["user_dir"] == "/Volumes/negarchive/negpy-user"
    assert steps["filename_pattern"] == share.FILENAME_PATTERN


def test_live_mode_needs_no_mount(db_session, served, clean_settings, monkeypatch):
    """The whole point of M6.3: nothing has to be mounted before this can run."""
    from app.services import smb

    monkeypatch.setattr(smb, "is_mounted", lambda target=None: False)
    livemode.apply(db_session)
    assert livemode.state(db_session)["ready"] is True


def test_live_mode_run_twice_changes_nothing_the_second_time(db_session, served, clean_settings):
    livemode.apply(db_session)
    again = livemode.apply(db_session)
    assert again.folders_created == [] and again.roots_added == [] and again.settings_changed == {}
    assert again.changed is False and "Already set up" in again.summary()


def test_live_mode_turns_watching_back_on_for_a_root_that_had_it_off(db_session, served, clean_settings):
    livemode.apply(db_session)
    root = db_session.query(LibraryRoot).filter(LibraryRoot.path == str(served / share.ROLLS_DIR)).one()
    root.watch = False
    db_session.commit()
    livemode.apply(db_session)
    db_session.refresh(root)
    assert root.watch is True


def test_live_state_is_checked_not_remembered(db_session, served, clean_settings):
    assert livemode.state(db_session)["ready"] is False
    livemode.apply(db_session)
    assert livemode.state(db_session)["ready"] is True
    root = db_session.query(LibraryRoot).filter(LibraryRoot.path == str(served / share.ROLLS_DIR)).one()
    db_session.delete(root)
    db_session.commit()
    assert livemode.state(db_session)["ready"] is False


def test_the_share_endpoint_answers_with_everything_the_card_needs(client, served, clean_settings):
    body = client.get("/api/share").json()
    assert body["ok"]
    assert body["share"]["mac_root"] == "/Volumes/negarchive"
    assert set(body["share"]["mac_folders"]) == set(share.LAYOUT)
    assert body["live"]["ready"] is False
    assert "pending" in body["inbox"]

    res = client.post("/api/share/setup")
    assert res.status_code == 200, res.text
    assert res.json()["live"]["ready"] is True
    assert client.get("/api/share").json()["live"]["ready"] is True


# --- the two address overrides (M6.3) ------------------------------------------------


def test_the_links_override_can_be_a_proxy_url(client, clean_settings):
    res = client.put("/api/system/settings", json={"public_base_url": "https://archive.example.com/"})
    assert res.status_code == 200, res.text
    info = client.get("/api/system/info").json()
    assert info["ui_url"] == "https://archive.example.com"  # no port: the proxy owns that
    assert info["ui_urls"][0] == "https://archive.example.com"


def test_a_bare_host_for_links_gets_the_ui_port(client, clean_settings, monkeypatch):
    monkeypatch.setenv("UI_PORT", "8021")
    client.put("/api/system/settings", json={"public_base_url": "192.168.1.10"})
    assert client.get("/api/system/info").json()["ui_url"] == "http://192.168.1.10:8021"


def test_the_share_override_is_its_own_setting(client, clean_settings, monkeypatch):
    monkeypatch.delenv(share.SHARE_HOST_ENV, raising=False)
    monkeypatch.delenv("NEGARCHIVE_PUBLIC_HOST", raising=False)
    client.put("/api/system/settings", json={"public_base_url": "https://archive.example.com", "share_host": "192.168.1.10"})
    body = client.get("/api/share").json()
    assert body["share"]["url"] == "smb://192.168.1.10/negarchive"  # SMB wants the box, not the proxy
    # Without its own value it borrows the links' hostname.
    client.put("/api/system/settings", json={"share_host": ""})
    assert client.get("/api/share").json()["share"]["url"] == "smb://archive.example.com/negarchive"


@pytest.mark.parametrize(
    "typed, host",
    [("nas.local", "nas.local"), ("smb://nas.local/negarchive", "nas.local"), ("192.168.1.10:445", "192.168.1.10")],
)
def test_a_pasted_share_address_is_forgiven(typed, host, monkeypatch):
    monkeypatch.setenv(share.SHARE_HOST_ENV, typed)
    assert share.host_override() == host


def test_env_overrides_still_work_without_a_database(monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "https://archive.example.com")
    assert network.ui_url() == "https://archive.example.com"
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "archive.local")
    monkeypatch.setenv("UI_PORT", "8021")
    assert network.ui_url() == "http://archive.local:8021"
    assert os.getenv("NEGARCHIVE_PUBLIC_HOST") == "archive.local"
