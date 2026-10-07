"""Explicit download of the locked local explanation model. No API downloads it."""

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import hf_hub_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/llm"))
    parser.add_argument(
        "--lock", type=Path, default=Path(__file__).resolve().parents[1] / "llm.lock.json"
    )
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    path = Path(
        hf_hub_download(
            repo_id=lock["repository"],
            revision=lock["revision"],
            filename=lock["filename"],
            local_dir=args.output,
            token=False,
        )
    )
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    if path.stat().st_size != lock["size_bytes"] or digest != lock["sha256"]:
        raise ValueError("Explanation model artifact does not match the lock")
    print(f"Verified pinned model in {path}")


if __name__ == "__main__":
    main()
