"""Construct a DSN from local secret files or ECS secrets; never print credentials."""

import os
from pathlib import Path
from urllib.parse import quote, urlencode


def database_url(env):
    if env.get("DATABASE_URL"):
        return env["DATABASE_URL"]
    password = env.get("PGPASSWORD")
    if password is None and env.get("PGPASSWORD_FILE"):
        password = Path(env["PGPASSWORD_FILE"]).read_text().rstrip("\n")
    if not password:
        raise ValueError("Database credentials are required")
    host = env.get("PGHOST", "")
    port = env.get("PGPORT", "5432")
    if not host or any(c in host for c in "/?#@") or not port.isdecimal():
        raise ValueError("Invalid database host or port")
    options = {"sslmode": env.get("PGSSLMODE", "prefer")}
    if env.get("PGSSLROOTCERT"):
        options["sslrootcert"] = env["PGSSLROOTCERT"]
    return (
        f"postgresql://{quote(env.get('PGUSER', 'refundguard'), safe='')}:"
        f"{quote(password, safe='')}@{host}:{port}/"
        f"{quote(env.get('PGDATABASE', 'refundguard'), safe='')}?{urlencode(options)}"
    )


def main():
    import sys

    env = dict(os.environ, DATABASE_URL=database_url(os.environ))
    os.execvpe(sys.argv[1], sys.argv[1:], env)


if __name__ == "__main__":
    main()
