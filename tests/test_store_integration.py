"""Real SQL integration tests; orthogonal fixture vectors are not RAG metrics."""

import os
import uuid
from dataclasses import replace
from datetime import date

import numpy as np
import psycopg
import pytest

from refundguard.corpus import json_hash
from refundguard.embeddings import DIMENSIONS
from refundguard.store import PolicyStore, connection, make_manifest

pytestmark = pytest.mark.integration


@pytest.fixture
def store():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL + pgvector database")
    with connection(url, initialize=True) as conn:
        conn.commit()  # Keep schema setup outside the transaction under test.
        try:
            yield PolicyStore(conn)
        finally:
            conn.rollback()  # Keep test data out of the baseline collections.


@pytest.fixture
def spec():
    return {
        "provider": "integration-fixture",
        "dimensions": DIMENSIONS,
        "test_run_id": str(uuid.uuid4()),
    }


@pytest.fixture
def vectors(chunks):
    return np.eye(DIMENSIONS, dtype=np.float32)[: len(chunks)]


def test_roundtrip_cosine_retrieval_and_idempotent_ingest(store, spec, chunks, vectors):
    collection_id = store.ingest(chunks, vectors, spec)
    assert store.ingest(chunks, vectors, spec) == collection_id
    assert store.count(collection_id) == len(chunks)
    target = 8  # An actual stored chunk, not a mocked DB response.
    hits = store.retrieve(collection_id, vectors[target], 5, scope="all")
    assert hits[0]["chunk_id"] == chunks[target].chunk_id
    assert hits[0]["cosine_distance"] == pytest.approx(0.0, abs=1e-6)
    assert hits[0]["text"] == chunks[target].text


def test_current_scope_excludes_superseded_and_future(store, spec, chunks, vectors):
    collection_id = store.ingest(chunks, vectors, spec)
    old_index = next(i for i, c in enumerate(chunks) if c.status == "SUPERSEDED")
    hits = store.retrieve(collection_id, vectors[old_index], 100, as_of=date(2026, 10, 6))
    assert len(hits) == 33
    assert all(h["status"] == "CURRENT" for h in hits)
    assert store.retrieve(collection_id, vectors[0], 100, as_of=date(2020, 1, 1)) == []


def test_mismatched_model_or_corpus_fails_closed(store, spec, chunks, vectors):
    store.ingest(chunks, vectors, spec)
    with pytest.raises(ValueError, match="No complete matching"):
        store.require_collection(chunks, {**spec, "revision": "different"})
    changed = [
        replace(chunk, source_sha256="different") if chunk.source == chunks[0].source else chunk
        for chunk in chunks
    ]
    with pytest.raises(ValueError, match="No complete matching"):
        store.require_collection(changed, spec)


def test_partial_ingestion_is_rolled_back(store, spec, chunks, vectors):
    if "PGlite" in store.server_info()["postgres_version"]:
        pytest.skip("PGlite socket returns no ROLLBACK result after SQL errors; run on native PG")
    duplicate_label = replace(chunks[0], chunk_id="different-id-same-label")
    bad_chunks = [*chunks, duplicate_label]
    bad_vectors = np.vstack([vectors, vectors[0]])
    collection_id = json_hash(make_manifest(bad_chunks, spec))
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.ingest(bad_chunks, bad_vectors, spec)
    store.conn.rollback()
    assert store.count(collection_id) == 0
    assert (
        store.conn.execute(
            "SELECT count(*) AS n FROM refundguard.collections WHERE collection_id = %s",
            (collection_id,),
        ).fetchone()["n"]
        == 0
    )


def test_mid_ingestion_application_error_rolls_back(store, spec, chunks, vectors):
    # A Python serialization error after a successful insert must not commit
    # either a partial collection or its manifest.
    bad_chunks = [chunks[0], replace(chunks[1], text=object()), *chunks[2:]]
    collection_id = json_hash(make_manifest(bad_chunks, spec))
    with pytest.raises(TypeError), store.conn.transaction():
        store.ingest(bad_chunks, vectors, spec)
    assert store.count(collection_id) == 0


def test_parameterization_and_tie_break(store, spec, chunks, vectors):
    collection_id = store.ingest(chunks, vectors, spec)
    assert store.retrieve("' OR 1=1; --", vectors[0], 5, scope="all") == []
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    vector[-1] = 1  # Equal cosine distance to every fixture vector.
    hits = store.retrieve(collection_id, vector, 100, scope="all")
    labels = [(h["source"], h["section"]) for h in hits]
    assert labels == sorted(labels)
