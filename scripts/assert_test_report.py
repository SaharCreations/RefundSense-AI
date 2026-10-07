"""Fail CI if tests failed or native PostgreSQL checks were skipped."""

import argparse
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--no-skips", action="store_true")
    args = parser.parse_args()
    cases = ET.parse(args.report).getroot().findall(".//testcase")
    if not cases or any(
        c.find("failure") is not None or c.find("error") is not None for c in cases
    ):
        raise SystemExit("Test evidence is missing or contains failures")
    skipped = sum(c.find("skipped") is not None for c in cases)
    if args.no_skips and skipped:
        raise SystemExit(f"Native verification must not skip tests ({skipped} skipped)")
    print(f"Verified {len(cases) - skipped} passed; {skipped} skipped.")


if __name__ == "__main__":
    main()
