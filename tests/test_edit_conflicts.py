from __future__ import annotations

import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from conftest import (
    API,
    DAY,
    MONTH,
    RESOURCE_TYPES,
    SINCE,
    TEXT_FIELDS,
    WEEK,
    assert_error,
    create_item,
    get_changes,
    get_view,
    login,
    match_headers,
    patch_item,
    sample,
    view_items,
)
from techo.errors import APIError


def test_patch_and_delete_require_a_strong_quoted_version_for_all_resources(browser, agent_headers):
    for resource in RESOURCE_TYPES:
        original = create_item(browser, resource, sample(resource, "conditional write"), agent_headers)
        before = (get_view(browser, month=MONTH), get_changes(browser), get_changes(browser, agent_headers))
        version = original["updated_at"]
        invalid = (
            None,
            "",
            version,
            f'W/"{version}"',
            "*",
            '"not-a-timestamp"',
            f'"{version}", "{version}"',
        )
        for etag in invalid:
            headers = dict(agent_headers)
            if etag is not None:
                headers["If-Match"] = etag
            assert_error(
                browser.patch(
                    f"{API}/{resource}/{original['id']}",
                    json={TEXT_FIELDS[resource]: "must not be accepted"},
                    headers=headers,
                ),
                400,
            )
            assert_error(browser.delete(f"{API}/{resource}/{original['id']}", headers=headers), 400)
        assert (
            get_view(browser, month=MONTH),
            get_changes(browser),
            get_changes(browser, agent_headers),
        ) == before


def test_two_clients_using_the_same_version_have_exactly_one_winning_update(project, agent_headers):
    with project.client() as left, project.client() as right:
        login(left)
        for resource in RESOURCE_TYPES:
            original = create_item(left, resource, sample(resource, "two clients"), agent_headers)
            left_seen = view_items(get_view(left, day=DAY), resource)[0]
            right_seen = view_items(get_view(right, day=DAY, headers=agent_headers), resource)[0]
            assert left_seen == right_seen == original
            before_changes = len(get_changes(left)["changes"]) + len(
                get_changes(left, agent_headers)["changes"]
            )
            barrier = Barrier(2)

            def update(client, seen, headers, text):
                barrier.wait(timeout=10)
                return client.patch(
                    f"{API}/{resource}/{original['id']}",
                    json={TEXT_FIELDS[resource]: text},
                    headers=match_headers(seen, headers),
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(update, left, left_seen, None, "left client wins"),
                    pool.submit(update, right, right_seen, agent_headers, "right client wins"),
                ]
                responses = [future.result(timeout=20) for future in futures]
            assert sorted(response.status_code for response in responses) == [200, 409]
            winner_response = next(response for response in responses if response.status_code == 200)
            assert_error(next(response for response in responses if response.status_code == 409), 409)
            winner = winner_response.json()
            assert winner_response.headers.get("ETag") == match_headers(winner)["If-Match"]
            assert winner["updated_at"] != original["updated_at"]
            assert winner["author"] == original["author"] == "agent"
            assert winner["created_at"] == original["created_at"]
            assert view_items(get_view(left, day=DAY), resource) == [winner]
            assert view_items(get_view(right, day=DAY, headers=agent_headers), resource) == [winner]
            changes = get_changes(left)["changes"] + get_changes(left, agent_headers)["changes"]
            assert len(changes) == before_changes + 1
            updates = [
                change
                for change in changes
                if change["type"] == RESOURCE_TYPES[resource]
                and change["id"] == original["id"]
                and change["op"] == "updated"
            ]
            assert len(updates) == 1 and updates[0]["data"] == winner
            actor = "human" if responses[0].status_code == 200 else "agent"
            assert winner["updated_by"] == actor


def test_stale_delete_conflicts_without_hiding_the_current_record_or_adding_a_change(browser, agent_headers):
    for resource in RESOURCE_TYPES:
        original = create_item(browser, resource, sample(resource, "stale delete"), agent_headers)
        current = patch_item(
            browser,
            resource,
            original["id"],
            {TEXT_FIELDS[resource]: "keep the latest edit"},
            version=original["updated_at"],
        )
        before = (get_view(browser, month=MONTH), get_changes(browser), get_changes(browser, agent_headers))
        stale = browser.delete(
            f"{API}/{resource}/{original['id']}", headers=match_headers(original, agent_headers)
        )
        assert_error(stale, 409)
        assert (
            get_view(browser, month=MONTH),
            get_changes(browser),
            get_changes(browser, agent_headers),
        ) == before
        assert view_items(get_view(browser, day=DAY), resource) == [current]
        deleted = browser.delete(
            f"{API}/{resource}/{original['id']}", headers=match_headers(current, agent_headers)
        )
        assert deleted.status_code == 200 and deleted.json() == {"ok": True}
        assert view_items(get_view(browser, day=DAY), resource) == []


def test_returning_to_the_original_value_still_rejects_the_original_version_including_noop_patch(
    browser, agent_headers
):
    for resource in RESOURCE_TYPES:
        original = create_item(browser, resource, sample(resource, "ABA"), agent_headers)
        field = TEXT_FIELDS[resource]
        intermediate = patch_item(
            browser, resource, original["id"], {field: "intermediate B"}, version=original["updated_at"]
        )
        restored = patch_item(
            browser, resource, original["id"], {field: original[field]}, version=intermediate["updated_at"]
        )
        assert restored[field] == original[field]
        assert len({original["updated_at"], intermediate["updated_at"], restored["updated_at"]}) == 3
        before = (get_view(browser, month=MONTH), get_changes(browser), get_changes(browser, agent_headers))
        for value in (original[field], "stale edit after ABA"):
            assert_error(
                browser.patch(
                    f"{API}/{resource}/{original['id']}",
                    json={field: value},
                    headers=match_headers(original, agent_headers),
                ),
                409,
            )
        assert (
            get_view(browser, month=MONTH),
            get_changes(browser),
            get_changes(browser, agent_headers),
        ) == before
        assert view_items(get_view(browser, day=DAY), resource) == [restored]


def test_repeating_reorder_with_the_same_ids_and_old_versions_conflicts_without_side_effects(
    browser, agent_headers
):
    originals = [
        create_item(browser, "goals", sample("goals", f"reorder {index}"), agent_headers)
        for index in range(3)
    ]
    ids = [row["id"] for row in reversed(originals)]
    body = {"period": WEEK, "ids": ids, "versions": {str(row["id"]): row["updated_at"] for row in originals}}
    first = browser.post(f"{API}/goals/reorder", json=body)
    assert first.status_code == 200 and first.json() == {"period": WEEK, "ids": ids}
    before = (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers))
    rows = before[0]["goals"]["weeks"][WEEK]
    assert [row["id"] for row in rows] == ids
    assert_error(browser.post(f"{API}/goals/reorder", json=body, headers=agent_headers), 409)
    current_versions = {str(row["id"]): row["updated_at"] for row in rows}
    one_stale = {**current_versions, str(originals[0]["id"]): originals[0]["updated_at"]}
    assert_error(
        browser.post(
            f"{API}/goals/reorder",
            json={**body, "versions": one_stale},
            headers=agent_headers,
        ),
        409,
    )
    assert (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers)) == before
    accepted = browser.post(f"{API}/goals/reorder", json={**body, "versions": current_versions})
    assert accepted.status_code == 200 and accepted.json() == first.json()
    assert (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers)) == before


def test_reorder_requires_a_version_for_exactly_every_id_and_supports_an_empty_group(browser, agent_headers):
    rows = [create_item(browser, "goals", sample("goals", str(index)), agent_headers) for index in range(2)]
    ids = [row["id"] for row in rows]
    versions = {str(row["id"]): row["updated_at"] for row in rows}
    before = (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers))
    assert_error(browser.post(f"{API}/goals/reorder", json={"period": WEEK, "ids": ids}), 400)
    for invalid in (
        {},
        {str(rows[0]["id"]): rows[0]["updated_at"]},
        {**versions, "2147483647": rows[0]["updated_at"]},
        {**versions, str(rows[1]["id"]): SINCE},
    ):
        assert_error(
            browser.post(
                f"{API}/goals/reorder",
                json={"period": WEEK, "ids": ids, "versions": invalid},
                headers=agent_headers,
            ),
            409,
        )
    assert (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers)) == before
    empty = browser.post(f"{API}/goals/reorder", json={"period": MONTH, "ids": [], "versions": {}})
    assert empty.status_code == 200 and empty.json() == {"period": MONTH, "ids": []}
    assert (get_view(browser, day=DAY), get_changes(browser), get_changes(browser, agent_headers)) == before


def test_service_patch_and_delete_require_keyword_only_versions_and_enforce_them(browser, agent_headers):
    journal = browser.app.state.journal
    for method in (journal.patch, journal.delete):
        parameter = inspect.signature(method).parameters["expected_updated_at"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
    for resource, kind in RESOURCE_TYPES.items():
        original = create_item(browser, resource, sample(resource, "service version"), agent_headers)
        values = {TEXT_FIELDS[resource]: "service update"}
        with pytest.raises(TypeError):
            journal.patch(kind, original["id"], values, "agent")
        with pytest.raises(TypeError):
            journal.delete(kind, original["id"], "agent")
        current = journal.patch(
            kind, original["id"], values, "agent", expected_updated_at=original["updated_at"]
        )
        before = (get_view(browser, month=MONTH), get_changes(browser))
        with pytest.raises(APIError) as failed_patch:
            journal.patch(kind, original["id"], values, "agent", expected_updated_at=original["updated_at"])
        assert failed_patch.value.status == 409
        with pytest.raises(APIError) as failed_delete:
            journal.delete(kind, original["id"], "agent", expected_updated_at=original["updated_at"])
        assert failed_delete.value.status == 409
        assert (get_view(browser, month=MONTH), get_changes(browser)) == before
        assert view_items(before[0], resource) == [current]
        journal.delete(kind, original["id"], "agent", expected_updated_at=current["updated_at"])
        assert view_items(get_view(browser, month=MONTH), resource) == []


def test_failed_stale_patch_cannot_reserve_the_rejected_content_identity(project, browser, agent_headers):
    original = create_item(browser, "notes", sample("notes", "receipt original"), agent_headers)
    current = patch_item(
        browser, "notes", original["id"], {"text": "winning content"}, version=original["updated_at"]
    )
    with sqlite3.connect(project.database_path) as connection:
        before = connection.execute("SELECT * FROM batch_receipts ORDER BY key").fetchall()
    changes_before = (get_changes(browser), get_changes(browser, agent_headers))
    assert_error(
        browser.patch(
            f"{API}/notes/{original['id']}",
            json={"text": "rejected stale content"},
            headers=match_headers(original, agent_headers),
        ),
        409,
    )
    with sqlite3.connect(project.database_path) as connection:
        assert connection.execute("SELECT * FROM batch_receipts ORDER BY key").fetchall() == before
    assert get_view(browser, day=DAY)["notes"] == [current]
    assert (get_changes(browser), get_changes(browser, agent_headers)) == changes_before
    response = browser.post(
        f"{API}/batch",
        json={"items": [{"type": "note", "date": DAY, "text": "rejected stale content"}]},
        headers=agent_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == [] and len(response.json()["created"]) == 1
    assert response.json()["created"][0]["item"]["id"] != original["id"]


def test_versions_are_compared_as_instants_when_timezone_changes(browser, agent_headers):
    from zoneinfo import ZoneInfo

    from techo import clock

    original_zone = clock.current_zone()
    try:
        for resource in RESOURCE_TYPES:
            item = create_item(browser, resource, sample(resource, "timezone change"), agent_headers)
            clock.configure(ZoneInfo("UTC"))
            patched = browser.patch(
                f"{API}/{resource}/{item['id']}",
                json={TEXT_FIELDS[resource]: "after timezone change"},
                headers=match_headers(item, agent_headers),
            )
            assert patched.status_code == 200, patched.text
            clock.configure(ZoneInfo("Asia/Tokyo"))
            assert (
                browser.delete(
                    f"{API}/{resource}/{item['id']}",
                    headers=match_headers(patched.json(), agent_headers),
                ).status_code
                == 200
            )
    finally:
        clock.configure(original_zone)
