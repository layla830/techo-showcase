from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from conftest import API, DAY, assert_error
from python_multipart.exceptions import MultipartParseError
from sqlalchemy.exc import IntegrityError
from starlette import formparsers
from starlette.datastructures import UploadFile
from starlette.requests import Request
from techo.api.photos import MAX_UPLOAD_BYTES, read_upload
from techo.database import Database
from techo.errors import APIError
from techo.repositories import Changes
from techo.services.photos import PhotoService
from test_photos import fetch, image_bytes, photo_files, upload

BOUNDARY = "techo-photo-upload-regression"


def large_jpeg(length: int) -> bytes:
    # As in test_photos, valid JPEG data may have padding after the image's end marker.
    return image_bytes().ljust(length, b"\0")


def multipart_body(content: bytes) -> bytes:
    return (
        (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="date"\r\n\r\n{DAY}\r\n'
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="large.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{BOUNDARY}--\r\n".encode()
    )


def upload_request(content: bytes) -> Request:
    body = multipart_body(content)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": [
                (b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        },
        receive,
    )


@pytest.fixture
def tracked_uploads(monkeypatch):
    handles = []
    rollovers = []
    spooled_file = formparsers.SpooledTemporaryFile

    def track(*args, **kwargs):
        handle = spooled_file(*args, **kwargs)
        handles.append(handle)

        def refuse_rollover():
            # Fail before the test itself could write any source image to disk.
            rollovers.append(handle)
            raise AssertionError("the source upload must stay in memory")

        monkeypatch.setattr(handle, "rollover", refuse_rollover)
        return handle

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track)
    yield handles
    assert not rollovers
    assert all(handle.closed and not handle._rolled for handle in handles)


@pytest.mark.parametrize("length", [1024 * 1024 + 1, MAX_UPLOAD_BYTES - 4096])
def test_large_valid_upload_stays_in_memory_and_closes(client, agent_headers, tracked_uploads, length):
    response = upload(client, large_jpeg(length), agent_headers)
    assert response.status_code == 201, response.text
    assert fetch(client, response.json(), agent_headers).status_code == 200
    assert len(tracked_uploads) == 1
    assert tracked_uploads[0].closed


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
def test_limit_counts_multipart_overhead_before_parsing(client, agent_headers, tracked_uploads, chunked):
    content = large_jpeg(MAX_UPLOAD_BYTES - 1)
    body = multipart_body(content)
    assert len(content) < MAX_UPLOAD_BYTES < len(body)
    chunks = (body[offset : offset + 65536] for offset in range(0, len(body), 65536))
    response = client.post(
        f"{API}/photos",
        content=chunks if chunked else body,
        headers={**agent_headers, "Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
    )
    assert assert_error(response, 413)["code"] == "payload_too_large"
    assert tracked_uploads == []


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ([("author", (None, "human"))], "author"),
        ([("date", (None, DAY))], "date"),
        ([("caption", (None, "caption")), ("author", (None, "human"))], "file"),
        ([("file", ("second.jpg", b"second file", "image/jpeg"))], "file"),
    ],
    ids=["unknown-field", "duplicate-field", "max-fields", "max-files"],
)
def test_form_rejections_close_uploads(client, agent_headers, tracked_uploads, extra, field):
    response = client.post(
        f"{API}/photos",
        files=[
            ("file", ("large.jpg", large_jpeg(1024 * 1024 + 1), "image/jpeg")),
            ("date", (None, DAY)),
            *extra,
        ],
        headers=agent_headers,
    )
    error = assert_error(response, 400)
    assert error["code"] == "validation_error" and error["field"] == field
    assert len(tracked_uploads) == 1
    assert tracked_uploads[0].closed


@pytest.mark.parametrize(
    "failure",
    [
        formparsers.MultiPartException("injected multipart failure"),
        MultipartParseError("injected parser failure"),
        RuntimeError("injected unexpected failure"),
        asyncio.CancelledError(),
    ],
    ids=["multipart-error", "parser-error", "unexpected-error", "cancelled"],
)
def test_parser_failures_close_allocated_uploads(monkeypatch, tracked_uploads, failure):
    parse = formparsers.MultiPartParser.parse
    content = large_jpeg(1024 * 1024 + 1)

    async def parse_then_fail(self):
        # Use real parser allocations and writes, then fail before returning its FormData.
        form = await parse(self)
        assert form["file"].size == len(content)
        assert not form["file"].file.closed
        raise failure

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", parse_then_fail)
    mapped = isinstance(failure, (formparsers.MultiPartException, MultipartParseError))
    with pytest.raises(APIError if mapped else type(failure)) as caught:
        asyncio.run(read_upload(upload_request(content)))
    if mapped:
        assert caught.value.__cause__ is failure
    else:
        assert caught.value is failure
    assert len(tracked_uploads) == 1
    assert tracked_uploads[0].closed


def test_upload_read_failure_closes_parsed_form(monkeypatch, tracked_uploads):
    failure = RuntimeError("injected upload read failure")

    async def fail_read(self, size=-1):
        raise failure

    monkeypatch.setattr(UploadFile, "read", fail_read)
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(read_upload(upload_request(large_jpeg(1024 * 1024 + 1))))
    assert caught.value is failure
    assert len(tracked_uploads) == 1
    assert tracked_uploads[0].closed


def test_rollback_cleanup_preserves_upload_reusing_id_and_hash(project, monkeypatch):
    raw = image_bytes()
    failed = {}
    survivor = {}
    survivor_paths = []
    survivor_bytes = []
    cleanup_calls = []
    append = Changes.append
    unlink = Path.unlink
    failure = IntegrityError("injected upload A rollback", {}, RuntimeError("database failure"))

    with closing(Database(project.settings())) as database:
        database.migrate()
        service = PhotoService(database, project.root / "data" / "photos")

        def fail_after_a_writes(self, kind, row, actor, *args, **kwargs):
            if kind == "photo" and actor == "agent":
                failed.update(
                    id=row.id,
                    hash=row.hash,
                    paths=[service.store.root / row.full_path, service.store.root / row.thumb_path],
                )
                assert all(path.is_file() for path in failed["paths"])
                raise failure
            return append(self, kind, row, actor, *args, **kwargs)

        def upload_b_before_a_cleanup(path, *args, **kwargs):
            if path in failed.get("paths", []):
                if not survivor:
                    # This hook runs after A's real transaction context rolled back, before unlink.
                    assert all(candidate.is_file() for candidate in failed["paths"])
                    with closing(sqlite3.connect(project.database_path)) as connection:
                        assert connection.execute("SELECT COUNT(*) FROM photos").fetchone() == (0,)
                        assert connection.execute("SELECT COUNT(*) FROM changes").fetchone() == (0,)
                    # B's successful BEGIN IMMEDIATE/commit proves A released SQLite's write lock.
                    survivor.update(service.create({"date": DAY}, raw, "human"))
                    for size in ("full", "thumb"):
                        saved = service.read(survivor["id"], size)
                        survivor_paths.append(saved)
                        survivor_bytes.append(saved.read_bytes())
                cleanup_calls.append(path)
            return unlink(path, *args, **kwargs)

        with monkeypatch.context() as schedule:
            schedule.setattr(Changes, "append", fail_after_a_writes)
            schedule.setattr(Path, "unlink", upload_b_before_a_cleanup)
            with pytest.raises(IntegrityError) as caught:
                service.create({"date": DAY}, raw, "agent")
            assert caught.value is failure

        assert survivor["id"] == failed["id"]
        assert survivor["hash"] == failed["hash"] and survivor["date"] == DAY
        assert cleanup_calls == failed["paths"]
        assert set(failed["paths"]).isdisjoint(survivor_paths)
        assert all(not path.exists() for path in failed["paths"])
        assert photo_files(project) == sorted(survivor_paths)
        for size, expected in zip(("full", "thumb"), survivor_bytes, strict=True):
            assert service.read(survivor["id"], size).read_bytes() == expected
        with closing(sqlite3.connect(project.database_path)) as connection:
            assert connection.execute("SELECT id, author FROM photos").fetchall() == [
                (survivor["id"], "human")
            ]
            assert connection.execute("SELECT COUNT(*) FROM changes").fetchone() == (1,)
