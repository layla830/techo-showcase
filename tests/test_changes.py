from __future__ import annotations

from conftest import (
    API,
    DAY,
    RESOURCE_TYPES,
    SINCE,
    TEXT_FIELDS,
    assert_error,
    assert_stamp,
    create_item,
    get_changes,
    match_headers,
    patch_item,
    sample,
)


def test_changes_filter_creates_updates_and_deletes_by_actual_actor_in_both_directions(
    browser, agent_headers
):
    expected_for_human = []
    expected_for_agent = []
    for resource, kind in RESOURCE_TYPES.items():
        agent_created = create_item(browser, resource, sample(resource, "agent owned"), agent_headers)
        expected_for_human.append((kind, agent_created["id"], "created"))
        agent_edited = patch_item(
            browser,
            resource,
            agent_created["id"],
            {TEXT_FIELDS[resource]: "edited by human"},
            version=agent_created["updated_at"],
        )
        expected_for_agent.append((kind, agent_created["id"], "updated"))
        browser_created = create_item(browser, resource, sample(resource, "browser owned"))
        expected_for_agent.append((kind, browser_created["id"], "created"))
        browser_edited = patch_item(
            browser,
            resource,
            browser_created["id"],
            {TEXT_FIELDS[resource]: "edited by agent"},
            agent_headers,
            version=browser_created["updated_at"],
        )
        expected_for_human.append((kind, browser_created["id"], "updated"))
        assert (
            browser.delete(
                f"{API}/{resource}/{browser_created['id']}",
                headers=match_headers(browser_edited, agent_headers),
            ).status_code
            == 200
        )
        expected_for_human.append((kind, browser_created["id"], "deleted"))
        assert (
            browser.delete(
                f"{API}/{resource}/{agent_created['id']}", headers=match_headers(agent_edited)
            ).status_code
            == 200
        )
        expected_for_agent.append((kind, agent_created["id"], "deleted"))
    for headers, expected, actor in (
        (None, expected_for_human, "agent"),
        (agent_headers, expected_for_agent, "human"),
    ):
        result = get_changes(browser, headers)
        assert [(change["type"], change["id"], change["op"]) for change in result["changes"]] == expected
        assert all(change["data"]["updated_by"] == actor for change in result["changes"])
        assert any(change["data"]["author"] != actor for change in result["changes"])
        assert result["has_more"] is False


def test_change_snapshots_are_independent_for_create_update_delete_and_use_default_timezone_timestamps(
    browser, agent_headers
):
    expected = {}
    for resource, kind in RESOURCE_TYPES.items():
        original = create_item(browser, resource, sample(resource, "snapshot original"), agent_headers)
        patch = {TEXT_FIELDS[resource]: "snapshot revised"}
        if resource == "goals":
            patch["status"] = "done"
        updated = patch_item(
            browser, resource, original["id"], patch, agent_headers, version=original["updated_at"]
        )
        deleted = browser.delete(
            f"{API}/{resource}/{original['id']}", headers=match_headers(updated, agent_headers)
        )
        assert deleted.status_code == 200 and deleted.json() == {"ok": True}
        expected[(kind, original["id"])] = (resource, original, updated)
    result = get_changes(browser)
    assert len(result["changes"]) == 12
    grouped = {}
    times = []
    change_ids = []
    for change in result["changes"]:
        assert {"change_id", "type", "id", "op", "at", "data"} <= change.keys()
        assert type(change["change_id"]) is int and change["change_id"] > 0
        change_ids.append(change["change_id"])
        times.append(assert_stamp(change["at"]))
        data = change["data"]
        assert_stamp(data["created_at"])
        assert_stamp(data["updated_at"])
        assert data["id"] == change["id"]
        grouped.setdefault((change["type"], change["id"]), []).append(change)
    assert times == sorted(times) and len(set(times)) == 12
    assert len(set(change_ids)) == 12
    for key, (resource, original, updated) in expected.items():
        changes = grouped[key]
        assert [entry["op"] for entry in changes] == ["created", "updated", "deleted"]
        assert changes[0]["data"] == original
        assert changes[1]["data"] == updated
        deleted = changes[2]["data"]
        assert_stamp(deleted["deleted_at"])
        assert deleted["author"] == deleted["updated_by"] == "agent"
        assert deleted["created_at"] == original["created_at"]
        assert deleted[TEXT_FIELDS[resource]] == updated[TEXT_FIELDS[resource]]
        assert original["deleted_at"] is None and updated["deleted_at"] is None
        assert original[TEXT_FIELDS[resource]] != updated[TEXT_FIELDS[resource]]
    assert result["cursor"] == result["changes"][-1]["at"]


def test_changes_paging_loses_or_duplicates_nothing_including_writes_between_pages(browser, agent_headers):
    expected_ids = [
        create_item(browser, "notes", {"date": DAY, "text": f"paged {index}"}, agent_headers)["id"]
        for index in range(11)
    ]
    since = SINCE
    seen = []
    first_change_at = None
    for page_number in range(20):
        page = get_changes(browser, since=since, limit=3)
        assert page["changes"]
        assert len(page["changes"]) <= 3
        assert all(assert_stamp(change["at"]) > assert_stamp(since) for change in page["changes"])
        assert page["cursor"] == page["changes"][-1]["at"]
        if first_change_at is None:
            first_change_at = page["changes"][0]["at"]
        seen.extend(page["changes"])
        since = page["cursor"]
        if page_number == 0:
            expected_ids.extend(
                create_item(
                    browser, "notes", {"date": DAY, "text": f"arrived while paging {index}"}, agent_headers
                )["id"]
                for index in range(4)
            )
        if not page["has_more"]:
            break
    else:
        raise AssertionError("changes pagination did not terminate")
    assert [change["id"] for change in seen] == expected_ids
    assert len({change["change_id"] for change in seen}) == len(expected_ids)
    assert all(change["type"] == "note" and change["op"] == "created" for change in seen)
    empty = get_changes(browser, since=since, limit=3)
    assert empty["changes"] == [] and empty["has_more"] is False
    assert empty["cursor"] == since
    strictly_later = get_changes(browser, since=first_change_at, limit=1000)
    assert [change["id"] for change in strictly_later["changes"]] == expected_ids[1:]


def test_changes_default_limit_is_five_hundred_and_maximum_limit_returns_the_complete_stream(
    browser, agent_headers
):
    response = browser.post(
        f"{API}/batch",
        json={
            "items": [{"type": "note", "date": DAY, "text": f"change limit {index}"} for index in range(600)]
        },
        headers=agent_headers,
    )
    assert response.status_code == 200, response.text
    expected_ids = [entry["item"]["id"] for entry in response.json()["created"]]
    assert len(expected_ids) == 600
    default_page = get_changes(browser)
    assert len(default_page["changes"]) == 500 and default_page["has_more"] is True
    assert default_page["cursor"] == default_page["changes"][-1]["at"]
    rest = get_changes(browser, since=default_page["cursor"])
    assert len(rest["changes"]) == 100 and rest["has_more"] is False
    whole = get_changes(browser, limit=1000)
    assert len(whole["changes"]) == 600 and whole["has_more"] is False
    assert [change["id"] for change in default_page["changes"] + rest["changes"]] == expected_ids
    assert [change["id"] for change in whole["changes"]] == expected_ids
    assert rest["cursor"] == whole["cursor"] == whole["changes"][-1]["at"]


def test_changes_reject_naive_timestamps_and_invalid_limits_but_accept_other_timezones(client, agent_headers):
    for params in (
        {},
        {"since": "2026-11-09T12:00:00"},
        {"since": "2026-11-09"},
        {"since": "not-a-timestamp"},
        {"since": "2026-02-29T00:00:00+08:00"},
        {"since": SINCE, "limit": 0},
        {"since": SINCE, "limit": -1},
        {"since": SINCE, "limit": 1001},
        {"since": SINCE, "limit": "many"},
    ):
        assert_error(client.get(f"{API}/changes", params=params, headers=agent_headers), 400)
    for since in ("2000-01-01T00:00:00Z", "2000-01-01T00:00:00-05:00"):
        accepted = get_changes(client, agent_headers, since=since, limit=1)
        assert accepted["changes"] == [] and accepted["has_more"] is False


def test_changes_cursor_compares_instants_when_timezone_changes(browser, agent_headers):
    from zoneinfo import ZoneInfo

    from techo import clock

    original_zone = clock.current_zone()
    try:
        create_item(browser, "notes", sample("notes", "before timezone change"))
        cursor = get_changes(browser, agent_headers)["cursor"]
        clock.configure(ZoneInfo("UTC"))
        response = browser.post(f"{API}/notes", json=sample("notes", "after timezone change"))
        assert response.status_code == 201, response.text
        after = response.json()
        feed = browser.get(f"{API}/changes", params={"since": cursor}, headers=agent_headers)
        assert feed.status_code == 200, feed.text
        assert after["id"] in {change["id"] for change in feed.json()["changes"]}
    finally:
        clock.configure(original_zone)
