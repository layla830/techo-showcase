from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

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
from test_photos import create_photo

PAGE = f"day:{DAY}"
STROKE_FIELDS = {"id", "page", "color", "width", "points", "author", "created_at"}


def sticker(**overrides):
    return {
        "item_type": "sticker",
        "ref": "pack:tape-sage",
        "text": None,
        "color": None,
        "x": 0.5,
        "y": 0.12,
        "scale": 1,
        "rotation": -4,
        "z": 0,
        **overrides,
    }


def text_item(**overrides):
    return {
        "item_type": "text",
        "ref": "hand",
        "text": "sushi date",
        "color": "#f4f2ee",
        "x": 0.6,
        "y": 0.8,
        "scale": 1,
        "rotation": 0,
        "z": 2,
        **overrides,
    }


def put(client, items, version=None, headers=None, page=PAGE):
    return client.put(
        f"{API}/decorations",
        params={"page": page},
        json={"version": version, "items": items},
        headers=headers,
    )


def read(client, headers=None, page=PAGE):
    response = client.get(f"{API}/decorations", params={"page": page}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def stroke(points=None, **overrides):
    return {
        "color": "#f4f2ee",
        "width": 0.006,
        "points": [1200, 3400, 128, 1215, 3410, 140] if points is None else points,
        **overrides,
    }


def add_strokes(client, strokes, headers=None, page=PAGE):
    return client.post(f"{API}/strokes", params={"page": page}, json={"strokes": strokes}, headers=headers)


def table_count(project, table):
    with sqlite3.connect(project.database_path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- decorations -----------------------------------------------------------------


def test_undecorated_page_reads_empty(client, agent_headers):
    assert read(client, agent_headers) == {"page": PAGE, "version": None, "items": []}
    assert read(client, agent_headers, page=f"month:{MONTH}") == {
        "page": f"month:{MONTH}",
        "version": None,
        "items": [],
    }


def test_put_replaces_the_page_and_sorts_by_z_then_original_order(browser, agent_headers):
    photo = create_photo(browser, agent_headers)
    items = [
        text_item(z=2),
        sticker(ref="emoji:🍣", z=1, x=0.1),
        {**sticker(), "item_type": "photo", "ref": str(photo["id"]), "text": "  polaroid  ", "z": 1},
        sticker(z=0, x=-0.25, y=1.25, scale=8, rotation=360),
    ]
    response = put(browser, items)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == PAGE
    assert_stamp(body["version"])
    assert [(item["z"], item["item_type"]) for item in body["items"]] == [
        (0, "sticker"),
        (1, "sticker"),
        (1, "photo"),
        (2, "text"),
    ]
    assert body["items"][2]["text"] == "polaroid"
    assert body["items"][0] == {**items[3], "scale": 8.0, "rotation": 360.0}
    assert read(browser) == body
    assert read(browser, agent_headers) == body

    replaced = put(browser, [sticker(ref="emoji:🌿")], body["version"])
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["version"] > body["version"]
    assert [item["ref"] for item in read(browser)["items"]] == ["emoji:🌿"]


def test_defaults_for_optional_fields(client, agent_headers):
    response = put(
        client, [{"item_type": "sticker", "ref": "emoji:⭐", "x": 0.5, "y": 0.5}], headers=agent_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {
            "item_type": "sticker",
            "ref": "emoji:⭐",
            "text": None,
            "color": None,
            "x": 0.5,
            "y": 0.5,
            "scale": 1.0,
            "rotation": 0.0,
            "z": 0,
        }
    ]


def test_version_conflict_returns_409_and_keeps_data(project, client, agent_headers):
    first = put(client, [sticker()], headers=agent_headers).json()
    stale_null = put(client, [text_item()], None, agent_headers)
    assert assert_error(stale_null, 409)["code"] == "conflict"
    second = put(client, [sticker(ref="pack:b")], first["version"], agent_headers).json()
    stale = put(client, [text_item()], first["version"], agent_headers)
    assert assert_error(stale, 409)["field"] == "version"
    never = put(client, [sticker()], first["version"], agent_headers, page="day:2026-11-10")
    assert_error(never, 409)
    assert read(client, agent_headers) == second
    assert read(client, agent_headers, page="day:2026-11-10")["version"] is None
    assert table_count(project, "decorations") == 1
    # The version may be sent in another offset; it names the same instant.
    utc = datetime.fromisoformat(second["version"]).astimezone(timezone.utc).isoformat()
    assert put(client, [], utc, agent_headers).status_code == 200


def test_empty_items_clear_the_page_with_a_new_version(client, agent_headers):
    first = put(client, [sticker(), text_item()], headers=agent_headers).json()
    cleared = put(client, [], first["version"], agent_headers)
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["items"] == [] and body["version"] is not None and body["version"] > first["version"]
    assert read(client, agent_headers) == body
    assert get_view(client, month=MONTH, headers=agent_headers)["decorated_pages"] == []
    assert_error(put(client, [sticker()], None, agent_headers), 409)


@pytest.mark.parametrize(
    ("item", "field"),
    [
        (sticker(item_type="video"), "item_type"),
        (sticker(extra=1), "extra"),
        (sticker(ref=None), "ref"),
        (sticker(ref=""), "ref"),
        (sticker(ref="tape-sage"), "ref"),
        (sticker(ref="pack:" + "x" * 96), "ref"),
        (sticker(text="hello"), "text"),
        (sticker(color="red"), "color"),
        (sticker(color="#fff"), "color"),
        (sticker(x=1.26), "x"),
        (sticker(y=-0.26), "y"),
        (sticker(x="0.5"), "x"),
        (sticker(x=True), "x"),
        (sticker(scale=0.09), "scale"),
        (sticker(scale=8.01), "scale"),
        (sticker(rotation=-361), "rotation"),
        (sticker(z=-1), "z"),
        (sticker(z=10001), "z"),
        (sticker(z=1.5), "z"),
        ({"item_type": "sticker", "ref": "emoji:x", "y": 0.5}, "x"),
        (text_item(text=None), "text"),
        (text_item(text="   "), "text"),
        (text_item(text="字" * 201), "text"),
        (text_item(ref=""), "ref"),
        (text_item(ref="s" * 41), "ref"),
        ({**sticker(), "item_type": "photo", "ref": "abc"}, "ref"),
        ({**sticker(), "item_type": "photo", "ref": "012"}, "ref"),
        ({**sticker(), "item_type": "photo", "ref": None}, "ref"),
        ({**sticker(), "item_type": "photo", "ref": "1", "text": "字" * 201}, "text"),
    ],
)
def test_item_validation_reports_field_and_index(client, agent_headers, item, field):
    response = put(client, [sticker(), item], headers=agent_headers)
    error = assert_error(response, 400, index=1)
    assert error["code"] == "validation_error"
    assert error["field"] == f"items.1.{field}", error
    assert read(client, agent_headers)["version"] is None


def test_text_item_may_omit_style_and_values_at_the_bounds_pass(client, agent_headers):
    items = [
        text_item(ref=None, text="  " + "字" * 200 + "  ", z=10000),
        sticker(ref="pack:" + "x" * 95, x=1.25, y=-0.25, scale=0.1, rotation=-360, color="#ABCDEF"),
    ]
    response = put(client, items, headers=agent_headers)
    assert response.status_code == 200, response.text
    assert response.json()["items"][1]["text"] == "字" * 200


def test_non_finite_numbers_are_rejected(client, agent_headers):
    for literal in ("Infinity", "NaN", "-Infinity"):
        body = '{"version": null, "items": [{"item_type": "sticker", "ref": "emoji:x", "x": %s, "y": 0.5}]}'
        response = client.put(
            f"{API}/decorations",
            params={"page": PAGE},
            content=(body % literal).encode(),
            headers={**agent_headers, "Content-Type": "application/json"},
        )
        assert assert_error(response, 400, index=0)["field"] == "items.0.x"


def test_body_shape_validation(client, agent_headers):
    url = f"{API}/decorations"
    missing_version = client.put(url, params={"page": PAGE}, json={"items": []}, headers=agent_headers)
    assert assert_error(missing_version, 400)["field"] == "version"
    unknown = client.put(
        url, params={"page": PAGE}, json={"version": None, "items": [], "x": 1}, headers=agent_headers
    )
    assert assert_error(unknown, 400)["field"] == "x"
    bad_version = put(client, [], "yesterday", agent_headers)
    assert assert_error(bad_version, 400)["field"] == "version"
    too_many = put(client, [sticker() for _ in range(201)], headers=agent_headers)
    assert assert_error(too_many, 400)["field"] == "items"
    assert put(client, [sticker() for _ in range(200)], headers=agent_headers).status_code == 200


@pytest.mark.parametrize(
    "page",
    ["day:2026-02-30", "day:2026-11-8", "month:2026-13", "month:2026-1", "week:2026-W46", "2026-11-08", ""],
)
def test_invalid_page_names(client, agent_headers, page):
    for response in (
        client.get(f"{API}/decorations", params={"page": page}, headers=agent_headers),
        put(client, [], headers=agent_headers, page=page),
        client.get(f"{API}/strokes", params={"page": page}, headers=agent_headers),
        add_strokes(client, [stroke()], agent_headers, page=page),
    ):
        assert assert_error(response, 400)["field"] == "page"
    assert assert_error(client.get(f"{API}/decorations", headers=agent_headers), 400)["field"] == "page"


def test_photo_items_must_reference_live_photos(browser, agent_headers):
    photo = create_photo(browser, agent_headers)
    gone = create_photo(browser, agent_headers)
    assert browser.delete(f"{API}/photos/{gone['id']}", headers=match_headers(gone)).status_code == 200

    def photo_item(ref):
        return {**sticker(), "item_type": "photo", "ref": ref}

    for ref in (str(gone["id"]), "99999"):
        error = assert_error(put(browser, [photo_item(str(photo["id"])), photo_item(ref)]), 400, index=1)
        assert error["field"] == "items.1.ref"
    assert read(browser)["version"] is None
    assert put(browser, [photo_item(str(photo["id"]))]).status_code == 200


def test_decorations_require_auth_and_browser_origin(client):
    assert_error(client.get(f"{API}/decorations", params={"page": PAGE}), 401)
    assert_error(put(client, []), 401)
    login(client)
    assert_error(put(client, [sticker()], headers={"Origin": "https://evil.example"}), 403)
    response = put(client, [sticker()], headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


# --- strokes ---------------------------------------------------------------------


def test_add_and_list_strokes(browser, agent_headers):
    response = add_strokes(browser, [stroke(), stroke(color="#123abc", width=0.05, points=[-2500, 12500, 0])])
    assert response.status_code == 201, response.text
    created = response.json()["strokes"]
    assert len(created) == 2 and created[0]["id"] < created[1]["id"]
    for item in created:
        assert set(item) == STROKE_FIELDS
        assert item["page"] == PAGE and item["author"] == "human"
        assert_stamp(item["created_at"])
    assert created[0]["points"] == [1200, 3400, 128, 1215, 3410, 140]
    assert created[1]["color"] == "#123abc" and created[1]["width"] == 0.05
    agent = add_strokes(browser, [stroke(width=0.0005)], agent_headers).json()["strokes"]
    assert agent[0]["author"] == "agent"
    listed = browser.get(f"{API}/strokes", params={"page": PAGE}).json()
    assert listed == {"page": PAGE, "strokes": created + agent}
    other = browser.get(f"{API}/strokes", params={"page": f"month:{MONTH}"}).json()
    assert other == {"page": f"month:{MONTH}", "strokes": []}


@pytest.mark.parametrize(
    ("bad", "field"),
    [
        (stroke(points=[]), "points"),
        (stroke(points=[1, 2]), "points"),
        (stroke(points=[1, 2, 3, 4]), "points"),
        (stroke(points=[0, 0, 0] * 5001), "points"),
        (stroke(points=[12501, 0, 128]), "points"),
        (stroke(points=[0, -2501, 128]), "points"),
        (stroke(points=[0, 0, 256]), "points"),
        (stroke(points=[0, 0, -1]), "points"),
        (stroke(points=[0.5, 0, 128]), "points.0"),
        (stroke(points=[True, 0, 128]), "points.0"),
        (stroke(points=["1", 0, 128]), "points.0"),
        (stroke(width=0.0004), "width"),
        (stroke(width=0.051), "width"),
        (stroke(width="0.01"), "width"),
        (stroke(color="#ggg000"), "color"),
        (stroke(color=None), "color"),
        ({"color": "#ffffff", "points": [0, 0, 0]}, "width"),
        (stroke(author="agent"), "author"),
    ],
)
def test_stroke_validation_rejects_the_whole_batch(project, client, agent_headers, bad, field):
    response = add_strokes(client, [stroke(), bad, stroke()], agent_headers)
    error = assert_error(response, 400, index=1)
    assert error["field"] == f"strokes.1.{field}", error
    assert table_count(project, "strokes") == 0


def test_stroke_point_bounds(client, agent_headers):
    points = [0, 0, 0] * 5000
    response = add_strokes(client, [stroke(points=points), stroke(points=[12500, -2500, 255])], agent_headers)
    assert response.status_code == 201, response.text
    assert len(response.json()["strokes"][0]["points"]) == 15000


def test_stroke_batch_size(client, agent_headers):
    assert assert_error(add_strokes(client, [], agent_headers), 400)["field"] == "strokes"
    assert assert_error(add_strokes(client, [stroke()] * 51, agent_headers), 400)["field"] == "strokes"
    assert add_strokes(client, [stroke()] * 50, agent_headers).status_code == 201


def test_page_stroke_limit_is_3000(project, client, agent_headers):
    small = stroke(points=[0, 0, 128])
    for _ in range(59):
        assert add_strokes(client, [small] * 50, agent_headers).status_code == 201
    assert add_strokes(client, [small] * 49, agent_headers).status_code == 201
    over = add_strokes(client, [small, small], agent_headers)
    assert assert_error(over, 409)["code"] == "conflict"
    last = add_strokes(client, [small], agent_headers)
    assert last.status_code == 201
    assert_error(add_strokes(client, [small], agent_headers), 409)
    assert table_count(project, "strokes") == 3000
    # Another page has its own budget, and deleting frees room.
    assert add_strokes(client, [small], agent_headers, page="day:2026-11-10").status_code == 201
    stroke_id = last.json()["strokes"][0]["id"]
    assert client.delete(f"{API}/strokes/{stroke_id}", headers=agent_headers).status_code == 200
    assert add_strokes(client, [small], agent_headers).status_code == 201


def test_delete_stroke_is_soft_idempotent_and_needs_no_if_match(project, browser, agent_headers):
    created = add_strokes(browser, [stroke(), stroke()], agent_headers).json()["strokes"]
    url = f"{API}/strokes/{created[0]['id']}"
    for _ in range(2):
        response = browser.delete(url)
        assert response.status_code == 200 and response.json() == {"ok": True}
    listed = browser.get(f"{API}/strokes", params={"page": PAGE}).json()["strokes"]
    assert listed == [created[1]]
    assert table_count(project, "strokes") == 2
    assert_error(browser.delete(f"{API}/strokes/99999"), 404)
    assert_error(browser.delete(url, headers={"Origin": "https://evil.example"}), 403)


def test_strokes_require_auth(client):
    assert_error(client.get(f"{API}/strokes", params={"page": PAGE}), 401)
    assert_error(add_strokes(client, [stroke()]), 401)
    assert_error(client.delete(f"{API}/strokes/1"), 401)


# --- month markers and change feed -----------------------------------------------


def test_month_lists_decorated_pages(client, agent_headers):
    assert get_view(client, month=MONTH, headers=agent_headers)["decorated_pages"] == []
    put(client, [sticker()], headers=agent_headers, page="day:2026-11-30")
    put(client, [sticker()], headers=agent_headers, page=f"month:{MONTH}")
    put(client, [sticker()], headers=agent_headers, page="day:2026-12-01")
    put(client, [sticker()], headers=agent_headers, page="month:2026-10")
    first = add_strokes(client, [stroke()], agent_headers, page="day:2026-11-01").json()["strokes"][0]
    add_strokes(client, [stroke()], agent_headers, page="day:2026-11-30")
    removed = add_strokes(client, [stroke()], agent_headers, page="day:2026-11-15").json()["strokes"][0]
    client.delete(f"{API}/strokes/{removed['id']}", headers=agent_headers)
    month = get_view(client, month=MONTH, headers=agent_headers)
    assert month["decorated_pages"] == ["day:2026-11-01", "day:2026-11-30", f"month:{MONTH}"]
    assert "decorated_pages" not in get_view(client, day="2026-11-30", headers=agent_headers)
    client.delete(f"{API}/strokes/{first['id']}", headers=agent_headers)
    assert get_view(client, month=MONTH, headers=agent_headers)["decorated_pages"] == [
        "day:2026-11-30",
        f"month:{MONTH}",
    ]
    assert get_view(client, month="2026-12", headers=agent_headers)["decorated_pages"] == ["day:2026-12-01"]


def test_month_peeks_top_stickers_and_photos_per_page(browser, agent_headers):
    assert get_view(browser, month=MONTH, headers=agent_headers)["page_peeks"] == {}
    photo = create_photo(browser, agent_headers)
    put(
        browser,
        [
            sticker(ref="pack:fig", z=0),
            text_item(z=1),
            sticker(ref="emoji:🌿", z=2),
            {**sticker(), "item_type": "photo", "ref": str(photo["id"]), "z": 3},
        ],
        headers=agent_headers,
        page="day:2026-11-11",
    )
    put(browser, [text_item()], headers=agent_headers, page="day:2026-11-12")
    peeks = get_view(browser, month=MONTH, headers=agent_headers)["page_peeks"]
    assert list(peeks) == ["day:2026-11-11"]
    shown = peeks["day:2026-11-11"]
    assert [(x["item_type"], x["ref"]) for x in shown] == [
        ("photo", str(photo["id"])),
        ("sticker", "emoji:🌿"),
        ("sticker", "pack:fig"),
    ]
    assert shown[0] == {
        "item_type": "photo",
        "ref": str(photo["id"]),
        "x": 0.5,
        "y": 0.12,
        "scale": 1,
        "rotation": -4,
        "z": 3,
    }


def test_decorations_and_strokes_stay_out_of_the_change_feed(browser, agent_headers):
    put(browser, [sticker()])
    created = add_strokes(browser, [stroke()]).json()["strokes"]
    browser.delete(f"{API}/strokes/{created[0]['id']}")
    put(browser, [text_item()], read(browser)["version"], agent_headers)
    add_strokes(browser, [stroke()], agent_headers)
    assert get_changes(browser)["changes"] == []
    assert get_changes(browser, agent_headers)["changes"] == []


def test_page_version_is_compared_as_an_instant_when_timezone_changes(browser, agent_headers):
    from zoneinfo import ZoneInfo

    from techo import clock

    original_zone = clock.current_zone()
    try:
        first = put(browser, [sticker()], headers=agent_headers).json()
        clock.configure(ZoneInfo("UTC"))
        second = put(browser, [sticker()], version=first["version"], headers=agent_headers)
        assert second.status_code == 200, second.text
    finally:
        clock.configure(original_zone)
