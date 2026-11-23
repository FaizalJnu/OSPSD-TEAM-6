"""Apply or inspect migrations: ``python -m meeting_prep.db {upgrade,current}``.

Reads DATABASE_URL. The deploy runs ``upgrade`` before starting the new release.
"""

import argparse
import os
import sys

from meeting_prep.config import ConfigError, require
from meeting_prep.db.migrate import current_revision, upgrade


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m meeting_prep.db")
    parser.add_argument("command", choices=["upgrade", "current"])
    args = parser.parse_args(argv)
    try:
        url = require(os.environ, "DATABASE_URL")
        if args.command == "upgrade":
            upgrade(url)
        print(current_revision(url) or "no migrations applied")
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
