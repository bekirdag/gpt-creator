#!/usr/bin/env python3
"""Generate a section-writing prompt for the create-pdr pipeline."""

import json
import sys
from pathlib import Path


def build_prompt(node, manifest, snippet_text):
    slug = node["slug"]
    title = (node.get("title") or "").strip()
    summary = (node.get("summary") or "").strip()
    label = node.get("label") or ""
    level = int(node.get("level") or 1)
    breadcrumbs = node.get("breadcrumbs") or []
    children = node.get("children_titles") or []
    heading_level = max(2, min(level + 1, 6))
    heading_token = "#" * heading_level

    parent = None
    parent_slug = node.get("parent_slug")
    if parent_slug:
        for candidate in manifest.get("nodes") or []:
            if candidate.get("slug") == parent_slug:
                parent = candidate
                break

    lines = []
    lines.append(
        "You are Codex, authoring a Product Requirements Document (PDR) based on the provided RFP excerpt."
    )
    lines.append("")
    lines.append("## Section metadata")
    lines.append(f"- Slug: {slug}")
    lines.append(f"- Outline label: {label}")
    lines.append(f"- Heading depth: {level}")
    lines.append(f"- Markdown heading token: {heading_token}")
    if breadcrumbs:
        lines.append(f"- Parent chain: {' > '.join(breadcrumbs)}")
    lines.append(f"- Title: {title}")
    if summary:
        lines.append(f"- Outline summary: {summary}")
    if parent and parent.get("summary"):
        lines.append(f"- Parent summary: {parent['summary']}")
    if children:
        lines.append("- Planned child headings:")
        for child in children:
            if child:
                lines.append(f"  * {child}")

    lines.append("")
    lines.append("## RFP excerpt (truncated)")
    lines.append(snippet_text)
    lines.append("")
    lines.append("## Writing instructions")
    lines.append(
        f"1. Begin with the heading `{heading_token} {title} {{#{slug}}}` (you may adjust the wording, but keep the heading level and anchor)."
    )
    lines.append(
        "2. Summarize the section at the appropriate fidelity: higher levels focus on narrative, scope, and success criteria; deeper levels provide concrete requirements, data flows, policies, and validation steps."
    )
    lines.append(
        "3. Align content strictly with the RFP while resolving gaps with reasonable assumptions explicitly marked as such."
    )
    lines.append(
        "4. Use ordered lists, bullet points, and sub-subheadings sparingly to improve structure, but do not create headings beyond the assigned level for this pass."
    )
    lines.append(
        "5. Reference downstream subsections (if any) but leave their detailed execution to later iterations."
    )
    lines.append(
        "6. Close with a short 'Key Considerations' bullet list anchoring the most important commitments for this section."
    )
    lines.append("")
    lines.append("## Output requirements")
    lines.append("Return Markdown only for this section. Do not include front-matter, global TOC, or commentary outside the section.")

    return "\n".join(lines) + "\n"


def main(argv) -> None:
    if len(argv) != 5:
        raise SystemExit("Usage: write_section_prompt.py NODE_JSON MANIFEST_JSON SNIPPET_PATH PROMPT_PATH")

    node_json = argv[1]
    manifest_path = Path(argv[2])
    snippet_path = Path(argv[3])
    prompt_path = Path(argv[4])

    node = json.loads(node_json)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snippet_text = snippet_path.read_text(encoding="utf-8")

    prompt_path.write_text(build_prompt(node, manifest, snippet_text), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
