"""Parameterized PostgreSQL + pgvector storage with immutable corpus snapshots."""

from contextlib import contextmanager
from datetime import date

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .corpus import Chunk, corpus_manifest, json_hash
from .embeddings import DIMENSIONS, validate_vectors

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS refundguard;
CREATE TABLE IF NOT EXISTS refundguard.collections (
    collection_id text PRIMARY KEY,
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS refundguard.policy_chunks (
    collection_id text NOT NULL REFERENCES refundguard.collections(collection_id),
    chunk_id text NOT NULL,
    source text NOT NULL,
    section text NOT NULL,
    status text NOT NULL CHECK (status IN ('CURRENT', 'SUPERSEDED')),
    effective_date date NOT NULL,
    superseded_date date,
    payload jsonb NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (collection_id, chunk_id),
    UNIQUE (collection_id, source, section)
);
"""


def make_manifest(chunks: list[Chunk], embedding_spec: dict) -> dict:
    return {
        **corpus_manifest(chunks),
        "schema_version": 1,
        "embedding": embedding_spec,
        "search": "exact_cosine",
    }


@contextmanager
def connection(database_url: str, initialize: bool = False):
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as conn:
        if initialize:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(SCHEMA)
        register_vector(conn)
        yield conn


class PolicyStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def ingest(self, chunks: list[Chunk], vectors: object, embedding_spec: dict) -> str:
        vectors = validate_vectors(vectors, len(chunks))
        if not chunks:
            raise ValueError("Cannot ingest an empty corpus")
        manifest = make_manifest(chunks, embedding_spec)
        collection_id = json_hash(manifest)
        # The caller's connection context is a single atomic transaction. An
        # embedding or insert failure never replaces the last complete corpus.
        self.conn.execute(
            "INSERT INTO refundguard.collections (collection_id, manifest) VALUES (%s, %s) "
            "ON CONFLICT (collection_id) DO NOTHING",
            (collection_id, Jsonb(manifest)),
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.conn.execute(
                """INSERT INTO refundguard.policy_chunks
                (collection_id, chunk_id, source, section, status, effective_date,
                 superseded_date, payload, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (collection_id, chunk_id) DO NOTHING""",
                (
                    collection_id,
                    chunk.chunk_id,
                    chunk.source,
                    chunk.section,
                    chunk.status,
                    chunk.effective_date,
                    chunk.superseded_date,
                    Jsonb(chunk.to_dict()),
                    vector,
                ),
            )
        count = self.count(collection_id)
        if count != len(chunks):
            raise ValueError(f"Stored {count} chunks; expected {len(chunks)}")
        return collection_id

    def count(self, collection_id: str) -> int:
        return self.conn.execute(
            "SELECT count(*) AS n FROM refundguard.policy_chunks WHERE collection_id = %s",
            (collection_id,),
        ).fetchone()["n"]

    def require_collection(self, chunks: list[Chunk], embedding_spec: dict) -> str:
        manifest = make_manifest(chunks, embedding_spec)
        collection_id = json_hash(manifest)
        row = self.conn.execute(
            "SELECT manifest FROM refundguard.collections WHERE collection_id = %s",
            (collection_id,),
        ).fetchone()
        if row is None or row["manifest"] != manifest or self.count(collection_id) != len(chunks):
            raise ValueError(
                "No complete matching collection. Run ingest with this corpus and model."
            )
        return collection_id

    def retrieve(
        self,
        collection_id: str,
        query_vector: object,
        k: int,
        scope: str = "current",
        as_of: date | None = None,
    ) -> list[dict]:
        if k < 1 or k > 1000:
            raise ValueError("k must be between 1 and 1000")
        if scope not in {"current", "all"}:
            raise ValueError("scope must be current or all")
        vector = validate_vectors([query_vector], 1)[0]
        as_of = as_of or date.today()
        # Scope is a request-level setting. Never choose it from a question's
        # expected sources/category. No lexical boosts or exact-ID shortcuts.
        rows = self.conn.execute(
            """SELECT payload, embedding <=> %s AS distance
            FROM refundguard.policy_chunks
            WHERE collection_id = %s AND
                (%s = 'all' OR
                 (status = 'CURRENT' AND effective_date <= %s
                  AND (superseded_date IS NULL OR superseded_date >= %s)))
            ORDER BY distance ASC, source COLLATE "C" ASC, section COLLATE "C" ASC, chunk_id COLLATE "C" ASC
            LIMIT %s""",
            (vector, collection_id, scope, as_of, as_of, k),
        ).fetchall()
        # Exact scan is deliberate: this tiny baseline needs no approximate index.
        return [
            {
                **row["payload"],
                "rank": rank,
                "cosine_distance": float(row["distance"]),
                "cosine_similarity": 1.0 - float(row["distance"]),
                "untrusted_reference_material": True,
            }
            for rank, row in enumerate(rows, 1)
        ]

    def server_info(self) -> dict:
        return {
            **self.conn.execute("SELECT version() AS postgres_version").fetchone(),
            **self.conn.execute(
                "SELECT extversion AS pgvector_version FROM pg_extension WHERE extname = 'vector'"
            ).fetchone(),
            "dimensions": DIMENSIONS,
        }
