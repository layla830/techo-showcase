from datetime import date

from conftest import API, create_item, get_view, match_headers, patch_item
from techo.services.seed import seed

START = date(2026, 11, 1)
TARGET = "2026-11-23"
TITLE = "example anniversary"


def test_overlapping_yearly_and_monthly_rules_preserve_edits_and_deletion(project, client, agent_headers):
    project.write_seed(
        [
            {"month_day": "11-23", "title": TITLE},
            {"day_of_month": 23, "title": TITLE},
        ]
    )
    path = project.root / "seed.json"
    assert seed(client.app.state.database, path, today=START) == 24
    events = get_view(client, month="2026-11", headers=agent_headers)["events"]
    assert len(events) == 1
    item = events[0]
    updated = patch_item(
        client,
        "events",
        item["id"],
        {"title": "edited", "date": "2026-11-24"},
        agent_headers,
        version=item["updated_at"],
    )
    assert seed(client.app.state.database, path, today=START) == 0
    events = get_view(client, month="2026-11", headers=agent_headers)["events"]
    assert [(event["id"], event["title"]) for event in events] == [(item["id"], "edited")]
    assert (
        client.delete(f"{API}/events/{item['id']}", headers=match_headers(updated, agent_headers)).status_code
        == 200
    )
    assert seed(client.app.state.database, path, today=START) == 0
    with project.client() as restarted:
        assert seed(restarted.app.state.database, path, today=START) == 0
        assert get_view(restarted, month="2026-11", headers=agent_headers)["events"] == []


def test_seed_remembers_reused_manual_event_after_edit_and_deletion(project, client, agent_headers):
    item = create_item(
        client, "events", {"date": TARGET, "title": TITLE, "kind": "anniversary"}, agent_headers
    )
    project.write_seed([{"month_day": "11-23", "title": TITLE}])
    path = project.root / "seed.json"
    assert seed(client.app.state.database, path, today=START) == 1
    updated = patch_item(
        client,
        "events",
        item["id"],
        {"title": "manual change", "date": "2026-12-01"},
        agent_headers,
        version=item["updated_at"],
    )
    assert (
        client.delete(f"{API}/events/{item['id']}", headers=match_headers(updated, agent_headers)).status_code
        == 200
    )
    assert seed(client.app.state.database, path, today=START) == 0
    with project.client() as restarted:
        assert seed(restarted.app.state.database, path, today=START) == 0
        assert get_view(restarted, day=TARGET, headers=agent_headers)["events"] == []
