from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(
        self, status: int, code: str, message: str, *, field: str | None = None, index: int | None = None
    ):
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.index = index

    def response(self) -> JSONResponse:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field is not None:
            error["field"] = self.field
        if self.index is not None:
            error["index"] = self.index
        headers = {"Retry-After": "60"} if self.status == 429 else None
        return JSONResponse({"error": error}, status_code=self.status, headers=headers)


def invalid(exc: ValidationError | RequestValidationError, *, index: int | None = None) -> APIError:
    first = exc.errors()[0]
    location = list(first["loc"])
    for name in ("items", "strokes"):
        if name in location:
            offset = location.index(name) + 1
            if offset < len(location) and isinstance(location[offset], int):
                index = location[offset]
            break
    path = ".".join(str(part) for part in location if part not in {"body", "query", "path", "header"})
    return APIError(400, "validation_error", first["msg"], field=path or None, index=index)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError):
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return invalid(exc).response()

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {
            400: "validation_error",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }
        return APIError(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail)).response()

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        log.error("Database operation failed (%s)", type(exc).__name__)
        return APIError(500, "internal_error", "数据库操作失败，请稍后重试").response()

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        log.error("Request failed (%s)", type(exc).__name__)
        return APIError(500, "internal_error", "服务暂时不可用").response()
