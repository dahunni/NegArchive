"""M6 — the network share, and the live mode built on it (docs/NEGPY_LIVE.md).

M5 made NegArchive and NegPy exchange files. M6 answers the question that leaves:
the two run on different machines, so *where* are those files? On a share both can
see, mounted by the container from Settings.

Mounting cannot be tested here — it needs a NAS and ``CAP_SYS_ADMIN``, and CI has
neither. What *can* be tested is everything that decides what gets mounted, and
that is where the bugs would be:

* a mount option string is a comma-separated list, so **a comma in a share name is
  an injection**. Every field that reaches the command line is validated, and the
  argv is built as a list so nothing is ever handed to a shell;
* the SMB password is written to a 0600 file and is **never** in the database, in
  ``/api/smb/status``, or in an export;
* a mounted share becomes a place library roots and NegPy's folders may live —
  and, crucially, **stops being one the moment it is not mounted**, so a root can
  never be registered inside an empty mount point;
* live mode's wiring is idempotent: run it twice and the second run changes
  nothing.

The live-mode tests point ``smb.mount_base()`` at a temporary directory and
pretend it is mounted. That is not a simulation of SMB — it is the real wiring
code, running against a real directory, which is the part that can be wrong.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.errors import ApiError
from app.services import livemode, settings_store, smb


@pytest.fixture
def db_session(client):
    """A session against the migrated test database.

    Depends on ``client`` because that fixture is what runs the migrations and the
    seed; the live-mode tests need the seeded gear catalog to have something to
    sync into NegPy's gear files.
    """
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- what may reach the command line ------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "photo,uid=0",          # ends the option and starts another: the injection
        "photo,credentials=/etc/shadow",
        "//nas/photo",          # a UNC, not a share name
        "photo/film",           # a path, not a share name
        "photo\\film",
        "",
    ],
)
def test_a_share_name_that_could_forge_a_mount_option_is_refused(bad):
    with pytest.raises(ApiError) as caught:
        smb.validate_share(bad)
    assert caught.value.code == "invalid_share"


@pytest.mark.parametrize("bad", ["http://nas.local", "nas local", "nas/photo", "", "a" * 300])
def test_a_host_that_is_not_a_host_is_refused(bad):
    with pytest.raises(ApiError) as caught:
        smb.validate_host(bad)
    assert caught.value.code == "invalid_host"


@pytest.mark.parametrize("bad", ["../../etc", "a/../../b", "film,uid=0", "a\\b"])
def test_a_subpath_may_not_climb_out_of_the_share(bad):
    with pytest.raises(ApiError) as caught:
        smb.validate_subpath(bad)
    assert caught.value.code == "invalid_subpath"


def test_a_subpath_is_forgiving_about_slashes():
    """``/film/`` and ``film`` are the same folder; typing either is reasonable."""
    assert smb.validate_subpath("/film/negatives/") == "film/negatives"
    assert smb.validate_subpath("") == ""


@pytest.mark.parametrize("field", ["username", "domain", "password"])
def test_a_credential_may_not_forge_a_line_in_the_credentials_file(field):
    """``mount.cifs`` parses that file line by line: a newline would add a line."""
    with pytest.raises(ApiError) as caught:
        smb.validate_credential("tim\npassword=stolen", field)
    assert caught.value.code == "invalid_credential"


def test_a_password_keeps_its_spaces():
    """Stripping a password silently turns the right one into the wrong one."""
    assert smb.validate_credential("  hunter2  ", "password") == "  hunter2  "
    assert smb.validate_credential("  tim  ", "username") == "tim"


# --- the command that gets run -------------------------------------------------


def test_the_mount_command_is_an_argv_list_with_the_subpath_in_the_unc():
    config = smb.Config(host="nas.local", share="photo", subpath="film", version="3.0")
    command = smb.mount_command(config)
    assert command[:4] == ["mount", "-t", "cifs", "//nas.local/photo/film"]
    assert command[4] == str(smb.mount_base())
    assert command[5] == "-o"
    # One string of options, and nothing that was not built here.
    assert len(command) == 7


def test_the_options_say_what_the_integration_needs():
    config = smb.Config(host="nas.local", share="photo")
    options = smb.mount_options(config)
    # Without uid/gid every file arrives owned by root and the app cannot read it.
    assert f"uid={os.getuid()}" in options
    # Byte-range locks over SMB are what corrupts SQLite, and NegPy's edits.db is one.
    assert "nobrl" in options
    # A share that goes away should fail the call, not park it in uninterruptible sleep.
    assert "soft" in options
    assert "rw" in options


def test_a_read_only_share_is_mounted_read_only():
    config = smb.Config(host="nas.local", share="photo", readonly=True)
    assert "ro" in smb.mount_options(config)
    assert "rw" not in smb.mount_options(config)


def test_the_negotiated_dialect_is_left_to_mount_cifs_when_asked():
    assert not any(o.startswith("vers=") for o in smb.mount_options(smb.Config(version="default")))
    assert "vers=2.1" in smb.mount_options(smb.Config(version="2.1"))


def test_an_unknown_dialect_is_refused():
    with pytest.raises(ApiError):
        smb.validate_version("42")


# --- where the password lives --------------------------------------------------


def test_the_password_goes_to_a_0600_file_and_the_options_point_at_it(data_dir):
    path = smb.write_credentials("tim", "hunter2", "WORKGROUP")
    try:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
        assert path.read_text() == "username=tim\npassword=hunter2\ndomain=WORKGROUP\n"
        assert f"credentials={path}" in smb.mount_options(smb.Config())
    finally:
        smb.forget_credentials()


def test_a_share_with_no_credentials_is_mounted_as_a_guest(data_dir):
    smb.forget_credentials()
    assert smb.has_credentials() is False
    assert "guest" in smb.mount_options(smb.Config())


def test_the_password_is_in_no_setting_and_in_no_status(client, data_dir):
    smb.write_credentials("tim", "hunter2")
    try:
        saved = client.put(
            "/api/smb/config",
            json={"host": "nas.local", "share": "photo", "username": "tim", "password": "hunter2"},
        )
        assert saved.status_code == 200

        # Not in the settings table, which *is* exported.
        settings = client.get("/api/system/settings").json()["settings"]
        assert "hunter2" not in repr(settings)
        assert "smb_password" not in settings

        # Not in the status the UI draws from either.
        status = client.get("/api/smb/status").json()
        assert "hunter2" not in repr(status)
        assert status["has_credentials"] is True
        assert status["config"]["username"] == "tim"
    finally:
        smb.forget_credentials()


def test_saving_without_a_password_keeps_the_stored_one(client, data_dir):
    """Changing the folder should not mean typing the NAS password again."""
    client.put(
        "/api/smb/config",
        json={"host": "nas.local", "share": "photo", "username": "tim", "password": "hunter2"},
    )
    assert smb.has_credentials()
    client.put("/api/smb/config", json={"host": "nas.local", "share": "photo", "subpath": "film"})
    assert smb.has_credentials()
    assert smb.credentials_path().read_text().endswith("password=hunter2\n")

    # An explicit empty password is how you say "guest share".
    client.put("/api/smb/config", json={"host": "nas.local", "share": "photo", "username": "", "password": ""})
    assert smb.has_credentials() is False


def test_a_bad_share_name_is_refused_by_the_endpoint_too(client):
    response = client.put("/api/smb/config", json={"host": "nas.local", "share": "photo,uid=0"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_share"


# --- a mounted share is a place files may live ---------------------------------


@pytest.fixture
def pretend_mounted(tmp_path, monkeypatch):
    """Point the mount base at a real directory and say it is mounted.

    Everything under test here is the wiring *around* the mount, and that wiring
    cannot tell a CIFS mount from a directory — which is the point.
    """
    base = tmp_path / "share"
    base.mkdir()
    monkeypatch.setattr(smb, "mount_base", lambda: base)
    monkeypatch.setattr(smb, "is_mounted", lambda target=None: True)
    return base


def test_an_unmounted_mount_point_is_not_a_place_a_root_may_live(tmp_path, monkeypatch):
    """The important half: an empty mount point must not accept a library root.

    A root registered inside one would import nothing and look like a broken
    feature, and it would still be there when the share came back somewhere else.
    """
    from app.services import importer

    base = tmp_path / "share"
    base.mkdir()
    monkeypatch.setattr(smb, "mount_base", lambda: base)
    monkeypatch.setattr(smb, "is_mounted", lambda target=None: False)
    assert base not in importer.allowed_bases()

    monkeypatch.setattr(smb, "is_mounted", lambda target=None: True)
    assert base in importer.allowed_bases()


def test_a_mounted_share_is_a_place_negpys_folders_may_live(pretend_mounted):
    from app.services.negpy import dirs

    assert pretend_mounted in dirs.allowed_bases()
    assert dirs.is_allowed(pretend_mounted / "negpy-user")


# --- live mode ------------------------------------------------------------------


def test_live_mode_needs_a_mounted_share(db_session, monkeypatch):
    monkeypatch.setattr(smb, "is_mounted", lambda target=None: False)
    with pytest.raises(ApiError) as caught:
        livemode.apply(db_session)
    assert caught.value.code == "not_mounted"


def test_live_mode_refuses_a_read_only_share(db_session, pretend_mounted):
    settings_store.set_value(db_session, "smb_readonly", True)
    db_session.commit()
    try:
        with pytest.raises(ApiError) as caught:
            livemode.apply(db_session)
        assert caught.value.code == "share_readonly"
    finally:
        settings_store.set_value(db_session, "smb_readonly", False)
        db_session.commit()


def test_live_mode_makes_the_folders_watches_them_and_points_negpy_at_the_share(
    db_session, pretend_mounted
):
    report = livemode.apply(db_session)

    for name in (livemode.ROLLS_DIR, livemode.EXPORTS_DIR, livemode.USER_DIR, livemode.HANDOFF_DIR):
        assert (pretend_mounted / name).is_dir(), f"{name} was not created"

    # Both folders a scan can arrive in are swept, or the sidecar loop never runs.
    from app.models import LibraryRoot

    roots = {r.path: r for r in db_session.query(LibraryRoot).all()}
    for name, _label in livemode.WATCHED:
        path = str(pretend_mounted / name)
        assert path in roots, f"{name} was not registered"
        assert roots[path].watch is True, f"{name} was registered but not watched"

    # NegPy's gear and presets go on the share, where the laptop can see them.
    assert settings_store.get(db_session, "negpy_user_dir") == str(pretend_mounted / livemode.USER_DIR)
    assert settings_store.get(db_session, "negpy_handoff_dir") == str(pretend_mounted / livemode.HANDOFF_DIR)
    assert settings_store.get(db_session, "watch_enabled") is True
    assert report.changed is True

    # And the gear sync actually wrote the files NegPy reads.
    assert (pretend_mounted / livemode.USER_DIR / "gear" / "cameras.json").is_file()


def test_live_mode_run_twice_changes_nothing_the_second_time(db_session, pretend_mounted):
    livemode.apply(db_session)
    again = livemode.apply(db_session)
    assert again.folders_created == []
    assert again.roots_added == []
    assert again.settings_changed == {}
    assert again.changed is False
    assert "Already set up" in again.summary()


def test_live_mode_turns_watching_back_on_for_a_root_that_had_it_off(db_session, pretend_mounted):
    """Registered but not swept is the difference between working and seeming not to."""
    from app.models import LibraryRoot

    livemode.apply(db_session)
    path = str(pretend_mounted / livemode.ROLLS_DIR)
    root = db_session.query(LibraryRoot).filter(LibraryRoot.path == path).one()
    root.watch = False
    db_session.commit()

    livemode.apply(db_session)
    db_session.refresh(root)
    assert root.watch is True


def test_live_state_reports_what_is_actually_there(db_session, pretend_mounted):
    before = livemode.state(db_session)
    assert before["ready"] is False

    livemode.apply(db_session)
    after = livemode.state(db_session)
    assert after["ready"] is True
    assert after["negpy_user_dir_on_share"] is True
    assert all(check["watched"] and check["exists"] for check in after["folders"])

    # A folder somebody deleted on the NAS is not "ready" any more.
    import shutil

    shutil.rmtree(pretend_mounted / livemode.ROLLS_DIR)
    assert livemode.state(db_session)["ready"] is False


def test_the_client_steps_name_the_folders_live_mode_actually_made(db_session, pretend_mounted):
    """The macOS instructions in Settings come from here, so they cannot go stale."""
    report = livemode.apply(db_session)
    steps = report.to_dict()["client"]
    assert steps["rolls"] == str(pretend_mounted / livemode.ROLLS_DIR)
    assert steps["user"] == str(pretend_mounted / livemode.USER_DIR)
    assert Path(steps["rolls"]).is_dir()
    # The preset the round trip depends on (docs/NEGPY_INTEGRATION.md).
    assert steps["filename_pattern"] == "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"


# --- the deployment tells the truth about itself --------------------------------


def test_status_explains_a_container_that_cannot_mount(client, monkeypatch):
    """A failure people will hit. It must name the fix, not print errno 1."""
    monkeypatch.setattr(smb, "capabilities", lambda: {
        "cifs_utils": True, "cifs_utils_path": "/sbin/mount.cifs",
        "sys_admin": False, "dac_read_search": False, "mount_base": "/mnt/negarchive",
    })
    reason = smb.explain_missing(smb.capabilities())
    assert "cap_add" in reason and "SYS_ADMIN" in reason


def test_status_explains_the_capability_everybody_forgets():
    """`cap_add: [SYS_ADMIN]` alone is the obvious Compose file and the wrong one:
    mount.cifs also needs CAP_DAC_READ_SEARCH, and says so only as "Unable to
    apply new capability set." So the check has to name it before the attempt."""
    reason = smb.explain_missing({
        "cifs_utils": True, "cifs_utils_path": "/sbin/mount.cifs",
        "sys_admin": True, "dac_read_search": False,
    })
    assert reason is not None
    assert "DAC_READ_SEARCH" in reason
    # And it must not blame SYS_ADMIN, which this container has.
    assert "missing CAP_DAC_READ_SEARCH" in reason


def test_status_is_satisfied_when_both_capabilities_are_present():
    assert smb.explain_missing({
        "cifs_utils": True, "cifs_utils_path": "/sbin/mount.cifs",
        "sys_admin": True, "dac_read_search": True,
    }) is None


def test_a_failed_mount_translates_libcap_ngs_message(monkeypatch):
    """The raw text is true and useless; the reply must carry the Compose fix."""
    completed = subprocess.CompletedProcess(
        args=["mount"], returncode=1, stdout="", stderr="Unable to apply new capability set.\n"
    )
    config = smb.Config(host="nas.local", share="photo")
    message = smb._explain_failure(completed, config)
    assert "DAC_READ_SEARCH" in message and "docker compose up -d" in message


def test_status_explains_an_image_without_mount_cifs():
    reason = smb.explain_missing({"cifs_utils": False, "sys_admin": True, "dac_read_search": True})
    assert "mount.cifs" in reason


# --- M6.1: what to type into NegPy's scan mode --------------------------------------


def test_the_scan_plan_names_the_folder_and_the_roll(client):
    roll = client.post("/api/films", json={"title": "Scan me"}).json()["film"]
    res = client.get(f"/api/negpy/rolls/{roll['id']}/scan")
    assert res.status_code == 200, res.text
    plan = res.json()["scan"]
    serial = roll["archive_serial"]
    assert plan["roll_name"] == serial
    assert plan["output_dir"].endswith("/" + livemode.ROLLS_DIR)
    assert plan["folder"] == f"{plan['output_dir']}/{serial}"
    assert plan["example_file"] == f"{serial}_Frame001.ARW"
    assert plan["already_linked"] is False
    # Nothing is mounted in CI, and the plan says so rather than pretending.
    assert plan["mounted"] is False
    assert plan["ready"] is False


def test_the_scan_plan_for_a_roll_that_does_not_exist_is_a_404(client):
    assert client.get("/api/negpy/rolls/999999/scan").status_code == 404
