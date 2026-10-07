"""Exercise the real browser -> Next.js -> FastAPI -> SQL approval path.

Requires a DISPOSABLE TEST_DATABASE_URL or explicit --pglite fallback. Generates
synthetic accounts/orders; performs synthetic HUMAN review through browser UI;
no payment provider or inference mock is used. Credentials remain private files
outside reports and are removed at the end. This is NOT a refund automation API.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from refundguard.auth import SCHEMA_AUTH, AuthStore
from refundguard.orders import seed_demo
from refundguard.rules import Customer, Ruleset
from refundguard.rules_evaluation import order_from_dict
from refundguard.workflow import ApprovalWorkflow, workflow_connection

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_http(url, proc):
    start = time.monotonic()
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() - start < 90:
            if proc.poll() is not None:
                raise RuntimeError("Local verification server exited; inspect its log")
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError("Local verification server readiness timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pglite", action="store_true")
    parser.add_argument("--with-retrieval", action="store_true")
    parser.add_argument("--report-directory", type=Path, default=ROOT / "reports/completion_v1")
    args = parser.parse_args()
    output = args.report_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NEXT_TELEMETRY_DISABLED="1", ORT_DISABLE_TELEMETRY="1")
    processes = []
    logs = []
    with tempfile.TemporaryDirectory(prefix="refundguard-live-") as temp:
        temp_path = Path(temp)
        try:
            if args.pglite:
                port = free_port()
                env.update(
                    REFUNDGUARD_PGLITE_PORT=str(port), REFUNDGUARD_PGLITE_DIR=str(temp_path / "pg")
                )
                log = (output / "postgres-wasm.log").open("w")
                logs.append(log)
                pg = subprocess.Popen(
                    ["node", "verification/pglite/server.mjs"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(pg)
                env["TEST_DATABASE_URL"] = (
                    f"postgresql://postgres@127.0.0.1:{port}/postgres?sslmode=disable"
                )
                start = time.monotonic()
                while time.monotonic() - start < 45:
                    try:
                        with workflow_connection(env["TEST_DATABASE_URL"]) as conn:
                            conn.execute("SELECT 1")
                        break
                    except Exception:
                        if pg.poll() is not None:
                            raise RuntimeError("Verification SQL runtime exited") from None
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Verification SQL readiness timed out")
            elif not env.get("TEST_DATABASE_URL"):
                raise ValueError(
                    "Set TEST_DATABASE_URL to a disposable PostgreSQL+pgvector database"
                )
            env["DATABASE_URL"] = env["TEST_DATABASE_URL"]
            with (output / "python-tests.log").open("w") as log:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--junitxml",
                        str(output / "python-tests.xml"),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                    check=True,
                )
            password = secrets.token_urlsafe(24)
            suffix = str(uuid4())[:8]
            raw = json.loads((ROOT / "data/demo_records.json").read_text())
            customer = replace(Customer(**raw["customers"][0]), customer_id=f"C-LIVE-{suffix}")
            original = order_from_dict(raw["orders"][1])
            orders = [
                replace(
                    original,
                    order_id=f"O-LIVE-{kind}-{suffix}",
                    customer_id=customer.customer_id,
                    delivered_on=datetime.now(UTC).date() - timedelta(days=5),
                )
                for kind in ["approve", "stale", "reject", "pending"]
            ]
            users = {role: f"live-{role}-{suffix}" for role in ["support", "reviewer"]}
            with workflow_connection(env["DATABASE_URL"]) as conn:
                with conn.transaction():
                    seed_demo(conn, orders, [customer])
                ApprovalWorkflow(
                    conn, Ruleset(ROOT / "config/demo_ruleset.json", ROOT / "data/policies")
                ).setup()
                conn.execute(SCHEMA_AUTH)
                for role, uid in users.items():
                    AuthStore(conn).create_user(uid, "ORG-DEMO", role, password)
                version = conn.execute("SELECT version() AS v").fetchone()["v"]
                vector_version = conn.execute(
                    "SELECT extversion AS v FROM pg_extension WHERE extname='vector'"
                ).fetchone()["v"]
            if args.with_retrieval:
                env["REFUNDGUARD_MODEL_DIR"] = str(ROOT / ".cache/model")
                with (output / "ingestion.log").open("w") as log:
                    subprocess.run(
                        [
                            str(Path(sys.executable).with_name("refundguard")),
                            "--model-dir",
                            env["REFUNDGUARD_MODEL_DIR"],
                            "ingest",
                            "--output",
                            str(output / "ingestion.json"),
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=log,
                        check=True,
                    )
            else:
                env.pop("REFUNDGUARD_MODEL_DIR", None)
            api_port, web_port = free_port(), free_port()
            env["REFUNDGUARD_API_URL"] = f"http://127.0.0.1:{api_port}"
            env["REFUNDGUARD_WEB_ORIGIN"] = f"http://127.0.0.1:{web_port}"
            fixture = {
                "users": users,
                "password": password,
                "orders": {
                    kind: order.order_id
                    for kind, order in zip(
                        ["approve", "stale", "reject", "pending"], orders, strict=True
                    )
                },
                "customer_id": customer.customer_id,
                "with_retrieval": args.with_retrieval,
            }
            private = temp_path / "fixture.json"
            private.write_text(json.dumps(fixture))
            private.chmod(0o600)
            env["REFUNDGUARD_LIVE_FIXTURE"] = str(private)
            env["REFUNDGUARD_LIVE_ORIGIN"] = env["REFUNDGUARD_WEB_ORIGIN"]
            env["REFUNDGUARD_LIVE_REPORT"] = str(output / "live-browser-results.json")
            env["REFUNDGUARD_DEMO_DIR"] = str(output)
            for name, command, workdir in [
                (
                    "api",
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "refundguard.api:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                    ],
                    ROOT,
                ),
                ("web", ["npm", "run", "dev", "--", "--port", str(web_port)], ROOT / "frontend"),
            ]:
                log = (output / f"{name}.log").open("w")
                logs.append(log)
                proc = subprocess.Popen(command, cwd=workdir, env=env, stdout=log, stderr=log)
                processes.append(proc)
                wait_http(
                    env["REFUNDGUARD_API_URL"] + "/health"
                    if name == "api"
                    else env["REFUNDGUARD_WEB_ORIGIN"],
                    proc,
                )
            with (output / "live-browser.log").open("w") as log:
                subprocess.run(
                    ["npx", "playwright", "test", "--config", "playwright.live.config.ts"],
                    cwd=ROOT / "frontend",
                    env=env,
                    stdout=log,
                    stderr=log,
                    check=True,
                )
            with workflow_connection(env["DATABASE_URL"]) as conn:
                rows = conn.execute(
                    "SELECT order_id,refunded_minor,refund_state FROM refundguard.orders "
                    "WHERE organization_id='ORG-DEMO' AND customer_id=%s ORDER BY order_id",
                    (customer.customer_id,),
                ).fetchall()
                assert (
                    next(r for r in rows if r["order_id"] == fixture["orders"]["approve"])[
                        "refunded_minor"
                    ]
                    == 8500
                )
                assert all(
                    r["refunded_minor"] == 0
                    for r in rows
                    if r["order_id"] != fixture["orders"]["approve"]
                )
                ledger = conn.execute(
                    "SELECT count(*) AS n FROM refundguard.demo_refund_ledger "
                    "WHERE payload->'refund'->>'organization_id'='ORG-DEMO' "
                    "AND payload->'refund'->>'order_id'=%s",
                    (fixture["orders"]["approve"],),
                ).fetchone()["n"]
                assert ledger == 1
                result = {
                    "scope": (
                        "real browser, Next.js, FastAPI, psycopg, "
                        "official PostgreSQL LangGraph checkpoints and synthetic SQL ledger"
                    ),
                    "postgres_version": version,
                    "pgvector_version": vector_version,
                    "pglite": args.pglite,
                    "retrieval": args.with_retrieval,
                    "original_seed_unchanged": True,
                    "synthetic_order_results": rows,
                    "approved_order_ledger_entries": ledger,
                    "credentials_saved_in_report": False,
                }
                (output / "live-stack.json").write_text(
                    json.dumps(result, indent=2, default=str) + "\n"
                )
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            for log in logs:
                log.close()
    print("Full-stack verification completed; credentials were removed.")


if __name__ == "__main__":
    main()
