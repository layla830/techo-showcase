from __future__ import annotations

import hashlib
import io
import os
import random
import sqlite3
import stat

import pytest
from conftest import (
    API,
    DAY,
    MONTH,
    ORIGIN,
    assert_error,
    assert_stamp,
    get_changes,
    get_view,
    login,
    match_headers,
)
from PIL import ExifTags, Image
from sqlalchemy.exc import IntegrityError
from techo import images
from techo.repositories import Changes

PHOTO_FIELDS = {
    "id",
    "date",
    "caption",
    "width",
    "height",
    "hash",
    "author",
    "updated_by",
    "created_at",
    "updated_at",
    "deleted_at",
}
CACHE = "private, max-age=31536000, immutable"
LIMIT = 2 * 1024 * 1024


def image_bytes(fmt="JPEG", size=(64, 48), color=(200, 40, 40), *, exif=None, mode="RGB", **options) -> bytes:
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    if exif is not None:
        options["exif"] = exif
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def oriented_jpeg_with_gps() -> bytes:
    # Stored 200x100: left half red, right half blue. Orientation 6 means "rotate 90° clockwise".
    image = Image.new("RGB", (200, 100), (255, 0, 0))
    image.paste((0, 0, 255), (100, 0, 200, 100))
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.Make] = "TestPhone"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (31.0, 14.0, 5.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (121.0, 28.0, 12.0)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=95)
    return buffer.getvalue()


def upload(client, content: bytes, headers=None, *, date=DAY, caption=None, filename="photo.jpg", extra=None):
    data = {"date": date} if date is not None else {}
    if caption is not None:
        data["caption"] = caption
    data.update(extra or {})
    return client.post(
        f"{API}/photos",
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
        headers=headers,
    )


def create_photo(client, headers=None, **kwargs) -> dict:
    content = kwargs.pop("content", None) or image_bytes()
    response = upload(client, content, headers, **kwargs)
    assert response.status_code == 201, response.text
    item = response.json()
    assert response.headers.get("ETag") == match_headers(item)["If-Match"]
    return item


def fetch(client, item, headers=None, size=None):
    params = {} if size is None else {"size": size}
    return client.get(f"{API}/photos/{item['id']}", params=params, headers=headers)


def photo_files(project) -> list:
    root = project.root / "data" / "photos"
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def test_upload_returns_entry_and_writes_private_hashed_files(project, client, agent_headers):
    item = create_photo(client, agent_headers, caption="  sushi date  ", content=image_bytes(size=(300, 200)))
    assert set(item) == PHOTO_FIELDS
    assert item["date"] == DAY and item["caption"] == "sushi date"
    assert (item["width"], item["height"]) == (300, 200)
    assert item["author"] == item["updated_by"] == "agent"
    assert item["deleted_at"] is None
    assert assert_stamp(item["created_at"]) == assert_stamp(item["updated_at"])

    full = fetch(client, item, agent_headers)
    assert full.status_code == 200
    assert item["hash"] == hashlib.sha256(full.content).hexdigest()[:12]
    files = photo_files(project)
    assert len(files) == 2
    month_dir = project.root / "data" / "photos" / "2026" / "11"
    for path in files:
        assert path.parent == month_dir
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert not path.name.startswith(".") and not path.name.endswith(".tmp")
    assert any(item["hash"] in path.name and path.name.endswith("-full.webp") for path in files)
    for directory in (month_dir, month_dir.parent, month_dir.parent.parent):
        if os.name == "posix":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_upload_accepts_png_and_webp_by_content_and_ignores_filename(client, agent_headers):
    png = create_photo(client, agent_headers, content=image_bytes("PNG"), filename="not-a-png.txt")
    webp = create_photo(client, agent_headers, content=image_bytes("WEBP"), filename="x.jpg")
    transparent = create_photo(
        client, agent_headers, content=image_bytes("PNG", mode="RGBA", color=(0, 0, 0, 0)), filename="a"
    )
    assert png["id"] < webp["id"] < transparent["id"]
    pixel = Image.open(io.BytesIO(fetch(client, transparent, agent_headers).content)).convert("RGB")
    assert all(channel > 240 for channel in pixel.getpixel((5, 5)))  # flattened onto white


def test_caption_trims_to_null_and_is_limited(client, agent_headers):
    assert create_photo(client, agent_headers, caption="   ")["caption"] is None
    assert create_photo(client, agent_headers, caption="字" * 200)["caption"] == "字" * 200
    error = assert_error(upload(client, image_bytes(), agent_headers, caption="字" * 201), 400)
    assert error["field"] == "caption"


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"date": None}, "date"),
        ({"date": "2026-02-30"}, "date"),
        ({"date": "2026/11/09"}, "date"),
        ({"extra": {"author": "human"}}, "author"),
    ],
)
def test_upload_form_field_validation(client, agent_headers, kwargs, field):
    error = assert_error(upload(client, image_bytes(), agent_headers, **kwargs), 400)
    assert error["code"] == "validation_error"
    assert error["field"] == field


def test_upload_requires_exactly_one_file(client, agent_headers):
    missing = client.post(f"{API}/photos", data={"date": DAY}, headers=agent_headers)
    assert assert_error(missing, 400)["field"] == "file"
    two = client.post(
        f"{API}/photos",
        data={"date": DAY},
        files=[("file", ("a.jpg", image_bytes())), ("file", ("b.jpg", image_bytes()))],
        headers=agent_headers,
    )
    assert assert_error(two, 400)["field"] == "file"
    as_json = client.post(f"{API}/photos", json={"date": DAY}, headers=agent_headers)
    assert assert_error(as_json, 400)["field"] == "file"


@pytest.mark.parametrize(
    "content",
    [
        b"definitely not an image",
        b"",
        image_bytes("GIF", mode="P", color=1),
        image_bytes("BMP"),
        image_bytes("TIFF"),
    ],
    ids=["text", "empty", "gif", "bmp", "tiff"],
)
def test_non_image_or_unsupported_format_is_rejected(project, client, agent_headers, content):
    error = assert_error(upload(client, content, agent_headers), 400)
    assert error["code"] == "validation_error" and error["field"] == "file"
    assert photo_files(project) == []


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_corrupt_image_is_rejected(project, client, agent_headers, fmt):
    noise = random.Random(7)
    image = Image.frombytes("RGB", (256, 256), bytes(noise.getrandbits(8) for _ in range(256 * 256 * 3)))
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    truncated = buffer.getvalue()[: len(buffer.getvalue()) // 2]
    error = assert_error(upload(client, truncated, agent_headers), 400)
    assert error["field"] == "file"
    assert photo_files(project) == []


def test_pixel_limit_is_enforced_before_decoding(client, agent_headers):
    # 7072 x 7072 is just over 50 million pixels, but the 1-bit PNG is tiny.
    content = image_bytes("PNG", size=(7072, 7072), mode="1", color=0)
    assert len(content) < LIMIT
    error = assert_error(upload(client, content, agent_headers), 400)
    assert error["field"] == "file" and "5000" in error["message"]


def test_body_over_two_megabytes_is_413(project, client, agent_headers):
    content = image_bytes() + b"\0" * LIMIT
    error = assert_error(upload(client, content, agent_headers), 413)
    assert error["code"] == "payload_too_large"

    # Without Content-Length (chunked), the streamed body is counted as well.
    boundary = "techo-test-boundary"

    def chunks():
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\n'.encode()
        for _ in range(3):
            yield b"\0" * (LIMIT // 2)
        yield f"\r\n--{boundary}--\r\n".encode()

    streamed = client.post(
        f"{API}/photos",
        content=chunks(),
        headers={**agent_headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert assert_error(streamed, 413)["code"] == "payload_too_large"
    assert photo_files(project) == []


def test_upload_just_under_the_limit_is_accepted(client, agent_headers):
    # Padding after the image is ignored by the decoder; the whole request stays under 2 MiB.
    content = image_bytes() + b"\0" * (LIMIT - 4096)
    response = upload(client, content, agent_headers)
    assert response.status_code == 201, response.text


def test_exif_orientation_is_applied_and_all_metadata_is_stripped(client, agent_headers):
    original = oriented_jpeg_with_gps()
    source = Image.open(io.BytesIO(original))
    assert source.getexif().get_ifd(ExifTags.IFD.GPSInfo)  # the fixture really carries GPS
    item = create_photo(client, agent_headers, content=original)
    assert (item["width"], item["height"]) == (100, 200)
    for size in ("full", "thumb"):
        response = fetch(client, item, agent_headers, size)
        assert response.status_code == 200
        result = Image.open(io.BytesIO(response.content))
        assert result.format == "WEBP"
        assert result.size == (100, 200)  # already below both size limits
        rgb = result.convert("RGB")
        top, bottom = rgb.getpixel((50, 20)), rgb.getpixel((50, 180))
        assert top[0] > 200 and top[2] < 60, top  # red half rotated to the top
        assert bottom[2] > 200 and bottom[0] < 60, bottom
        assert len(result.getexif()) == 0
        assert not {"exif", "xmp", "icc_profile"} & set(result.info)
        for marker in (b"Exif", b"EXIF", b"XMP ", b"ICCP", b"TestPhone"):
            assert marker not in response.content


def test_full_and_thumb_sizes(client, agent_headers):
    content = image_bytes(size=(3000, 2000), quality=60)
    item = create_photo(client, agent_headers, content=content)
    assert (item["width"], item["height"]) == (1600, 1067)
    full = fetch(client, item, agent_headers)
    default = Image.open(io.BytesIO(full.content))
    assert default.size == (1600, 1067)
    assert len(full.content) <= 400 * 1024
    thumb = fetch(client, item, agent_headers, "thumb")
    assert Image.open(io.BytesIO(thumb.content)).size == (400, 267)
    assert fetch(client, item, agent_headers, "full").content == full.content
    tall = create_photo(client, agent_headers, content=image_bytes(size=(500, 2400)))
    assert (tall["width"], tall["height"]) == (333, 1600)
    small = create_photo(client, agent_headers, content=image_bytes(size=(120, 90)))
    assert (small["width"], small["height"]) == (120, 90)
    assert Image.open(io.BytesIO(fetch(client, small, agent_headers, "thumb").content)).size == (120, 90)


def test_full_quality_steps_down_towards_the_size_target():
    noise = random.Random(3)
    image = Image.frombytes("RGB", (1600, 1600), noise.randbytes(1600 * 1600 * 3))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    processed = images.process(buffer.getvalue())
    at_80 = io.BytesIO()
    image.save(at_80, "WEBP", quality=80, method=4)
    assert len(at_80.getvalue()) > images.FULL_TARGET_BYTES
    assert len(processed.full.data) < len(at_80.getvalue())


def test_photo_read_requires_auth_and_sets_cache_headers(client, agent_headers):
    item = create_photo(client, agent_headers)
    anonymous = fetch(client, item)
    assert_error(anonymous, 401)
    assert anonymous.headers["Cache-Control"] == "no-store"
    assert_error(fetch(client, item, {"X-Techo-Token": "wrong-token"}), 401)

    response = fetch(client, item, agent_headers, "thumb")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/webp"
    assert response.headers["Cache-Control"] == CACHE
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    # The cache-busting query parameter used by the frontend is accepted.
    busted = client.get(
        f"{API}/photos/{item['id']}", params={"size": "thumb", "h": item["hash"]}, headers=agent_headers
    )
    assert busted.status_code == 200 and busted.content == response.content

    login(client)
    browser = fetch(client, item)
    assert browser.status_code == 200 and browser.headers["Cache-Control"] == CACHE

    missing = client.get(f"{API}/photos/99999")
    assert_error(missing, 404)
    assert missing.headers["Cache-Control"] == "no-store"
    bad_size = fetch(client, item, size="huge")
    assert assert_error(bad_size, 400)["field"] == "size"
    assert bad_size.headers["Cache-Control"] == "no-store"
    # Other API responses keep no-store.
    assert get_view_response(client).headers["Cache-Control"] == "no-store"


def get_view_response(client):
    return client.get(f"{API}/month", params={"ym": MONTH})


def test_browser_upload_checks_origin(client):
    login(client)
    response = upload(client, image_bytes(), {"Origin": "https://evil.example"})
    assert_error(response, 403)
    cross = upload(client, image_bytes(), {"Sec-Fetch-Site": "cross-site"})
    assert_error(cross, 403)
    item = create_photo(client, {"Origin": ORIGIN})
    assert item["author"] == "human"


def test_patch_requires_if_match_and_updates_caption_and_date(project, browser, agent_headers):
    item = create_photo(browser, agent_headers, caption="first")
    url = f"{API}/photos/{item['id']}"
    assert assert_error(browser.patch(url, json={"caption": "x"}), 400)["field"] == "If-Match"
    for bad in ("*", 'W/"' + item["updated_at"] + '"', item["updated_at"], '"not a time"'):
        assert_error(browser.patch(url, json={"caption": "x"}, headers={"If-Match": bad}), 400)
    files_before = photo_files(project)

    response = browser.patch(url, json={"caption": "", "date": "2026-11-20"}, headers=match_headers(item))
    assert response.status_code == 200, response.text
    updated = response.json()
    assert response.headers["ETag"] == match_headers(updated)["If-Match"]
    assert updated["caption"] is None and updated["date"] == "2026-11-20"
    assert updated["author"] == "agent" and updated["updated_by"] == "human"
    assert updated["hash"] == item["hash"]
    assert photo_files(project) == files_before  # files stay where they were
    assert fetch(browser, updated).status_code == 200
    assert get_view(browser, day=DAY)["photos"] == []
    assert get_view(browser, day="2026-11-20")["photos"] == [updated]

    stale = browser.patch(url, json={"caption": "late"}, headers=match_headers(item))
    assert assert_error(stale, 409)["code"] == "conflict"
    for payload, field in (
        ({}, None),
        ({"date": None}, "date"),
        ({"hash": "abc"}, "hash"),
        ({"width": 5}, "width"),
        ({"caption": "字" * 201}, "caption"),
    ):
        error = assert_error(browser.patch(url, json=payload, headers=match_headers(updated)), 400)
        if field is not None:
            assert error["field"] == field
    assert_error(
        browser.patch(f"{API}/photos/99999", json={"caption": "x"}, headers=match_headers(item)), 404
    )


def test_delete_requires_if_match_soft_deletes_and_keeps_files(project, browser, agent_headers):
    item = create_photo(browser, agent_headers)
    url = f"{API}/photos/{item['id']}"
    assert_error(browser.delete(url), 400)
    stale = {"updated_at": "2026-01-01T00:00:00.000000+08:00"}
    assert_error(browser.delete(url, headers=match_headers(stale)), 409)
    files = photo_files(project)
    response = browser.delete(url, headers=match_headers(item))
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert photo_files(project) == files
    assert_error(fetch(browser, item), 404)
    assert_error(fetch(browser, item, size="thumb"), 404)
    assert get_view(browser, month=MONTH)["photos"] == []
    assert_error(browser.delete(url, headers=match_headers(item)), 404)
    assert_error(browser.patch(url, json={"caption": "x"}, headers=match_headers(item)), 404)


def test_month_and_day_include_photos_sorted_by_date_then_id(browser, agent_headers):
    later = create_photo(browser, agent_headers, date="2026-11-20")
    first = create_photo(browser, agent_headers, date=DAY)
    second = create_photo(browser, date=DAY)
    other_month = create_photo(browser, date="2026-12-01")
    gone = create_photo(browser, date=DAY)
    assert browser.delete(f"{API}/photos/{gone['id']}", headers=match_headers(gone)).status_code == 200
    month = get_view(browser, month=MONTH)
    assert [photo["id"] for photo in month["photos"]] == [first["id"], second["id"], later["id"]]
    assert month["photos"][0] == first
    assert [photo["id"] for photo in get_view(browser, day=DAY)["photos"]] == [first["id"], second["id"]]
    assert [photo["id"] for photo in get_view(browser, month="2026-12")["photos"]] == [other_month["id"]]


def test_photo_changes_are_recorded_for_the_other_party(browser, agent_headers):
    agent_photo = create_photo(browser, agent_headers, caption="from agent")
    human_photo = create_photo(browser, caption="from human")
    seen_by_human = get_changes(browser)["changes"]
    assert [(change["type"], change["id"], change["op"]) for change in seen_by_human] == [
        ("photo", agent_photo["id"], "created")
    ]
    assert seen_by_human[0]["data"] == agent_photo
    assert "full_path" not in seen_by_human[0]["data"]

    patched = browser.patch(
        f"{API}/photos/{agent_photo['id']}", json={"caption": "edited"}, headers=match_headers(agent_photo)
    ).json()
    assert browser.delete(f"{API}/photos/{human_photo['id']}", headers=match_headers(human_photo)).json() == {
        "ok": True
    }
    seen_by_agent = get_changes(browser, agent_headers)["changes"]
    assert [(change["type"], change["id"], change["op"]) for change in seen_by_agent] == [
        ("photo", human_photo["id"], "created"),
        ("photo", agent_photo["id"], "updated"),
        ("photo", human_photo["id"], "deleted"),
    ]
    assert seen_by_agent[1]["data"] == patched
    assert seen_by_agent[2]["data"]["deleted_at"] is not None


def test_failed_commit_removes_written_files_and_row(project, client, agent_headers, monkeypatch):
    def fail(self, kind, *args, **kwargs):
        raise IntegrityError("injected failure", {}, RuntimeError("database failure"))

    monkeypatch.setattr(Changes, "append", fail)
    response = upload(client, image_bytes(), agent_headers)
    assert response.status_code == 500
    monkeypatch.undo()
    assert photo_files(project) == []
    assert get_view(client, month=MONTH, headers=agent_headers)["photos"] == []
    with sqlite3.connect(project.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM photos").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM changes").fetchone() == (0,)
    item = create_photo(client, agent_headers)
    assert fetch(client, item, agent_headers).status_code == 200


def test_photos_are_not_accepted_by_batch(client, agent_headers):
    response = client.post(
        f"{API}/batch", json={"items": [{"type": "photo", "date": DAY}]}, headers=agent_headers
    )
    assert assert_error(response, 400, index=0)["code"] == "validation_error"


def test_photo_storage_follows_the_configured_data_directory(project, client, agent_headers):
    assert client.app.state.settings.photos_path == project.root / "data" / "photos"
    create_photo(client, agent_headers)
    assert all(path.is_relative_to(project.root) for path in photo_files(project))
    assert not any(name.endswith(".tmp") for _, _, names in os.walk(project.root) for name in names)
