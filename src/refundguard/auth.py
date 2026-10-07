"""SQL-backed local accounts and revocable opaque bearer sessions.

Account organization and role are server-side facts. No self-registration,
client-selected roles, JWT claims, or model-issued authorization is accepted.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .rules import exact_id
from .workflow import Actor

SESSION_TTL = timedelta(hours=8)
LOGIN_WINDOW = timedelta(minutes=15)
MAX_LOGIN_ATTEMPTS = 5
SCHEMA_AUTH = """
CREATE SCHEMA IF NOT EXISTS refundguard;
CREATE TABLE IF NOT EXISTS refundguard.api_users (
    user_id text PRIMARY KEY,
    organization_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('support', 'reviewer')),
    password_hash text NOT NULL,
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS refundguard.api_sessions (
    token_sha256 text PRIMARY KEY,
    user_id text NOT NULL REFERENCES refundguard.api_users(user_id),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS api_session_expiry ON refundguard.api_sessions(expires_at);
CREATE TABLE IF NOT EXISTS refundguard.login_limits (
    username_sha256 text PRIMARY KEY,
    window_started timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts >= 0)
);
"""


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    user_id: str
    organization_id: str
    role: str

    @property
    def actor(self):
        return Actor(self.organization_id, self.user_id)


class AuthenticationFailed(ValueError):
    pass


class LoginLimited(ValueError):
    pass


class AuthStore:
    def __init__(self, conn, hasher=None, dummy_hash=None, clock=None):
        self.conn = conn
        self.hasher = hasher or PasswordHasher()
        self.dummy_hash = dummy_hash or self.hasher.hash(secrets.token_urlsafe(32))
        self.clock = clock or (lambda: datetime.now(UTC))

    def create_user(self, user_id, organization_id, role, password):
        exact_id(user_id)
        exact_id(organization_id)
        if role not in {"support", "reviewer"}:
            raise ValueError("Role must be support or reviewer")
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise ValueError("Choose a password of 12 to 128 characters")
        with self.conn.transaction():
            exists = self.conn.execute(
                "SELECT 1 FROM refundguard.api_users WHERE user_id=%s", (user_id,)
            ).fetchone()
            if exists:
                raise ValueError("Account already exists; provisioning never overwrites it")
            self.conn.execute(
                "INSERT INTO refundguard.api_users "
                "(user_id, organization_id, role, password_hash) VALUES (%s,%s,%s,%s)",
                (user_id, organization_id, role, self.hasher.hash(password)),
            )

    def login(self, user_id, password):
        exact_id(user_id)
        now, key = self.clock(), digest(user_id)
        # Reserve/check an attempt before expensive password verification. PostgreSQL
        # serializes the account bucket across API workers; no process-local limiter.
        with self.conn.transaction():
            row = self.conn.execute(
                """INSERT INTO refundguard.login_limits
                (username_sha256, window_started, attempts) VALUES (%s,%s,1)
                ON CONFLICT (username_sha256) DO UPDATE SET
                attempts=CASE WHEN refundguard.login_limits.window_started <= %s
                    THEN 1 ELSE refundguard.login_limits.attempts+1 END,
                window_started=CASE WHEN refundguard.login_limits.window_started <= %s
                    THEN EXCLUDED.window_started ELSE refundguard.login_limits.window_started END
                RETURNING attempts""",
                (key, now, now - LOGIN_WINDOW, now - LOGIN_WINDOW),
            ).fetchone()
        if row["attempts"] > MAX_LOGIN_ATTEMPTS:
            raise LoginLimited("Try again after the login window resets")
        user = self.conn.execute(
            "SELECT * FROM refundguard.api_users WHERE user_id=%s", (user_id,)
        ).fetchone()
        try:
            valid = self.hasher.verify(user["password_hash"] if user else self.dummy_hash, password)
        except VerificationError:
            valid = False
        if not valid or not user or not user["enabled"]:
            raise AuthenticationFailed("Invalid credentials")
        verified_hash = user["password_hash"]
        token = secrets.token_urlsafe(32)
        with self.conn.transaction():
            # Recheck the account under a lock; disablement cannot race session creation.
            user = self.conn.execute(
                "SELECT * FROM refundguard.api_users WHERE user_id=%s FOR UPDATE", (user_id,)
            ).fetchone()
            if not user["enabled"]:
                raise AuthenticationFailed("Invalid credentials")
            if user["password_hash"] != verified_hash:
                try:
                    self.hasher.verify(user["password_hash"], password)
                except VerificationError as exc:
                    raise AuthenticationFailed("Invalid credentials") from exc
            self.conn.execute(
                "INSERT INTO refundguard.api_sessions "
                "(token_sha256, user_id, created_at, expires_at) VALUES (%s,%s,%s,%s)",
                (digest(token), user_id, now, now + SESSION_TTL),
            )
            self.conn.execute(
                "UPDATE refundguard.login_limits SET attempts=0 WHERE username_sha256=%s", (key,)
            )
            if self.hasher.check_needs_rehash(user["password_hash"]):
                self.conn.execute(
                    "UPDATE refundguard.api_users SET password_hash=%s WHERE user_id=%s",
                    (self.hasher.hash(password), user_id),
                )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": int(SESSION_TTL.total_seconds()),
        }

    def authenticate(self, token):
        if not isinstance(token, str) or not 40 <= len(token) <= 128:
            raise AuthenticationFailed("Invalid session")
        row = self.conn.execute(
            """SELECT u.user_id, u.organization_id, u.role FROM refundguard.api_sessions s
            JOIN refundguard.api_users u ON u.user_id=s.user_id
            WHERE s.token_sha256=%s AND s.revoked_at IS NULL AND s.expires_at>%s AND u.enabled""",
            (digest(token), self.clock()),
        ).fetchone()
        if not row:
            raise AuthenticationFailed("Invalid session")
        return Identity(**row)

    def logout(self, token):
        self.conn.execute(
            "UPDATE refundguard.api_sessions SET revoked_at=%s "
            "WHERE token_sha256=%s AND revoked_at IS NULL",
            (self.clock(), digest(token)),
        )
