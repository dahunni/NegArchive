"""Health, LAN discovery, settings and the optional password (docs/ROADMAP.md, M3).

The password tests matter most. The feature is opt-in, so the default has to be
"wide open" and the opt-in has to be airtight — including `/static`, which is
where the pictures are, and excluding `/api/health` and `/api/system/info`, which
a phone needs before it can even ask for the password.
"""

import xml.etree.ElementTree as ET

from app import auth

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


# --- health -------------------------------------------------------------------


def test_health_reports_the_database_too(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


# --- LAN discovery ------------------------------------------------------------


def test_system_info_reports_the_lan_url_and_the_data_directory(client):
    body = client.get("/api/system/info").json()
    assert body["app"] == "NegArchive"
    assert isinstance(body["lan_ips"], list)
    assert body["data_dir"]
    assert body["ui_port"] == 8021
    assert body["qr_url"] == "/api/system/qr.svg"
    assert body["auth_required"] is False
    assert "rolls" in body["counts"] and "frames" in body["counts"]


def test_the_public_host_override_wins(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "negarchive.local")
    monkeypatch.setenv("UI_PORT", "9000")
    body = client.get("/api/system/info").json()
    assert body["ui_url"] == "http://negarchive.local:9000"
    assert body["ui_urls"][0] == "http://negarchive.local:9000"


def test_the_qr_code_is_an_svg_of_the_ui_url(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "192.168.1.37")
    res = client.get("/api/system/qr.svg")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.headers["x-qr-target"] == "http://192.168.1.37:8021"
    # It is real, parseable SVG, and it follows the theme.
    root = ET.fromstring(res.text)
    assert root.tag.endswith("svg")
    assert 'stroke="currentColor"' in res.text


def test_the_qr_code_can_encode_an_arbitrary_url(client):
    res = client.get("/api/system/qr.svg?url=http://example.invalid/roll/7")
    assert res.status_code == 200
    assert res.headers["x-qr-target"] == "http://example.invalid/roll/7"


# --- settings -----------------------------------------------------------------


def test_settings_round_trip(client):
    assert client.get("/api/system/settings").json()["settings"]["watch_enabled"] is True

    res = client.put("/api/system/settings", json={"watch_enabled": False})
    assert res.status_code == 200, res.text
    assert res.json()["settings"]["watch_enabled"] is False
    assert client.get("/api/system/settings").json()["settings"]["watch_enabled"] is False

    client.put("/api/system/settings", json={"watch_enabled": True})


def test_an_unknown_setting_is_refused(client):
    res = client.put("/api/system/settings", json={"colour_of_the_bikeshed": "green"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "unknown_setting"
    assert "colour_of_the_bikeshed" in res.json()["error"]["message"]


def test_the_settings_response_carries_the_watch_readout(client):
    watch = client.get("/api/system/settings").json()["watch"]
    assert set(watch) >= {"enabled", "interval_seconds", "roots_total", "roots_watched", "last_scan_at"}


# --- the optional shared password --------------------------------------------


def test_no_password_by_default(client):
    assert auth.is_enabled() is False
    assert client.get("/api/films").status_code == 200


def test_with_a_password_set_the_api_is_closed(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")

    closed = client.get("/api/films")
    assert closed.status_code == 401
    assert closed.json()["error"]["code"] == "unauthorized"

    # The pictures are closed too: an archive whose images are public is not closed.
    assert client.get("/static/catalog/cameras/nikon-f5.svg").status_code == 401


def test_health_and_info_stay_open_with_a_password_set(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")
    assert client.get("/api/health").status_code == 200
    info = client.get("/api/system/info")
    assert info.status_code == 200
    assert info.json()["auth_required"] is True, "the phone has to know it needs to ask"


def test_the_right_password_opens_it_and_the_wrong_one_does_not(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")

    wrong = client.post("/api/system/login", json={"password": "hunter2"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_password"

    right = client.post("/api/system/login", json={"password": "darkroom-1968"})
    assert right.status_code == 200
    token = right.json()["token"]
    assert token and len(token) == 64

    # Bearer token…
    assert client.get("/api/films", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    # …and the cookie the login set on this client.
    assert client.cookies.get(auth.COOKIE_NAME) == token
    assert client.get("/api/films").status_code == 200

    client.post("/api/system/logout")
    client.cookies.clear()


def test_the_token_survives_a_restart(monkeypatch):
    """It is derived from the password, so updating the container is not a logout."""
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")
    first = auth.expected_token()
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")
    assert auth.expected_token() == first
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "something else")
    assert auth.expected_token() != first, "changing the password revokes every session"


def test_a_stale_token_is_rejected(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PASSWORD", "darkroom-1968")
    stale = auth.token_for("the old password")
    assert client.get("/api/films", headers={"Authorization": f"Bearer {stale}"}).status_code == 401


def test_login_is_a_no_op_when_no_password_is_configured(client):
    res = client.post("/api/system/login", json={"password": "anything"})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "auth_required": False, "token": None}
