import json
import os
import pathlib
import re
from typing import Iterable


def format_bytes(num: int) -> str:
    if num < 0:
        return f"{num} B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def emit(lines: Iterable[str], limit: int) -> int:
    lines = list(lines)
    if limit > 0 and len(lines) > limit:
        omitted = len(lines) - limit
        lines = lines[:limit]
        lines.append(f"... ({omitted} line(s) truncated) ...")
    print("\n".join(lines))
    return 0


def main() -> int:
    path = pathlib.Path(os.environ.get("GC_DUMP_FILE", ""))
    if not path:
        return 0

    try:
        limit = int(os.environ.get("GC_MAX_LINES", "200"))
    except Exception:
        limit = 200

    pointer_mode = os.environ.get("GC_CONTEXT_POINTER_MODE", "").strip().lower() not in {"", "0", "false"}

    if pointer_mode:
        digest = os.environ.get("GC_CONTEXT_POINTER_DIGEST", "").strip()
        try:
            stat = path.stat()
            size_bytes = stat.st_size
        except Exception:
            size_bytes = -1

        preview_lines = []
        pointer_limit = max(0, min(12, limit))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _ in range(pointer_limit):
                    line = handle.readline()
                    if not line:
                        break
                    preview_lines.append(line.rstrip("\n"))
        except Exception as exc:
            print(f"(failed to read staged doc: {exc})")
            return 0

        descriptor = path.name
        if size_bytes >= 0:
            descriptor += f" — {format_bytes(size_bytes)}"
        if digest:
            descriptor += f" (sha256≈{digest})"

        print(f"(context trimmed for doc-snippet mode) {descriptor}")
        if preview_lines:
            print("Preview:")
            for raw_line in preview_lines:
                clean = raw_line.strip()
                if len(clean) > 160:
                    clean = clean[:160].rstrip() + " …"
                if not clean:
                    clean = "(blank line)"
                print(f"- {clean}")
        else:
            print("(no preview available)")
        return 0

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"(failed to read text: {exc})")
        return 0

    try:
        parsed = json.loads(raw)
        preview = json.dumps(parsed, indent=2)[:4000]
        print("JSON summary:")
        print(preview)
        return 0
    except Exception:
        pass

    ext = path.suffix.lower()
    css_exts = {".css", ".scss", ".sass", ".less", ".pcss", ".styl"}
    markup_exts = {".html", ".htm", ".vue", ".jsx", ".tsx"}

    if ext in css_exts:
        tokens = re.findall(r"--([a-z0-9_-]+)", raw, re.I)
        unique = sorted({token for token in tokens if token})
        lines = ["CSS variables (first 40):"]
        for token in unique[:40]:
            lines.append(f"- --{token}")
        if len(unique) > 40:
            lines.append(f"... ({len(unique) - 40} additional variables omitted)")
        return emit(lines, limit)

    if ext in markup_exts:
        clean = re.sub(r"<script[\s\S]*?</script>", "", raw, flags=re.I)
        clean = re.sub(r"<style[\s\S]*?</style>", "", clean, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", clean)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return emit(["(markup collapsed to empty after stripping tags)"], limit)
        chunks = [text[i : i + 200] for i in range(0, len(text), 200)]
        lines = ["Markup summary:"] + chunks[:5]
        if len(chunks) > 5:
            lines.append(f"... ({len(chunks) - 5} additional chunks omitted)")
        return emit(lines, limit)

    lines = raw.splitlines()
    result = []
    max_width = 160
    table_run = 0
    table_notice = False
    sql_insert_run = 0
    sql_notice = False

    def truncate(line: str) -> str:
        if len(line) <= max_width:
            return line
        return line[:max_width].rstrip() + " …"

    for original in lines:
        line = original.rstrip()
        stripped = line.lstrip()

        if not stripped:
            if not result or result[-1] != "":
                result.append("")
            continue

        pipe_count = line.count("|")
        is_table_like = pipe_count >= 6 or (pipe_count >= 3 and "," in line and len(line) > 80)
        if is_table_like:
            table_run += 1
        else:
            table_run = 0
            table_notice = False
        if is_table_like and table_run > 30:
            if not table_notice:
                result.append("... (additional table rows truncated) ...")
                table_notice = True
            continue

        upper = stripped.upper()
        if upper.startswith("INSERT INTO") or upper.startswith("UPDATE "):
            sql_insert_run += 1
        else:
            sql_insert_run = 0
            sql_notice = False
        if sql_insert_run > 40:
            if not sql_notice:
                result.append("... (repetitive SQL statements truncated) ...")
                sql_notice = True
            continue

        line = truncate(line.replace("\t", "  "))
        result.append(line)

    if not result:
        result = ["(no textual content captured)"]

    if limit > 0 and len(result) > limit:
        omitted = len(result) - limit
        result = result[:limit]
        result.append(f"... ({omitted} line(s) truncated) ...")

    print("\n".join(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
