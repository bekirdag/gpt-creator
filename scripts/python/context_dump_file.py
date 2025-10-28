import json
import os
import pathlib
import re
from typing import Iterable


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

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"(failed to read text: {exc})")
        return 0

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

    try:
        parsed = json.loads(raw)
        preview = json.dumps(parsed, indent=2)[:4000]
        return emit(["JSON summary:", preview], limit)
    except Exception:
        pass

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

    return emit(result or ["(no textual content captured)"], limit)


if __name__ == "__main__":
    raise SystemExit(main())
