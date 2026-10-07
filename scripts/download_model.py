"""Download the measured model revision and verify every locked artifact."""

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/model"))
    args = parser.parse_args()
    lock_path = Path(__file__).resolve().parents[1] / "model.lock.json"
    lock = json.loads(lock_path.read_text())
    location = Path(
        snapshot_download(
            repo_id=lock["repository"],
            revision=lock["revision"],
            allow_patterns=list(lock["artifacts"]),
            local_dir=args.output,
        )
    )
    for filename, expected in lock["artifacts"].items():
        actual = hashlib.sha256((location / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Model artifact hash mismatch: {filename}")
    print(f"Verified {len(lock['artifacts'])} model artifacts in {location}")


if __name__ == "__main__":
    main()
