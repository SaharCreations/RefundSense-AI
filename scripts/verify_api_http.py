"""Real loopback HTTP + Uvicorn restart smoke test on a disposable test database.

All accounts and approvals are synthetic. Generated credentials and bearer
values are never written to reports. The original demo orders remain unchanged.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from refundguard.orders import seed_demo
from refundguard.rules import Customer
from refundguard.rules_evaluation import order_from_dict
from refundguard.workflow import workflow_connection

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/api_v1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-explanations", action="store_true")
    parser.add_argument("--report-directory", type=Path)
    args = parser.parse_args()
    output = args.report_directory or (
        ROOT / "reports/explanation_v1" if args.with_explanations else OUTPUT
    )
    url = os.environ["TEST_DATABASE_URL"]
    password = secrets.token_urlsafe(24)
    env = dict(
        os.environ,
        DATABASE_URL=url,
        REFUNDGUARD_BOOTSTRAP_PASSWORD=password,
        REFUNDGUARD_MODEL_DIR=str(ROOT / ".cache/model"),
    )
    if args.with_explanations:
        env["REFUNDGUARD_LLM_MODEL"] = str(ROOT / ".cache/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf")
    executable = str(Path(sys.executable).with_name("refundguard"))
    suffix = str(uuid4())[:8]
    support, reviewer = f"http-support-{suffix}", f"http-reviewer-{suffix}"
    for arguments in [
        ["auth-init"],
        [
            "auth-create-user",
            "--organization-id",
            "ORG-DEMO",
            "--user-id",
            support,
            "--role",
            "support",
        ],
        [
            "auth-create-user",
            "--organization-id",
            "ORG-DEMO",
            "--user-id",
            reviewer,
            "--role",
            "reviewer",
        ],
    ]:
        command = subprocess.run(
            [executable, *arguments], cwd=ROOT, env=env, capture_output=True, text=True
        )
        assert command.returncode == 0, "Trusted provisioning CLI failed"
    raw = json.loads((ROOT / "data/demo_records.json").read_text())
    customer = replace(Customer(**raw["customers"][0]), customer_id=f"C-HTTP-{suffix}")
    order = replace(
        order_from_dict(raw["orders"][1]),
        order_id=f"O-HTTP-{suffix}",
        customer_id=customer.customer_id,
        delivered_on=datetime.now(UTC).date() - timedelta(days=5),
    )
    with workflow_connection(url) as conn:
        with conn.transaction():
            seed_demo(conn, [order], [customer])
        version = conn.execute("SELECT version() AS version").fetchone()["version"]
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    checks = []

    def start():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "refundguard.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Uvicorn failed to start")
                try:
                    if httpx.get(base + "/health", timeout=1, trust_env=False).status_code == 200:
                        return process
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("Uvicorn readiness deadline exceeded")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise

    def stop(process):
        process.terminate()
        process.wait(timeout=10)

    def request(client, method, path, expected, **kwargs):
        response = client.request(method, path, **kwargs)
        checks.append(
            {
                "method": method,
                "path": path,
                "expected_status": expected,
                "actual_status": response.status_code,
            }
        )
        assert response.status_code == expected, f"HTTP smoke failure on {method} {path}"
        return response.json() if response.content else None

    process = start()
    try:
        with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
            support_login = request(
                client,
                "POST",
                "/api/v1/auth/login",
                200,
                json={"user_id": support, "password": password},
            )
            reviewer_login = request(
                client,
                "POST",
                "/api/v1/auth/login",
                200,
                json={"user_id": reviewer, "password": password},
            )
            support_headers = {"Authorization": "Bearer " + support_login["access_token"]}
            reviewer_headers = {"Authorization": "Bearer " + reviewer_login["access_token"]}
            data = {"order_id": order.order_id, "customer_id": customer.customer_id}
            request(client, "POST", "/api/v1/assessments", 401, json=data)
            assessed = request(
                client, "POST", "/api/v1/assessments", 200, json=data, headers=support_headers
            )
            assert assessed["refund_amount_minor"] == 8500
            explanations = {}
            if args.with_explanations:
                for name, question in [
                    ("supported", "What is the standard return window for most eligible items?"),
                    ("unsupported", "What refund policy applies to cryptocurrency payments?"),
                ]:
                    explanations[name] = request(
                        client,
                        "POST",
                        "/api/v1/policy/answer",
                        200,
                        json={"question": question},
                        headers=support_headers,
                    )
                    assert "generation" not in explanations[name]["answer"]
                    assert explanations[name]["answer"]["execution_allowed"] is False
                assert explanations["supported"]["answer"]["status"] == "answered"
                assert explanations["unsupported"]["answer"]["status"] == "abstain"
                explanations["assessment"] = request(
                    client,
                    "POST",
                    "/api/v1/assessments/explain",
                    200,
                    json=data,
                    headers=support_headers,
                )
                assert explanations["assessment"]["authoritative_assessment"] == assessed
                assert "USD 85.00" in explanations["assessment"]["deterministic_summary"]
                assert (
                    explanations["assessment"]["policy_explanation"]["execution_allowed"] is False
                )
                with workflow_connection(url) as conn:
                    assert (
                        conn.execute(
                            "SELECT count(*) AS n FROM refundguard.demo_refund_ledger "
                            "WHERE payload->'refund'->>'order_id'=%s",
                            (order.order_id,),
                        ).fetchone()["n"]
                        == 0
                    )

            pending = request(
                client, "POST", "/api/v1/workflows", 200, json=data, headers=support_headers
            )
            assert pending["status"] == "pending"
            path = "/api/v1/workflows/" + pending["workflow_id"]
            decision = {"approved": True, "payload_sha256": pending["payload_sha256"]}
            request(
                client, "POST", path + "/decisions", 403, json=decision, headers=support_headers
            )
            request(
                client,
                "POST",
                path + "/decisions",
                422,
                json={**decision, "approved": "true"},
                headers=reviewer_headers,
            )
            request(
                client,
                "POST",
                path + "/decisions",
                409,
                json={**decision, "payload_sha256": "0" * 64},
                headers=reviewer_headers,
            )
            evidence = request(
                client,
                "POST",
                "/api/v1/policy/search",
                200,
                json={"question": "What is the current opened electronics restocking fee?", "k": 3},
                headers=support_headers,
            )
            assert len(evidence["retrieved"]) == 3
            assert all(c["status"] == "CURRENT" for c in evidence["retrieved"])
        stop(process)
        process = start()
        with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
            identity = request(client, "GET", "/api/v1/auth/me", 200, headers=reviewer_headers)
            assert identity["role"] == "reviewer"
            assert request(client, "GET", path, 200, headers=reviewer_headers) == pending
            done = request(
                client, "POST", path + "/decisions", 200, json=decision, headers=reviewer_headers
            )
            assert done["status"] == "executed"
            assert (
                request(
                    client,
                    "POST",
                    path + "/decisions",
                    200,
                    json=decision,
                    headers=reviewer_headers,
                )
                == done
            )
            assert request(client, "POST", path + "/recover", 200, headers=reviewer_headers) == done
            audit = request(client, "GET", path + "/audit", 200, headers=reviewer_headers)
            assert [e["event"] for e in audit["events"]] == ["proposed", "approved", "executed"]
            request(client, "POST", "/api/v1/auth/logout", 204, headers=reviewer_headers)
            request(client, "GET", "/api/v1/auth/me", 401, headers=reviewer_headers)
            schema = request(client, "GET", "/openapi.json", 200)
        with workflow_connection(url) as conn:
            count = conn.execute(
                "SELECT count(*) AS n FROM refundguard.demo_refund_ledger WHERE workflow_id=%s",
                (pending["workflow_id"],),
            ).fetchone()["n"]
        assert count == 1
        report = {
            "status": "passed",
            "demo_only": True,
            "postgres_version": version,
            "transport": "Real loopback HTTP through two separate Uvicorn processes",
            "checks": checks,
            "session_survives_server_restart": True,
            "approval_interrupt_survives_server_restart": True,
            "ledger_rows": count,
            "duplicate_execution": False,
            "assessment": assessed,
            "pending": pending,
            "executed": done,
            "policy_search": evidence,
            "secrets_omitted": True,
            "explanations": explanations,
            "explanations_created_no_ledger_entries": args.with_explanations,
        }
        output.mkdir(parents=True, exist_ok=True)
        (output / "http_smoke.json").write_text(json.dumps(report, indent=2) + "\n")
        (output / "openapi.json").write_text(json.dumps(schema, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "http_checks": len(checks),
                    "uvicorn_processes": 2,
                    "ledger_rows": count,
                    "real_dense_policy_search": "passed",
                },
                indent=2,
            )
        )
    finally:
        if process.poll() is None:
            stop(process)


if __name__ == "__main__":
    main()
