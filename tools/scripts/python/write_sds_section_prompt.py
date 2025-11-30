#!/usr/bin/env python3
"""Generate a section-writing prompt for the create-sds pipeline."""

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
        "You are Codex, documenting a System Design Specification (SDS) based on the Product Requirements Document excerpt below."
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
    lines.append("## PDR excerpt (truncated)")
    lines.append(snippet_text)
    lines.append("")
    lines.append("## Writing instructions")
    lines.append(
        f"1. Begin with the heading `{heading_token} {title} {{#{slug}}}` (adjust wording if needed, but keep the level and anchor)."
    )
    lines.append(
        "2. Articulate the architectural intent for this section, then specify components, interactions, and data contracts in increasing detail."
    )
    lines.append(
        "3. Map requirements from the PDR into concrete technical decisions: technologies, responsibilities, data models, interfaces, and operational policies."
    )
    lines.append(
        "4. If diagrams are referenced, describe their structure textually (component, sequence, deployment) so engineers can implement them."
    )
    lines.append(
        "5. Cover scalability, reliability, security, observability, and DevOps implications relevant to this scope."
    )
    lines.append("6. Call out assumptions explicitly and flag open questions or risks.")
    lines.append("7. Close with bullet lists for 'Open Questions & Risks' and 'Verification Strategy'.")
    lines.append("")
    lines.append("## Output requirements")
    lines.append(
        "Return Markdown only for this section. Do not include front-matter, global TOC, or commentary outside the section."
    )

    return "\n".join(lines) + "\n"


def main(argv) -> None:
    if len(argv) != 5:
        raise SystemExit("Usage: write_sds_section_prompt.py NODE_JSON MANIFEST_JSON SNIPPET_PATH PROMPT_PATH")

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
