"""Create local random demo credentials once; never overwrite or print them."""

import secrets
from pathlib import Path


def main():
    folder = Path(".local")
    folder.mkdir(exist_ok=True, mode=0o700)
    for name in ["database_password", "support_password", "reviewer_password"]:
        path = folder / name
        if not path.exists():
            with path.open("x") as handle:
                path.chmod(0o600)
                handle.write(secrets.token_urlsafe(24) + "\n")
    print("Local credential files are ready in .local/; existing values were retained.")


if __name__ == "__main__":
    main()
