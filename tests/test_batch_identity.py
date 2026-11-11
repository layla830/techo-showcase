from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from conftest import (
    API,
    DAY,
    MONTH,
    RESOURCE_TYPES,
    TEXT_FIELDS,
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
from sqlalchemy.exc import IntegrityError
from techo.repositories import Changes


def batch(client, items, headers):
    response = client.post(f"{API}/batch", json={"items": items}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"created", "skipped"}, result
    return result


def receipts(project):
    with sqlite3.connect(project.database_path) as connection:
        return connection.execute(
            "SELECT key, resource_type, resource_id, created_at FROM batch_receipts ORDER BY key"
        ).fetchall()


def assert_skipped(result, items, records):
    assert result["created"] == []
    assert result["skipped"] == [
        {"index": index, "type": item["type"], "id": record["id"]}
        for index, (item, record) in enumerate(zip(items, records, strict=True))
    ]


def test_source_and_legacy_replays_preserve_manual_edits_for_all_resources(browser, agent_headers):
    items = [
        {"type": kind, "source_key": f"chat:original:{kind}", **sample(resource, "original source")}
        for resource, kind in RESOURCE_TYPES.items()
    ]
    first = batch(browser, items, agent_headers)
    assert first["skipped"] == [] and len(first["created"]) == 4
    records = [entry["item"] for entry in first["created"]]
    edited_items = []
    for resource, item, original in zip(RESOURCE_TYPES, items, records, strict=True):
        changes = {TEXT_FIELDS[resource]: f"human revised {resource}"}
        changes.update({"scope": "month", "period": MONTH} if resource == "goals" else {"date": "2026-11-10"})
        edited = patch_item(browser, resource, original["id"], changes, version=original["updated_at"])
        assert edited["author"] == "agent" and edited["updated_by"] == "human"
        edited_items.append({key: value for key, value in {**item, **changes}.items() if key != "source_key"})
    before = get_view(browser, month=MONTH)
    streams = (get_changes(browser), get_changes(browser, agent_headers))
    legacy = [{key: value for key, value in item.items() if key != "source_key"} for item in items]
    for replay in (items, legacy, edited_items):
        assert_skipped(batch(browser, replay, agent_headers), replay, records)
    assert get_view(browser, month=MONTH) == before
    assert (get_changes(browser), get_changes(browser, agent_headers)) == streams


def test_reusing_source_key_with_changed_payload_never_overwrites_the_original(browser, agent_headers):
    items = [
        {"type": kind, "source_key": f"chat:stable:{kind}", **sample(resource, "first payload")}
        for resource, kind in RESOURCE_TYPES.items()
    ]
    first = batch(browser, items, agent_headers)
    records = [entry["item"] for entry in first["created"]]
    assert len(records) == 4
    before = get_view(browser, month=MONTH)
    changes_before = get_changes(browser)
    changed = [
        {**item, TEXT_FIELDS[resource]: f"different retry for {resource}"}
        for resource, item in zip(RESOURCE_TYPES, items, strict=True)
    ]
    assert_skipped(batch(browser, changed, agent_headers), changed, records)
    assert get_view(browser, month=MONTH) == before
    assert get_changes(browser) == changes_before


def test_source_and_legacy_replays_do_not_resurrect_deleted_batch_items(browser, agent_headers):
    items = [
        {"type": kind, "source_key": f"chat:deleted:{kind}", **sample(resource, "delete source")}
        for resource, kind in RESOURCE_TYPES.items()
    ]
    records = [entry["item"] for entry in batch(browser, items, agent_headers)["created"]]
    assert len(records) == 4
    for resource, original in zip(RESOURCE_TYPES, records, strict=True):
        response = browser.delete(f"{API}/{resource}/{original['id']}", headers=match_headers(original))
        assert response.status_code == 200 and response.json() == {"ok": True}
    streams = (get_changes(browser), get_changes(browser, agent_headers))
    legacy = [{key: value for key, value in item.items() if key != "source_key"} for item in items]
    for replay in (items, legacy):
        assert_skipped(batch(browser, replay, agent_headers), replay, records)
    view = get_view(browser, month=MONTH)
    for resource in RESOURCE_TYPES:
        assert view_items(view, resource) == []
    assert (get_changes(browser), get_changes(browser, agent_headers)) == streams


def test_binding_source_to_existing_content_survives_manual_edits_and_restart(project, agent_headers):
    items = [
        {"type": kind, "source_key": f"chat:bind:{kind}", **sample(resource, "existing content")}
        for resource, kind in RESOURCE_TYPES.items()
    ]
    with project.client() as active:
        login(active)
        originals = [
            create_item(active, resource, sample(resource, "existing content")) for resource in RESOURCE_TYPES
        ]
        before_binding = get_changes(active, agent_headers)
        assert_skipped(batch(active, items, agent_headers), items, originals)
        assert get_changes(active, agent_headers) == before_binding
        for resource, original in zip(RESOURCE_TYPES, originals, strict=True):
            patch_item(
                active,
                resource,
                original["id"],
                {TEXT_FIELDS[resource]: f"keep this manual {resource}"},
                version=original["updated_at"],
            )
        expected_view = get_view(active, month=MONTH)
        expected_changes = get_changes(active, agent_headers)
        expected_receipts = receipts(project)
    with project.client() as restarted:
        legacy = [{key: value for key, value in item.items() if key != "source_key"} for item in items]
        for replay in (items, legacy):
            assert_skipped(batch(restarted, replay, agent_headers), replay, originals)
        assert get_view(restarted, month=MONTH, headers=agent_headers) == expected_view
        assert get_changes(restarted, agent_headers) == expected_changes
        assert receipts(project) == expected_receipts


def test_source_keys_trim_allow_two_hundred_characters_and_reject_invalid_keys_atomically(
    project, browser, agent_headers
):
    items = [
        {"type": "note", **sample("notes", "trimmed key"), "source_key": " \tchat:trimmed\n "},
        {"type": "note", **sample("notes", "maximum key"), "source_key": "k" * 200},
    ]
    records = [entry["item"] for entry in batch(browser, items, agent_headers)["created"]]
    assert len(records) == 2
    canonical = [{**items[0], "source_key": "chat:trimmed"}, {**items[1], "source_key": "  " + "k" * 200}]
    assert_skipped(batch(browser, canonical, agent_headers), canonical, records)
    before = (get_view(browser, month=MONTH), get_changes(browser), receipts(project))
    for index, key in enumerate(("", " \t\n ", "k" * 201)):
        valid = {"type": "note", **sample("notes", f"rolled back {index}"), "source_key": f"valid:{index}"}
        invalid = {"type": "note", **sample("notes", "invalid key"), "source_key": key}
        assert_error(
            browser.post(f"{API}/batch", json={"items": [valid, invalid]}, headers=agent_headers),
            400,
            index=1,
        )
        assert (get_view(browser, month=MONTH), get_changes(browser), receipts(project)) == before


def test_explicit_new_source_can_recreate_history_and_still_deduplicates_active_content(
    browser, agent_headers
):
    old_item = {"type": "note", **sample("notes", "historical content")}
    original = batch(browser, [old_item], agent_headers)["created"][0]["item"]
    assert browser.delete(f"{API}/notes/{original['id']}", headers=match_headers(original)).status_code == 200
    new_source = {**old_item, "source_key": "chat:explicitly-new"}
    second = batch(browser, [new_source], agent_headers)
    assert second["skipped"] == [] and len(second["created"]) == 1
    replacement = second["created"][0]["item"]
    assert replacement["id"] != original["id"]
    another_source = {**old_item, "source_key": "chat:another-new-source"}
    assert_skipped(batch(browser, [another_source], agent_headers), [another_source], [replacement])
    edited = patch_item(
        browser, "notes", replacement["id"], {"text": "human revision"}, version=replacement["updated_at"]
    )
    assert_skipped(batch(browser, [another_source], agent_headers), [another_source], [replacement])
    assert_skipped(batch(browser, [old_item], agent_headers), [old_item], [original])
    manual = [create_item(browser, "notes", sample("notes", "historical content")) for _ in range(2)]
    assert len({original["id"], replacement["id"], *(row["id"] for row in manual)}) == 4
    visible = get_view(browser, day=DAY)["notes"]
    assert {row["id"]: row for row in visible} == {row["id"]: row for row in [edited, *manual]}


def test_cross_type_source_conflicts_roll_back_rows_changes_and_receipts(project, browser, agent_headers):
    bound = {"type": "note", **sample("notes", "bound source"), "source_key": "chat:global-key"}
    original = batch(browser, [bound], agent_headers)["created"][0]["item"]
    before = (get_view(browser, month=MONTH), get_changes(browser), receipts(project))
    prefix = {"type": "event", **sample("events", "rolled back prefix"), "source_key": "chat:prefix"}
    for conflict_items in (
        [prefix, {"type": "media", **sample("media"), "source_key": bound["source_key"]}],
        [
            prefix,
            {"type": "note", **sample("notes", "in-batch conflict"), "source_key": prefix["source_key"]},
        ],
    ):
        assert_error(
            browser.post(f"{API}/batch", json={"items": conflict_items}, headers=agent_headers),
            409,
            index=1,
        )
        assert (get_view(browser, month=MONTH), get_changes(browser), receipts(project)) == before
    retry = batch(browser, [prefix], agent_headers)
    assert retry["skipped"] == [] and len(retry["created"]) == 1
    assert get_view(browser, day=DAY)["notes"] == [original]


def test_database_failure_leaves_no_source_or_content_receipts(project, browser, agent_headers, monkeypatch):
    items = [
        {"type": kind, **sample(resource, "atomic identity"), "source_key": f"chat:atomic:{kind}"}
        for resource, kind in list(RESOURCE_TYPES.items())[:2]
    ]
    before = receipts(project)
    append = Changes.append
    calls = 0

    def fail_after_second_change(self, *args, **kwargs):
        nonlocal calls
        append(self, *args, **kwargs)
        calls += 1
        if calls == 2:
            raise IntegrityError("injected receipt rollback", {}, RuntimeError("database failure"))

    with monkeypatch.context() as patch:
        patch.setattr(Changes, "append", fail_after_second_change)
        failed = browser.post(f"{API}/batch", json={"items": items}, headers=agent_headers)
    assert_error(failed, 500)
    assert receipts(project) == before
    assert get_changes(browser)["changes"] == []
    view = get_view(browser, month=MONTH)
    for resource in RESOURCE_TYPES:
        assert view_items(view, resource) == []
    retried = batch(browser, items, agent_headers)
    assert retried["skipped"] == [] and len(retried["created"]) == 2


def test_concurrent_same_source_with_different_payloads_creates_one_unchanged_record(browser):
    journal = browser.app.state.journal
    barrier = Barrier(6)

    def submit(index):
        barrier.wait(timeout=10)
        return journal.batch(
            [{"type": "note", "date": DAY, "text": f"candidate {index}", "source_key": "chat:concurrent"}],
            "agent",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    created = [entry for result in results for entry in result["created"]]
    skipped = [entry for result in results for entry in result["skipped"]]
    assert len(created) == 1 and len(skipped) == 5
    winner = created[0]["item"]
    assert all(entry == {"index": 0, "type": "note", "id": winner["id"]} for entry in skipped)
    assert get_view(browser, day=DAY)["notes"] == [winner]
    changes = get_changes(browser)["changes"]
    assert len(changes) == 1 and changes[0]["op"] == "created" and changes[0]["data"] == winner
