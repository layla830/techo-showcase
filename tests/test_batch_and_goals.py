from __future__ import annotations

from conftest import (
    API,
    DAY,
    MONTH,
    RESOURCE_TYPES,
    TEXT_FIELDS,
    WEEK,
    assert_error,
    assert_record,
    create_item,
    get_changes,
    get_view,
    match_headers,
    patch_item,
    sample,
    view_items,
)


def post_batch(client, items, headers):
    response = client.post(f"{API}/batch", json={"items": items}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"created", "skipped"}, body
    return body


def test_batch_all_four_types_deduplicate_trimmed_existing_and_in_batch_items(browser, agent_headers):
    resources = list(RESOURCE_TYPES)
    existing = {}
    for resource in resources:
        headers = None if resource in ("notes", "goals") else agent_headers
        existing[resource] = create_item(browser, resource, sample(resource, "existing"), headers)
    duplicates = []
    fresh = []
    repeated = []
    for resource in resources:
        field = TEXT_FIELDS[resource]
        old = sample(resource, "existing")
        old[field] = " \t" + old[field] + "\n "
        duplicates.append({"type": RESOURCE_TYPES[resource], **old})
        new = sample(resource, "new batch item")
        fresh.append({"type": RESOURCE_TYPES[resource], **new})
        repeated.append({"type": RESOURCE_TYPES[resource], **new, field: "  " + new[field] + "  "})
    items = duplicates + fresh + repeated
    result = post_batch(browser, items, agent_headers)
    assert [entry["index"] for entry in result["created"]] == [4, 5, 6, 7]
    new_ids = {}
    for index, resource in enumerate(resources):
        entry = result["created"][index]
        assert entry["type"] == RESOURCE_TYPES[resource]
        assert_record(entry["item"], resource, sample(resource, "new batch item"), author="agent")
        new_ids[resource] = entry["item"]["id"]
    expected_skipped = {
        index: (RESOURCE_TYPES[resource], existing[resource]["id"])
        for index, resource in enumerate(resources)
    }
    expected_skipped.update(
        {index + 8: (RESOURCE_TYPES[resource], new_ids[resource]) for index, resource in enumerate(resources)}
    )
    assert {entry["index"]: (entry["type"], entry["id"]) for entry in result["skipped"]} == expected_skipped
    rerun = post_batch(browser, items, agent_headers)
    assert rerun["created"] == []
    assert sorted(entry["index"] for entry in rerun["skipped"]) == list(range(12))
    view = get_view(browser, month=MONTH)
    for resource in resources:
        records = view_items(view, resource)
        assert {item["id"] for item in records} == {existing[resource]["id"], new_ids[resource]}
        assert next(item for item in records if item["id"] == existing[resource]["id"]) == existing[resource]


def test_batch_failure_rolls_back_all_four_resource_types_and_the_change_log(browser, agent_headers):
    valid = [{"type": kind, **sample(resource, "atomic")} for resource, kind in RESOURCE_TYPES.items()]
    invalid = {"type": "goal", "scope": "week", "period": WEEK, "text": "invalid", "status": "unknown"}
    failed = browser.post(
        f"{API}/batch",
        json={"items": valid + [invalid, {"type": "note", **sample("notes", "after failure")}]},
        headers=agent_headers,
    )
    assert_error(failed, 400, index=4)
    view = get_view(browser, month=MONTH)
    for resource in RESOURCE_TYPES:
        assert view_items(view, resource) == []
    assert get_changes(browser)["changes"] == []
    retry = post_batch(browser, valid, agent_headers)
    assert len(retry["created"]) == 4 and retry["skipped"] == []
    assert len(get_changes(browser)["changes"]) == 4


def test_batch_does_not_resurrect_soft_deleted_duplicates_for_each_resource(client, agent_headers):
    deleted_ids = {}
    items = []
    for resource, kind in RESOURCE_TYPES.items():
        payload = sample(resource, "deleted manual entry")
        item = create_item(client, resource, payload, agent_headers)
        deleted_ids[resource] = item["id"]
        response = client.delete(f"{API}/{resource}/{item['id']}", headers=match_headers(item, agent_headers))
        assert response.status_code == 200
        items.append({"type": kind, **payload})
    result = post_batch(client, items, agent_headers)
    assert result["created"] == []
    assert result["skipped"] == [
        {"index": index, "type": RESOURCE_TYPES[resource], "id": deleted_ids[resource]}
        for index, resource in enumerate(RESOURCE_TYPES)
    ]
    view = get_view(client, month=MONTH, headers=agent_headers)
    for resource in RESOURCE_TYPES:
        assert view_items(view, resource) == []


def test_batch_requires_agent_even_with_a_browser_session(browser, agent_headers):
    body = {"items": [{"type": "note", **sample("notes")}]}
    assert_error(browser.post(f"{API}/batch", json=body), 403)
    assert_error(browser.post(f"{API}/batch", json=body, headers={"X-Techo-Token": "wrong"}), 401)
    assert get_view(browser, month=MONTH)["notes"] == []
    accepted = browser.post(f"{API}/batch", json=body, headers=agent_headers)
    assert accepted.status_code == 200
    assert accepted.json()["created"][0]["item"]["author"] == "agent"


def test_batch_accepts_hundreds_of_entries_and_replaying_it_creates_nothing(client, agent_headers):
    items = [{"type": "note", "date": DAY, "text": f"historical entry {index:04d}"} for index in range(600)]
    first = post_batch(client, items, agent_headers)
    assert first["skipped"] == []
    assert [entry["index"] for entry in first["created"]] == list(range(600))
    ids = [entry["item"]["id"] for entry in first["created"]]
    assert len(set(ids)) == 600
    second = post_batch(client, items, agent_headers)
    assert second["created"] == []
    assert [entry["index"] for entry in second["skipped"]] == list(range(600))
    assert [entry["id"] for entry in second["skipped"]] == ids
    visible = get_view(client, day=DAY, headers=agent_headers)["notes"]
    assert {item["text"] for item in visible} == {entry["text"] for entry in items}
    assert len(visible) == 600


def test_batch_bounds_unknown_fields_and_validation_indices_are_enforced(client, agent_headers):
    valid = {"type": "note", **sample("notes")}
    for body in ({"items": []}, {"items": [valid] * 1001}, {}, {"items": [valid], "extra": True}):
        assert_error(client.post(f"{API}/batch", json=body, headers=agent_headers), 400)
    invalid_items = [
        {"type": "unknown", "date": DAY, "text": "wrong type"},
        {**valid, "author": "human"},
        {**valid, "updated_by": "human"},
        {**valid, "unknown_field": "not accepted"},
        {**valid, "date": "2026-02-29"},
        {**valid, "text": "字" * 501},
        {"type": "goal", **sample("goals"), "date": DAY},
    ]
    for invalid in invalid_items:
        assert_error(
            client.post(f"{API}/batch", json={"items": [invalid]}, headers=agent_headers), 400, index=0
        )
        assert_error(
            client.post(f"{API}/batch", json={"items": [valid, invalid]}, headers=agent_headers), 400, index=1
        )
    assert get_view(client, day=DAY, headers=agent_headers)["notes"] == []


def test_batch_deduplication_keys_keep_dates_types_scopes_and_periods_distinct(client, agent_headers):
    items = [
        {"type": "note", "date": DAY, "text": "shared"},
        {"type": "note", "date": "2026-11-10", "text": "shared"},
        {"type": "media", "date": DAY, "title": "shared", "kind": "book"},
        {"type": "event", "date": DAY, "title": "shared", "kind": "plan"},
        {"type": "media", "date": DAY, "title": " shared ", "kind": "film"},
        {"type": "goal", "scope": "week", "period": WEEK, "text": "shared"},
        {"type": "goal", "scope": "week", "period": "2026-W47", "text": "shared"},
        {"type": "goal", "scope": "month", "period": MONTH, "text": "shared"},
        {"type": "goal", "scope": "week", "period": WEEK, "text": " shared ", "status": "done"},
    ]
    result = post_batch(client, items, agent_headers)
    assert [entry["index"] for entry in result["created"]] == [0, 1, 2, 3, 5, 6, 7]
    assert [entry["index"] for entry in result["skipped"]] == [4, 8]
    created = {entry["index"]: entry["item"] for entry in result["created"]}
    assert result["skipped"][0]["id"] == created[2]["id"]
    assert result["skipped"][1]["id"] == created[5]["id"]
    assert created[5]["status"] == "open"


def test_goals_default_to_append_and_reordering_persists_across_restart(project, agent_headers):
    with project.client() as active:
        first = create_item(active, "goals", {**sample("goals", "first"), "sort": 20}, agent_headers)
        second = create_item(active, "goals", sample("goals", "second"), agent_headers)
        third = create_item(active, "goals", {**sample("goals", "third"), "status": "dropped"}, agent_headers)
        assert first["sort"] < second["sort"] < third["sort"]
        other = create_item(
            active, "goals", {"scope": "month", "period": MONTH, "text": "other period"}, agent_headers
        )
        ids = [third["id"], first["id"], second["id"]]
        response = active.post(
            f"{API}/goals/reorder",
            json={
                "period": WEEK,
                "ids": ids,
                "versions": {str(item["id"]): item["updated_at"] for item in (first, second, third)},
            },
            headers=agent_headers,
        )
        assert response.status_code == 200
        assert response.json() == {"period": WEEK, "ids": ids}
        fourth = create_item(active, "goals", sample("goals", "fourth"), agent_headers)
        expected_ids = ids + [fourth["id"]]
        view = get_view(active, day=DAY, headers=agent_headers)
        assert [item["id"] for item in view["goals"]["weeks"][WEEK]] == expected_ids
        assert view["goals"]["month"] == [other]
    with project.client() as restarted:
        view = get_view(restarted, day=DAY, headers=agent_headers)
        assert [item["id"] for item in view["goals"]["weeks"][WEEK]] == expected_ids
        assert view["goals"]["month"] == [other]


def test_reorder_requires_the_complete_live_set_and_rejects_stale_or_foreign_ids(client, agent_headers):
    original = [
        create_item(client, "goals", sample("goals", str(index)), agent_headers) for index in range(3)
    ]
    ids = [item["id"] for item in original]
    foreign = create_item(
        client, "goals", {"scope": "month", "period": MONTH, "text": "foreign"}, agent_headers
    )
    versions = {str(item["id"]): item["updated_at"] for item in original}
    known_versions = {
        **versions,
        str(foreign["id"]): foreign["updated_at"],
        "2147483647": original[0]["updated_at"],
    }
    for invalid in ([], ids[:2], ids + [ids[0]], [ids[0], ids[1], foreign["id"]], ids + [2147483647]):
        assert_error(
            client.post(
                f"{API}/goals/reorder",
                json={
                    "period": WEEK,
                    "ids": invalid,
                    "versions": {str(record_id): known_versions[str(record_id)] for record_id in invalid},
                },
                headers=agent_headers,
            ),
            409,
        )
        visible = get_view(client, day=DAY, headers=agent_headers)["goals"]["weeks"][WEEK]
        assert [item["id"] for item in visible] == ids
    newcomer = create_item(client, "goals", sample("goals", "concurrent addition"), agent_headers)
    assert_error(
        client.post(
            f"{API}/goals/reorder",
            json={"period": WEEK, "ids": ids, "versions": versions},
            headers=agent_headers,
        ),
        409,
    )
    removed = client.delete(f"{API}/goals/{ids[1]}", headers=match_headers(original[1], agent_headers))
    assert removed.status_code == 200
    with_newcomer = {**versions, str(newcomer["id"]): newcomer["updated_at"]}
    assert_error(
        client.post(
            f"{API}/goals/reorder",
            json={"period": WEEK, "ids": ids + [newcomer["id"]], "versions": with_newcomer},
            headers=agent_headers,
        ),
        409,
    )
    live = [newcomer["id"], ids[2], ids[0]]
    response = client.post(
        f"{API}/goals/reorder",
        json={
            "period": WEEK,
            "ids": live,
            "versions": {str(record_id): with_newcomer[str(record_id)] for record_id in live},
        },
        headers=agent_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"period": WEEK, "ids": live}
    assert [
        item["id"] for item in get_view(client, day=DAY, headers=agent_headers)["goals"]["weeks"][WEEK]
    ] == live


def test_goal_patch_can_move_between_valid_periods_and_both_views_update(client, agent_headers):
    item = create_item(client, "goals", sample("goals"), agent_headers)
    moved = patch_item(
        client,
        "goals",
        item["id"],
        {"scope": "month", "period": "2026-12", "status": "done"},
        agent_headers,
        version=item["updated_at"],
    )
    assert_record(
        moved,
        "goals",
        {"scope": "month", "period": "2026-12", "text": sample("goals")["text"], "status": "done"},
        author="agent",
    )
    assert view_items(get_view(client, month=MONTH, headers=agent_headers), "goals") == []
    assert get_view(client, month="2026-12", headers=agent_headers)["goals"]["month"] == [moved]
    assert_error(
        client.patch(
            f"{API}/goals/{item['id']}", json={"scope": "week"}, headers=match_headers(moved, agent_headers)
        ),
        400,
    )
    assert get_view(client, month="2026-12", headers=agent_headers)["goals"]["month"] == [moved]
