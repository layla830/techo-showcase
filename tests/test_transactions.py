from concurrent.futures import ThreadPoolExecutor

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import API, DAY, MONTH, WEEK, get_changes, get_view
from sqlalchemy.exc import IntegrityError
from techo.models import Base
from techo.repositories import Changes


def test_batch_database_failure_rolls_back_rows_and_changes(browser, agent_headers, monkeypatch):
    original = Changes.append
    calls = 0

    def fail_after_write(self, *args, **kwargs):
        nonlocal calls
        original(self, *args, **kwargs)
        calls += 1
        if calls == 2:
            raise IntegrityError("injected failure", {}, RuntimeError("database failure"))

    with monkeypatch.context() as patch:
        patch.setattr(Changes, "append", fail_after_write)
        response = browser.post(
            f"{API}/batch",
            json={"items": [{"type": "note", "date": DAY, "text": text} for text in ("first", "second")]},
            headers=agent_headers,
        )
    assert response.status_code == 500
    assert get_view(browser, month=MONTH)["notes"] == []
    assert get_changes(browser)["changes"] == []


def test_concurrent_batches_create_duplicate_only_once(client, agent_headers):
    journal = client.app.state.journal
    items = [{"type": "note", "date": DAY, "text": "one concurrent note"}]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: journal.batch(items, "agent"), range(6)))
    assert sum(len(result["created"]) for result in results) == 1
    assert sum(len(result["skipped"]) for result in results) == 5
    assert len(get_view(client, month=MONTH, headers=agent_headers)["notes"]) == 1


def test_concurrent_goal_appends_have_distinct_sort_positions(client, agent_headers):
    journal = client.app.state.journal

    def create(index):
        return journal.create("goal", {"scope": "week", "period": WEEK, "text": f"goal {index}"}, "agent")

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(create, range(12)))
    assert sorted(row["sort"] for row in rows) == list(range(12))
    goals = get_view(client, month=MONTH, headers=agent_headers)["goals"]["weeks"][WEEK]
    assert [row["sort"] for row in goals] == list(range(12))


def test_change_cursor_does_not_skip_an_uncommitted_writer(client, agent_headers):
    database = client.app.state.database
    with database.transaction(write=True) as session:
        item = client.app.state.journal._create(
            session, "note", {"date": DAY, "text": "not committed yet"}, "human"
        )
        before = get_changes(client, headers=agent_headers)
        assert before["changes"] == []
    after = get_changes(client, headers=agent_headers, since=before["cursor"])
    assert [change["id"] for change in after["changes"]] == [item["id"]]
    assert after["changes"][0]["data"]["text"] == "not committed yet"
    assert get_changes(client, headers=agent_headers, since=after["cursor"])["changes"] == []


def test_head_migration_matches_declared_schema(client):
    with client.app.state.database.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0003"
