"""Local, real dense embeddings. No credentials and no fallback to fake vectors."""

import importlib.metadata
import os
from pathlib import Path

import numpy as np

from .corpus import json_hash, sha256

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


def validate_vectors(vectors: object, count: int) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.shape != (count, DIMENSIONS):
        raise ValueError(f"Expected {count} vectors of dimension {DIMENSIONS}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("Embedding contains NaN or infinity")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("Embedding contains a zero vector")
    return array / norms


class DenseEmbedder:
    def __init__(self, model_dir: Path | None = None, threads: int = 2):
        # Also enforce the process-level opt-out at the inference boundary.
        os.environ["ORT_DISABLE_TELEMETRY"] = "1"
        import onnxruntime
        from fastembed import TextEmbedding

        onnxruntime.disable_telemetry_events()
        from tokenizers import Tokenizer

        self.model = TextEmbedding(
            model_name=MODEL_NAME,
            cache_dir=os.getenv("FASTEMBED_CACHE_PATH", ".cache/fastembed"),
            threads=threads,
            providers=["CPUExecutionProvider"],
            specific_model_path=str(model_dir) if model_dir else None,
        )
        # FastEmbed is pinned: capture the exact resolved artifacts so different
        # downloaded revisions can never silently share the same database index.
        resolved_dir = Path(self.model.model._model_dir)
        files = sorted(
            p
            for p in resolved_dir.rglob("*")
            if p.is_file()
            and p.suffix in {".onnx", ".json", ".txt", ".data"}
            and not any(part.startswith(".") for part in p.relative_to(resolved_dir).parts)
        )
        if not files or not any(p.suffix == ".onnx" for p in files):
            raise ValueError("Cannot fingerprint embedding model files")
        artifacts = {str(p.relative_to(resolved_dir)): sha256(p.read_bytes()) for p in files}
        self.tokenizer = Tokenizer.from_file(str(resolved_dir / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.spec = {
            "provider": "fastembed",
            "model": MODEL_NAME,
            "dimensions": DIMENSIONS,
            "fastembed_version": importlib.metadata.version("fastembed"),
            "onnxruntime_version": importlib.metadata.version("onnxruntime"),
            "numpy_version": importlib.metadata.version("numpy"),
            "execution_provider": "CPUExecutionProvider",
            "normalized": True,
            "document_method": "passage_embed",
            "query_method": "query_embed",
            "max_tokens": 512,
            "artifacts": artifacts,
        }
        self.spec["fingerprint"] = json_hash(self.spec)

    def _check_lengths(self, texts: list[str]) -> None:
        for i, text in enumerate(texts):
            if not text.strip():
                raise ValueError("Cannot embed an empty string")
            length = len(self.tokenizer.encode(text).ids)
            if length > 512:
                raise ValueError(
                    f"Text {i} is {length} tokens; maximum is 512. "
                    "Split long sections explicitly; silent truncation is disabled."
                )

    def documents(self, texts: list[str]) -> np.ndarray:
        self._check_lengths(texts)
        return validate_vectors(list(self.model.passage_embed(texts, batch_size=32)), len(texts))

    def queries(self, texts: list[str]) -> np.ndarray:
        self._check_lengths(texts)
        return validate_vectors(list(self.model.query_embed(texts, batch_size=32)), len(texts))
