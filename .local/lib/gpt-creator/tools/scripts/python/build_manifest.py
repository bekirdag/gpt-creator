#!/usr/bin/env python3
"""Build manifest json structures from a table-of-contents JSON."""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional


slug_re = re.compile(r"[^a-z0-9]+")


def slugify(text: str, seen: set) -> str:
    base = slug_re.sub("-", (text or "").lower()).strip("-") or "section"
    slug = base
    idx = 2
    while slug in seen:
        slug = f"{base}-{idx}"
        idx += 1
    seen.add(slug)
    return slug


def walk(node: Dict, path: List[int], parent: Optional[Dict], seen: set, nodes: List[Dict]) -> None:
    title = (node.get("title") or "").strip()
    summary = (node.get("summary") or "").strip()
    slug = slugify(title or "section", seen)
    label = ".".join(str(i + 1) for i in path)
    breadcrumbs = []
    parent_slug = None
    parent_label = None
    if parent is not None:
        breadcrumbs = parent["breadcrumbs"] + [parent["title"]]
        parent_slug = parent["slug"]
        parent_label = parent["label"]
    entry = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "label": label,
        "level": len(path),
        "path": path,
        "parent_slug": parent_slug,
        "parent_label": parent_label,
        "breadcrumbs": breadcrumbs,
        "children_titles": [
            (child.get("title") or "").strip() for child in (node.get("subsections") or [])
        ],
    }
    nodes.append(entry)
    for idx, child in enumerate(node.get("subsections") or []):
        walk(child, path + [idx], entry, seen, nodes)


def build_manifest(toc: Dict) -> Dict:
    sections = toc.get("sections") or []
    nodes: List[Dict] = []
    seen: set = set()

    for idx, section in enumerate(sections):
        walk(section, [idx], None, seen, nodes)

    nodes_by_path = sorted(nodes, key=lambda item: item["path"])
    nodes_generation_order = sorted(nodes, key=lambda item: (item["level"], item["path"]))

    return {
        "toc": toc,
        "nodes": nodes_by_path,
        "generation_order": [item["slug"] for item in nodes_generation_order],
    }


def main(argv) -> None:
    if len(argv) != 4:
        raise SystemExit("Usage: build_manifest.py TOC_JSON MANIFEST_JSON FLAT_JSON")

    toc_path = Path(argv[1])
    manifest_path = Path(argv[2])
    flat_path = Path(argv[3])

    toc = json.loads(toc_path.read_text(encoding="utf-8"))
    manifest = build_manifest(toc)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    flat_path.write_text(json.dumps(manifest["nodes"], indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
