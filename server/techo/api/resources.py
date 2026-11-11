from fastapi import APIRouter, Response

from ..schemas import (
    Batch,
    EventCreate,
    EventPatch,
    GoalCreate,
    GoalPatch,
    MediaCreate,
    MediaPatch,
    NoteCreate,
    NotePatch,
    Reorder,
)
from .dependencies import Authenticated, ExpectedVersion, Journal

router = APIRouter(tags=["journal"])


def record_response(response: Response, item: dict) -> dict:
    response.headers["ETag"] = '"' + item["updated_at"] + '"'
    return item


@router.post("/notes", status_code=201)
def create_note(payload: NoteCreate, response: Response, actor: Authenticated, journal: Journal):
    return record_response(response, journal.create("note", payload.model_dump(mode="json"), actor.name))


@router.patch("/notes/{record_id}")
def patch_note(
    record_id: int,
    payload: NotePatch,
    response: Response,
    actor: Authenticated,
    journal: Journal,
    version: ExpectedVersion,
):
    item = journal.patch(
        "note",
        record_id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor.name,
        expected_updated_at=version,
    )
    return record_response(response, item)


@router.delete("/notes/{record_id}")
def delete_note(record_id: int, actor: Authenticated, journal: Journal, version: ExpectedVersion):
    journal.delete("note", record_id, actor.name, expected_updated_at=version)
    return {"ok": True}


@router.post("/media", status_code=201)
def create_media(payload: MediaCreate, response: Response, actor: Authenticated, journal: Journal):
    return record_response(response, journal.create("media", payload.model_dump(mode="json"), actor.name))


@router.patch("/media/{record_id}")
def patch_media(
    record_id: int,
    payload: MediaPatch,
    response: Response,
    actor: Authenticated,
    journal: Journal,
    version: ExpectedVersion,
):
    item = journal.patch(
        "media",
        record_id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor.name,
        expected_updated_at=version,
    )
    return record_response(response, item)


@router.delete("/media/{record_id}")
def delete_media(record_id: int, actor: Authenticated, journal: Journal, version: ExpectedVersion):
    journal.delete("media", record_id, actor.name, expected_updated_at=version)
    return {"ok": True}


@router.post("/events", status_code=201)
def create_event(payload: EventCreate, response: Response, actor: Authenticated, journal: Journal):
    return record_response(response, journal.create("event", payload.model_dump(mode="json"), actor.name))


@router.patch("/events/{record_id}")
def patch_event(
    record_id: int,
    payload: EventPatch,
    response: Response,
    actor: Authenticated,
    journal: Journal,
    version: ExpectedVersion,
):
    item = journal.patch(
        "event",
        record_id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor.name,
        expected_updated_at=version,
    )
    return record_response(response, item)


@router.delete("/events/{record_id}")
def delete_event(record_id: int, actor: Authenticated, journal: Journal, version: ExpectedVersion):
    journal.delete("event", record_id, actor.name, expected_updated_at=version)
    return {"ok": True}


@router.post("/goals", status_code=201)
def create_goal(payload: GoalCreate, response: Response, actor: Authenticated, journal: Journal):
    return record_response(
        response, journal.create("goal", payload.model_dump(mode="json", exclude_unset=True), actor.name)
    )


@router.post("/goals/reorder")
def reorder_goals(payload: Reorder, actor: Authenticated, journal: Journal):
    return journal.reorder(payload.period, payload.ids, actor.name, versions=payload.versions)


@router.patch("/goals/{record_id}")
def patch_goal(
    record_id: int,
    payload: GoalPatch,
    response: Response,
    actor: Authenticated,
    journal: Journal,
    version: ExpectedVersion,
):
    item = journal.patch(
        "goal",
        record_id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor.name,
        expected_updated_at=version,
    )
    return record_response(response, item)


@router.delete("/goals/{record_id}")
def delete_goal(record_id: int, actor: Authenticated, journal: Journal, version: ExpectedVersion):
    journal.delete("goal", record_id, actor.name, expected_updated_at=version)
    return {"ok": True}


@router.post("/batch")
def batch(payload: Batch, actor: Authenticated, journal: Journal):
    return journal.batch(
        [item.model_dump(mode="json", exclude_unset=True) for item in payload.items], actor.name
    )
