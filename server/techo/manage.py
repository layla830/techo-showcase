from __future__ import annotations

import argparse
import getpass
import json

from pwdlib import PasswordHash

from .config import Settings
from .database import Database
from .services.seed import seed


def main() -> None:
    parser = argparse.ArgumentParser(description="techo maintenance")
    parser.add_argument("command", choices=["hash-password", "init-db", "seed"])
    args = parser.parse_args()
    if args.command == "hash-password":
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm: ")
        if not password or password != confirmation:
            parser.error("passwords must be non-empty and match")
        print(PasswordHash.recommended().hash(password))
        return
    settings = Settings.from_env()
    database = Database(settings)
    try:
        database.migrate()
        count = seed(database, settings.project_root / "seed.json")
        print(json.dumps({"ok": True, "seeded": count}))
    finally:
        database.close()


if __name__ == "__main__":
    main()
