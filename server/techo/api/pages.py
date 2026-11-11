from fastapi import APIRouter

from ..schemas import DecorationsPut, StrokesCreate
from .dependencies import Authenticated, Pages

router = APIRouter(tags=["pages"])


@router.get("/decorations")
def get_decorations(page: str, actor: Authenticated, pages: Pages):
    return pages.decorations(page)


@router.put("/decorations")
def put_decorations(page: str, payload: DecorationsPut, actor: Authenticated, pages: Pages):
    items = [item.model_dump(mode="json") for item in payload.items]
    return pages.replace_decorations(page, payload.version, items, actor.name)


@router.get("/strokes")
def get_strokes(page: str, actor: Authenticated, pages: Pages):
    return pages.strokes(page)


@router.post("/strokes", status_code=201)
def add_strokes(page: str, payload: StrokesCreate, actor: Authenticated, pages: Pages):
    return pages.add_strokes(page, [stroke.model_dump(mode="json") for stroke in payload.strokes], actor.name)


@router.delete("/strokes/{stroke_id}")
def delete_stroke(stroke_id: int, actor: Authenticated, pages: Pages):
    pages.delete_stroke(stroke_id)
    return {"ok": True}
