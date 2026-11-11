from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from conftest import API, DAY, MONTH, get_view
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from test_photos import create_photo, fetch

ROOT = Path(__file__).resolve().parents[1]
OLD_TABLES = (
    "notes",
    "media",
    "events",
    "goals",
    "changes",
    "batch_receipts",
    "sessions",
    "seed_occurrences",
)


def dump(project):
    with sqlite3.connect(project.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in OLD_TABLES
        }


def make_0002_database(project):
    project.database_path.parent.mkdir(parents=True)
    engine = create_engine(URL.create("sqlite", database=str(project.database_path)))
    config = Config()
    config.set_main_option("script_location", str(ROOT / "server" / "migrations"))
    at = "2026-11-09T08:00:00.000000+08:00"
    note = {
        "id": 1,
        "author": "human",
        "updated_by": "human",
        "created_at": at,
        "updated_at": at,
        "deleted_at": None,
        "date": DAY,
        "text": "first note",
        "mood": "calm",
    }
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0002")
            columns = list(note)
            connection.exec_driver_sql(
                f"INSERT INTO notes ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(note[column] for column in columns),
            )
            connection.exec_driver_sql(
                "INSERT INTO changes (actor, resource_type, resource_id, op, at, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                ("human", "note", 1, "created", at, json.dumps(note)),
            )
            connection.exec_driver_sql(
                "INSERT INTO batch_receipts (key, resource_type, resource_id, created_at) VALUES (?, ?, ?, ?)",
                ("content:legacy", "note", 1, at),
            )
            connection.exec_driver_sql(
                "INSERT INTO sessions (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                ("0" * 64, at, "2027-02-07T08:00:00.000000+08:00"),
            )
    finally:
        engine.dispose()
    return note


def test_upgrade_from_0002_keeps_old_data_and_adds_photo_page_tables(project, agent_headers):
    note = make_0002_database(project)
    before = dump(project)
    for _ in range(2):  # a restart re-runs the migration step as a no-op
        with project.client() as client:
            with sqlite3.connect(project.database_path) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
                tables = {
                    row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            assert {"photos", "pages", "decorations", "strokes"} <= tables
            assert dump(project) == before
            month = get_view(client, month=MONTH, headers=agent_headers)
            assert month["notes"] == [note]
            assert month["photos"] == [] and month["decorated_pages"] == []
    with project.client() as client:
        photo = create_photo(client, agent_headers)
        assert fetch(client, photo, agent_headers).status_code == 200
        response = client.put(
            f"{API}/decorations",
            params={"page": f"day:{DAY}"},
            json={
                "version": None,
                "items": [{"item_type": "photo", "ref": str(photo["id"]), "x": 0.5, "y": 0.5}],
            },
            headers=agent_headers,
        )
        assert response.status_code == 200, response.text
        assert get_view(client, month=MONTH, headers=agent_headers)["decorated_pages"] == [f"day:{DAY}"]


def test_backup_includes_uploaded_photos(project, client, agent_headers, tmp_path):
    spec = importlib.util.spec_from_file_location("techo_backup_under_test", ROOT / "tools" / "backup.py")
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    create_photo(client, agent_headers)
    source = project.root / "data" / "photos"
    originals = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert len(originals) == 2
    destination = backup.make_backup(project.root, tmp_path.parent / (tmp_path.name + "-backups"))
    copied = destination / "data" / "photos"
    assert {
        path.relative_to(copied): path.read_bytes() for path in copied.rglob("*") if path.is_file()
    } == originals
    metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["includes"]["photos"] is True
    assert {record["path"] for record in metadata["data_files"]} >= {
        f"data/photos/{relative.as_posix()}" for relative in originals
    }
