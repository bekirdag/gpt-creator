#!/usr/bin/env python3
"""Generate the final PDR review prompt."""

import sys
from pathlib import Path


PROMPT_HEADER = """You are a principal product strategist performing a final quality review of a Product Requirements Document (PDR).

Goals:
- Confirm the PDR is comprehensive enough for engineering, design, compliance, and go-to-market teams to build and launch the product described in the RFP.
- Ensure every section of the PDR is internally consistent, aligned with neighbouring sections, and free of contradictions.
- Identify gaps or ambiguous areas that would block execution, and resolve them by updating the PDR content.
- Guarantee terminology, roles, success metrics, and scope stay synchronized across all sections.

Method:
1. Read the RFP excerpt to anchor requirements.
2. Audit the current PDR, checking that vision, scope, user journeys, functional specs, non-functional requirements, compliance, analytics, rollout, and success metrics interlock without conflicts.
3. Revise the PDR directly so it is self-consistent, implementation-ready, and efficient—no redundant or conflicting guidance.
4. Output the improved PDR in Markdown. Do not include commentary, checklists, or code fences—return the updated document only.

## RFP Excerpt
"""

PROMPT_CURRENT_PDR = "\n\n## Current PDR\n"
PROMPT_FOOTER = "\n\n## End PDR\n"


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def main(argv) -> None:
    if len(argv) != 4:
        raise SystemExit("Usage: write_review_prompt.py PDR_PATH RFP_SNIPPET_PATH PROMPT_PATH")

    pdr_path = Path(argv[1])
    snippet_path = Path(argv[2])
    prompt_path = Path(argv[3])

    prompt_path.parent.mkdir(parents=True, exist_ok=True)

    snippet_text = ensure_trailing_newline(snippet_path.read_text(encoding="utf-8"))
    pdr_text = ensure_trailing_newline(pdr_path.read_text(encoding="utf-8"))

    prompt = PROMPT_HEADER + snippet_text + PROMPT_CURRENT_PDR + pdr_text + PROMPT_FOOTER
    prompt_path.write_text(prompt, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
