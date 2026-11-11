#!/usr/bin/env python3
"""Back up SQLite, optional photos and seed into a new private directory."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_TIMEOUT = 300


class BackupError(Exception):
    pass


def regular_file(path: Path):
    if path.is_symlink() or not path.is_file():
        raise BackupError("数据源必须为普通文件，不能是符号链接。")


def private_file(path: Path):
    # Exclusive creation is intentional: never truncate an existing destination.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def copy_file(source: Path, target: Path):
    regular_file(source)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with source.open("rb") as reader, private_file(target) as writer:
        shutil.copyfileobj(reader, writer)
    target.chmod(0o600)


def file_record(path: Path, destination: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "path": path.relative_to(destination).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": digest,
    }


def make_backup(project: Path, output_dir: Path) -> Path:
    project = project.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve()
    if not project.is_dir():
        raise BackupError("项目根目录不存在。")
    if output_dir.is_relative_to(project) or project.is_relative_to(output_dir):
        raise BackupError("备份路径与项目路径重叠；请选择项目外且不包含项目的独立目录。")
    if output_dir.exists() and not output_dir.is_dir():
        raise BackupError("备份根路径必须为目录。")
    data = project / "data"
    if data.is_symlink() or not data.is_dir():
        raise BackupError("data 必须为项目内的普通目录。")
    database = data / "techo.db"
    regular_file(database)
    photos = data / "photos"
    seed = project / "seed.json"
    has_photos = photos.exists() or photos.is_symlink()
    has_seed = seed.exists() or seed.is_symlink()
    if has_photos and (photos.is_symlink() or not photos.is_dir()):
        raise BackupError("photos 必须为普通目录，不能是符号链接。")
    if has_seed:
        regular_file(seed)

    started = datetime.now(UTC)
    destination = output_dir / started.strftime("%Y%m%dT%H%M%S.%fZ")
    previous_umask = os.umask(0o077)
    created = False
    try:
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            destination.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            raise BackupError("时间戳备份目录已存在，拒绝覆盖。") from None
        created = True
        backup_data = destination / "data"
        backup_data.mkdir(mode=0o700)
        target_database = backup_data / "techo.db"
        with private_file(target_database):
            pass

        deadline = time.monotonic() + BACKUP_TIMEOUT

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise BackupError("SQLite 快照超时；本次备份未完成。")

        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)) as source:
            with closing(sqlite3.connect(target_database, timeout=30)) as target:
                # Read the live WAL database through SQLite, never copy its db/WAL files.
                source.backup(target, pages=256, progress=progress, sleep=0.05)
                target.execute("PRAGMA journal_mode=DELETE").fetchone()
                result = [row[0] for row in target.execute("PRAGMA quick_check")]
                if result != ["ok"]:
                    raise BackupError("SQLite quick_check 未通过；本次备份未完成。")
        target_database.chmod(0o600)
        files = [target_database]

        if has_photos:
            backup_photos = backup_data / "photos"
            backup_photos.mkdir(mode=0o700)
            for directory, dirnames, filenames in os.walk(photos, followlinks=False, onerror=walk_error):
                directory = Path(directory)
                for name in sorted(dirnames + filenames):
                    item = directory / name
                    relative = item.relative_to(photos)
                    if item.is_symlink() or name == ".env" or name.startswith(".env."):
                        raise BackupError("photos 中含符号链接或环境文件，拒绝复制。")
                    target = backup_photos / relative
                    if item.is_dir():
                        target.mkdir(mode=0o700, exist_ok=False)
                    else:
                        copy_file(item, target)
                        files.append(target)
        if has_seed:
            target_seed = destination / "seed.json"
            copy_file(seed, target_seed)
            files.append(target_seed)

        records = [file_record(path, destination) for path in sorted(files)]
        metadata = {
            "format_version": 1,
            "complete": True,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "timezone": "UTC",
            "sqlite_version": sqlite3.sqlite_version,
            "database": "data/techo.db",
            "quick_check": "ok",
            "includes": {"photos": has_photos, "seed": has_seed},
            "contains_database_sessions": True,
            "session_notice": "数据库包含可用的登录会话；备份必须视为秘密数据。不会复制 .env 或其他目录。",
            "data_files": records,
        }
        # This is the completion marker. Failed runs keep their new files for inspection.
        with private_file(destination / "metadata.json") as handle:
            handle.write((json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        return destination
    except Exception:
        if created:
            print(
                json.dumps({"partial_destination": str(destination), "complete": False}, ensure_ascii=False),
                file=sys.stderr,
            )
        raise
    finally:
        os.umask(previous_umask)


def walk_error(error):
    raise error


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BackupError("命令或参数无效，请用 --help 查看用法。")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = Parser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="项目外的备份根目录；每次创建新的 UTC 时间戳子目录")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="默认使用脚本所在项目")
    try:
        args = parser.parse_args(argv)
        destination = make_backup(args.project_root, args.output_dir)
    except (BackupError, OSError, sqlite3.Error, ValueError) as exc:
        # Our own messages are fixed text; OS/SQLite exceptions may contain secrets.
        message = (
            str(exc)
            if isinstance(exc, BackupError)
            else "备份未完成：检查源文件、数据库、空间及权限。现有文件未被删除。"
        )
        print(
            json.dumps({"error": {"code": "backup_failed", "message": message}}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {"ok": True, "destination": str(destination), "metadata": str(destination / "metadata.json")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
