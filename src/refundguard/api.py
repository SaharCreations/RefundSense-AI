"""FastAPI boundary for SQL rules, policy retrieval, and human approval.

No identities, scope, amounts, assessment dates, or executable payloads come from
LLM prose. Use uvicorn refundguard.api:create_app --factory --host 127.0.0.1.
"""

import os
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from .auth import AuthenticationFailed, AuthStore, Identity, LoginLimited
from .corpus import load_corpus
from .orders import order_connection, read_order_customer
from .rules import Principal, RecordUnavailable, RefundRequest, Ruleset, assess_refund, exact_id
from .workflow import ApprovalWorkflow, workflow_connection, workflow_id

PREFIX = "/api/v1"


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path = Path("data")
    rules_config: Path = Path("config/demo_ruleset.json")
    model_dir: Path | None = None
    llm_model: Path | None = None
    llm_lock: Path = Path("llm.lock.json")

    @classmethod
    def from_env(cls):
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL is required")
        return cls(
            url,
            Path(os.getenv("REFUNDGUARD_DATA_DIR", "data")),
            Path(os.getenv("REFUNDGUARD_RULES_CONFIG", "config/demo_ruleset.json")),
            Path(os.environ["REFUNDGUARD_MODEL_DIR"])
            if os.getenv("REFUNDGUARD_MODEL_DIR")
            else None,
            Path(os.environ["REFUNDGUARD_LLM_MODEL"])
            if os.getenv("REFUNDGUARD_LLM_MODEL")
            else None,
            Path(os.getenv("REFUNDGUARD_LLM_LOCK", "llm.lock.json")),
        )


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    user_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("user_id")
    @classmethod
    def exact_user(cls, value):
        return exact_id(value)


class OrderInput(Input):
    order_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    customer_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    reason: Literal["standard_return", "damaged_on_arrival", "warranty"] = "standard_return"

    @field_validator("order_id", "customer_id")
    @classmethod
    def exact_record(cls, value):
        return exact_id(value)


class Decision(Input):
    approved: StrictBool
    payload_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class Search(Input):
    question: Annotated[StrictStr, Field(min_length=1, max_length=2000)]
    k: Annotated[StrictInt, Field(ge=1, le=20)] = 5

    @field_validator("question")
    @classmethod
    def not_empty(cls, value):
        if not value.strip():
            raise ValueError("Question must contain text")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int


class IdentityResponse(BaseModel):
    user_id: str
    organization_id: str
    role: Literal["support", "reviewer"]


class AssessmentResponse(BaseModel):
    decision: Literal["eligible", "ineligible", "review"]
    reason_code: str
    refund_amount_minor: int | None
    restocking_fee_minor: int | None
    currency: str
    candidate_payload: dict | None
    assessment_only: bool
    execution_allowed: bool
    human_approval_required_for_execution: bool
    rules_version: str
    ruleset_fingerprint: str
    conventions: dict
    citations: list[dict]
    snapshot: dict


class RefundPayload(BaseModel):
    action: Literal["refund"]
    organization_id: str
    order_id: str
    customer_id: str
    refund_amount_minor: int
    restocking_fee_minor: int
    currency: str
    payment_method: str
    original_payment_reference: str


class ExecutionPayload(BaseModel):
    execution_target: Literal["demo_ledger"]
    idempotency_key: str
    refund: RefundPayload


class WorkflowResponse(BaseModel):
    workflow_id: str
    status: Literal["pending", "approved", "rejected", "expired", "stale", "executed"]
    exact_execution_payload: ExecutionPayload
    payload_sha256: str
    approval_ttl_seconds: int
    expires_at: str | None
    assessment: AssessmentResponse
    result: dict | None
    demo_only: bool


class BlockedResponse(BaseModel):
    status: Literal["assessment_blocked"]
    assessment: AssessmentResponse


class EvidenceResponse(BaseModel):
    question: str
    scope: Literal["current"]
    as_of: str
    collection_id: str
    retrieved: list[dict]
    evidence_only: bool


class ExplanationResponse(BaseModel):
    status: Literal["answered", "abstain"]
    explanation: str
    citations: list[dict]
    abstention_reason: str | None
    human_review_required: bool
    explanation_version: str
    execution_allowed: Literal[False]
    evidence_is_untrusted_reference: bool


class PolicyAnswerResponse(BaseModel):
    question: str
    as_of: str
    collection_id: str
    retrieval_scope: Literal["all"]
    answer: ExplanationResponse
    selector: dict


class AssessmentExplanationResponse(BaseModel):
    authoritative_assessment: AssessmentResponse
    deterministic_summary: str
    policy_explanation: ExplanationResponse
    selector: dict


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    ruleset = Ruleset(settings.rules_config, settings.data_dir / "policies")
    hasher = PasswordHasher()
    dummy_hash = hasher.hash(secrets.token_urlsafe(32))
    app = FastAPI(
        title="RefundSense AI",
        version="0.1.0",
        description="Authenticated portfolio demo; no real payment gateway.",
    )
    app.state.settings = settings
    app.state.ruleset = ruleset
    app.state.hasher, app.state.dummy_hash = hasher, dummy_hash
    app.state.clock = lambda: datetime.now(UTC)
    app.state.selector = None
    app.state.selector_load_lock = threading.Lock()
    app.state.embedder = None
    app.state.embedding_lock = threading.Lock()
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw values or attacker-controlled extra field names.
        known = {
            "body",
            "path",
            "query",
            "user_id",
            "password",
            "order_id",
            "customer_id",
            "reason",
            "wid",
            "approved",
            "payload_sha256",
            "question",
            "k",
        }
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "invalid_request",
                    "fields": [
                        {
                            "location": [
                                part if part in known else "unknown_field" for part in e["loc"]
                            ],
                            "type": e["type"],
                        }
                        for e in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(RecordUnavailable)
    async def unavailable(request, exc):
        return JSONResponse(status_code=404, content={"detail": {"code": "record_unavailable"}})

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": {"code": "database_unavailable"}})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(status_code=500, content={"detail": {"code": "internal_error"}})

    def auth_store(conn):
        return AuthStore(conn, hasher, dummy_hash, clock=app.state.clock)

    def identity(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Identity:
        if not credentials:
            raise HTTPException(
                401, {"code": "authentication_required"}, headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            with workflow_connection(settings.database_url) as conn:
                return auth_store(conn).authenticate(credentials.credentials)
        except AuthenticationFailed as exc:
            raise HTTPException(
                401, {"code": "invalid_session"}, headers={"WWW-Authenticate": "Bearer"}
            ) from exc

    def reviewer(user: Annotated[Identity, Depends(identity)]) -> Identity:
        if user.role != "reviewer":
            raise HTTPException(403, {"code": "reviewer_required"})
        return user

    def exact_workflow(wid: str):
        try:
            return workflow_id(wid)
        except ValueError as exc:
            raise HTTPException(422, {"code": "invalid_workflow_id"}) from exc

    def workflow_action(user, wid, operation):
        wid = exact_workflow(wid)
        with workflow_connection(settings.database_url) as conn:
            service = ApprovalWorkflow(conn, ruleset, clock=app.state.clock)
            try:
                return operation(service, user.actor, wid)
            except RecordUnavailable:
                raise
            except ValueError as exc:
                raise HTTPException(409, {"code": "workflow_conflict"}) from exc

    @app.get("/health")
    def health():
        with workflow_connection(settings.database_url) as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "demo_only": True}

    @app.post(PREFIX + "/auth/login", response_model=TokenResponse)
    def login(body: Login):
        try:
            with workflow_connection(settings.database_url) as conn:
                return auth_store(conn).login(body.user_id, body.password.get_secret_value())
        except LoginLimited as exc:
            raise HTTPException(
                429, {"code": "login_limited"}, headers={"Retry-After": "900"}
            ) from exc
        except AuthenticationFailed as exc:
            raise HTTPException(
                401, {"code": "invalid_credentials"}, headers={"WWW-Authenticate": "Bearer"}
            ) from exc

    @app.get(PREFIX + "/auth/me", response_model=IdentityResponse)
    def me(user: Annotated[Identity, Depends(identity)]):
        return user

    @app.post(PREFIX + "/auth/logout", status_code=204)
    def logout(
        user: Annotated[Identity, Depends(identity)],
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    ):
        with workflow_connection(settings.database_url) as conn:
            auth_store(conn).logout(credentials.credentials)
        return None

    @app.post(PREFIX + "/assessments", response_model=AssessmentResponse)
    def assessment(body: OrderInput, user: Annotated[Identity, Depends(identity)]):
        req = RefundRequest(body.order_id, body.customer_id, app.state.clock().date(), body.reason)
        principal = Principal(user.organization_id)
        with order_connection(settings.database_url) as conn:
            order, customer = read_order_customer(conn, principal, req)
            return assess_refund(principal, customer, order, req, ruleset)

    @app.post(PREFIX + "/workflows", response_model=WorkflowResponse | BlockedResponse)
    def propose(body: OrderInput, user: Annotated[Identity, Depends(identity)]):
        if user.organization_id != "ORG-DEMO":
            raise HTTPException(403, {"code": "demo_organization_required"})
        with workflow_connection(settings.database_url) as conn:
            service = ApprovalWorkflow(conn, ruleset, clock=app.state.clock)
            return service.propose(user.actor, body.order_id, body.customer_id, body.reason)

    @app.get(PREFIX + "/workflows/{wid}", response_model=WorkflowResponse)
    def view(wid: str, user: Annotated[Identity, Depends(identity)]):
        return workflow_action(user, wid, lambda service, actor, key: service.view(actor, key))

    @app.post(PREFIX + "/workflows/{wid}/decisions", response_model=WorkflowResponse)
    def decide(wid: str, body: Decision, user: Annotated[Identity, Depends(reviewer)]):
        return workflow_action(
            user,
            wid,
            lambda service, actor, key: service.decide(
                actor, key, body.approved, body.payload_sha256
            ),
        )

    @app.post(PREFIX + "/workflows/{wid}/recover", response_model=WorkflowResponse)
    def recover(wid: str, user: Annotated[Identity, Depends(reviewer)]):
        return workflow_action(user, wid, lambda service, actor, key: service.recover(actor, key))

    @app.get(PREFIX + "/workflows/{wid}/audit")
    def audit(wid: str, user: Annotated[Identity, Depends(reviewer)]):
        wid = exact_workflow(wid)
        with workflow_connection(settings.database_url) as conn:
            service = ApprovalWorkflow(conn, ruleset, clock=app.state.clock)
            with service.transaction():
                service._row(wid, user.actor)  # Scope check before audit access.
                events = conn.execute(
                    "SELECT event_id, actor_id, event, occurred_at, detail "
                    "FROM refundguard.audit_events WHERE workflow_id=%s ORDER BY event_id",
                    (wid,),
                ).fetchall()
        return {"workflow_id": wid, "events": events}

    def retrieve_evidence(question, k, scope):
        if settings.model_dir is None or not settings.model_dir.is_dir():
            raise HTTPException(503, {"code": "policy_search_not_configured"})
        from .embeddings import DenseEmbedder
        from .store import PolicyStore, connection

        with app.state.embedding_lock:
            if app.state.embedder is None:
                app.state.embedder = DenseEmbedder(settings.model_dir)
            embedder = app.state.embedder
            try:
                vector = embedder.queries([question])[0]
            except ValueError as exc:
                raise HTTPException(422, {"code": "question_exceeds_model_limits"}) from exc
        as_of = app.state.clock().date()
        chunks = load_corpus(settings.data_dir / "policies")
        with connection(settings.database_url) as conn:
            store = PolicyStore(conn)
            try:
                collection = store.require_collection(chunks, embedder.spec)
            except ValueError as exc:
                raise HTTPException(503, {"code": "policy_index_not_ready"}) from exc
            retrieved = store.retrieve(collection, vector, k, scope, as_of)
        return retrieved, collection, as_of

    def local_selector():
        if settings.llm_model is None or not settings.llm_model.is_file():
            raise HTTPException(503, {"code": "explanation_model_not_configured"})
        from .explanation import LocalSelector

        with app.state.selector_load_lock:
            if app.state.selector is None:
                try:
                    app.state.selector = LocalSelector(settings.llm_model, settings.llm_lock)
                except ImportError as exc:
                    raise HTTPException(503, {"code": "explanation_runtime_not_installed"}) from exc
                except (ValueError, FileNotFoundError) as exc:
                    raise HTTPException(503, {"code": "explanation_model_invalid"}) from exc
        return app.state.selector

    def demo_scope(user):
        if user.organization_id != "ORG-DEMO":
            raise HTTPException(403, {"code": "demo_organization_required"})

    @app.post(PREFIX + "/policy/search", response_model=EvidenceResponse)
    def search(body: Search, user: Annotated[Identity, Depends(identity)]):
        demo_scope(user)
        retrieved, collection, as_of = retrieve_evidence(body.question, body.k, "current")
        return {
            "question": body.question,
            "scope": "current",
            "as_of": as_of.isoformat(),
            "collection_id": collection,
            "retrieved": retrieved,
            "evidence_only": True,
        }

    @app.post(PREFIX + "/policy/answer", response_model=PolicyAnswerResponse)
    def policy_answer(body: Search, user: Annotated[Identity, Depends(identity)]):
        from .explanation import explain

        demo_scope(user)
        selector = local_selector()
        # Historical candidates are permitted for status questions only. Quote
        # validation rejects all superseded eligibility/window/fee sections.
        retrieved, collection, as_of = retrieve_evidence(body.question, body.k, "all")
        answer = explain(body.question, retrieved, selector, as_of)
        return {
            "question": body.question,
            "as_of": as_of.isoformat(),
            "collection_id": collection,
            "retrieval_scope": "all",
            "answer": answer,
            "selector": selector.spec,
        }

    @app.post(PREFIX + "/assessments/explain", response_model=AssessmentExplanationResponse)
    def explain_assessment(body: OrderInput, user: Annotated[Identity, Depends(identity)]):
        from .explanation import assessment_query, assessment_summary, explain

        demo_scope(user)
        result = assessment(body, user)
        selector = local_selector()
        question = assessment_query(result)
        retrieved, _, as_of = retrieve_evidence(question, 5, "current")
        explanation = explain(question, retrieved, selector, as_of, assessment=result)
        return {
            "authoritative_assessment": result,
            "deterministic_summary": assessment_summary(result),
            "policy_explanation": explanation,
            "selector": selector.spec,
        }

    return app
