from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from techo.app import create_app
from techo.config import Settings

API = "/techo/api/v1"
ORIGIN = "https://techo.example.com"
PASSWORD = "test-only-password-not-a-secret"
AGENT_TOKEN = "test-only-agent-token-" + "0" * 40
SINCE = "2000-01-01T00:00:00+08:00"
DAY = "2026-11-09"
MONTH = "2026-11"
WEEK = "2026-W46"
RESOURCE_TYPES = {"notes": "note", "media": "media", "events": "event", "goals": "goal"}
TEXT_FIELDS = {"notes": "text", "media": "title", "events": "title", "goals": "text"}
RESOURCE_FIELDS = {
    "notes": {"date", "text", "mood"},
    "media": {"date", "kind", "title", "note"},
    "events": {"date", "time", "title", "kind", "place"},
    "goals": {"scope", "period", "text", "status", "sort"},
}
COMMON_FIELDS = {"id", "author", "updated_by", "created_at", "updated_at", "deleted_at"}


@dataclass
class Project:
    root: Path
    password_hash: str

    @property
    def database_path(self) -> Path:
        return self.root / "data" / "techo.db"

    def settings(self) -> Settings:
        return Settings(
            project_root=self.root,
            password_hash=self.password_hash,
            agent_token=AGENT_TOKEN,
            public_origin=ORIGIN,
        )

    def client(self) -> TestClient:
        # Always construct a fresh application; entering the context runs lifespan.
        return TestClient(create_app(self.settings()), base_url=ORIGIN)

    def write_seed(self, entries: list[dict[str, Any]]) -> None:
        (self.root / "seed.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(scope="session")
def password_hash() -> str:
    return PasswordHash.recommended().hash(PASSWORD)


@pytest.fixture
def project(tmp_path: Path, password_hash: str) -> Project:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><html><body>techo-contract-static-page</body></html>",
        encoding="utf-8",
    )
    (frontend / "fixture.css").write_text("body { color: #123456; }", encoding="utf-8")
    result = Project(tmp_path, password_hash)
    result.write_seed([])
    return result


@pytest.fixture
def client(project: Project):
    with project.client() as active:
        yield active


@pytest.fixture
def agent_headers() -> dict[str, str]:
    return {"X-Techo-Token": AGENT_TOKEN}


@pytest.fixture
def browser(client: TestClient) -> TestClient:
    login(client)
    return client


def login(client: TestClient):
    response = client.post(f"{API}/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json() == {"author": "human"}
    assert client.cookies.get("techo_session")
    return response


def sample(resource: str, label: str = "original") -> dict[str, Any]:
    return {
        "notes": {"date": DAY, "text": f"note {label}", "mood": "calm"},
        "media": {"date": DAY, "kind": "book", "title": f"media {label}", "note": "first note"},
        "events": {
            "date": DAY,
            "time": "09:30",
            "title": f"event {label}",
            "kind": "plan",
            "place": "home",
        },
        "goals": {"scope": "week", "period": WEEK, "text": f"goal {label}"},
    }[resource]


def assert_error(response, status: int, *, index: int | None = None) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert isinstance(body, dict) and isinstance(body.get("error"), dict), body
    error = body["error"]
    assert isinstance(error.get("code"), str) and error["code"], body
    assert isinstance(error.get("message"), str) and error["message"], body
    if index is not None:
        assert error.get("index") == index, body
    return error


def assert_stamp(value: str) -> datetime:
    assert isinstance(value, str) and value.endswith("+08:00"), value
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(hours=8), value
    return parsed


def assert_record(
    item: dict[str, Any],
    resource: str,
    expected: dict[str, Any],
    *,
    author: str,
    updated_by: str | None = None,
) -> None:
    assert COMMON_FIELDS | RESOURCE_FIELDS[resource] <= item.keys(), item
    assert type(item["id"]) is int and item["id"] > 0, item
    assert item["author"] == author, item
    assert item["updated_by"] == (updated_by or author), item
    assert item["deleted_at"] is None, item
    assert assert_stamp(item["created_at"]) <= assert_stamp(item["updated_at"]), item
    for field, value in expected.items():
        assert item[field] == value, (field, item)


def match_headers(record: dict[str, Any], headers=None) -> dict[str, str]:
    return {**(headers or {}), "If-Match": f'"{record["updated_at"]}"'}


def create_item(client: TestClient, resource: str, payload: dict[str, Any], headers=None):
    response = client.post(f"{API}/{resource}", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    item = response.json()
    assert response.headers.get("ETag") == match_headers(item)["If-Match"]
    return item


def patch_item(
    client: TestClient,
    resource: str,
    item_id: int,
    payload: dict[str, Any],
    headers=None,
    *,
    version: str,
):
    response = client.patch(
        f"{API}/{resource}/{item_id}",
        json=payload,
        headers=match_headers({"updated_at": version}, headers),
    )
    assert response.status_code == 200, response.text
    item = response.json()
    assert response.headers.get("ETag") == match_headers(item)["If-Match"]
    return item


def get_view(client: TestClient, *, day: str | None = None, month: str | None = None, headers=None):
    assert (day is None) != (month is None)
    suffix, params = ("day", {"date": day}) if day is not None else ("month", {"ym": month})
    response = client.get(f"{API}/{suffix}", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def view_items(view: dict[str, Any], resource: str) -> list[dict[str, Any]]:
    if resource != "goals":
        return view[resource]
    goals = view["goals"]
    return goals["month"] + [item for week in goals["weeks"].values() for item in week]


def get_changes(client: TestClient, headers=None, *, since: str = SINCE, limit: int | None = None):
    params: dict[str, Any] = {"since": since}
    if limit is not None:
        params["limit"] = limit
    response = client.get(f"{API}/changes", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"changes", "cursor", "has_more"} <= body.keys(), body
    assert isinstance(body["changes"], list), body
    assert type(body["has_more"]) is bool, body
    assert_stamp(body["cursor"])
    return body
