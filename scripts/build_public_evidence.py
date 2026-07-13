#!/usr/bin/env python3
"""Build or verify the tracked credential-free public evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from app.evidence.public_fixture import verify_bundle, write_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("evidence/public-fixture-v1"),
        help="Directory to write (default: evidence/public-fixture-v1)",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        metavar="DIR",
        help="Regenerate in memory and verify every tracked byte in DIR",
    )
    args = parser.parse_args(argv)

    try:
        if args.verify is not None:
            manifest = verify_bundle(args.verify)
            output_dir = args.verify
            action = "verified"
        else:
            manifest = write_bundle(args.out)
            output_dir = args.out
            action = "wrote"
    except (OSError, TypeError, ValueError) as exc:
        print(f"FAIL public evidence: {exc}", file=sys.stderr)
        return 1

    manifest_digest = hashlib.sha256(
        (output_dir / "manifest.json").read_bytes()
    ).hexdigest()
    print(f"OK {action} public evidence: {output_dir}")
    print(f"OK evidence content address: {manifest['artifact']['content_address']}")
    print(f"OK manifest content address: sha256:{manifest_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
