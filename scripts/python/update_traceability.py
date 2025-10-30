#!/usr/bin/env python3
"""
Generate docs/traceability.json in a deterministic manner.

The script parses PDR/SDS acceptance criteria, associates them with
evidence (tests, verify scripts, runbooks), and writes a canonical JSON
matrix. Re-running the script with unchanged sources produces identical
output. Use `python3 scripts/python/update_traceability.py --check`
within CI to assert that the checked-in artefact is up to date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT_DEFAULT = Path(__file__).resolve().parents[2]
TRACEABILITY_PATH = Path("docs/traceability.json")

AC_SECTION_PATTERN = re.compile(r"^##\s+.+Acceptance Criteria", re.IGNORECASE)

HYPHEN_VARIANTS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


@dataclass(frozen=True)
class AcceptanceCriterion:
    ac_id: str
    title: str
    description: str
    source_path: Path
    source_line: int


@dataclass(frozen=True)
class Evidence:
    ac_id: str
    path: Path
    evidence_type: str
    description: str


def _stable_doc_id(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    digest = hashlib.sha256(str(resolved).encode("utf-8", "replace")).hexdigest().upper()
    return f"DOC-{digest[:8]}"


def _normalize_ac_id(raw: str) -> str:
    cleaned = (raw or "").strip().translate(HYPHEN_VARIANTS)
    cleaned = cleaned.rstrip(":")
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        raise ValueError("Empty AC identifier encountered.")
    if not cleaned.upper().startswith("AC-"):
        cleaned = f"AC-{cleaned[2:]}" if cleaned.upper().startswith("AC") else cleaned
    cleaned = cleaned.upper()
    return cleaned


def _parse_acceptance_criteria(doc_path: Path) -> Iterable[AcceptanceCriterion]:
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped.startswith("- **AC"):
            i += 1
            continue
        parts = line.split("**")
        if len(parts) < 2:
            i += 1
            continue
        inner = parts[1].strip()
        if not inner:
            i += 1
            continue
        tokens = inner.split()
        if not tokens:
            i += 1
            continue
        raw_id = tokens[0]
        try:
            ac_id = _normalize_ac_id(raw_id)
        except ValueError:
            i += 1
            continue
        title = inner[len(raw_id) :].strip(" :\u2010\u2011\u2012\u2013\u2014")
        description_lines: List[str] = []
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            if next_line.strip() == "":
                if description_lines:
                    break
                j += 1
                continue
            if next_line.lstrip().startswith("- **AC"):
                break
            if next_line.startswith("## "):
                break
            description_lines.append(next_line.strip())
            j += 1
        description = " ".join(description_lines).strip()
        yield AcceptanceCriterion(
            ac_id=ac_id,
            title=title,
            description=description,
            source_path=doc_path,
            source_line=i + 1,
        )
        i = j
    return []


def load_acceptance_criteria(root: Path) -> List[AcceptanceCriterion]:
    candidates = [
        root / "docs" / "PDR.md",
        root / "docs" / "SDS.md",
        root / "docs" / "automation" / "SDS.md",
        root / "docs" / "automation" / "traceability.md",
    ]
    seen_ids: Dict[str, AcceptanceCriterion] = {}
    for path in candidates:
        if not path.exists():
            continue
        for ac in _parse_acceptance_criteria(path):
            if ac.ac_id in seen_ids:
                raise ValueError(
                    f"Duplicate acceptance criterion {ac.ac_id} found in "
                    f"{path.relative_to(root)} (previously defined in "
                    f"{seen_ids[ac.ac_id].source_path.relative_to(root)})."
                )
            seen_ids[ac.ac_id] = ac
    return [seen_ids[ac_id] for ac_id in sorted(seen_ids)]


def load_evidence(root: Path) -> List[Evidence]:
    manual_map = {
        "AC-1": [
            Evidence(
                ac_id="AC-1",
                path=root / "verify" / "acceptance.sh",
                evidence_type="verify-script",
                description="Acceptance smoke test covering API, web, and admin reachability.",
            ),
        ],
        "AC-2": [
            Evidence(
                ac_id="AC-2",
                path=root / "verify" / "check-openapi.sh",
                evidence_type="verify-script",
                description="OpenAPI validation via swagger-cli / openapi-generator.",
            ),
        ],
        "AC-3": [
            Evidence(
                ac_id="AC-3",
                path=root / "verify" / "check-a11y.sh",
                evidence_type="verify-script",
                description="Accessibility gate using pa11y for web and admin.",
            ),
        ],
        "AC-4": [
            Evidence(
                ac_id="AC-4",
                path=root / "verify" / "check-lighthouse.sh",
                evidence_type="verify-script",
                description="Lighthouse performance & accessibility thresholds.",
            ),
        ],
        "AC-5": [
            Evidence(
                ac_id="AC-5",
                path=root / "verify" / "check-consent.sh",
                evidence_type="verify-script",
                description="Consent checker ensuring privacy link and selectors.",
            ),
        ],
        "AC-6": [
            Evidence(
                ac_id="AC-6",
                path=root / "verify" / "check-program-filters.sh",
                evidence_type="verify-script",
                description="Program filter verification across API endpoints.",
            ),
        ],
    }

    evidence: List[Evidence] = []
    for items in manual_map.values():
        evidence.extend(items)
    missing_paths = [
        e.path for e in evidence if not e.path.is_file()
    ]
    if missing_paths:
        rel_paths = ", ".join(str(path.relative_to(root)) for path in missing_paths)
        raise FileNotFoundError(f"Evidence file(s) missing: {rel_paths}")
    return evidence


def _build_evidence_index(evidence: Iterable[Evidence]) -> Dict[str, List[Evidence]]:
    index: Dict[str, List[Evidence]] = {}
    for item in evidence:
        index.setdefault(item.ac_id, []).append(item)
    for items in index.values():
        items.sort(key=lambda e: (str(e.path), e.evidence_type))
    return index


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_payload(root: Path) -> Dict[str, object]:
    acceptance = load_acceptance_criteria(root)
    evidence_index = _build_evidence_index(load_evidence(root))

    missing_evidence = sorted(ac.ac_id for ac in acceptance if ac.ac_id not in evidence_index)
    if missing_evidence:
        raise RuntimeError(
            "Traceability gap: acceptance criteria lacking evidence -> "
            + ", ".join(missing_evidence)
        )

    criteria_obj: Dict[str, Dict[str, object]] = OrderedDict()
    for ac in acceptance:
        entries = []
        for evidence in evidence_index.get(ac.ac_id, []):
            entries.append(
                OrderedDict(
                    [
                        ("type", evidence.evidence_type),
                        ("path", str(evidence.path.relative_to(root))),
                        ("sha256", _hash_file(evidence.path)),
                        ("description", evidence.description),
                    ]
                )
            )
        criteria_obj[ac.ac_id] = OrderedDict(
            [
                ("title", ac.title),
                ("description", ac.description),
                (
                    "source",
                    OrderedDict(
                        [
                            ("path", str(ac.source_path.relative_to(root))),
                            ("doc_id", _stable_doc_id(ac.source_path)),
                            ("line", ac.source_line),
                        ]
                    ),
                ),
                ("evidence", entries),
            ]
        )

    doc_sources = OrderedDict()
    for ac in acceptance:
        rel = str(ac.source_path.relative_to(root))
        doc_sources.setdefault(rel, _stable_doc_id(ac.source_path))

    payload = OrderedDict(
        [
            (
                "meta",
                OrderedDict(
                    [
                        ("generator", "scripts/python/update_traceability.py"),
                        ("version", 1),
                        ("sources", doc_sources),
                    ]
                ),
            ),
            ("acceptance_criteria", criteria_obj),
        ]
    )
    return payload


def render_payload(payload: Dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def write_traceability(root: Path, payload: Dict[str, object]) -> None:
    out_path = root / TRACEABILITY_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    contents = render_payload(payload)
    out_path.write_text(contents, encoding="utf-8")


def check_traceability(root: Path, payload: Dict[str, object]) -> bool:
    out_path = root / TRACEABILITY_PATH
    if not out_path.exists():
        print(f"[traceability] Missing artefact: {TRACEABILITY_PATH}", file=sys.stderr)
        return False
    existing = out_path.read_text(encoding="utf-8")
    fresh = render_payload(payload)
    if existing != fresh:
        print(f"[traceability] {TRACEABILITY_PATH} out of date.", file=sys.stderr)
        return False
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Update docs/traceability.json deterministically.")
    parser.add_argument(
        "--root",
        default=str(ROOT_DEFAULT),
        help="Project root (default: repository root inferred from script location).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write output; exit non-zero if artefact is stale or missing.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        payload = build_payload(root)
    except Exception as exc:  # noqa: BLE001 - propagate failure to CI
        print(f"[traceability] {exc}", file=sys.stderr)
        return 2

    if args.check:
        return 0 if check_traceability(root, payload) else 1

    write_traceability(root, payload)
    print(f"[traceability] Wrote {TRACEABILITY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
