from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from orca.readiness import check_release_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline, read-only ORCA structural preflight; never a release authorization"
        )
    )
    parser.add_argument("--repository", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--evidence-manifest", type=Path)
    args = parser.parse_args(argv)
    report = check_release_readiness(args.repository, args.evidence_manifest)
    print(json.dumps(report, indent=2, sort_keys=True))
    # This offline diagnostic is deliberately incapable of authorizing a release.
    # Code 2 means all structural inputs were present but remain unverified.
    return 2 if report.get("structural_inputs_present") else 1


if __name__ == "__main__":
    raise SystemExit(main())
