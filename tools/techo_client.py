#!/usr/bin/env python3
"""Small agent CLI for the /techo/api/v1 contract (Python 3.12+)."""

import argparse
import http.client
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://techo.example.com/techo"
TIMEOUT = 30
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # nginx client_max_body_size 2m for /techo/


@dataclass(frozen=True)
class Multipart:
    content_type: str
    data: bytes


def multipart(fields: dict, filename: str, content: bytes) -> Multipart:
    boundary = "techo-" + secrets.token_hex(16)
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode("utf-8")
            + b"\r\n"
        )
    # The server identifies images by content, so the name and type here are informational.
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "photo"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return Multipart(f"multipart/form-data; boundary={boundary}", b"".join(parts))


class ClientError(Exception):
    def __init__(self, code: str, message: str, **details):
        self.payload = {"error": {"code": code, "message": message, **details}}
        super().__init__(message)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may echo arbitrary arguments; keep credentials out of errors.
        raise ClientError("usage_error", "命令或参数无效，请用 --help 查看用法。")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the agent token to a redirect destination.
        return None


def redact(value, token: str):
    if isinstance(value, str):
        if token:
            value = value.replace(token, "[redacted]")
        return re.sub(r"(https?://)[^/\s]+@", r"\1[redacted]@", value, flags=re.I)
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    return value


def emit(payload, *, error=False, token=""):
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(redact(payload, token), ensure_ascii=False, allow_nan=False), file=stream)


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def load_config(env_file: Path) -> tuple[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError:
        raise ClientError("configuration_error", "请先在后端虚拟环境安装 python-dotenv。") from None
    try:
        values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
    except (OSError, UnicodeError):
        raise ClientError("configuration_error", "无法读取指定的 UTF-8 环境文件。") from None
    token = os.environ.get("TECHO_AGENT_TOKEN", values.get("TECHO_AGENT_TOKEN") or "").strip()
    base_url = os.environ.get("TECHO_BASE_URL", values.get("TECHO_BASE_URL") or DEFAULT_BASE_URL).strip()
    if not token or any(ord(char) < 32 or ord(char) > 126 for char in token):
        raise ClientError("configuration_error", "请配置有效的 TECHO_AGENT_TOKEN。")
    try:
        parsed = urlsplit(base_url)
        valid = (
            (
                parsed.scheme == "https"
                or (
                    parsed.scheme == "http"
                    and re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]+)?", parsed.netloc.lower())
                )
            )
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
            and not any(char.isspace() or ord(char) < 32 for char in base_url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ClientError(
            "configuration_error",
            "TECHO_BASE_URL 仅支持不含凭据、查询或片段的 HTTPS，或 127.0.0.1、localhost、[::1] 的 HTTP。",
        )
    return base_url.rstrip("/"), token


def make_parser() -> Parser:
    parser = Parser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=PROJECT_ROOT / ".env", help="默认读取项目根 .env；环境变量优先"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("month", help="读取整月").add_argument("ym", help="YYYY-MM")
    commands.add_parser("day", help="读取某天").add_argument("date", help="YYYY-MM-DD")
    changes = commands.add_parser("changes", help="读取另一方的变更；保存响应 cursor 后继续翻页")
    changes.add_argument("--since", required=True, help="带时区的 ISO8601 游标")
    changes.add_argument("--limit", type=int, help="服务端默认 500，最大 1000")

    note = commands.add_parser("add-note")
    note.add_argument("--date", required=True)
    note.add_argument("--text", required=True)
    note.add_argument("--mood")
    media = commands.add_parser("add-media")
    media.add_argument("--date", required=True)
    media.add_argument("--kind", required=True, choices=("book", "film", "series", "show", "other"))
    media.add_argument("--title", required=True)
    media.add_argument("--note")
    event = commands.add_parser("add-event")
    event.add_argument("--date", required=True)
    event.add_argument("--title", required=True)
    event.add_argument("--time")
    event.add_argument("--kind", default="plan", choices=("plan", "anniversary"))
    event.add_argument("--place")
    goal = commands.add_parser("add-goal")
    goal.add_argument("--scope", required=True, choices=("week", "month"))
    goal.add_argument("--period", required=True)
    goal.add_argument("--text", required=True)
    goal.add_argument("--status", choices=("open", "done", "dropped"))
    goal.add_argument("--sort", type=int)
    commands.add_parser("batch", help='提交 UTF-8 JSON 文件，结构为 {"items": [...]}').add_argument(
        "path", type=Path
    )
    photo = commands.add_parser("photo-add", help="上传已压缩的 JPEG/PNG/WebP，整个请求不超过 2MB")
    photo.add_argument("--date", required=True)
    photo.add_argument("--file", required=True, type=Path)
    photo.add_argument("--caption")
    commands.add_parser("decorations", help="只读：某页的装修").add_argument(
        "page", help="day:YYYY-MM-DD 或 month:YYYY-MM"
    )
    commands.add_parser("strokes", help="只读：某页的笔迹").add_argument(
        "page", help="day:YYYY-MM-DD 或 month:YYYY-MM"
    )
    reorder = commands.add_parser("reorder", help="ids 必须完整包含该 period 所有未删除目标")
    reorder.add_argument("--period", required=True)
    reorder.add_argument("--ids", type=int, nargs="*", required=True)
    reorder.add_argument("--versions-file", type=Path, required=True, help="id 到 updated_at 的 JSON 对象")
    return parser


def operation(args) -> tuple[str, str, dict | None, dict | None]:
    if args.command == "month":
        return "GET", "/month", {"ym": args.ym}, None
    if args.command == "day":
        return "GET", "/day", {"date": args.date}, None
    if args.command == "changes":
        query = {"since": args.since}
        if args.limit is not None:
            query["limit"] = args.limit
        return "GET", "/changes", query, None
    if args.command in {"decorations", "strokes"}:
        return "GET", "/" + args.command, {"page": args.page}, None
    if args.command == "photo-add":
        try:
            content = args.file.read_bytes()
        except OSError:
            raise ClientError("validation_error", "无法读取照片文件。", field="file") from None
        fields = {"date": args.date}
        if args.caption is not None:
            fields["caption"] = args.caption
        body = multipart(fields, args.file.name, content)
        if len(body.data) > MAX_UPLOAD_BYTES:
            raise ClientError("payload_too_large", "上传请求超过 2MB，请先压缩照片。", field="file")
        return "POST", "/photos", None, body
    if args.command == "batch":
        try:
            body = json.loads(args.path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
        except (OSError, UnicodeError, ValueError):
            raise ClientError(
                "validation_error", "batch 文件必须是可读取的 UTF-8 JSON。", field="path"
            ) from None
        return "POST", "/batch", None, body
    if args.command == "reorder":
        try:
            versions = json.loads(
                args.versions_file.read_text(encoding="utf-8-sig"), parse_constant=reject_constant
            )
            if not isinstance(versions, dict):
                raise ValueError
        except (OSError, UnicodeError, ValueError):
            raise ClientError(
                "validation_error", "versions 文件必须是可读取的 UTF-8 JSON 对象。", field="versions_file"
            ) from None
        return (
            "POST",
            "/goals/reorder",
            None,
            {
                "period": args.period,
                "ids": args.ids,
                "versions": versions,
            },
        )
    fields = {
        "add-note": ("notes", ("date", "text", "mood")),
        "add-media": ("media", ("date", "kind", "title", "note")),
        "add-event": ("events", ("date", "time", "title", "kind", "place")),
        "add-goal": ("goals", ("scope", "period", "text", "status", "sort")),
    }
    resource, names = fields[args.command]
    body = {name: getattr(args, name) for name in names if getattr(args, name) is not None}
    # Real calendar dates, ISO weeks, lengths and batch semantics belong to the server.
    return "POST", "/" + resource, None, body


def request(base_url: str, token: str, method: str, path: str, query, body):
    url = base_url + "/api/v1" + path
    if query:
        url += "?" + urlencode(query)
    headers = {"X-Techo-Token": token, "Accept": "application/json"}
    data = None
    if isinstance(body, Multipart):
        data = body.data
        headers["Content-Type"] = body.content_type
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        # One request only, including writes. The server may have committed on timeout.
        with build_opener(NoRedirect()).open(req, timeout=TIMEOUT) as response:
            raw = response.read()
    except HTTPError as exc:
        with exc:
            try:
                payload = json.loads(exc.read().decode("utf-8-sig"), parse_constant=reject_constant)
            except (ValueError, UnicodeError):
                payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            if isinstance(error.get("code"), str) and isinstance(error.get("message"), str):
                failure = ClientError(error["code"], error["message"])
                failure.payload = {"error": error}
                raise failure from None
        raise ClientError("http_error", f"HTTP {exc.code} 请求失败。", status=exc.code) from None
    try:
        return json.loads(raw.decode("utf-8-sig"), parse_constant=reject_constant)
    except (ValueError, UnicodeError):
        raise ClientError(
            "response_error", "服务端响应不是 UTF-8 JSON；写请求请先查询结果再决定是否重试。"
        ) from None


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    token = os.environ.get("TECHO_AGENT_TOKEN", "").strip()
    try:
        args = make_parser().parse_args(argv)
        base_url, token = load_config(args.env_file)
        method, path, query, body = operation(args)
        emit(request(base_url, token, method, path, query, body), token=token)
        return 0
    except ClientError as exc:
        emit(exc.payload, error=True, token=token)
        return 1
    except (URLError, TimeoutError, OSError, http.client.HTTPException):
        emit(
            {
                "error": {
                    "code": "network_error",
                    "message": "请求失败或超时；写请求未自动重试，请先查询结果。",
                }
            },
            error=True,
            token=token,
        )
        return 1
    except (ValueError, UnicodeError):
        emit(
            {
                "error": {
                    "code": "validation_error",
                    "message": "请求无法编码为有效的 UTF-8 JSON 或 HTTP 请求。",
                }
            },
            error=True,
            token=token,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
