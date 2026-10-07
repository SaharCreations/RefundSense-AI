"""FastAPI HTTP boundary exercised against SQL users, sessions, orders, and graph state."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from refundguard.api import Settings, create_app
from refundguard.auth import SCHEMA_AUTH, AuthStore, digest
from refundguard.orders import seed_demo
from refundguard.rules import Customer
from refundguard.rules_evaluation import order_from_dict
from refundguard.workflow import ApprovalWorkflow, workflow_connection

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-test-password-only"


@pytest.fixture(scope="module")
def api():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    settings = Settings(url, ROOT / "data", ROOT / "config/demo_ruleset.json")
    app = create_app(settings)
    clock = [datetime(2026, 10, 6, 12, tzinfo=UTC)]
    app.state.clock = lambda: clock[0]
    with workflow_connection(url) as conn:
        ApprovalWorkflow(conn, app.state.ruleset).setup()
        conn.execute(SCHEMA_AUTH)
        auth = AuthStore(conn, app.state.hasher, app.state.dummy_hash, app.state.clock)
        suffix = str(uuid4())[:8]
        users = {}
        for key, org, role in [
            ("support", "ORG-DEMO", "support"),
            ("reviewer", "ORG-DEMO", "reviewer"),
            ("other", "ORG-OTHER", "reviewer"),
            ("disabled", "ORG-DEMO", "support"),
        ]:
            users[key] = f"api-{key}-{suffix}"
            auth.create_user(users[key], org, role, PASSWORD)
        conn.execute(
            "UPDATE refundguard.api_users SET enabled=false WHERE user_id=%s", (users["disabled"],)
        )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, users, clock


@pytest.fixture
def records(api):
    app, _, _, _ = api
    raw = json.loads((ROOT / "data/demo_records.json").read_text())
    suffix = str(uuid4())[:8]
    customers = [
        replace(Customer(**c), customer_id=f"{c['customer_id']}-{suffix}") for c in raw["customers"]
    ]
    orders = [
        replace(
            order_from_dict(o),
            order_id=f"{o['order_id']}-{suffix}",
            customer_id=f"{o['customer_id']}-{suffix}",
        )
        for o in raw["orders"]
    ]
    with workflow_connection(app.state.settings.database_url) as conn:
        with conn.transaction():
            seed_demo(conn, orders, customers)
    return orders


def login(api, role="support"):
    _, client, users, _ = api
    response = client.post(
        "/api/v1/auth/login", json={"user_id": users[role], "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(api, role="support"):
    return {"Authorization": "Bearer " + login(api, role)}


def body(order):
    return {"order_id": order.order_id, "customer_id": order.customer_id}


def propose(api, records):
    response = api[1].post("/api/v1/workflows", json=body(records[1]), headers=headers(api))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    return response.json()


def sql(api, statement, args=()):
    with workflow_connection(api[0].state.settings.database_url) as conn:
        cursor = conn.execute(statement, args)
        return cursor.fetchall() if cursor.description else []


def ledger(api, wid):
    return sql(api, "SELECT * FROM refundguard.demo_refund_ledger WHERE workflow_id=%s", (wid,))


def test_login_me_hashed_storage_and_logout(api):
    _, client, users, _ = api
    token = login(api)
    authorized = {"Authorization": "Bearer " + token}
    response = client.get("/api/v1/auth/me", headers=authorized)
    assert response.status_code == 200
    assert response.json() == {
        "user_id": users["support"],
        "organization_id": "ORG-DEMO",
        "role": "support",
    }
    assert response.headers["cache-control"] == "no-store"
    stored = sql(
        api, "SELECT * FROM refundguard.api_sessions WHERE token_sha256=%s", (digest(token),)
    )[0]
    assert token not in str(stored) and stored["token_sha256"] == digest(token)
    password_hash = sql(
        api, "SELECT password_hash FROM refundguard.api_users WHERE user_id=%s", (users["support"],)
    )[0]["password_hash"]
    assert password_hash.startswith("$argon2id$") and PASSWORD not in password_hash
    assert client.post("/api/v1/auth/logout", headers=authorized).status_code == 204
    assert client.get("/api/v1/auth/me", headers=authorized).status_code == 401


@pytest.mark.parametrize("authorization", [None, "Basic fake", "Bearer fake", "Bearer " + "x" * 43])
def test_missing_invalid_or_wrong_scheme_cannot_assess(api, records, authorization):
    auth_headers = {"Authorization": authorization} if authorization else {}
    assert (
        api[1].post("/api/v1/assessments", json=body(records[0]), headers=auth_headers).status_code
        == 401
    )


def test_wrong_unknown_disabled_login_share_generic_error(api):
    _, client, users, _ = api
    for user, password in [
        (users["support"], "bad"),
        ("no-such-" + str(uuid4())[:8], "bad"),
        (users["disabled"], PASSWORD),
    ]:
        result = client.post("/api/v1/auth/login", json={"user_id": user, "password": password})
        assert result.status_code == 401
        assert result.json() == {"detail": {"code": "invalid_credentials"}}
        assert password not in result.text


def test_session_expiry_disable_and_live_role_change(api):
    app, client, users, clock = api
    token = login(api, "reviewer")
    auth_headers = {"Authorization": "Bearer " + token}
    original = clock[0]
    try:
        clock[0] += timedelta(hours=8)
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
    finally:
        clock[0] = original
    sql(
        api,
        "UPDATE refundguard.api_users SET role='support' WHERE user_id=%s",
        (users["reviewer"],),
    )
    try:
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["role"] == "support"
        assert (
            client.post(f"/api/v1/workflows/{uuid4()}/recover", headers=auth_headers).status_code
            == 403
        )
        sql(
            api,
            "UPDATE refundguard.api_users SET enabled=false WHERE user_id=%s",
            (users["reviewer"],),
        )
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401
    finally:
        sql(
            api,
            "UPDATE refundguard.api_users SET role='reviewer', enabled=true WHERE user_id=%s",
            (users["reviewer"],),
        )


def test_login_limit_persists_and_resets_after_window(api):
    _, client, _, clock = api
    unknown = "rate-test-" + str(uuid4())[:8]
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"user_id": unknown, "password": "bad"}
            ).status_code
            == 401
        )
    blocked = client.post("/api/v1/auth/login", json={"user_id": unknown, "password": "bad"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "900"
    original = clock[0]
    try:
        clock[0] += timedelta(minutes=15)
        assert (
            client.post(
                "/api/v1/auth/login", json={"user_id": unknown, "password": "bad"}
            ).status_code
            == 401
        )
    finally:
        clock[0] = original


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", "ORG-OTHER"),
        ("user_id", "reviewer"),
        ("requested_on", "2020-01-01"),
        ("refund_amount_minor", 1),
        ("payload", {}),
        ("role", "reviewer"),
    ],
)
def test_client_cannot_supply_scope_date_role_or_money(api, records, field, value):
    response = api[1].post(
        "/api/v1/assessments", json={**body(records[0]), field: value}, headers=headers(api)
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_request"


def test_sql_assessment_amount_premium_and_damage_reason(api, records):
    auth_headers = headers(api)
    for index, expected in [(1, 8500), (2, 10000)]:
        result = api[1].post("/api/v1/assessments", json=body(records[index]), headers=auth_headers)
        assert result.status_code == 200, result.text
        assert result.json()["refund_amount_minor"] == expected
        assert result.json()["execution_allowed"] is False
    damaged = api[1].post(
        "/api/v1/assessments",
        json={**body(records[4]), "reason": "damaged_on_arrival"},
        headers=auth_headers,
    )
    assert damaged.status_code == 200
    assert damaged.json()["decision"] == "eligible"
    assert damaged.json()["refund_amount_minor"] == 10000


def test_exact_ids_and_cross_org_return_same_unavailable(api, records):
    auth_headers = headers(api)
    for data, authorization in [
        ({**body(records[0]), "order_id": "wrong-exact-id"}, auth_headers),
        ({**body(records[0]), "customer_id": records[2].customer_id}, auth_headers),
        (body(records[0]), headers(api, "other")),
    ]:
        result = api[1].post("/api/v1/assessments", json=data, headers=authorization)
        assert result.status_code == 404
        assert result.json() == {"detail": {"code": "record_unavailable"}}


def test_support_cannot_approve_recover_or_read_audit(api, records):
    view = propose(api, records)
    auth_headers = headers(api)
    path = "/api/v1/workflows/" + view["workflow_id"]
    assert (
        api[1]
        .post(
            path + "/decisions",
            json={"approved": True, "payload_sha256": view["payload_sha256"]},
            headers=auth_headers,
        )
        .status_code
        == 403
    )
    assert api[1].post(path + "/recover", headers=auth_headers).status_code == 403
    assert api[1].get(path + "/audit", headers=auth_headers).status_code == 403
    assert ledger(api, view["workflow_id"]) == []


def test_reviewer_exact_payload_approval_receipt_retry_and_audit(api, records):
    view = propose(api, records)
    auth_headers = headers(api, "reviewer")
    path = "/api/v1/workflows/" + view["workflow_id"]
    before = api[1].get(path, headers=auth_headers)
    assert before.json() == view and ledger(api, view["workflow_id"]) == []
    wrong = api[1].post(
        path + "/decisions",
        json={"approved": True, "payload_sha256": "0" * 64},
        headers=auth_headers,
    )
    assert wrong.status_code == 409
    approval = {"approved": True, "payload_sha256": view["payload_sha256"]}
    done = api[1].post(path + "/decisions", json=approval, headers=auth_headers)
    assert done.status_code == 200, done.text
    assert (
        done.json()["status"] == "executed" and done.json()["result"]["refund_amount_minor"] == 8500
    )
    assert (
        api[1].post(path + "/decisions", json=approval, headers=auth_headers).json() == done.json()
    )
    assert api[1].post(path + "/recover", headers=auth_headers).json() == done.json()
    assert len(ledger(api, view["workflow_id"])) == 1
    audit = api[1].get(path + "/audit", headers=auth_headers).json()
    assert [x["event"] for x in audit["events"]] == ["proposed", "approved", "executed"]
    assert audit["events"][1]["actor_id"] == api[2]["reviewer"]


def test_cross_org_workflow_decision_recovery_and_audit_denied(api, records):
    view = propose(api, records)
    auth_headers = headers(api, "other")
    path = "/api/v1/workflows/" + view["workflow_id"]
    for result in [
        api[1].get(path, headers=auth_headers),
        api[1].post(
            path + "/decisions",
            json={"approved": True, "payload_sha256": view["payload_sha256"]},
            headers=auth_headers,
        ),
        api[1].post(path + "/recover", headers=auth_headers),
        api[1].get(path + "/audit", headers=auth_headers),
    ]:
        assert result.status_code == 404, result.text
    assert ledger(api, view["workflow_id"]) == []


@pytest.mark.parametrize("approved", ["true", "false", 1, 0, None])
def test_approval_rejects_non_boolean(api, records, approved):
    view = propose(api, records)
    result = api[1].post(
        "/api/v1/workflows/" + view["workflow_id"] + "/decisions",
        json={"approved": approved, "payload_sha256": view["payload_sha256"]},
        headers=headers(api, "reviewer"),
    )
    assert result.status_code == 422
    assert ledger(api, view["workflow_id"]) == []


def test_rejection_and_ineligible_proposal_execute_nothing(api, records):
    view = propose(api, records)
    result = api[1].post(
        "/api/v1/workflows/" + view["workflow_id"] + "/decisions",
        json={"approved": False, "payload_sha256": view["payload_sha256"]},
        headers=headers(api, "reviewer"),
    )
    assert result.status_code == 200 and result.json()["status"] == "rejected"
    blocked = api[1].post("/api/v1/workflows", json=body(records[3]), headers=headers(api))
    assert blocked.status_code == 200 and blocked.json()["status"] == "assessment_blocked"
    assert ledger(api, view["workflow_id"]) == []


def test_live_changed_order_invalidates_approval(api, records):
    view = propose(api, records)
    sql(
        api,
        "UPDATE refundguard.orders SET refund_state='pending' "
        "WHERE organization_id=%s AND order_id=%s",
        ("ORG-DEMO", records[1].order_id),
    )
    result = api[1].post(
        "/api/v1/workflows/" + view["workflow_id"] + "/decisions",
        json={"approved": True, "payload_sha256": view["payload_sha256"]},
        headers=headers(api, "reviewer"),
    )
    assert result.status_code == 200 and result.json()["status"] == "stale"
    assert ledger(api, view["workflow_id"]) == []


def test_validation_never_echoes_password_or_unknown_extra_input(api):
    secret = "never-echo-this-credential"
    result = api[1].post(
        "/api/v1/auth/login", json={"user_id": "x", "password": secret, "extra": secret}
    )
    assert result.status_code == 422 and secret not in result.text
    result = api[1].post(
        "/api/v1/auth/login", json={"user_id": "x", "password": secret, secret: secret}
    )
    assert result.status_code == 422 and secret not in result.text
    result = api[1].post(
        "/api/v1/auth/login", json={"user_id": "x", "password": {"secret": secret}}
    )
    assert result.status_code == 422 and secret not in result.text


def test_policy_search_configuration_limits_and_no_scope_override(api):
    auth_headers = headers(api)
    path = "/api/v1/policy/search"
    result = api[1].post(
        path, json={"question": "What is the refund window?"}, headers=auth_headers
    )
    assert (
        result.status_code == 503
        and result.json()["detail"]["code"] == "policy_search_not_configured"
    )
    other = api[1].post(path, json={"question": "policy"}, headers=headers(api, "other"))
    assert other.status_code == 403
    for invalid in [
        {"question": " "},
        {"question": "test", "k": 0},
        {"question": "test", "k": "5"},
        {"question": "test", "scope": "all"},
    ]:
        assert api[1].post(path, json=invalid, headers=auth_headers).status_code == 422


def test_openapi_has_typed_schema_and_bearer_security(api):
    schema = api[1].get("/openapi.json").json()
    decision = schema["paths"]["/api/v1/workflows/{wid}/decisions"]["post"]
    assert decision["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["schemas"]["Decision"]["additionalProperties"] is False
    assert (
        schema["components"]["schemas"]["Decision"]["properties"]["approved"]["type"] == "boolean"
    )
    assert api[1].get("/health").json() == {"status": "ok", "demo_only": True}


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/v1/policy/answer", {"question": "What is the return window?"}),
        ("/api/v1/assessments/explain", {"order_id": "ORD-1001", "customer_id": "CUST-1001"}),
    ],
)
def test_explanation_routes_require_authentication(api, path, payload):
    assert api[1].post(path, json=payload).status_code == 401


def test_policy_explanation_requires_explicit_local_model(api):
    response = api[1].post(
        "/api/v1/policy/answer", json={"question": "Return window?"}, headers=headers(api)
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "explanation_model_not_configured"


def test_explanation_cannot_accept_client_amount_or_decision(api):
    response = api[1].post(
        "/api/v1/assessments/explain",
        headers=headers(api),
        json={
            "order_id": "ORD-1001",
            "customer_id": "CUST-1001",
            "refund_amount_minor": 1,
            "decision": "eligible",
        },
    )
    assert response.status_code == 422


def test_explanation_rejects_other_organization_before_inference(api):
    response = api[1].post(
        "/api/v1/policy/answer", json={"question": "Return window?"}, headers=headers(api, "other")
    )
    assert response.status_code == 403
