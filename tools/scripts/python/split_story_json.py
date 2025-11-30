#!/usr/bin/env python3
"""Split a story bundle JSON into individual story files."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def slugify(text: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    return "-".join(filter(None, slug.split("-")))


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    bundle_path = Path(sys.argv[1])
    stories_dir = Path(sys.argv[2])

    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    epic_id = payload.get("epic_id") or ""

    stories = payload.get("user_stories") or []
    for story in stories:
        sid = story.get("story_id") or ""
        if not sid:
            continue
        slug = slugify(sid)
        story_out = {"epic_id": epic_id, "story": story}
        (stories_dir / f"{slug}.json").write_text(json.dumps(story_out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
