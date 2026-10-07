"""One local command: secrets, containers, pinned dense model, schemas and SQL users.

Requires Docker Compose. Accounts are created only when missing. No refund approval
or execution occurs. Original seeded dates/facts are never overwritten.
"""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="Build optional CPU LLM support")
    args = parser.parse_args()
    run("python3", "scripts/local_secrets.py")
    compose = ["docker", "compose", "-f", "compose.yaml"]
    if args.llm:
        compose += ["-f", "compose.llm.yaml"]
    run(*compose, "up", "-d", "--build", "db", "api")
    # Model download/ingestion is a deliberate setup operation, never an API side effect.
    run("uv", "run", "--no-project", "--python", "3.12", "--with", "huggingface-hub==1.33.0", "python", "scripts/download_model.py")
    for cmd in ["seed-demo", "workflow-init", "auth-init"]:
        run(
            *compose,
            "exec",
            "-T",
            "api",
            "python",
            "scripts/container_entrypoint.py",
            "refundguard",
            cmd,
        )
    for role in ["support", "reviewer"]:
        password = (ROOT / ".local" / f"{role}_password").read_text().strip()
        # Stdin carries the secret; it never appears in argv or container configuration.
        code = """import os,sys
from refundguard.auth import AuthStore
from refundguard.workflow import workflow_connection
with workflow_connection(os.environ['DATABASE_URL']) as c:
 a=AuthStore(c)
 uid=sys.argv[1]
 if not c.execute('SELECT 1 FROM refundguard.api_users WHERE user_id=%s',(uid,)).fetchone():
  a.create_user(uid,'ORG-DEMO',sys.argv[2],sys.stdin.read().strip())
print('Account ready:',uid)
"""
        subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "api",
                "python",
                "scripts/container_entrypoint.py",
                "python",
                "-c",
                code,
                f"demo-{role}",
                role,
            ],
            input=password,
            text=True,
            cwd=ROOT,
            check=True,
        )
    run(
        *compose,
        "exec",
        "-T",
        "api",
        "python",
        "scripts/container_entrypoint.py",
        "refundguard",
        "--model-dir",
        ".cache/model",
        "ingest",
        "--output",
        "/tmp/refundguard-ingestion.json",
    )
    if args.llm:
        run("uv", "run", "--locked", "python", "scripts/download_llm.py")
    run(*compose, "up", "-d", "web")
    print(
        json.dumps(
            {
                "url": "http://127.0.0.1:3000",
                "users": ["demo-support", "demo-reviewer"],
                "password_files": [".local/support_password", ".local/reviewer_password"],
                "refund_execution": "synthetic ledger only",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
