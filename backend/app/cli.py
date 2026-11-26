"""Admin command line. Self-registration only creates analysts, so the first admin comes from here.

    uv run python -m app.cli create-user admin@example.com --role admin
    uv run python -m app.cli requeue            # re-deliver lost background jobs

The password is read with getpass, so it never appears in shell history or process lists.
"""

import argparse
import getpass
import sys

from app.core.errors import Conflict
from app.core.permissions import Role
from app.db.session import get_sessionmaker
from app.modules.auth import service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create a user with a given role")
    create.add_argument("email")
    create.add_argument("--role", choices=[r.value for r in Role], default=Role.ANALYST.value)
    requeue = sub.add_parser("requeue", help="re-deliver queued or stale running jobs")
    requeue.add_argument("--older-than", type=int, default=60, help="seconds (default 60)")
    args = parser.parse_args(argv)

    if args.command == "requeue":
        from app.worker.sweep import requeue_lost

        print(f"re-delivered {requeue_lost(args.older_than)} job(s)")
        return 0

    password = getpass.getpass("Password (min 12 characters): ")
    if not 12 <= len(password) <= 128:
        print("Password must be 12-128 characters.", file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        try:
            user = service.register(db, args.email, password, Role(args.role))
        except Conflict as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Created {user.role} {user.email} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
