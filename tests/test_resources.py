from __future__ import annotations

from conftest import (
    API,
    DAY,
    MONTH,
    RESOURCE_TYPES,
    TEXT_FIELDS,
    assert_error,
    assert_record,
    create_item,
    get_view,
    match_headers,
    patch_item,
    sample,
    view_items,
)


def test_four_resource_crud_and_soft_deletion_follow_the_response_contract(client, agent_headers):
    patches = {
        "notes": {"text": "revised note", "mood": "happy"},
        "media": {"title": "revised media", "kind": "film"},
        "events": {"title": "revised event", "time": "20:15"},
        "goals": {"text": "revised goal", "status": "done"},
    }
    for resource in RESOURCE_TYPES:
        payload = sample(resource)
        item = create_item(client, resource, payload, agent_headers)
        assert_record(item, resource, payload, author="agent")
        if resource == "goals":
            assert item["status"] == "open"
            assert type(item["sort"]) is int and item["sort"] >= 0
        revised = patch_item(
            client, resource, item["id"], patches[resource], agent_headers, version=item["updated_at"]
        )
        assert_record(revised, resource, {**payload, **patches[resource]}, author="agent")
        assert revised["id"] == item["id"]
        assert revised["created_at"] == item["created_at"]
        for view in (
            get_view(client, day=DAY, headers=agent_headers),
            get_view(client, month=MONTH, headers=agent_headers),
        ):
            assert view_items(view, resource) == [revised]
        deleted = client.delete(
            f"{API}/{resource}/{item['id']}", headers=match_headers(revised, agent_headers)
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        for view in (
            get_view(client, day=DAY, headers=agent_headers),
            get_view(client, month=MONTH, headers=agent_headers),
        ):
            assert view_items(view, resource) == []
        assert_error(
            client.patch(
                f"{API}/{resource}/{item['id']}",
                json=patches[resource],
                headers=match_headers(revised, agent_headers),
            ),
            404,
        )
        assert_error(
            client.delete(f"{API}/{resource}/2147483647", headers=match_headers(revised, agent_headers)),
            404,
        )


def test_cross_author_updates_preserve_the_creator_and_record_the_actual_editor(browser, agent_headers):
    for resource in RESOURCE_TYPES:
        for creator, creator_headers, editor, editor_headers in (
            ("agent", agent_headers, "human", None),
            ("human", None, "agent", agent_headers),
        ):
            payload = sample(resource, creator)
            original = create_item(browser, resource, payload, creator_headers)
            assert_record(original, resource, payload, author=creator)
            field = TEXT_FIELDS[resource]
            changes = {field: f"edited by {editor}"}
            updated = patch_item(
                browser, resource, original["id"], changes, editor_headers, version=original["updated_at"]
            )
            assert_record(updated, resource, {**payload, **changes}, author=creator, updated_by=editor)
            assert updated["created_at"] == original["created_at"]
            reverted = patch_item(
                browser,
                resource,
                original["id"],
                {field: payload[field]},
                creator_headers,
                version=updated["updated_at"],
            )
            assert reverted["author"] == reverted["updated_by"] == creator


def test_protected_metadata_and_unknown_fields_are_rejected_on_create_and_patch(client, agent_headers):
    forbidden = {
        "author": "human",
        "updated_by": "human",
        "id": 1000,
        "created_at": "2001-01-01T00:00:00+08:00",
        "updated_at": "2001-01-01T00:00:00+08:00",
        "deleted_at": None,
        "unknown_field": "silently accepting this would violate the contract",
    }
    for resource in RESOURCE_TYPES:
        original = create_item(client, resource, sample(resource), agent_headers)
        for field, value in forbidden.items():
            assert_error(
                client.post(
                    f"{API}/{resource}",
                    json={**sample(resource, "forged"), field: value},
                    headers=agent_headers,
                ),
                400,
            )
            assert_error(
                client.patch(
                    f"{API}/{resource}/{original['id']}",
                    json={field: value},
                    headers=match_headers(original, agent_headers),
                ),
                400,
            )
        assert view_items(get_view(client, month=MONTH, headers=agent_headers), resource) == [original]


def test_patch_null_clears_nullable_fields_and_preserves_omitted_fields(client, agent_headers):
    for resource, nullable_fields in (
        ("notes", ("mood",)),
        ("media", ("note",)),
        ("events", ("time", "place")),
    ):
        payload = sample(resource)
        item = create_item(client, resource, payload, agent_headers)
        expected = dict(payload)
        updated = item
        for field in nullable_fields:
            expected[field] = None
            updated = patch_item(
                client, resource, item["id"], {field: None}, agent_headers, version=updated["updated_at"]
            )
            assert_record(updated, resource, expected, author="agent")
        assert view_items(get_view(client, day=DAY, headers=agent_headers), resource) == [updated]


def test_required_fields_cannot_be_cleared_by_patch_or_create(client, agent_headers):
    required = {
        "notes": ("date", "text"),
        "media": ("date", "kind", "title"),
        "events": ("date", "title", "kind"),
        "goals": ("scope", "period", "text", "status", "sort"),
    }
    for resource, fields in required.items():
        item = create_item(client, resource, sample(resource), agent_headers)
        for field in fields:
            assert_error(
                client.patch(
                    f"{API}/{resource}/{item['id']}",
                    json={field: None},
                    headers=match_headers(item, agent_headers),
                ),
                400,
            )
            assert_error(
                client.post(
                    f"{API}/{resource}", json={**sample(resource, "null"), field: None}, headers=agent_headers
                ),
                400,
            )
        assert view_items(get_view(client, month=MONTH, headers=agent_headers), resource) == [item]


def test_required_text_is_trimmed_nonblank_and_notes_allow_exactly_five_hundred_characters(
    client, agent_headers
):
    for resource, field in TEXT_FIELDS.items():
        payload = sample(resource)
        payload[field] = "  去掉两端空白  "
        original = create_item(client, resource, payload, agent_headers)
        assert original[field] == "去掉两端空白"
        for blank in ("", "   ", "\t\n  "):
            assert_error(
                client.post(
                    f"{API}/{resource}", json={**sample(resource), field: blank}, headers=agent_headers
                ),
                400,
            )
            assert_error(
                client.patch(
                    f"{API}/{resource}/{original['id']}",
                    json={field: blank},
                    headers=match_headers(original, agent_headers),
                ),
                400,
            )
    valid = create_item(
        client, "notes", {"date": DAY, "text": "字" * 500, "mood": "any short words"}, agent_headers
    )
    assert valid["text"] == "字" * 500
    assert_error(
        client.post(f"{API}/notes", json={"date": DAY, "text": "字" * 501}, headers=agent_headers), 400
    )
    assert_error(
        client.patch(
            f"{API}/notes/{valid['id']}",
            json={"text": "字" * 501},
            headers=match_headers(valid, agent_headers),
        ),
        400,
    )
    still_valid = patch_item(
        client, "notes", valid["id"], {"text": "文" * 500}, agent_headers, version=valid["updated_at"]
    )
    assert still_valid["text"] == "文" * 500


def test_invalid_calendar_dates_times_enums_and_nonexistent_iso_weeks_return_400(client, agent_headers):
    for resource in ("notes", "media", "events"):
        for invalid in ("2026-02-29", "2026-04-31", "2026-1-09", "not-a-date"):
            assert_error(
                client.post(
                    f"{API}/{resource}", json={**sample(resource), "date": invalid}, headers=agent_headers
                ),
                400,
            )
    for invalid in ("24:00", "12:60", "9:30", "09:30:00"):
        assert_error(
            client.post(f"{API}/events", json={**sample("events"), "time": invalid}, headers=agent_headers),
            400,
        )
    for scope, period in (
        ("week", "2021-W53"),
        ("week", "2026-W00"),
        ("week", "2026-W54"),
        ("week", "2026-W1"),
        ("week", "2026-11"),
        ("month", "2026-W46"),
        ("month", "2026-13"),
    ):
        assert_error(
            client.post(
                f"{API}/goals",
                json={"scope": scope, "period": period, "text": "invalid period"},
                headers=agent_headers,
            ),
            400,
        )
    for resource, field, value in (
        ("media", "kind", "podcast"),
        ("events", "kind", "reminder"),
        ("goals", "scope", "day"),
        ("goals", "status", "pending"),
    ):
        assert_error(
            client.post(f"{API}/{resource}", json={**sample(resource), field: value}, headers=agent_headers),
            400,
        )
    for path, params in (
        ("day", {"date": "2026-02-29"}),
        ("day", {"date": "2026-1-09"}),
        ("month", {"ym": "2026-13"}),
        ("month", {"ym": "2026-1"}),
    ):
        assert_error(client.get(f"{API}/{path}", params=params, headers=agent_headers), 400)
    leap = create_item(
        client, "events", {**sample("events"), "date": "2028-02-29", "time": "23:59"}, agent_headers
    )
    assert leap["date"] == "2028-02-29"
    for period in ("2020-W53", "2026-W53"):
        valid = create_item(
            client, "goals", {"scope": "week", "period": period, "text": period}, agent_headers
        )
        assert valid["period"] == period


def test_month_and_day_include_intersecting_iso_weeks_across_year_and_month_boundaries(client, agent_headers):
    goals = {}
    for period in ("2020-W52", "2020-W53", "2021-W01", "2021-W04", "2021-W05"):
        goals[period] = create_item(
            client, "goals", {"scope": "week", "period": period, "text": period}, agent_headers
        )
    january_goal = create_item(
        client, "goals", {"scope": "month", "period": "2021-01", "text": "January"}, agent_headers
    )
    create_item(client, "goals", {"scope": "month", "period": "2020-12", "text": "December"}, agent_headers)
    dated = {}
    for day in ("2020-12-31", "2021-01-01", "2021-01-31", "2021-02-01"):
        dated[day] = create_item(client, "notes", {"date": day, "text": day}, agent_headers)
    january = get_view(client, month="2021-01", headers=agent_headers)
    assert set(january) == {
        "ym",
        "notes",
        "media",
        "events",
        "goals",
        "photos",
        "decorated_pages",
        "page_peeks",
    }
    assert january["ym"] == "2021-01"
    assert set(january["goals"]["weeks"]) == {"2020-W53", "2021-W01", "2021-W02", "2021-W03", "2021-W04"}
    assert january["goals"]["weeks"]["2020-W53"] == [goals["2020-W53"]]
    assert january["goals"]["weeks"]["2021-W02"] == []
    assert january["goals"]["weeks"]["2021-W03"] == []
    assert january["goals"]["month"] == [january_goal]
    assert {item["id"] for item in january["notes"]} == {dated["2021-01-01"]["id"], dated["2021-01-31"]["id"]}
    first_day = get_view(client, day="2021-01-01", headers=agent_headers)
    assert set(first_day) == {"date", "ym", "notes", "media", "events", "goals", "photos"}
    assert first_day["date"] == "2021-01-01" and first_day["ym"] == "2021-01"
    assert first_day["notes"] == [dated["2021-01-01"]]
    assert first_day["goals"] == {"month": [january_goal], "weeks": {"2020-W53": [goals["2020-W53"]]}}
    december = get_view(client, month="2020-12", headers=agent_headers)
    assert december["goals"]["weeks"]["2020-W53"] == [goals["2020-W53"]]
    may = get_view(client, month="2021-05", headers=agent_headers)
    assert set(may["goals"]["weeks"]) == {
        "2021-W17",
        "2021-W18",
        "2021-W19",
        "2021-W20",
        "2021-W21",
        "2021-W22",
    }
    assert all(items == [] for items in may["goals"]["weeks"].values())
