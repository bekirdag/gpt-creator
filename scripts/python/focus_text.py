import json
import os
import re
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Optional, List, Tuple, Set, Dict, Sequence

_original_re_compile = re.compile
_original_re__compile = getattr(re, "_compile", None)
invalid_regex_patterns = []
START_PATCH_MARKER = "apply_patch <<'PATCH'"
END_PATCH_MARKER = "PATCH"
COMMAND_BLOCK_PATTERN = re.compile(
    r'\b(sudo|chown)\b|rm\s+-rf\s+/|chmod\s+[0-7]{3}\s+/|curl\s+http|wget\s+http',
    flags=re.IGNORECASE,
)
COMMAND_WHITELIST_PATTERN = re.compile(
    r'^(git|pnpm|npm|node|bash|sh|python3|python|sqlite3|jq|rg|find|ls|date|apply_patch|sed|awk|perl|cat|tee|mv|cp|mkdir|touch|gpt-creator)\b'
)

output_path = Path(sys.argv[1])
project_root = Path(sys.argv[2])

_shim_compile_user_pattern = None
shim_base = project_root / ".gpt-creator" / "shims"
if shim_base.exists():
    sys.path.insert(0, str(shim_base))
    try:
        from regex_utils import compile_user_pattern as _shim_compile_user_pattern  # type: ignore
    except Exception:
        _shim_compile_user_pattern = None

if _shim_compile_user_pattern is None:
    import logging

    _regex_log = logging.getLogger("gc-runner.regex")

    def compile_user_pattern(fragment: str, *, flags: int = 0, allow_regex: bool = False):
        pattern = fragment if allow_regex else re.escape(fragment)
        try:
            if _original_re__compile is not None:
                return _original_re__compile(pattern, flags)
            return _original_re_compile(pattern, flags)
        except re.error as exc:
            _regex_log.warning("Invalid regex %r (%s); falling back to literal.", fragment, exc)
            escaped = re.escape(fragment)
            if _original_re__compile is not None:
                return _original_re__compile(escaped, flags)
            return _original_re_compile(escaped, flags)
else:
    compile_user_pattern = _shim_compile_user_pattern


def findall_user_pattern(fragment: str, text: str, *, flags: int = 0, allow_regex: bool = False):
    return compile_user_pattern(fragment, flags=flags, allow_regex=allow_regex).findall(text)


def _scan_apply_patch_blocks(text: str, start: str = START_PATCH_MARKER, end: str = END_PATCH_MARKER):
    results = []
    search_from = 0
    while True:
        start_idx = text.find(start, search_from)
        if start_idx == -1:
            break
        content_start = start_idx + len(start)
        if content_start < len(text) and text[content_start] == "\n":
            content_start += 1
        end_idx = text.find(end, content_start)
        if end_idx == -1:
            break
        results.append(text[content_start:end_idx])
        search_from = end_idx + len(end)
    return results


def _extract_apply_patch_blocks(text: str):
    try:
        pattern = re.compile(
            re.escape(START_PATCH_MARKER) + r"\n(.*?)\n" + re.escape(END_PATCH_MARKER),
            flags=re.S,
        )
        blocks = pattern.findall(text)
    except re.error:
        blocks = []
    if not blocks:
        blocks = _scan_apply_patch_blocks(text)
    return [block.strip("\n") for block in blocks if block.strip()]


def _git_status_porcelain(root: Path) -> Dict[str, str]:
    try:
        proc = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            cwd=str(root),
            check=False,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    result: Dict[str, str] = {}
    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:]
        if ' -> ' in path:
            path = path.split(' -> ', 1)[-1]
        path = path.strip().strip('"')
        if path:
            result[path] = status.strip()
    return result


def _status_delta(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, str]:
    delta: Dict[str, str] = {}
    for path, status in after.items():
        if path not in before:
            delta[path] = status
    return delta


def _snippet(text: Optional[str], limit: int = 160) -> str:
    if not text:
        return ""
    stripped = text.strip()
    if not stripped:
        return ""
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."


def compile_safe(pattern: str, flags: int = 0):
    try:
        if _original_re__compile is not None:
            return _original_re__compile(pattern, flags)
        return _original_re_compile(pattern, flags)
    except re.error:
        invalid_regex_patterns.append(pattern)
        return compile_user_pattern(pattern, flags=flags, allow_regex=False)


re.compile = compile_safe
if _original_re__compile is not None:
    re._compile = compile_safe

apply_timeout_env = os.environ.get("GC_APPLY_PHASE_TIMEOUT_SECONDS", "1500")
try:
    apply_timeout = int(apply_timeout_env)
    if apply_timeout <= 0:
        apply_timeout = 1500
except Exception:
    apply_timeout = 1500

patch_artifact_spec = os.environ.get("GC_PATCH_ARTIFACT_PATH", "").strip()

if not output_path.exists():
    print("no-output", flush=True)
    sys.exit(0)

raw = output_path.read_text(encoding='utf-8').strip()
if not raw:
    print("empty-output", flush=True)
    sys.exit(0)

# Remove code fences if present
if '```' in raw:
    cleaned = []
    fenced = False
    for line in raw.splitlines():
        marker = line.strip()
        if marker.startswith('```'):
            fenced = not fenced
            continue
        if not fenced:
            cleaned.append(line)
    raw = '\n'.join(cleaned).strip()

start = raw.find('{')
end = raw.rfind('}')
if start == -1 or end == -1 or end <= start:
    blocks = _extract_apply_patch_blocks(raw)
    if blocks:
        inferred_focus = []
        changes_from_blocks = []
        for block in blocks:
            block_text = block.strip("\n")
            if not block_text:
                continue
            if not block_text.endswith('\n'):
                block_text += '\n'
            changes_from_blocks.append({
                'type': 'patch',
                'diff': block_text,
            })
            candidate = None
            for line in block_text.splitlines():
                stripped = line.strip()
                if stripped.startswith('+++ b/'):
                    candidate = stripped[6:].strip()
                    if candidate and candidate != '/dev/null':
                        break
                elif stripped.startswith('diff --git '):
                    parts = stripped.split()
                    if len(parts) >= 4:
                        candidate = parts[3][2:].strip()
                        if candidate and candidate != '/dev/null':
                            break
            if candidate and candidate not in inferred_focus:
                inferred_focus.append(candidate)
        if not changes_from_blocks:
            raise SystemExit("JSON not found in Codex output")
        focus_values = inferred_focus or ['(auto) apply_patch']
        payload = {
            'plan': [],
            'focus': focus_values,
            'changes': changes_from_blocks,
            'commands': [],
            'notes': ["Auto-recovered legacy apply_patch output; prefer JSON responses."],
        }
    else:
        raise SystemExit("JSON not found in Codex output")
else:
    fragment = raw[start:end+1]
    prefix = raw[:start].strip()
    suffix = raw[end+1:].strip()
    has_extra_text = bool(prefix) or bool(suffix)

    if has_extra_text:
        raw_dump = output_path.with_suffix(output_path.suffix + '.raw.txt')
        raw_dump.parent.mkdir(parents=True, exist_ok=True)
        raw_dump.write_text(raw, encoding='utf-8')
        rel_dump = raw_dump
        try:
            rel_dump = raw_dump.relative_to(project_root)
        except ValueError:
            rel_dump = raw_dump
        payload = {
            'plan': [],
            'changes': [],
            'commands': [],
            'notes': [
                f"Codex output contained extra text outside the JSON envelope; review {rel_dump}."
            ],
        }
        print('STATUS parse-error')
        print(f"RAW {rel_dump}")
    else:
        fragment = re.sub(r'\\"(?=[}\]\n])', r'\\""', fragment)

        while True:
            try:
                payload = json.loads(fragment)
                break
            except json.JSONDecodeError as exc:
                if 'Invalid \\escape' in exc.msg:
                    fragment = fragment[:exc.pos] + '\\' + fragment[exc.pos:]
                    continue
                decoder = json.JSONDecoder(strict=False)
                try:
                    payload = decoder.decode(fragment)
                    break
                except json.JSONDecodeError:
                    raw_dump = output_path.with_suffix(output_path.suffix + '.raw.txt')
                    raw_dump.parent.mkdir(parents=True, exist_ok=True)
                    raw_dump.write_text(raw, encoding='utf-8')
                    fragment_dump = output_path.with_suffix(output_path.suffix + '.fragment.json')
                    fragment_dump.parent.mkdir(parents=True, exist_ok=True)
                    fragment_dump.write_text(fragment, encoding='utf-8')
                    rel_dump = raw_dump
                    try:
                        rel_dump = raw_dump.relative_to(project_root)
                    except ValueError:
                        rel_dump = raw_dump
                    rel_fragment = fragment_dump
                    try:
                        rel_fragment = fragment_dump.relative_to(project_root)
                    except ValueError:
                        rel_fragment = fragment_dump
                    payload = {
                        'plan': [],
                        'changes': [],
                        'commands': [],
                        'notes': [
                            f"Codex output could not be parsed as JSON; review {rel_dump}.",
                            f"Invalid JSON fragment saved at {rel_fragment}."
                        ],
                        'invalid_json_path': str(rel_fragment),
                    }
                    print('STATUS parse-error')
                    print(f"RAW {rel_dump}")
                    break

def _normalize_focus(items):
    normalized = []
    for raw_item in items:
        if isinstance(raw_item, str):
            candidate = raw_item.strip()
            if len(candidate) >= 2:
                normalized.append(candidate)
    return normalized

def _extract_focus_from_text(text):
    import json
    import ast
    import re

    if not isinstance(text, str):
        return []

    focus_pattern = r'focus\s*:\s*(\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}|[^;]+)'
    matches = findall_user_pattern(focus_pattern, text, flags=re.IGNORECASE, allow_regex=True)
    extracted = []
    for segment in matches:
        segment = segment.strip()
        if not segment:
            continue
        parsed = None
        opening = segment[:1]
        closing = segment[-1:]
        if (opening, closing) in {('[', ']'), ('{', '}'), ('(', ')')}:
            inner = segment[1:-1].strip()
            if opening in {'[', '{'}:
                try:
                    parsed = json.loads(segment)
                except Exception:
                    try:
                        parsed = ast.literal_eval(segment)
                    except Exception:
                        parsed = None
            else:
                parsed = [item.strip() for item in inner.split(',')]
            if isinstance(parsed, (list, tuple)):
                extracted.extend(_normalize_focus(parsed))
                continue
            segment = inner
        parts = [item.strip() for item in re.split(r'[,\n]', segment) if item.strip()]
        extracted.extend(_normalize_focus(parts))
    return extracted

focus_targets = payload.get('focus')
focus_valid = False
if isinstance(focus_targets, list) and focus_targets:
    normalized_focus = _normalize_focus(focus_targets)
    if len(normalized_focus) == len(focus_targets):
        focus_valid = True
        focus_targets = normalized_focus

if not focus_valid:
    inferred_focus = []
    plan_entries = payload.get('plan')
    inferred_plan = []
    if isinstance(plan_entries, list):
        for entry in plan_entries:
            if isinstance(entry, dict):
                entry_focus = entry.get('focus')
                if isinstance(entry_focus, list):
                    inferred_focus.extend(_normalize_focus(entry_focus))
                text_fields = [
                    entry.get('task'),
                    entry.get('step'),
                    entry.get('description'),
                    entry.get('summary'),
                ]
                for text_value in text_fields:
                    if isinstance(text_value, str) and text_value.strip():
                        inferred_plan.append(text_value.strip())
                        break
                else:
                    inferred_plan.append(json.dumps(entry, ensure_ascii=False))
            elif isinstance(entry, str):
                inferred_focus.extend(_extract_focus_from_text(entry))
                inferred_plan.append(entry)
    if inferred_focus:
        seen = set()
        ordered_focus = []
        for item in inferred_focus:
            if item not in seen:
                seen.add(item)
                ordered_focus.append(item)
        focus_targets = ordered_focus
        payload['focus'] = focus_targets
        focus_valid = True
        if inferred_plan:
            payload['plan'] = inferred_plan
        notes_list = payload.get('notes')
        message = "Focus array inferred from plan; include a top-level `focus` list next time."
        if isinstance(notes_list, list):
            notes_list.append(message)
        else:
            payload['notes'] = [message]

if not focus_valid:
    note_focus = []
    notes_field = payload.get('notes')
    if isinstance(notes_field, list):
        for entry in notes_field:
            if not isinstance(entry, str):
                continue
            note_focus.extend(_extract_focus_from_text(entry))
        if note_focus:
            seen = set()
            ordered = []
            for item in note_focus:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
            if ordered:
                focus_targets = ordered
                payload['focus'] = focus_targets
                focus_valid = True
                reminder = "Focus array inferred from notes; include a top-level `focus` list next time."
                if isinstance(notes_field, list):
                    notes_field.append(reminder)
                else:
                    payload['notes'] = [reminder]

if not focus_valid:
    pending_changes = payload.get('changes')
    pending_commands = payload.get('commands')
    has_changes = isinstance(pending_changes, list) and any(pending_changes)
    has_commands = isinstance(pending_commands, list) and any(pending_commands)
    if not has_changes and not has_commands:
        focus_targets = []
        payload['focus'] = focus_targets
        focus_valid = True
        notes_list = payload.get('notes')
        message = (
            "Focus omitted because no changes or commands were provided in this response; "
            "declare explicit targets once edits begin."
        )
        if isinstance(notes_list, list):
            notes_list.append(message)
        else:
            payload['notes'] = [message]

if not focus_valid:
    print('STATUS parse-error')
    print('NOTE Focus targets missing or invalid. Add a `focus` array listing the exact files or symbols you will touch, then rerun work-on-tasks.')
    sys.exit(1)

# Normalize change payloads so legacy formats (missing `type`, raw diff strings)
# still apply cleanly without aborting the task workflow.
raw_changes = payload.get('changes') or []
changes = []
for entry in raw_changes:
    if isinstance(entry, str):
        changes.append({
            'type': 'patch',
            'diff': entry,
        })
        continue
    if not isinstance(entry, dict):
        raise ValueError('Change entries must be objects or unified diff strings')
    normalized = dict(entry)
    ctype = normalized.get('type')
    if not ctype:
        if normalized.get('diff'):
            normalized['type'] = 'patch'
        elif 'content' in normalized:
            normalized['type'] = 'file'
    changes.append(normalized)

written = []
patched = []
noop_entries = []
manual_notes = []
actual_changes = 0
change_bytes = {}
collected_patch_diffs: List[str] = []

def rewrite_patch_paths(diff_text: str) -> str:
    mapping = {
        'api/': 'apps/api/',
        'web/': 'apps/web/',
        'admin/': 'apps/admin/',
        'site/': 'apps/web/',
    }

    def rewrite_path(path: str) -> str:
        for old, new in mapping.items():
            if path.startswith(old) and not path.startswith(new):
                return new + path[len(old):]
        return path

    lines = diff_text.splitlines()
    rewritten = []
    for line in lines:
        if line.startswith('diff --git a/'):
            parts = line.split()
            if len(parts) >= 4:
                a_path = parts[2][2:]
                b_path = parts[3][2:]
                new_a = rewrite_path(a_path)
                new_b = rewrite_path(b_path)
                if new_a != a_path or new_b != b_path:
                    line = f"diff --git a/{new_a} b/{new_b}"
        elif line.startswith('--- a/'):
            path = line[6:]
            new_path = rewrite_path(path)
            if new_path != path:
                line = f"--- a/{new_path}"
        elif line.startswith('+++ b/'):
            path = line[6:]
            new_path = rewrite_path(path)
            if new_path != path:
                line = f"+++ b/{new_path}"
        rewritten.append(line)
    return '\n'.join(rewritten)

def ensure_diff_headers(diff_text: str, path: str) -> str:
    if 'diff --git ' in diff_text:
        return diff_text

    lines = diff_text.splitlines()
    header = [
        f'diff --git a/{path} b/{path}',
        f'--- a/{path}',
        f'+++ b/{path}',
    ]
    return '\n'.join(header + lines)

def extract_path_from_diff(diff_text: str) -> Optional[str]:
    for line in diff_text.splitlines():
        if line.startswith('+++ b/'):
            candidate = line[6:].strip()
            if candidate and candidate != '/dev/null':
                return candidate
    return None

def ensure_within_root(path: Path) -> Path:
    try:
        full = (project_root / path).resolve(strict=False)
        project = project_root.resolve(strict=True)
    except FileNotFoundError:
        project = project_root.resolve()
        full = (project_root / path).resolve(strict=False)
    if not str(full).startswith(str(project)):
        raise ValueError(f"Path {path} escapes project root")
    return full

for change in changes:
    ctype = change.get('type')
    path = change.get('path')
    if not path:
        if ctype == 'patch':
            inferred = extract_path_from_diff(change.get('diff') or '')
            if inferred:
                path = inferred
                change['path'] = path
    if not path:
        raise ValueError('Change entry missing path')
    if ctype == 'file':
        content = change.get('content', '')
        dest = ensure_within_root(Path(path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.is_dir():
            try:
                rel_path = str(dest.relative_to(project_root))
            except ValueError:
                rel_path = str(dest)
            manual_notes.append(
                f"Skipped writing {rel_path} because that path already exists as a directory."
            )
            continue
        try:
            rel_path = str(dest.relative_to(project_root))
        except ValueError:
            rel_path = str(dest)
        if dest.exists():
            existing = dest.read_text(encoding='utf-8')
            if existing == content:
                noop_entries.append(rel_path + ' (unchanged)')
                continue
        dest.write_text(content, encoding='utf-8')
        written.append(rel_path)
        change_bytes[rel_path] = len(content.encode('utf-8'))
        actual_changes += 1
    elif ctype == 'patch':
        diff = change.get('diff')
        if not diff:
            raise ValueError(f"Patch change for {path} missing diff")
        diff = rewrite_patch_paths(diff)
        diff = ensure_diff_headers(diff, path)
        diff_bytes = len(diff.encode('utf-8'))
        if not diff.endswith('\n'):
            diff += '\n'
        collected_patch_diffs.append(diff)

        try:
            proc = subprocess.run(
                ['git', 'apply', '--whitespace=nowarn', '-'],
                input=diff.encode('utf-8'),
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=apply_timeout,
            )
            timeout_err = False
        except subprocess.TimeoutExpired:
            timeout_err = True
            proc = CompletedProcess(
                args=['git', 'apply', '--whitespace=nowarn', '-'],
                returncode=124,
                stdout=b'',
                stderr=f'git apply timed out after {apply_timeout}s'.encode('utf-8'),
            )

        if timeout_err or proc.returncode != 0:
            git_err = proc.stderr.decode('utf-8') if proc.stderr else ''
            if timeout_err:
                manual_notes.append(
                    f"git apply timed out after {apply_timeout}s while processing {path}; patch queued for manual review."
                )

            try:
                three_way = subprocess.run(
                    ['git', 'apply', '--3way', '--whitespace=nowarn', '-'],
                    input=diff.encode('utf-8'),
                    cwd=str(project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=apply_timeout,
                )
                three_way_timeout = False
            except subprocess.TimeoutExpired:
                three_way_timeout = True
                three_way = CompletedProcess(
                    args=['git', 'apply', '--3way', '--whitespace=nowarn', '-'],
                    returncode=124,
                    stdout=b'',
                    stderr=f'git apply --3way timed out after {apply_timeout}s'.encode('utf-8'),
                )

            if three_way_timeout:
                manual_notes.append(
                    f"git apply --3way timed out after {apply_timeout}s for {path}; attempting fallback."
                )

            if not three_way_timeout and three_way.returncode == 0:
                patched.append(path + ' (3way)')
                change_bytes[path] = diff_bytes
                actual_changes += 1
                continue

            git_err += three_way.stderr.decode('utf-8') if three_way.stderr else ''

            try:
                fallback = subprocess.run(
                    ['patch', '-p1', '--forward', '--silent'],
                    input=diff.encode('utf-8'),
                    cwd=str(project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=apply_timeout,
                )
                fallback_timeout = False
            except subprocess.TimeoutExpired:
                fallback_timeout = True
                fallback = CompletedProcess(
                    args=['patch', '-p1', '--forward', '--silent'],
                    returncode=124,
                    stdout=b'',
                    stderr=f'patch command timed out after {apply_timeout}s'.encode('utf-8'),
                )
                manual_notes.append(
                    f"patch command timed out after {apply_timeout}s while applying {path}; manual intervention required."
                )
            if fallback.returncode != 0:
                # check if patch already applied
                already = subprocess.run(
                    ['git', 'apply', '--reverse', '--check', '-'],
                    input=diff.encode('utf-8'),
                    cwd=str(project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if already.returncode == 0:
                    noop_entries.append(path + ' (already applied)')
                    continue

                new_content = None
                diff_lines = diff.splitlines()
                multi_file = sum(1 for line in diff_lines if line.startswith('diff --git ')) > 1
                if not multi_file and any(line.startswith('--- /dev/null') for line in diff_lines):
                    capture = False
                    content_lines = []
                    for line in diff_lines:
                        if line.startswith('@@'):
                            capture = True
                            continue
                        if not capture:
                            continue
                        if not line or line.startswith('diff --git'):
                            continue
                        if line.startswith('+'):
                            content_lines.append(line[1:])
                        elif line.startswith('-') or line.startswith('---') or line.startswith('+++'):
                            continue
                        elif line.startswith('\\'):
                            continue
                        else:
                            content_lines.append(line)
                    if content_lines:
                        new_content = '\n'.join(content_lines)
                        if not new_content.endswith('\n'):
                            new_content += '\n'
                if new_content is not None:
                    dest = ensure_within_root(Path(path))
                    if dest.exists() and dest.is_dir():
                        new_content = None
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if dest.exists():
                            existing = dest.read_text(encoding='utf-8')
                            if existing == new_content:
                                noop_entries.append(path + ' (already exists)')
                                continue
                        dest.write_text(new_content, encoding='utf-8')
                        patched.append(path + ' (reconstructed)')
                        change_bytes[path] = len(new_content.encode('utf-8'))
                        actual_changes += 1
                        continue

                if new_content is None:
                    try:
                        proc_noctx = subprocess.run(
                            ['git', 'apply', '--reject', '--whitespace=nowarn', '-'],
                            input=diff.encode('utf-8'),
                            cwd=str(project_root),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                        )
                        if proc_noctx.returncode == 0:
                            patched.append(path + ' (partial apply)')
                            change_bytes[path] = diff_bytes
                            actual_changes += 1
                            continue
                        else:
                            git_err += proc_noctx.stderr.decode('utf-8')
                    except Exception:
                        pass

                manual_patch = output_path.with_suffix(output_path.suffix + f".{len(manual_notes)+1}.patch")
                manual_patch.write_text(diff, encoding='utf-8')
                relative_manual = manual_patch
                try:
                    relative_manual = manual_patch.relative_to(project_root)
                except ValueError:
                    pass

                applied_via_helper = False
                helper = project_root / "scripts" / "auto_apply_patch.sh"
                if helper.exists() and helper.is_file():
                    try:
                        result = subprocess.run(
                            [str(helper), str(manual_patch)],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if result.stdout:
                            sys.stdout.write(result.stdout)
                        if result.stderr:
                            sys.stderr.write(result.stderr)
                        if result.returncode == 0:
                            applied_via_helper = True
                        elif result.returncode == 3:
                            manual_notes.append(
                                f"Patch for {path} hit conflicts even after auto_apply_patch; see {relative_manual}."
                            )
                    except Exception:
                        applied_via_helper = False

                if applied_via_helper:
                    manual_notes.append(
                        f"Patch for {path} required manual context merge but was auto-applied via scripts/auto_apply_patch.sh."
                    )
                    patched.append(path + ' (auto)')
                else:
                    manual_notes.append(
                        f"Patch for {path} could not be applied automatically. Review and apply {relative_manual} manually."
                    )
                    patched.append(path + ' (manual)')
                    sys.stderr.write(git_err)
                    sys.stderr.write(fallback.stderr.decode('utf-8'))
                continue
            patched.append(path + ' (patch)')
            change_bytes[path] = diff_bytes
            actual_changes += 1
        else:
            patched.append(path)
            change_bytes[path] = diff_bytes
            actual_changes += 1
    else:
        raise ValueError(f"Unknown change type: {ctype}")

command_entries = payload.get('commands') or []
executed_commands: List[str] = []
if isinstance(command_entries, list) and command_entries:
    baseline_status = _git_status_porcelain(project_root)
    for raw_cmd in command_entries:
        if not isinstance(raw_cmd, str):
            continue
        command = raw_cmd.strip()
        if not command:
            continue
        if COMMAND_BLOCK_PATTERN.search(command):
            manual_notes.append(f"Command '{command}' skipped (blocked by policy).")
            continue
        if not COMMAND_WHITELIST_PATTERN.match(command):
            manual_notes.append(f"Command '{command}' skipped (not whitelisted).")
            continue
        if os.environ.get("GC_RG_NARROW", "") == "1" and command.startswith("rg "):
            if " -m " not in command and "--max-count" not in command:
                command = command.replace("rg ", "rg -m 200 --max-count 200 ", 1)
            if "--max-filesize" not in command:
                command = command.replace("rg ", "rg --max-filesize 256K ", 1)
        if os.environ.get("GC_TESTS_SUMMARY", "") == "1" and ("pnpm test" in command or "npm test" in command) and "--reporter" not in command:
            command += " --reporter summary"
        try:
            proc_cmd = subprocess.run(
                ['bash', '-lc', command],
                capture_output=True,
                text=True,
                cwd=str(project_root),
                timeout=apply_timeout,
                check=False,
            )
        except Exception as exc:
            manual_notes.append(f"Command '{command}' failed to run: {exc}")
            continue
        if proc_cmd.stdout:
            sys.stdout.write(proc_cmd.stdout)
        if proc_cmd.stderr:
            sys.stderr.write(proc_cmd.stderr)
        if proc_cmd.returncode != 0:
            snippet = _snippet(proc_cmd.stderr) or _snippet(proc_cmd.stdout)
            note = f"Command '{command}' exited with status {proc_cmd.returncode}; review output."
            if snippet:
                note += f" stderr: {snippet}"
            manual_notes.append(note)
            if "doc_registry.py" in command and proc_cmd.returncode in {2, 127}:
                manual_notes.append("Doc registry tool missing (src/lib/doc_registry.py).")
        else:
            manual_notes.append(f"Command '{command}' executed successfully.")
            executed_commands.append(command)
    post_status = _git_status_porcelain(project_root)
    delta_status = _status_delta(baseline_status, post_status)
    if delta_status:
        for path, status in delta_status.items():
            label = f"{path} (command)"
            status_code = status.strip()
            if status_code == "??":
                if label not in written:
                    written.append(label)
            else:
                if label not in patched:
                    patched.append(label)
            try:
                resolved = ensure_within_root(Path(path))
                if resolved.exists() and resolved.is_file():
                    size_value = resolved.stat().st_size
                else:
                    size_value = change_bytes.get(path, 0)
            except Exception:
                size_value = change_bytes.get(path, 0)
            change_bytes[path] = size_value
        actual_changes += len(delta_status)
    elif executed_commands:
        manual_notes.append(
            "Commands executed but produced no new tracked changes; verify if additional steps are required."
        )

if patch_artifact_spec and collected_patch_diffs:
    try:
        artifact_target = ensure_within_root(Path(patch_artifact_spec))
        artifact_target.parent.mkdir(parents=True, exist_ok=True)
        combined_diff = "\n".join(collected_patch_diffs)
        if combined_diff and not combined_diff.endswith("\n"):
            combined_diff += "\n"
        artifact_target.write_text(combined_diff, encoding="utf-8")
        diff_lines = combined_diff.splitlines()
        hunk_count = sum(1 for line in diff_lines if line.startswith("@@"))
        line_count = len(diff_lines)
        relative_patch: Path = artifact_target
        try:
            relative_patch = artifact_target.relative_to(project_root)
        except ValueError:
            pass
        manual_notes.append(
            f"Patch artifact saved to {relative_patch} (hunks={hunk_count}, lines={line_count})."
        )
        print(f"ARTIFACT {relative_patch}\t{hunk_count}\t{line_count}")
    except Exception as exc:
        manual_notes.append(f"Failed to write patch artifact ({patch_artifact_spec}): {exc}")

if invalid_regex_patterns:
    logged_patterns = []
    for raw_pattern in invalid_regex_patterns:
        text_pattern = str(raw_pattern)
        if text_pattern in logged_patterns:
            continue
        logged_patterns.append(text_pattern)
        snippet = text_pattern.replace("\n", "\\n")
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        manual_notes.append(
            f"Regex pattern {snippet!r} was invalid; treated as a literal text match instead."
        )

summary = {
    'written': written,
    'patched': patched,
    'noop': noop_entries,
    'commands': payload.get('commands') or [],
    'notes': (payload.get('notes') or []) + manual_notes,
}
if actual_changes > 0:
    print('STATUS ok')
else:
    print('STATUS noop')
print('APPLIED')
for path in written:
    print(f"WRITE {path}")
for path in patched:
    print(f"PATCH {path}")
for path, size in change_bytes.items():
    print(f"SIZE {path}\t{size}")
for path in noop_entries:
    print(f"NOOP {path}")
for cmd in summary['commands']:
    print(f"CMD {cmd}")
for note in summary['notes']:
    print(f"NOTE {note}")
