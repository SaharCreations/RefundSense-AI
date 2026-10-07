"""Demo-only subprocess restart verification against TEST_DATABASE_URL.

Creates unique ORG-DEMO test records. Decisions are explicitly synthetic test
reviewer inputs, never approvals for real customer payments.
"""

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from refundguard.orders import seed_demo
from refundguard.rules import Customer
from refundguard.rules_evaluation import order_from_dict
from refundguard.workflow import workflow_connection

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/workflow_v1"


def main():
    url = os.environ["TEST_DATABASE_URL"]
    env = dict(os.environ, DATABASE_URL=url)
    executable = Path(sys.executable).with_name("refundguard")
    command_log = []

    def run(*args):
        command = [str(executable), *args]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        command_log.append({"args": list(args), "returncode": result.returncode})
        if result.returncode:
            raise RuntimeError(f"CLI failed: {result.stderr}")
        return json.loads(result.stdout)

    run("workflow-init")
    records = json.loads((ROOT / "data/demo_records.json").read_text())
    suffix = str(uuid4())[:8]
    customer = replace(Customer(**records["customers"][0]), customer_id=f"C-RESTART-{suffix}")
    order = replace(
        order_from_dict(records["orders"][1]),
        order_id=f"O-RESTART-{suffix}",
        customer_id=customer.customer_id,
        delivered_on=datetime.now(UTC).date() - timedelta(days=5),
    )
    with workflow_connection(url) as conn:
        with conn.transaction():
            seed_demo(conn, [order], [customer])
        version = conn.execute("SELECT version() AS version").fetchone()["version"]
    identity = ["--organization-id", "ORG-DEMO", "--user-id", "synthetic-test-reviewer"]
    pending = run(
        "workflow-propose",
        *identity,
        "--order-id",
        order.order_id,
        "--customer-id",
        customer.customer_id,
    )
    assert pending["status"] == "pending"
    wid = pending["workflow_id"]
    resumed_view = run("workflow-view", *identity, "--workflow-id", wid)
    assert resumed_view == pending
    done = run(
        "workflow-decide",
        *identity,
        "--workflow-id",
        wid,
        "--decision",
        "approve",
        "--payload-sha256",
        pending["payload_sha256"],
    )
    retry = run("workflow-recover", *identity, "--workflow-id", wid)
    replay = run(
        "workflow-decide",
        *identity,
        "--workflow-id",
        wid,
        "--decision",
        "approve",
        "--payload-sha256",
        pending["payload_sha256"],
    )
    assert done["status"] == "executed" and done == retry == replay
    with workflow_connection(url) as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM refundguard.demo_refund_ledger WHERE workflow_id=%s",
            (wid,),
        ).fetchone()["n"]
        final = conn.execute(
            "SELECT refunded_minor, refund_state FROM refundguard.orders "
            "WHERE organization_id=%s AND order_id=%s",
            ("ORG-DEMO", order.order_id),
        ).fetchone()
        events = conn.execute(
            "SELECT actor_id, event, detail FROM refundguard.audit_events "
            "WHERE workflow_id=%s ORDER BY event_id",
            (wid,),
        ).fetchall()
    assert n == 1 and final == {"refunded_minor": 8500, "refund_state": "refunded"}
    assert [e["event"] for e in events] == ["proposed", "approved", "executed"]
    evidence = {
        "status": "passed",
        "demo_only": True,
        "postgres_version": version,
        "processes": len(command_log),
        "commands": command_log,
        "pending": pending,
        "executed": done,
        "retry_receipt_matches": True,
        "ledger_rows": n,
        "live_order_after": final,
        "audit_events": events,
        "scope": "Independent CLI processes, sequential retries; not concurrency verification",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "process_restart.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in evidence.items()
                if k not in {"pending", "executed", "commands", "audit_events"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
