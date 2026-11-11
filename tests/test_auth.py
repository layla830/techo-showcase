from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie

from conftest import (
    API,
    DAY,
    MONTH,
    ORIGIN,
    PASSWORD,
    RESOURCE_TYPES,
    SINCE,
    WEEK,
    assert_error,
    create_item,
    get_view,
    login,
    match_headers,
    sample,
)


def test_health_and_prefixed_frontend_are_public(client):
    health = client.get(f"{API}/healthz")
    assert health.status_code == 200
    assert health.json() == {"ok": True}
    page = client.get("/techo/")
    assert page.status_code == 200
    assert "techo-contract-static-page" in page.text
    asset = client.get("/techo/fixture.css")
    assert asset.status_code == 200
    assert "#123456" in asset.text


def test_all_key_api_endpoints_require_authentication(client):
    requests = [
        ("GET", "/me", {}),
        ("GET", "/openapi.json", {}),
        ("GET", "/day", {"params": {"date": DAY}}),
        ("GET", "/month", {"params": {"ym": MONTH}}),
        ("GET", "/changes", {"params": {"since": SINCE}}),
        ("POST", "/logout", {}),
        ("POST", "/batch", {"json": {"items": [{"type": "note", **sample("notes")}]}}),
        ("POST", "/goals/reorder", {"json": {"period": WEEK, "ids": [], "versions": {}}}),
    ]
    for resource in RESOURCE_TYPES:
        requests.extend(
            [
                ("POST", f"/{resource}", {"json": sample(resource)}),
                ("PATCH", f"/{resource}/1", {"json": sample(resource)}),
                ("DELETE", f"/{resource}/1", {}),
            ]
        )
    for method, path, kwargs in requests:
        assert_error(client.request(method, API + path, **kwargs), 401)


def test_login_sets_a_secure_ninety_day_scoped_cookie_and_me_identity(client, agent_headers):
    before = datetime.now(timezone.utc)
    response = login(client)
    after = datetime.now(timezone.utc)
    cookies = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        cookies.load(value)
    cookie = cookies["techo_session"]
    assert cookie["httponly"]
    assert cookie["secure"]
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/techo/"
    assert cookie["max-age"] or cookie["expires"]
    if cookie["max-age"]:
        assert int(cookie["max-age"]) == 90 * 24 * 60 * 60
    if cookie["expires"]:
        expiration = parsedate_to_datetime(cookie["expires"])
        assert before + timedelta(days=90, seconds=-2) <= expiration
        assert expiration <= after + timedelta(days=90, seconds=2)
    assert client.get(f"{API}/me").json() == {"author": "human"}
    agent = client.get(f"{API}/me", headers=agent_headers)
    assert agent.status_code == 200
    assert agent.json() == {"author": "agent"}
    assert_error(client.get(f"http://techo.example.com{API}/me"), 401)
    for headers in (None, agent_headers):
        schema = client.get(f"{API}/openapi.json", headers=headers)
        assert schema.status_code == 200
        assert isinstance(schema.json().get("paths"), dict)


def test_session_survives_restart_and_logout_revokes_a_captured_cookie(project):
    with project.client() as first:
        login(first)
        captured = {"Cookie": f"techo_session={first.cookies.get('techo_session')}"}
    with project.client() as restarted:
        identity = restarted.get(f"{API}/me", headers=captured)
        assert identity.status_code == 200
        assert identity.json() == {"author": "human"}
        logout = restarted.post(f"{API}/logout", headers=captured)
        assert logout.status_code == 200
        assert logout.json() == {"ok": True}
        assert_error(restarted.get(f"{API}/me", headers=captured), 401)
    with project.client() as restarted_again:
        assert_error(restarted_again.get(f"{API}/me", headers=captured), 401)


def test_server_rejects_a_session_whose_database_expiration_has_passed(project):
    with project.client() as active:
        login(active)
        # Only the temporary fixture database is changed; the cookie stays intact.
        with sqlite3.connect(project.database_path) as database:
            changed = database.execute(
                "UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00+08:00",)
            ).rowcount
            assert changed == 1
        assert_error(active.get(f"{API}/me"), 401)
        assert_error(active.post(f"{API}/notes", json=sample("notes")), 401)


def test_explicit_bad_token_never_falls_back_to_a_valid_cookie(browser, agent_headers):
    for invalid in ("incorrect-agent-token", ""):
        headers = {"X-Techo-Token": invalid}
        assert_error(browser.get(f"{API}/me", headers=headers), 401)
        assert_error(browser.post(f"{API}/notes", json=sample("notes"), headers=headers), 401)
    assert get_view(browser, month=MONTH)["notes"] == []
    item = create_item(browser, "notes", sample("notes"), headers=agent_headers)
    assert item["author"] == item["updated_by"] == "agent"


def test_sixth_login_is_rate_limited_despite_rotating_forged_forwarding_headers(client):
    for attempt in range(6):
        headers = {
            "Origin": ORIGIN,
            "X-Forwarded-For": f"198.51.100.{attempt + 1}",
            "X-Real-IP": f"203.0.113.{attempt + 1}",
            "Forwarded": f"for=192.0.2.{attempt + 1};proto=https",
        }
        response = client.post(f"{API}/login", json={"password": "wrong password"}, headers=headers)
        assert_error(response, 401 if attempt < 5 else 429)
        assert not client.cookies.get("techo_session")
    assert_error(client.post(f"{API}/login", json={"password": PASSWORD}), 429)


def test_cookie_writes_enforce_origin_and_cross_site_fetch_metadata(browser):
    item = create_item(browser, "notes", sample("notes"))
    goal = create_item(browser, "goals", sample("goals"))
    rejected_headers = [
        {"Origin": "https://unrelated.example"},
        {"Origin": "null"},
        {"Origin": "http://techo.example.com"},
        {"Origin": "https://techo.example.com:444"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    ]
    for headers in rejected_headers:
        assert_error(browser.post(f"{API}/notes", json=sample("notes", "blocked"), headers=headers), 403)
        assert_error(
            browser.patch(f"{API}/notes/{item['id']}", json={"text": "blocked"}, headers=headers), 403
        )
        assert_error(browser.delete(f"{API}/notes/{item['id']}", headers=headers), 403)
        assert_error(
            browser.post(
                f"{API}/goals/reorder",
                json={"period": WEEK, "ids": [goal["id"]], "versions": {str(goal["id"]): goal["updated_at"]}},
                headers=headers,
            ),
            403,
        )
        assert_error(browser.post(f"{API}/logout", headers=headers), 403)
    accepted = browser.patch(
        f"{API}/notes/{item['id']}",
        json={"text": "same origin accepted"},
        headers=match_headers(item, {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}),
    )
    assert accepted.status_code == 200
    assert accepted.json()["text"] == "same origin accepted"
    assert [row["id"] for row in get_view(browser, month=MONTH)["notes"]] == [item["id"]]
