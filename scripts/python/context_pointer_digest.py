import hashlib
import fnmatch
import os
from pathlib import Path

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


def _expand_brace_pattern(pattern: str) -> list[str]:
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


def _extra_excludes():
    results = []
    raw = os.environ.get("GC_CONTEXT_EXCLUDES", "")
    if raw:
        for entry in raw.replace(":", "\n").splitlines():
            entry = entry.strip()
            if entry:
                results.extend(_expand_brace_pattern(entry))
    return results


def _is_excluded(path: Path) -> bool:
    text = str(path).replace("\\", "/")
    for pattern in DEFAULT_GLOB_EXPANDED:
        pattern_clean = pattern.strip()
        if not pattern_clean:
            continue
        glob_candidate = pattern_clean
        if fnmatch.fnmatch(text, glob_candidate) or fnmatch.fnmatch(text, f"*{glob_candidate}"):
            return True
    for suffix in DEFAULT_SUFFIXES:
        if text.endswith(suffix):
            return True
    for token in _extra_excludes():
        token_clean = token.strip()
        if not token_clean:
            continue
        if fnmatch.fnmatch(text, token_clean) or fnmatch.fnmatch(text, f"*{token_clean}"):
            return True
    return False


def main() -> int:
    path = Path(os.environ.get("GC_CONTEXT_POINTER_FILE", ""))
    chunk = b""
    try:
        if _is_excluded(path):
            print("")
            return 0
        with path.open("rb") as handle:
            chunk = handle.read(8192)
    except Exception:
        chunk = b""

    if not chunk:
        print("")
    else:
        print(hashlib.sha256(chunk).hexdigest()[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
