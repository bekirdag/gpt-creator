#!/usr/bin/env python3
"""Convert discovery manifest TSV into scan.json artifact."""

import csv
import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        raise SystemExit("Usage: scan_manifest_to_json.py MANIFEST_PATH PROJECT_ROOT OUT_PATH")

    manifest_path = Path(argv[1])
    project_root = Path(argv[2])
    out_path = Path(argv[3])

    rows = []
    with manifest_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            doc_type = row.get("type") or ""
            if not doc_type:
                continue
            confidence = float(row.get("confidence") or 0)
            path_value = row.get("path") or ""
            rows.append(
                {
                    "type": doc_type,
                    "confidence": confidence,
                    "path": str(Path(path_value).resolve()),
                }
            )

    scan_payload = {
        "project_root": str(project_root.resolve()),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifacts": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(scan_payload, fh, indent=2)

    print(str(out_path))


if __name__ == "__main__":
    main(sys.argv)
