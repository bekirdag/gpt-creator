import fnmatch
import json
import os
import pathlib
import re
from typing import Iterable, List

DEFAULT_GLOB_EXCLUDES = [
    ".gpt-creator/staging/plan/work/runs/**",
    ".gpt-creator/logs/**",
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "apps/**/cypress/**",
    "apps/**/tests/**",
    "apps/**/dist-tests/**",
    "apps/**/fixtures/**",
    "apps/**/public/**/*.{png,jpg,jpeg,gif,webp,svg}",
    "apps/web/final_output.json",
    "apps/api/prisma/migrations/**",
    "db/sql_dump.sql",
    "sql/sql_dump.sql",
    "docs/**/diagrams/**/*.{svg,drawio}",
    "docs/**/evidence/**",
    "docs/**/uat-evidence/**",
    "docs/qa/assets/**",
    "ops/lighthouse/**",
    "ops/pa11y/**",
    "ops/monitoring/**",
    "ops/nginx/rendered/**",
    "docker/**",
    "docker.bak/**",
    "Library/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "*.lock",
    "pnpm-lock.yaml",
    "program_vue.jsonclip",
]

DEFAULT_SUFFIXES = (".meta.json", ".log", ".log.gz")


def _expand_brace_pattern(pattern: str) -> List[str]:
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    prefix, remainder = pattern.split("{", 1)
    body, suffix = remainder.split("}", 1)
    options = [option.strip() for option in body.split(",") if option.strip()]
    if not options:
        return [pattern.replace("{", "").replace("}", "")]
    return [f"{prefix}{option}{suffix}" for option in options]


DEFAULT_GLOB_EXPANDED = []
for _pattern in DEFAULT_GLOB_EXCLUDES:
    DEFAULT_GLOB_EXPANDED.extend(_expand_brace_pattern(_pattern))


def _extra_excludes() -> List[str]:
    raw = os.environ.get("GC_CONTEXT_EXCLUDES", "")
    if not raw:
        return []
    candidates: List[str] = []
    for entry in raw.replace(":", "\n").splitlines():
        entry = entry.strip()
        if entry:
            candidates.extend(_expand_brace_pattern(entry))
    return candidates


def _is_excluded(path: pathlib.Path) -> bool:
    text = str(path).replace("\\", "/")
    for pattern in DEFAULT_GLOB_EXPANDED:
        pattern_clean = pattern.strip()
        if not pattern_clean:
            continue
        if fnmatch.fnmatch(text, pattern_clean) or fnmatch.fnmatch(text, f"*{pattern_clean}"):
            return True
    for suffix in EXCLUDE_SUFFIXES:
        if suffix and text.endswith(suffix):
            return True
    for token in _extra_excludes():
        token_clean = token.strip()
        if not token_clean:
            continue
        if fnmatch.fnmatch(text, token_clean) or fnmatch.fnmatch(text, f"*{token_clean}"):
            return True
    return False


def _resolve_cap(value: str, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return default if parsed <= 0 else parsed


def emit(lines: Iterable[str], line_limit: int, byte_limit: int) -> int:
    line_cap = line_limit if line_limit > 0 else _resolve_cap("", 300)
    byte_cap = byte_limit if byte_limit > 0 else 65536
    buffer = list(lines)
    truncated = False
    if len(buffer) > line_cap:
        buffer = buffer[:line_cap]
        truncated = True
    text = "\n".join(buffer)
    encoded = text.encode("utf-8", "ignore")
    if len(encoded) > byte_cap:
        truncated = True
        text = encoded[:byte_cap].decode("utf-8", "ignore")
    text = text.rstrip("\n")
    if truncated:
        if text:
            text = f"{text}\n... (truncated)"
        else:
            text = "... (truncated)"
    print(text)
    return 0


def main() -> int:
    path = pathlib.Path(os.environ.get("GC_DUMP_FILE", ""))
    if not path:
        return 0
    if _is_excluded(path):
        return 0
    if path.name.endswith(".meta.json"):
        return 0
    line_limit = _resolve_cap(os.environ.get("GC_MAX_LINES", "0"), 300)
    byte_limit = _resolve_cap(os.environ.get("GC_MAX_BYTES", "0"), 65536)

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
        return emit(lines, line_limit, byte_limit)

    if ext in markup_exts:
        clean = re.sub(r"<script[\s\S]*?</script>", "", raw, flags=re.I)
        clean = re.sub(r"<style[\s\S]*?</style>", "", clean, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", clean)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return emit(["(markup collapsed to empty after stripping tags)"], line_limit, byte_limit)
        chunks = [text[i : i + 200] for i in range(0, len(text), 200)]
        lines = ["Markup summary:"] + chunks[:5]
        if len(chunks) > 5:
            lines.append(f"... ({len(chunks) - 5} additional chunks omitted)")
        return emit(lines, line_limit, byte_limit)

    try:
        parsed = json.loads(raw)
        preview = json.dumps(parsed, indent=2)[:4000]
        return emit(["JSON summary:", preview], line_limit, byte_limit)
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

    output_lines = result or ["(no textual content captured)"]
    return emit(output_lines, line_limit, byte_limit)


if __name__ == "__main__":
    raise SystemExit(main())
