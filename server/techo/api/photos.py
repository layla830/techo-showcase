from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..errors import APIError
from ..schemas import PhotoPatch
from .dependencies import Authenticated, ExpectedVersion, Photos
from .resources import record_response

router = APIRouter(tags=["photos"])

# nginx caps /techo/ request bodies at 2m (2 MiB); the server enforces the same limit.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
PHOTO_CACHE_CONTROL = "private, max-age=31536000, immutable"
FORM_FIELDS = {"date", "caption"}


def too_large() -> APIError:
    return APIError(413, "payload_too_large", "上传请求不能超过 2MB，请先压缩照片")


def form_error(message: str, field: str = "file") -> APIError:
    return APIError(400, "validation_error", message, field=field)


class _BodyStream:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._body


class _CleanupParser(MultiPartParser):
    """Release partial uploads when parsing is cancelled or fails unexpectedly.

    Starlette closes them for its own parse errors, but has no public cleanup hook for
    cancellation or an unexpected exception; this keeps that compatibility detail in one place.
    """

    async def parse(self) -> FormData:
        try:
            return await super().parse()
        except BaseException:
            for handle in self._files_to_close_on_error:
                handle.close()
            raise


async def read_upload(request: Request) -> tuple[dict, bytes]:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_UPLOAD_BYTES:
                raise too_large()
        except ValueError:
            raise form_error("Content-Length 无效", "Content-Length") from None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_UPLOAD_BYTES:
            raise too_large()
        body.extend(chunk)
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "multipart/form-data":
        raise form_error("请求必须为 multipart/form-data，且只包含一个 file")
    # Cap the whole body before parsing, then parse the in-memory copy.
    parser = _CleanupParser(
        request.headers, _BodyStream(bytes(body)), max_files=1, max_fields=len(FORM_FIELDS)
    )
    parser.spool_max_size = MAX_UPLOAD_BYTES
    form = None
    try:
        try:
            form = await parser.parse()
        except (MultiPartException, MultipartParseError) as exc:
            raise form_error("请求必须为 multipart/form-data，且只包含一个 file") from exc
        values: dict = {}
        upload: UploadFile | None = None
        for key, value in form.multi_items():
            if key == "file":
                if upload is not None or not isinstance(value, UploadFile):
                    raise form_error("file 必须是一个上传文件")
                upload = value
            elif key in FORM_FIELDS:
                if key in values or not isinstance(value, str):
                    raise form_error(f"{key} 只能提供一次文本值", key)
                values[key] = value
            else:
                raise form_error("Extra inputs are not permitted", key)
        if upload is None:
            raise form_error("file 必填")
        return values, await upload.read()
    finally:
        if form is not None:
            await form.close()


@router.post("/photos", status_code=201)
async def create_photo(request: Request, response: Response, actor: Authenticated, photos: Photos):
    values, raw = await read_upload(request)
    # Decoding and re-encoding is CPU work; keep it off the event loop.
    item = await run_in_threadpool(photos.create, values, raw, actor.name)
    return record_response(response, item)


@router.get("/photos/{record_id}")
def read_photo(record_id: int, actor: Authenticated, photos: Photos, size: Literal["full", "thumb"] = "full"):
    path = photos.read(record_id, size)
    # app.privacy_headers keeps this Cache-Control for successful photo reads only.
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": PHOTO_CACHE_CONTROL})


@router.patch("/photos/{record_id}")
def patch_photo(
    record_id: int,
    payload: PhotoPatch,
    response: Response,
    actor: Authenticated,
    photos: Photos,
    version: ExpectedVersion,
):
    item = photos.patch(
        record_id,
        payload.model_dump(mode="json", exclude_unset=True),
        actor.name,
        expected_updated_at=version,
    )
    return record_response(response, item)


@router.delete("/photos/{record_id}")
def delete_photo(record_id: int, actor: Authenticated, photos: Photos, version: ExpectedVersion):
    photos.delete(record_id, actor.name, expected_updated_at=version)
    return {"ok": True}
