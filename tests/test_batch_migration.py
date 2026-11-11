from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from conftest import API, MONTH, RESOURCE_TYPES, TEXT_FIELDS, create_item, get_view, sample, view_items
from sqlalchemy import create_engine
from sqlalchemy.engine import URL


def stored_rows(project):
    with sqlite3.connect(project.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in (*RESOURCE_TYPES, "changes")
        }


def stored_receipts(project):
    with sqlite3.connect(project.database_path) as connection:
        return connection.execute(
            "SELECT key, resource_type, resource_id, created_at FROM batch_receipts ORDER BY key"
        ).fetchall()


def make_0001_database(project):
    project.database_path.parent.mkdir(parents=True)
    engine = create_engine(URL.create("sqlite", database=str(project.database_path)))
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "server" / "migrations")
    )
    start = datetime.fromisoformat("2026-11-09T08:00:00+08:00")
    replays = []
    current_rows = {resource: [] for resource in RESOURCE_TYPES}
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0001"
            assert (
                connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'batch_receipts'"
                ).first()
                is None
            )
            sequence = 0
            for resource, kind in RESOURCE_TYPES.items():
                for record_id, state in ((1, "live"), (2, "deleted")):
                    sequence += 1
                    created_at = (start + timedelta(seconds=sequence * 10)).isoformat()
                    middle_at = (start + timedelta(seconds=sequence * 10 + 1)).isoformat()
                    current_at = (start + timedelta(seconds=sequence * 10 + 2)).isoformat()
                    original = sample(resource, f"legacy {state} A")
                    middle = sample(resource, f"legacy {state} middle")
                    current = sample(resource, f"legacy {state} B")
                    # Old releases used trim-only text keys. Keep padding in the
                    # stored snapshot, then replay the canonical, unpadded text.
                    original[TEXT_FIELDS[resource]] = " \t" + original[TEXT_FIELDS[resource]] + "\n "
                    if resource == "goals":
                        for values in (original, middle, current):
                            values.update(status="open", sort=record_id - 1)
                        middle.update(scope="month", period=MONTH)
                        current.update(scope="month", period="2026-12")
                    else:
                        middle["date"] = "2026-11-10"
                        current["date"] = "2026-12-09"
                    metadata = {
                        "id": record_id,
                        "author": "agent",
                        "created_at": created_at,
                        "deleted_at": None,
                    }
                    snapshots = [
                        ("created", "agent", created_at, {**metadata, **original}),
                        ("updated", "human", middle_at, {**metadata, **middle}),
                    ]
                    for op, actor, at, snapshot in snapshots:
                        snapshot.update(updated_by=actor, updated_at=at)
                        connection.exec_driver_sql(
                            "INSERT INTO changes (actor, resource_type, resource_id, op, at, snapshot) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (actor, kind, record_id, op, at, json.dumps(snapshot)),
                        )
                    # B deliberately has no change snapshot: the migration must
                    # scan the current tables as well, including soft deletion.
                    row = {
                        **metadata,
                        **current,
                        "updated_by": "human",
                        "updated_at": current_at,
                        "deleted_at": current_at if state == "deleted" else None,
                    }
                    columns = list(row)
                    connection.exec_driver_sql(
                        f"INSERT INTO {resource} ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})",
                        tuple(row[column] for column in columns),
                    )
                    current_rows[resource].append(row)
                    for payload in (original, middle, current):
                        canonical = {**payload, TEXT_FIELDS[resource]: payload[TEXT_FIELDS[resource]].strip()}
                        replays.append(({"type": kind, **canonical}, record_id))
    finally:
        engine.dispose()
    return replays, current_rows


def replay_and_assert_skipped(client, replays, headers):
    response = client.post(f"{API}/batch", json={"items": [item for item, _ in replays]}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "created": [],
        "skipped": [
            {"index": index, "type": item["type"], "id": record_id}
            for index, (item, record_id) in enumerate(replays)
        ],
    }


def test_upgrade_from_real_0001_backfills_all_snapshots_and_current_rows_including_soft_deletion(
    project, agent_headers
):
    replays, current_rows = make_0001_database(project)
    old_rows = stored_rows(project)
    assert len(replays) == 24 and len(old_rows["changes"]) == 16
    with project.client() as active:
        with sqlite3.connect(project.database_path) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
        assert len(stored_receipts(project)) == 24
        receipts_before = stored_receipts(project)
        replay_and_assert_skipped(active, replays, agent_headers)
        assert stored_rows(project) == old_rows
        assert stored_receipts(project) == receipts_before
        november = get_view(active, month=MONTH, headers=agent_headers)
        december = get_view(active, month="2026-12", headers=agent_headers)
        for resource in RESOURCE_TYPES:
            assert view_items(november, resource) == []
            assert view_items(december, resource) == [current_rows[resource][0]]


def test_migration_restarts_preserve_receipts_and_never_rebind_history_to_a_later_manual_duplicate(
    project, agent_headers
):
    replays, _ = make_0001_database(project)
    original_item, original_id = replays[0]
    with project.client() as active:
        # A manual duplicate is allowed even though A's receipt still points to
        # the original record, whose current content is B.
        manual = create_item(
            active,
            "notes",
            {key: value for key, value in original_item.items() if key != "type"},
            agent_headers,
        )
        assert manual["id"] != original_id
        replay_and_assert_skipped(active, replays, agent_headers)
        source = {**original_item, "source_key": "chat:migrated-existing-content"}
        response = active.post(f"{API}/batch", json={"items": [source]}, headers=agent_headers)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "created": [],
            "skipped": [{"index": 0, "type": "note", "id": manual["id"]}],
        }
        expected_receipts = stored_receipts(project)
        expected_rows = stored_rows(project)
        expected_view = get_view(active, month=MONTH, headers=agent_headers)
    for _ in range(2):
        with project.client() as restarted:
            with sqlite3.connect(project.database_path) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
            replay_and_assert_skipped(restarted, replays, agent_headers)
            response = restarted.post(f"{API}/batch", json={"items": [source]}, headers=agent_headers)
            assert response.status_code == 200, response.text
            assert response.json() == {
                "created": [],
                "skipped": [{"index": 0, "type": "note", "id": manual["id"]}],
            }
            assert stored_rows(project) == expected_rows
            assert stored_receipts(project) == expected_receipts
            assert get_view(restarted, month=MONTH, headers=agent_headers) == expected_view
