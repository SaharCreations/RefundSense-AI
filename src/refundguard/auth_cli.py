"""Trusted local provisioning. No public user creation or role mutation route."""

import getpass
import json
import os
import sys

from .auth import SCHEMA_AUTH, AuthStore
from .workflow import workflow_connection


def run_auth(args):
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL to your development PostgreSQL database")
    with workflow_connection(url) as conn:
        if args.command == "auth-init":
            conn.execute(SCHEMA_AUTH)
            result = {"status": "auth_schema_initialized"}
        else:
            password = os.getenv("REFUNDGUARD_BOOTSTRAP_PASSWORD")
            if password is None:
                if not sys.stdin.isatty():
                    raise ValueError(
                        "Set REFUNDGUARD_BOOTSTRAP_PASSWORD for noninteractive provisioning"
                    )
                password = getpass.getpass("New account password (12-128 characters): ")
                if password != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords do not match")
            AuthStore(conn).create_user(args.user_id, args.organization_id, args.role, password)
            result = {
                "status": "account_created",
                "user_id": args.user_id,
                "organization_id": args.organization_id,
                "role": args.role,
            }
    print(json.dumps(result, indent=2))
    return 0
