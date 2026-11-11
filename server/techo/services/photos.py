from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import ValidationError

from ..database import Database
from ..errors import APIError, invalid
from ..images import ProcessedPhoto, Rendition, process
from ..models import Photo, serialize
from ..repositories import Changes, Resources
from ..schemas import PhotoCreate
from .journal import require_version

SIZES = ("full", "thumb")


class PhotoStore:
    """Files under data/photos: private modes, atomic rename, removable on rollback."""

    def __init__(self, root: Path):
        self.root = root

    def _directory(self, relative: Path) -> Path:
        directory = self.root
        for part in ("", *relative.parts):  # "" checks the photos root itself
            directory = directory / part
            if not directory.exists():
                directory.mkdir(mode=0o700, exist_ok=True)
                directory.chmod(0o700)
        return directory

    def write(self, relative: str, data: bytes) -> Path:
        target = self.root / relative
        directory = self._directory(Path(relative).parent)
        temporary = directory / f".{target.name}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def path(self, relative: str) -> Path | None:
        target = (self.root / relative).resolve()
        root = self.root.resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return None
        return target


def file_name(record_id: int, date: str, rendition: Rendition, size: str, *, nonce: str) -> str:
    # A rolled-back id can be reused; the nonce isolates each upload's files and cleanup.
    return f"{date[:4]}/{date[5:7]}/{record_id}-{rendition.digest[:12]}-{nonce}-{size}.webp"


class PhotoService:
    def __init__(self, database: Database, root: Path):
        self.database = database
        self.store = PhotoStore(root)

    def validate(self, values: dict) -> dict:
        try:
            return PhotoCreate.model_validate(values).model_dump(mode="json")
        except ValidationError as exc:
            raise invalid(exc) from exc

    def create(self, values: dict, raw: bytes, actor: str) -> dict:
        values = self.validate(values)
        processed: ProcessedPhoto = process(raw)
        nonce = secrets.token_hex(16)
        written: list[Path] = []
        try:
            with self.database.transaction(write=True) as session:
                changes = Changes(session)
                at = changes.timestamp()
                row = Photo(
                    date=values["date"],
                    caption=values["caption"],
                    width=processed.full.width,
                    height=processed.full.height,
                    hash=processed.hash,
                    full_path="",
                    thumb_path="",
                    author=actor,
                    updated_by=actor,
                    created_at=at,
                    updated_at=at,
                    deleted_at=None,
                )
                session.add(row)
                session.flush()
                row.full_path = file_name(row.id, row.date, processed.full, "full", nonce=nonce)
                row.thumb_path = file_name(row.id, row.date, processed.thumb, "thumb", nonce=nonce)
                for relative, rendition in (
                    (row.full_path, processed.full),
                    (row.thumb_path, processed.thumb),
                ):
                    written.append(self.store.write(relative, rendition.data))
                changes.append("photo", row, actor, "created", at)
                item = serialize("photo", row)
        except BaseException:
            # The row did not commit: remove only the files this request created.
            for path in written:
                path.unlink(missing_ok=True)
            raise
        return item

    def read(self, record_id: int, size: str) -> Path:
        with self.database.transaction() as session:
            row = Resources(session).get("photo", record_id)
            relative = row.full_path if size == "full" else row.thumb_path
        path = self.store.path(relative)
        if path is None:
            raise APIError(404, "not_found", "照片文件不存在")
        return path

    def patch(self, record_id: int, values: dict, actor: str, *, expected_updated_at: str) -> dict:
        if not values:
            raise APIError(400, "validation_error", "PATCH 至少需要一个字段")
        if "date" in values and values["date"] is None:
            raise APIError(400, "validation_error", "必填字段不能清空", field="date")
        with self.database.transaction(write=True) as session:
            row = Resources(session).get("photo", record_id)
            require_version(row, expected_updated_at)
            merged = self.validate({"date": row.date, "caption": row.caption, **values})
            if all(getattr(row, field) == value for field, value in merged.items()):
                return serialize("photo", row)
            # Changing the date keeps the files where they are; paths are stored per row.
            row.date, row.caption = merged["date"], merged["caption"]
            changes = Changes(session)
            row.updated_at = changes.timestamp()
            row.updated_by = actor
            changes.append("photo", row, actor, "updated", row.updated_at)
            return serialize("photo", row)

    def delete(self, record_id: int, actor: str, *, expected_updated_at: str) -> None:
        with self.database.transaction(write=True) as session:
            row = Resources(session).get("photo", record_id)
            require_version(row, expected_updated_at)
            changes = Changes(session)
            row.updated_at = row.deleted_at = changes.timestamp()
            row.updated_by = actor
            changes.append("photo", row, actor, "deleted", row.updated_at)
