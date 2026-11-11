from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from conftest import (
    API,
    DAY,
    MONTH,
    RESOURCE_TYPES,
    TEXT_FIELDS,
    assert_record,
    create_item,
    get_changes,
    get_view,
    login,
    match_headers,
    patch_item,
    sample,
)
from techo.services.seed import seed


def shift_month(day: date, offset: int) -> date:
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def month_names(start: date, end: date) -> list[str]:
    current = start.replace(day=1)
    result = []
    while current <= end:
        result.append(current.strftime("%Y-%m"))
        current = shift_month(current, 1)
    return result


def collect_events(client, months: list[str], headers) -> list[dict]:
    return [item for month in months for item in get_view(client, month=month, headers=headers)["events"]]


def default_zone_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def test_seed_monthly_and_annual_rules_have_an_exact_two_year_window_and_skip_invalid_dates(
    project, agent_headers
):
    start, end = date(2027, 1, 31), date(2029, 1, 31)
    rules = [
        {"day_of_month": 23, "title": "monthly 23"},
        {"day_of_month": 31, "title": "monthly 31"},
        {"month_day": "01-31", "title": "annual January 31"},
        {"month_day": "02-29", "title": "annual leap day"},
    ]
    expected = set()
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            for day_number, title in ((23, "monthly 23"), (31, "monthly 31")):
                if day_number <= monthrange(year, month)[1]:
                    day = date(year, month, day_number)
                    if start <= day < end:
                        expected.add((day.isoformat(), title))
    expected.update(
        {
            ("2027-01-31", "annual January 31"),
            ("2028-01-31", "annual January 31"),
            ("2028-02-29", "annual leap day"),
        }
    )
    months = month_names(date(2026, 12, 1), date(2029, 2, 1))
    with project.client() as active:
        # Startup sees an empty file. The supported seeder entry point supplies a
        # fixed date here so leap days and both boundaries never depend on CI time.
        project.write_seed(rules)
        seed(active.app.state.database, project.root / "seed.json", today=start)
        first = collect_events(active, months, agent_headers)
        assert len(first) == len(expected)
        assert {(item["date"], item["title"]) for item in first} == expected
        for item in first:
            assert_record(
                item,
                "events",
                {
                    "date": item["date"],
                    "title": item["title"],
                    "kind": "anniversary",
                    "time": None,
                    "place": None,
                },
                author="seed",
            )
        seed(active.app.state.database, project.root / "seed.json", today=start)
        second = collect_events(active, months, agent_headers)
        assert {item["id"]: item for item in second} == {item["id"]: item for item in first}
        assert len(second) == len(first)


def test_same_date_seed_titles_coexist_and_only_human_or_agent_edits_enter_changes(project, agent_headers):
    target = shift_month(default_zone_today(), 1).replace(day=23)
    project.write_seed(
        [
            {"day_of_month": 23, "title": "monthly first title"},
            {"day_of_month": 23, "title": "monthly second title"},
            {"month_day": target.strftime("%m-%d"), "title": "annual third title"},
        ]
    )
    with project.client() as active:
        login(active)
        events = get_view(active, day=target.isoformat())["events"]
        assert len(events) == 3
        assert {item["title"] for item in events} == {
            "monthly first title",
            "monthly second title",
            "annual third title",
        }
        assert all(item["author"] == item["updated_by"] == "seed" for item in events)
        assert get_changes(active)["changes"] == []
        assert get_changes(active, agent_headers)["changes"] == []
        original = next(item for item in events if item["title"] == "monthly first title")
        edited = patch_item(
            active,
            "events",
            original["id"],
            {"title": "User edited the seeded event"},
            version=original["updated_at"],
        )
        for_agent = get_changes(active, agent_headers)
        assert len(for_agent["changes"]) == 1
        change = for_agent["changes"][0]
        assert (change["type"], change["id"], change["op"]) == ("event", original["id"], "updated")
        assert change["data"] == edited
        assert edited["author"] == "seed" and edited["updated_by"] == "human"
        assert get_changes(active)["changes"] == []
        agent_edit = patch_item(
            active,
            "events",
            original["id"],
            {"place": "agent edit"},
            agent_headers,
            version=edited["updated_at"],
        )
        for_browser = get_changes(active)
        assert len(for_browser["changes"]) == 1
        assert for_browser["changes"][0]["op"] == "updated"
        assert for_browser["changes"][0]["data"] == agent_edit
        assert agent_edit["author"] == "seed" and agent_edit["updated_by"] == "agent"


def test_seed_repeated_lifespans_preserve_edits_and_do_not_resurrect_deleted_monthly_or_annual_items(
    project, agent_headers
):
    today = default_zone_today()
    monthly_edit_day = shift_month(today, 1).replace(day=23)
    monthly_delete_day = shift_month(today, 2).replace(day=23)
    annual_edit_day = shift_month(today, 1).replace(day=15)
    annual_delete_day = annual_edit_day.replace(year=annual_edit_day.year + 1)
    project.write_seed(
        [
            {"day_of_month": 23, "title": "stable monthly"},
            {"month_day": annual_edit_day.strftime("%m-%d"), "title": "stable annual"},
        ]
    )
    months = month_names(today, shift_month(today, 24))
    with project.client() as active:
        login(active)
        original = collect_events(active, months, agent_headers)
        by_key = {(item["date"], item["title"]): item for item in original}
        expected = {item["id"]: item for item in original}
        for target, old_title, new_title in (
            (monthly_edit_day, "stable monthly", "manually changed monthly"),
            (annual_edit_day, "stable annual", "manually changed annual"),
        ):
            item = by_key[(target.isoformat(), old_title)]
            patch = {
                "date": (target + timedelta(days=1)).isoformat(),
                "title": new_title,
                "kind": "plan",
                "time": "08:45",
                "place": "keep this edit",
            }
            expected[item["id"]] = patch_item(active, "events", item["id"], patch, version=item["updated_at"])
        for target, title in (
            (monthly_delete_day, "stable monthly"),
            (annual_delete_day, "stable annual"),
        ):
            item = by_key[(target.isoformat(), title)]
            response = active.delete(f"{API}/events/{item['id']}", headers=match_headers(item))
            assert response.status_code == 200
            del expected[item["id"]]
    for _ in range(2):
        with project.client() as restarted:
            actual = collect_events(restarted, months, agent_headers)
            assert len(actual) == len(expected)
            assert {item["id"]: item for item in actual} == expected
            for target, title in (
                (monthly_edit_day, "stable monthly"),
                (annual_edit_day, "stable annual"),
                (monthly_delete_day, "stable monthly"),
                (annual_delete_day, "stable annual"),
            ):
                assert not any(
                    item["date"] == target.isoformat() and item["title"] == title for item in actual
                )


def test_empty_seed_and_repeated_startup_migrations_preserve_data_changes_and_sessions(
    project, agent_headers
):
    with project.client() as active:
        login(active)
        cookie = {"Cookie": f"techo_session={active.cookies.get('techo_session')}"}
        originals = {}
        for resource in RESOURCE_TYPES:
            original = create_item(active, resource, sample(resource, "persistent"), agent_headers)
            originals[resource] = original
            patch_item(
                active,
                resource,
                original["id"],
                {TEXT_FIELDS[resource]: "persist this edit"},
                version=original["updated_at"],
            )
        deleted = create_item(active, "notes", sample("notes", "persist deletion"), agent_headers)
        assert (
            active.delete(
                f"{API}/notes/{deleted['id']}", headers=match_headers(deleted, agent_headers)
            ).status_code
            == 200
        )
        month_before = get_view(active, month=MONTH)
        day_before = get_view(active, day=DAY)
        changes_before = get_changes(active)
        assert all(item["author"] != "seed" for item in month_before["events"])
    assert project.database_path.is_file()
    for _ in range(3):
        with project.client() as restarted:
            assert restarted.get(f"{API}/healthz").json() == {"ok": True}
            me = restarted.get(f"{API}/me", headers=cookie)
            assert me.status_code == 200 and me.json() == {"author": "human"}
            assert get_view(restarted, month=MONTH, headers=agent_headers) == month_before
            assert get_view(restarted, day=DAY, headers=agent_headers) == day_before
            assert get_changes(restarted, cookie) == changes_before
    with project.client() as writable:
        next_note = create_item(writable, "notes", sample("notes", "after migrations"), agent_headers)
        assert next_note["id"] > deleted["id"] > originals["notes"]["id"]
