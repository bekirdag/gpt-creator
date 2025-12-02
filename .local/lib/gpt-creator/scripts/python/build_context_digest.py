import hashlib
import os
import sys
from pathlib import Path

RUN_DIR = os.getenv("GC_RUN_DIR") or os.getenv("GC_STAGING_RUN_DIR") or ""
RUN_DIR_REAL = os.path.realpath(RUN_DIR) if RUN_DIR else ""


def _safe_walk(root: Path):
    seen = set()
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        try:
            base_real = os.path.realpath(base)
        except OSError:
            dirs[:] = []
            continue
        if base_real in seen:
            dirs[:] = []
            continue
        seen.add(base_real)
        if RUN_DIR_REAL and (base_real == RUN_DIR_REAL or base_real.startswith(RUN_DIR_REAL + os.sep)):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
        yield base, dirs, files


def build_digest(context_path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return [""]

    try:
        raw = context_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [f"(failed to read shared context: {exc})"]

    lines = raw.splitlines()
    sections = []
    current_name = None
    current_lines = []

    for line in lines:
        if line.startswith("----- FILE: ") and line.endswith(" -----"):
            if current_name is not None:
                sections.append((current_name, current_lines))
            current_name = line[len("----- FILE: ") : -len(" -----")].strip() or "unnamed"
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line.rstrip())

    if current_name is not None:
        sections.append((current_name, current_lines))

    output = [
        "Tip: use gpt-creator show-file <path> --range start:end to inspect additional context."
    ]
    remaining = max(limit - len(output), 10)

    if not sections:
        output.append("(no staged context files indexed)")
        return output

    per_header_cost = 2
    seen_digests = set()
    duplicate_examples = []
    duplicate_count = 0

    for index, (name, section_lines) in enumerate(sections, 1):
        name_lower = name.lower()
        if name_lower.endswith("discovery.yaml") or name_lower.endswith("discovery.yml"):
            continue
        if remaining <= 0:
            output.append(
                "… (context digest truncated for display; raise --context-lines or open the context file directly for the remainder)"
            )
            break

        digest_src = "\n".join(section_lines).encode("utf-8", "replace")
        digest = hashlib.sha256(digest_src).hexdigest()[:12]
        if digest in seen_digests:
            duplicate_count += 1
            if len(duplicate_examples) < 4:
                duplicate_examples.append(name)
            continue
        seen_digests.add(digest)

        heading = f"### {name} (sha256 {digest})"
        output.append(heading)
        remaining -= 1
        if remaining <= 0:
            output.append(
                "… (context digest truncated for display; raise --context-lines or open the context file directly for the remainder)"
            )
            break

        remaining_sections = len(sections) - index
        reserved_for_rest = max(0, remaining_sections * per_header_cost)
        available_for_this = max(3, min(12, remaining - reserved_for_rest))

        sample_lines = []
        for raw_line in section_lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("... (additional "):
                continue
            if stripped.startswith("----- FILE:"):
                continue
            stripped = stripped.replace("\t", "  ")
            if len(stripped) > 160:
                stripped = stripped[:160].rstrip() + " …"
            sample_lines.append(stripped)
            if len(sample_lines) >= available_for_this:
                break

        if not sample_lines:
            sample_lines = ["(no excerpt captured; file may be binary or truncated)"]

        for sample in sample_lines:
            if remaining <= 0:
                output.append(
                    "… (context digest truncated for display; raise --context-lines or open the context file directly for the remainder)"
                )
                break
            output.append(sample)
            remaining -= 1

        if remaining <= 0:
            break

        if index != len(sections):
            output.append("")
            remaining -= 1

    if duplicate_count:
        suffix = "" if duplicate_count == 1 else "s"
        message = f"(Skipped {duplicate_count} additional context file{suffix} with duplicate content"
        if duplicate_examples:
            shown = ", ".join(duplicate_examples)
            if duplicate_count > len(duplicate_examples):
                shown += ", …"
            message += f": {shown}"
        message += ")"
        output.append("")
        output.append(message)

    return output


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    context_path = Path(sys.argv[1])
    dest_path = Path(sys.argv[2])
    try:
        limit = int(sys.argv[3])
    except Exception:
        limit = 400

    if limit <= 0:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("", encoding="utf-8")
        return 0

    digest_lines = build_digest(context_path, limit)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text("\n".join(digest_lines).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
