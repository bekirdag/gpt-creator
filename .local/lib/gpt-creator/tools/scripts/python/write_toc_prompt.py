#!/usr/bin/env python3
"""Generate the table-of-contents prompt for the create-pdr pipeline."""

import sys
from pathlib import Path


PROMPT_HEADER = """You are Codex, drafting a Product Requirements Document (PDR) from a Request for Proposal (RFP).

Follow this process:
1. Study the RFP excerpt.
2. Identify the highest-level themes first (vision, goals, product scope, user segments, success metrics, operating constraints).
3. Break each theme into progressively more detailed sections and subsections, going from high-level strategy down to detailed requirements, policies, integrations, and validation.
4. Propose a complete table of contents for the PDR before any narrative is written.

Output strict JSON matching this schema:
{
  "document_title": "string",
  "sections": [
    {
      "title": "Top level heading",
      "summary": "1-3 sentence overview of what belongs in this section",
      "subsections": [
        {
          "title": "Sub heading",
          "summary": "Short summary",
          "subsections": [
            {
              "title": "Nested heading",
              "summary": "Short summary"
            }
          ]
        }
      ]
    }
  ]
}

Rules:
- Order sections from highest-level concepts down to implementation and validation details.
- Provide at least three top-level sections.
- Each subsection list may be empty, but include the key subsections necessary to cover the RFP requirements.
- Do not include prose outside the JSON response.

## RFP Excerpt
"""

PROMPT_FOOTER = """

## End RFP Excerpt
"""


def main(argv) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: write_toc_prompt.py PROMPT_PATH SNIPPET_PATH")

    prompt_path = Path(argv[1])
    snippet_path = Path(argv[2])

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    snippet = snippet_path.read_text(encoding="utf-8")

    prompt_path.write_text(PROMPT_HEADER + snippet + PROMPT_FOOTER, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
