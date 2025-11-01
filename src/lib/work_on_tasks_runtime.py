#!/usr/bin/env python3
"""Runtime helpers extracted from bin/gpt-creator."""

import os
import sys
from pathlib import Path

_HELPER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "python"
if _HELPER_DIR.exists():
    helper_str = str(_HELPER_DIR)
    if helper_str not in sys.path:
        sys.path.insert(0, helper_str)

_EXTRA_HELPER_DIR = os.getenv("GC_PY_HELPERS_DIR", "")
if _EXTRA_HELPER_DIR:
    try:
        extra_path = Path(_EXTRA_HELPER_DIR).resolve()
        extra_str = str(extra_path)
        if extra_path.exists() and extra_str not in sys.path:
            sys.path.insert(0, extra_str)
    except Exception:
        pass

def main():
    if len(sys.argv) < 2:
        print("Usage: work_on_tasks_runtime.py <apply|prompt> …", file=sys.stderr)
        sys.exit(1)
    mode = sys.argv[1]
    args = sys.argv[2:]
    if mode == "apply":
        if len(args) != 2:
            print("apply requires 2 arguments", file=sys.stderr)
            sys.exit(1)
        sys.argv = [sys.argv[0]] + args
        import json
        import os
        import re
        import shlex
        import subprocess
        from pathlib import Path
        from subprocess import CompletedProcess
        from collections import OrderedDict
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
            r'^(git|pnpm|npm|node|bash|sh|python3|python|sqlite3|jq|sed|awk|perl|cat|tee|mv|cp|mkdir|touch|gpt-creator)\b'
        )

        output_path = Path(sys.argv[1])
        project_root = Path(sys.argv[2])
        try:
            project_root_resolved = project_root.resolve()
        except Exception:
            project_root_resolved = project_root

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

        DOC_SUFFIXES = ('.md', '.mdx', '.markdown', '.rst', '.adoc', '.txt')
        DOC_PATH_PREFIXES = (
            'docs/',
            '.gpt-creator/staging/docs/',
            '.gpt-creator/staging/plan/docs/',
        )
        DOC_PATH_EXACT = {
            'docs',
            '.gpt-creator/staging/docs',
            '.gpt-creator/staging/plan/docs',
        }
        RG_OPTIONS_EXPECT_VALUE = {
            '-A',
            '-B',
            '-C',
            '-E',
            '-M',
            '-d',
            '-e',
            '-f',
            '-g',
            '-j',
            '-m',
            '-r',
            '-t',
            '-T',
            '--after-context',
            '--before-context',
            '--color',
            '--colors',
            '--context',
            '--context-separator',
            '--dfa-size-limit',
            '--encoding',
            '--engine',
            '--field-context-separator',
            '--field-match-separator',
            '--file',
            '--glob',
            '--hyperlink-format',
            '--iglob',
            '--ignore-file',
            '--max-columns',
            '--max-count',
            '--max-depth',
            '--max-filesize',
            '--path-separator',
            '--pre',
            '--pre-glob',
            '--regexp',
            '--regex',
            '--replace',
            '--sort',
            '--sortr',
            '--threads',
            '--type',
            '--type-add',
            '--type-clear',
            '--type-not',
        }
        SED_MAX_WINDOW = 40
        NOTE_CHAR_LIMIT = 300
        NOTE_REASONING_BUDGET_CHARS = 6000
        MAX_CONSECUTIVE_NON_ACTION_NOTES = 2
        COMMAND_LABEL_LIMIT = 96
        MAX_BLOCKED_COMMAND_DETAILS = 5
        BLOCK_REASON_LABELS = {
            'heredoc': 'raw heredoc writes',
            'python-non3': 'python (use python3)',
            'missing-helper': 'missing apply-block helper',
            'sed-window': 'oversized sed slices',
            'doc-search': 'documentation search',
            'show-file-range': 'show-file missing --range',
            'duplicate': 'duplicate commands',
            'policy': 'policy guardrails',
            'non-whitelist': 'non-whitelisted commands',
        }

        def _token_targets_doc(token: str) -> bool:
            candidate = token.strip().strip('\'"')
            if not candidate or candidate in {'|', '||', '&&', ';'}:
                return False
            if candidate.startswith('-'):
                return False
            base_candidate = candidate.rstrip(',;')
            if base_candidate.startswith('--'):
                return False
            path_fragment = base_candidate
            if ':' in path_fragment:
                prefix, suffix = path_fragment.rsplit(':', 1)
                if suffix.isdigit():
                    path_fragment = prefix
            normalized = path_fragment.replace('\\', '/').lstrip('./')
            normalized_lower = normalized.lower()
            if normalized_lower in DOC_PATH_EXACT:
                return True
            if any(normalized_lower.startswith(prefix) for prefix in DOC_PATH_PREFIXES):
                return True
            if any(normalized_lower.endswith(suffix) for suffix in DOC_SUFFIXES):
                return True
            try:
                candidate_path = (project_root / path_fragment).resolve()
                rel = candidate_path.relative_to(project_root_resolved)
                rel_str = str(rel).replace('\\', '/').lower()
                if rel_str in DOC_PATH_EXACT:
                    return True
                if any(rel_str.startswith(prefix) for prefix in DOC_PATH_PREFIXES):
                    return True
                if any(rel_str.endswith(suffix) for suffix in DOC_SUFFIXES):
                    return True
            except Exception:
                pass
            return False

        def _command_targets_docs(command: str) -> bool:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            if not tokens:
                return False
            if tokens[0] == 'rg':
                idx = 1
                pattern_consumed = False
                while idx < len(tokens):
                    token = tokens[idx]
                    if token == '--':
                        idx += 1
                        break
                    if token.startswith('-'):
                        if '=' in token:
                            idx += 1
                            continue
                        if token in RG_OPTIONS_EXPECT_VALUE:
                            idx += 2
                        else:
                            idx += 1
                        continue
                    if not pattern_consumed:
                        pattern_consumed = True
                        idx += 1
                        break
                if not pattern_consumed:
                    return False
                remainder = tokens[idx:]
                return any(_token_targets_doc(tok) for tok in remainder)
            if tokens[0] == 'gpt-creator' and len(tokens) >= 2 and tokens[1] == 'show-file':
                for token in tokens[2:]:
                    if token.startswith('-'):
                        continue
                    return _token_targets_doc(token)
                return False
            for token in tokens[1:]:
                if _token_targets_doc(token):
                    return True
            return False

        def _show_file_lacks_range(command: str) -> bool:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            if len(tokens) < 2:
                return False
            if tokens[0] != 'gpt-creator' or tokens[1] != 'show-file':
                return False
            return not any(tok.startswith('--range') for tok in tokens[2:])

        def _normalize_command_wrapper(text: str) -> str:
            normalized = text.strip()
            while len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'`', '"', "'"}:
                normalized = normalized[1:-1].strip()
            return normalized

        def _sed_window_exceeds(command: str, *, threshold: int = SED_MAX_WINDOW) -> Tuple[bool, int]:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            if not tokens or tokens[0] != 'sed':
                return (False, 0)
            max_window = 0

            def consider_fragment(fragment: str) -> None:
                nonlocal max_window
                fragment = fragment.strip()
                if not fragment:
                    return
                match = re.fullmatch(r'(\d+),(\d+)p', fragment)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2))
                    if end >= start:
                        span = end - start + 1
                        if span > max_window:
                            max_window = span

            for token in tokens[1:]:
                token_stripped = token.strip().strip('\'"')
                if not token_stripped:
                    continue
                # Multiple segments can be separated by ';'
                for fragment in token_stripped.split(';'):
                    consider_fragment(fragment)

            if max_window > threshold:
                return (True, max_window)
            return (False, max_window)

        def _summarize_stream(label: str, text: str, *, max_lines: int = 4) -> str:
            if not text:
                return ''
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            if not lines:
                return ''
            if len(lines) <= max_lines:
                body = '\n'.join(lines)
            else:
                clipped = lines[:max_lines // 2] + ['…'] + lines[-(max_lines // 2):]
                body = '\n'.join(clipped)
            return f"{label}:\n{body}"

        def _truncate_command_text(command: str, limit: int = COMMAND_LABEL_LIMIT) -> str:
            snippet = command.strip()
            if len(snippet) <= limit:
                return snippet
            return snippet[:limit - 1] + '…'

        def _format_action_result(action: str, result: str) -> str:
            return f"Action: {action.strip()} | Result: {result.strip()}"

        def _has_action_token(text: str) -> bool:
            lowered = text.lower()
            return any(token in lowered for token in ('action:', 'result:', 'command', 'next:', 'plan:', 'test:'))


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

        if not output_path.exists():
            print("no-output", flush=True)
            sys.exit(0)

        raw = output_path.read_text(encoding='utf-8').strip()
        if not raw:
            print("empty-output", flush=True)
            sys.exit(0)

        def _strip_wrapped_json_fence(text: str) -> str:
            lines = text.splitlines()
            if len(lines) >= 2:
                first = lines[0].strip()
                last = lines[-1].strip()
                if first.startswith("```") and last == "```":
                    language = first[3:].strip().lower()
                    if language in {"json", "jsonc"} or language.startswith("json "):
                        return "\n".join(lines[1:-1]).strip()
            return text

        raw = _strip_wrapped_json_fence(raw)

        payload = None

        def _try_parse_json_payload(text: str):
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
                return None
            fragment = text[start_idx:end_idx + 1]
            fragment = re.sub(r'\\"(?=[}\]\n])', r'\\""', fragment)
            attempts = 0
            while attempts < 5:
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError as exc:
                    if 'Invalid \\escape' in exc.msg:
                        fragment = fragment[:exc.pos] + '\\' + fragment[exc.pos:]
                        attempts += 1
                        continue
                    decoder = json.JSONDecoder(strict=False)
                    try:
                        return decoder.decode(fragment)
                    except json.JSONDecodeError:
                        break
            raw_dump = output_path.with_suffix(output_path.suffix + '.raw.txt')
            fragment_dump = output_path.with_suffix(output_path.suffix + '.fragment.json')
            try:
                raw_dump.parent.mkdir(parents=True, exist_ok=True)
                raw_dump.write_text(text, encoding='utf-8')
                fragment_dump.parent.mkdir(parents=True, exist_ok=True)
                fragment_dump.write_text(fragment, encoding='utf-8')
            except Exception:
                pass
            return None

        def _parse_apply_patch_payload(text: str):
            blocks = _extract_apply_patch_blocks(text)
            if not blocks:
                return None
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
                return None
            focus_values = inferred_focus or ['(auto) apply_patch']
            return {
                'plan': [],
                'focus': focus_values,
                'changes': changes_from_blocks,
                'commands': [],
                'notes': ["Recovered edits from apply_patch blocks in the response."],
            }

        def _extract_section_lines(text: str):
            headings = {"plan", "focus", "commands", "notes", "changes"}
            sections: Dict[str, List[str]] = {}
            current = None
            in_fence = False
            fence_lang = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("```"):
                    if in_fence:
                        in_fence = False
                        fence_lang = ""
                    else:
                        in_fence = True
                        fence_lang = stripped[3:].strip().lower()
                    if current:
                        sections.setdefault(current, []).append(line)
                    continue
                if not in_fence:
                    candidate = stripped.rstrip(':').lower()
                    if candidate in headings:
                        current = candidate
                        sections.setdefault(current, [])
                        continue
                if current:
                    sections.setdefault(current, []).append(line)
            return sections

        def _parse_list_items(lines: List[str]) -> List[str]:
            items: List[str] = []
            in_block = False
            block_lines: List[str] = []
            for raw_line in lines:
                stripped = raw_line.strip()
                if stripped.startswith("```"):
                    if in_block:
                        block_lines.append(raw_line)
                        block_content = "\n".join(block_lines).strip()
                        if block_content:
                            items.append(block_content)
                        block_lines = []
                        in_block = False
                    else:
                        in_block = True
                        block_lines = [raw_line]
                    continue
                if in_block:
                    block_lines.append(raw_line)
                    continue
                if not stripped:
                    continue
                cleaned = re.sub(r'^[\-\*\d\.\)\s]+', '', stripped)
                items.append(cleaned)
            if block_lines:
                block_content = "\n".join(block_lines).strip()
                if block_content:
                    items.append(block_content)
            return items

        def _normalise_command_items(items: List[str]) -> List[str]:
            normalised: List[str] = []
            for item in items:
                if item.startswith("```"):
                    lines = [line.strip("\n") for line in item.splitlines()]
                    body = []
                    in_body = False
                    for line in lines:
                        marker = line.strip()
                        if marker.startswith("```"):
                            in_body = not in_body
                            continue
                        if in_body:
                            body.append(line)
                    command = "\n".join(body).strip()
                    if command:
                        normalised.append(command)
                    continue
                normalised.append(item)
            return normalised

        def _extract_diff_blocks(text: str) -> List[str]:
            diffs: List[str] = []
            seen: Set[str] = set()
            fence_pattern = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)
            for match in fence_pattern.finditer(text):
                diff_text = match.group(1).strip()
                if not diff_text:
                    continue
                if not diff_text.endswith('\n'):
                    diff_text += '\n'
                if diff_text not in seen:
                    seen.add(diff_text)
                    diffs.append(diff_text)
            plain_pattern = re.compile(r"^diff --git .*?(?=^diff --git |\Z)", re.S | re.M)
            for match in plain_pattern.finditer(text):
                diff_text = match.group(0).strip()
                if not diff_text:
                    continue
                if not diff_text.endswith('\n'):
                    diff_text += '\n'
                if diff_text not in seen:
                    seen.add(diff_text)
                    diffs.append(diff_text)
            return diffs

        def _parse_freeform_payload(text: str):
            sections = _extract_section_lines(text)
            if not sections:
                return None
            plan_items = _parse_list_items(sections.get("plan", []))
            focus_items = _parse_list_items(sections.get("focus", []))
            command_items = _normalise_command_items(_parse_list_items(sections.get("commands", [])))
            notes_items = _parse_list_items(sections.get("notes", []))
            freeform_changes = _parse_list_items(sections.get("changes", []))
            diff_blobs = _extract_diff_blocks("\n".join(freeform_changes)) if freeform_changes else []
            if not diff_blobs:
                diff_blobs = _extract_diff_blocks(text)
            change_entries = [{'type': 'patch', 'diff': blob} for blob in diff_blobs]
            return {
                'plan': plan_items,
                'focus': focus_items,
                'changes': change_entries,
                'commands': command_items,
                'notes': notes_items,
            }

        payload = _try_parse_json_payload(raw)
        if payload is None:
            payload = _parse_apply_patch_payload(raw)
        if payload is None:
            payload = _parse_freeform_payload(raw)
        if payload is None:
            raise SystemExit("Agent output could not be parsed into actionable instructions.")

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
        if isinstance(focus_targets, list):
            normalized_focus = _normalize_focus(focus_targets)
            if len(normalized_focus) == len(focus_targets):
                focus_valid = True
                focus_targets = normalized_focus
            elif not focus_targets:
                focus_targets = []
                focus_valid = True

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
            focus_targets = []
            payload['focus'] = focus_targets
            focus_valid = True

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
            type_hint = normalized.get('type')
            normalized_hint = type_hint.strip().lower() if isinstance(type_hint, str) else ''
            diff_reference = None
            if normalized_hint in ('patch_file', 'patch_path'):
                diff_reference = (
                    normalized.get('diff_path')
                    or normalized.get('path')
                    or normalized.get('file')
                )
                normalized.pop('file', None)
                if diff_reference and normalized.get('path') == diff_reference:
                    normalized.pop('path', None)
            elif normalized.get('diff_path'):
                diff_reference = normalized.get('diff_path')
            if diff_reference:
                diff_path = Path(diff_reference)
                if not diff_path.is_absolute():
                    diff_path = project_root / diff_path
                text = diff_path.read_text(encoding='utf-8')
                normalized['type'] = 'patch'
                normalized['diff'] = text if text.endswith('\n') else text + '\n'
                normalized.pop('diff_path', None)
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

        existing_notes = payload.get('notes')
        if isinstance(existing_notes, list):
            cleaned_notes: List[str] = []
            reasoning_chars = 0
            longform_flag = False
            non_action_streak = 0
            stop_prompt_sent = False
            for entry in existing_notes:
                if not isinstance(entry, str):
                    continue
                text = entry.strip()
                if not text:
                    continue
                reasoning_chars += len(text)
                has_action = _has_action_token(text)
                if len(text) > NOTE_CHAR_LIMIT and not has_action:
                    longform_flag = True
                    text = text[:NOTE_CHAR_LIMIT].rstrip() + '…'
                cleaned_notes.append(text)
                if has_action:
                    non_action_streak = 0
                else:
                    non_action_streak += 1
                    if (
                        non_action_streak > MAX_CONSECUTIVE_NON_ACTION_NOTES
                        and not stop_prompt_sent
                    ):
                        manual_notes.append(
                            _format_action_result(
                                "notes-stop-and-plan",
                                "blocked — convert narration into actionable checklist tied to upcoming commands before continuing"
                            )
                        )
                        stop_prompt_sent = True
            payload['notes'] = cleaned_notes
            if longform_flag:
                manual_notes.append(
                    _format_action_result(
                        "notes-trim-longform",
                        "blocked — narration trimmed (>300 chars); restate as Action/Result bullets referencing commands"
                    )
                )
            if reasoning_chars > NOTE_REASONING_BUDGET_CHARS:
                manual_notes.append(
                    _format_action_result(
                        "notes-reasoning-budget",
                        "warning — cumulative reasoning exceeded ~1.5k tokens; keep subsequent updates concise and command-linked"
                    )
                )
        elif existing_notes is not None:
            payload['notes'] = []
        actual_changes = 0
        change_bytes = {}

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

        for index, change in enumerate(changes):
            if not isinstance(change, dict):
                manual_notes.append(
                    _format_action_result(f"change[{index}]", "blocked — expected object payload")
                )
                continue

            raw_type = change.get('type')
            if isinstance(raw_type, str):
                normalized_type = raw_type.strip().lower()
            else:
                normalized_type = ''

            if normalized_type in ('edit', 'patch'):
                ctype = 'patch'
            elif normalized_type in ('file', 'create'):
                ctype = 'file'
            else:
                ctype = normalized_type

            raw_path = change.get('path')
            path = raw_path.strip() if isinstance(raw_path, str) else ''

            if ctype == 'patch':
                diff_value = change.get('diff')
                if not isinstance(diff_value, str) or not diff_value.strip():
                    manual_notes.append(
                        _format_action_result(f"change[{index}]", "blocked — patch diff missing or empty")
                    )
                    continue
                if not path:
                    inferred = extract_path_from_diff(diff_value or '')
                    if inferred:
                        path = inferred
                        change['path'] = path
                if not path:
                    manual_notes.append(
                        _format_action_result(f"change[{index}]", "blocked — path missing or empty")
                    )
                    continue
                change['type'] = 'patch'
            elif ctype == 'file':
                if not path:
                    manual_notes.append(
                        _format_action_result(f"change[{index}]", "blocked — path missing or empty")
                    )
                    continue
                content_value = change.get('content')
                if not isinstance(content_value, str):
                    manual_notes.append(
                        _format_action_result(f"change[{index}]", "blocked — file content missing or not text")
                    )
                    continue
                change['type'] = 'file'
            else:
                descriptor = (raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else 'unknown')
                manual_notes.append(
                    _format_action_result(f"change[{index}]", f"blocked — unknown type '{descriptor}'")
                )
                continue

            if change['type'] == 'file':
                content = change.get('content', '')
                dest = ensure_within_root(Path(path))
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest.is_dir():
                    try:
                        rel_path = str(dest.relative_to(project_root))
                    except ValueError:
                        rel_path = str(dest)
                    manual_notes.append(
                        _format_action_result(f"write {rel_path}", "blocked — destination is an existing directory")
                    )
                    continue
                try:
                    rel_path = str(dest.relative_to(project_root))
                except ValueError:
                    rel_path = str(dest)
                rel_path_lower = rel_path.lstrip("./").lower()
                if rel_path_lower.startswith("docs/") or rel_path_lower.startswith(".gpt-creator/staging/docs"):
                    manual_notes.append(
                        _format_action_result(f"write {rel_path}", "blocked — documentation changes out of scope")
                    )
                    continue
                if dest.exists():
                    existing = dest.read_text(encoding='utf-8')
                    if existing == content:
                        noop_entries.append(rel_path + ' (unchanged)')
                        continue
                dest.write_text(content, encoding='utf-8')
                written.append(rel_path)
                change_bytes[rel_path] = len(content.encode('utf-8'))
                actual_changes += 1
                if rel_path_lower.startswith("docs/") or rel_path_lower.startswith(".gpt-creator/staging/docs"):
                    manual_notes.append(
                        _format_action_result("doc-update-followup", "note — verify related code changes before letting doc edits stand")
                    )
            elif ctype == 'patch':
                diff = change.get('diff')
                diff = rewrite_patch_paths(diff)
                diff = ensure_diff_headers(diff, path)
                diff_bytes = len(diff.encode('utf-8'))
                if not diff.endswith('\n'):
                    diff += '\n'

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
                            _format_action_result(
                                _truncate_command_text(f"git apply {path}"),
                                f"blocked — timed out after {apply_timeout}s; patch queued for manual review"
                            )
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
                            _format_action_result(
                                _truncate_command_text(f"git apply --3way {path}"),
                                f"blocked — timed out after {apply_timeout}s; attempting fallback"
                            )
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
                            _format_action_result(
                                _truncate_command_text(f"patch --forward {path}"),
                                f"blocked — timed out after {apply_timeout}s; manual intervention required"
                            )
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
                                        _format_action_result(
                                            _truncate_command_text(f"auto_apply_patch {path}"),
                                            f"blocked — conflicts remained; review {relative_manual}"
                                        )
                                    )
                            except Exception:
                                applied_via_helper = False

                        if applied_via_helper:
                            manual_notes.append(
                                _format_action_result(
                                    _truncate_command_text(f"auto_apply_patch {path}"),
                                    "note — manual context merge succeeded via helper script"
                                )
                            )
                            patched.append(path + ' (auto)')
                        else:
                            manual_notes.append(
                                _format_action_result(
                                    _truncate_command_text(f"git apply {path}"),
                                    f"blocked — auto-apply failed; review {relative_manual}"
                                )
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

        command_entries = payload.get('commands') or []
        executed_commands: List[str] = []
        seen_commands: Set[str] = set()
        blocked_command_counts: Dict[str, Dict[str, object]] = {}
        blocked_command_total = 0

        def _git_diff_name_status(root: Path) -> Dict[str, str]:
            try:
                proc = subprocess.run(
                    ['git', 'diff', '--name-status', 'HEAD'],
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    check=False,
                )
            except Exception:
                return {}
            if proc.returncode != 0:
                return {}
            diff_map: Dict[str, str] = {}
            for raw_line in proc.stdout.splitlines():
                if not raw_line.strip():
                    continue
                parts = raw_line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                status, path = parts
                path = path.strip()
                if path:
                    diff_map[path] = status.strip()
            return diff_map

        def _git_untracked_files(root: Path) -> Set[str]:
            try:
                proc = subprocess.run(
                    ['git', 'ls-files', '--others', '--exclude-standard'],
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    check=False,
                )
            except Exception:
                return set()
            if proc.returncode != 0:
                return set()
            return {line.strip() for line in proc.stdout.splitlines() if line.strip()}

        command_diff_before = _git_diff_name_status(project_root)
        command_untracked_before = _git_untracked_files(project_root)

        def _record_blocked_command(reason: str, command: str) -> None:
            nonlocal blocked_command_total
            blocked_command_total += 1
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            canonical = ' '.join(tokens) if tokens else command.strip()
            bucket = blocked_command_counts.setdefault(
                reason,
                {'total': 0, 'examples': [], 'commands': OrderedDict()}
            )
            bucket['total'] = int(bucket['total']) + 1
            commands_map: OrderedDict = bucket['commands']  # type: ignore[assignment]
            commands_map[canonical] = commands_map.get(canonical, 0) + 1
            examples: List[str] = bucket['examples']  # type: ignore[assignment]
            label = _truncate_command_text(command)
            if len(examples) < MAX_BLOCKED_COMMAND_DETAILS and label not in examples:
                examples.append(label)

        skip_command_processing = False
        if isinstance(command_entries, list) and command_entries:
            precheck_non_whitelisted = []
            for raw_cmd in command_entries:
                if not isinstance(raw_cmd, str):
                    continue
                trimmed = _normalize_command_wrapper(raw_cmd)
                if not trimmed:
                    continue
                if not COMMAND_WHITELIST_PATTERN.match(trimmed):
                    precheck_non_whitelisted.append(trimmed)
            if precheck_non_whitelisted:
                skip_command_processing = True
                sample = _truncate_command_text(precheck_non_whitelisted[0])
                manual_notes.append(
                    _format_action_result(
                        "command-precheck",
                        f"blocked — {len(precheck_non_whitelisted)} command(s) not in whitelist (first: {sample})"
                    )
                )
                manual_notes.append(
                    _format_action_result(
                        "command-precheck-remediation",
                        "remove or replace non-whitelisted commands; allowed prefixes include bash, python3, pnpm, git, gpt-creator apply-block"
                    )
                )
                command_entries = []

        if isinstance(command_entries, list) and command_entries and not skip_command_processing:
            baseline_status = _git_status_porcelain(project_root)
            for raw_cmd in command_entries:
                if not isinstance(raw_cmd, str):
                    continue
                command = _normalize_command_wrapper(raw_cmd)
                if not command:
                    continue
                lower_command = command.lower()
                first_token = command.split()[0] if command.split() else ""
                if first_token == "cat":
                    if '<<' in command:
                        _record_blocked_command('heredoc', command)
                        continue
                if first_token == "python":
                    _record_blocked_command('python-non3', command)
                    continue
                override_exec: Optional[Sequence[str]] = None
                token_list: Optional[List[str]] = None
                if first_token == "gpt-creator":
                    try:
                        token_list = shlex.split(command)
                    except ValueError:
                        token_list = None
                    if token_list and len(token_list) >= 2 and token_list[1] == "apply-block":
                        helper_path = project_root / "scripts" / "python" / "write_block.py"
                        if not helper_path.exists():
                            _record_blocked_command('missing-helper', command)
                            continue
                        override_exec = ['python3', str(helper_path)] + token_list[2:]
                if first_token == "sed":
                    exceeds_window, window_span = _sed_window_exceeds(command)
                    if exceeds_window:
                        _record_blocked_command('sed-window', command)
                        continue
                if first_token == "rg":
                    if _command_targets_docs(command):
                        _record_blocked_command('doc-search', command)
                        continue
                if lower_command.startswith("gpt-creator show-file"):
                    if _command_targets_docs(command):
                        _record_blocked_command('doc-search', command)
                        continue
                    if _show_file_lacks_range(command):
                        _record_blocked_command('show-file-range', command)
                        continue
                if command in seen_commands:
                    _record_blocked_command('duplicate', command)
                    continue
                seen_commands.add(command)
                if COMMAND_BLOCK_PATTERN.search(command):
                    _record_blocked_command('policy', command)
                    continue
                if not COMMAND_WHITELIST_PATTERN.match(command):
                    _record_blocked_command('non-whitelist', command)
                    continue
                if first_token in {"python3"} and ".write_text(" in command:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            "warning — prefer gpt-creator apply-block or write_block.py for file rewrites"
                        )
                    )
                try:
                    if override_exec is not None:
                        proc_cmd = subprocess.run(
                            list(override_exec),
                            capture_output=True,
                            text=True,
                            cwd=str(project_root),
                            timeout=apply_timeout,
                            check=False,
                        )
                    else:
                        proc_cmd = subprocess.run(
                            ['bash', '-lc', command],
                            capture_output=True,
                            text=True,
                            cwd=str(project_root),
                            timeout=apply_timeout,
                            check=False,
                        )
                except Exception as exc:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            f"failed — {exc}"
                        )
                    )
                    continue
                if proc_cmd.stdout:
                    sys.stdout.write(proc_cmd.stdout)
                if proc_cmd.stderr:
                    sys.stderr.write(proc_cmd.stderr)
                if proc_cmd.returncode != 0:
                    note = _format_action_result(
                        _truncate_command_text(command),
                        f"failed — exit {proc_cmd.returncode}; revise before retrying"
                    )
                    summary_parts = []
                    stdout_summary = _summarize_stream("stdout", proc_cmd.stdout)
                    stderr_summary = _summarize_stream("stderr", proc_cmd.stderr)
                    if stdout_summary:
                        summary_parts.append(stdout_summary)
                    if stderr_summary:
                        summary_parts.append(stderr_summary)
                    if summary_parts:
                        manual_notes.append(note + "\n" + '\n'.join(summary_parts))
                    else:
                        manual_notes.append(note)
                else:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            "success"
                        )
                    )
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
                    _format_action_result(
                        "post-command-delta",
                        "warning — commands ran but produced no tracked changes; confirm if additional steps are required"
                    )
                )

        command_diff_after = _git_diff_name_status(project_root)
        command_untracked_after = _git_untracked_files(project_root)
        extra_command_changes: Dict[str, str] = {}
        for path, status in command_diff_after.items():
            if command_diff_before.get(path) != status:
                extra_command_changes[path] = status
        extra_untracked = command_untracked_after.difference(command_untracked_before)

        if extra_command_changes or extra_untracked:
            written_set = set(written)
            patched_set = set(patched)
            for path, status in extra_command_changes.items():
                label = f"{path} (command)"
                if status.startswith('A'):
                    if label not in written_set:
                        written.append(label)
                        written_set.add(label)
                else:
                    if label not in patched_set:
                        patched.append(label)
                        patched_set.add(label)
                try:
                    resolved_path = ensure_within_root(Path(path))
                    if resolved_path.exists() and resolved_path.is_file():
                        change_bytes[path] = resolved_path.stat().st_size
                    else:
                        change_bytes[path] = change_bytes.get(path, 0)
                except Exception:
                    change_bytes[path] = change_bytes.get(path, 0)
            for path in sorted(extra_untracked):
                label = f"{path} (command)"
                if label in written_set:
                    continue
                written.append(label)
                written_set.add(label)
                try:
                    resolved_path = ensure_within_root(Path(path))
                    if resolved_path.exists() and resolved_path.is_file():
                        change_bytes[path] = resolved_path.stat().st_size
                    else:
                        change_bytes[path] = change_bytes.get(path, 0)
                except Exception:
                    change_bytes[path] = change_bytes.get(path, 0)
            actual_changes += len(extra_command_changes) + len(extra_untracked)

        if blocked_command_total:
            for reason, data in blocked_command_counts.items():
                total = int(data.get('total', 0))  # type: ignore[arg-type]
                examples: List[str] = list(data.get('examples', []))  # type: ignore[assignment]
                label = BLOCK_REASON_LABELS.get(reason, reason.replace('-', ' '))
                detail = ''
                if examples:
                    detail = '; '.join(examples)
                extra = max(total - len(examples), 0)
                if extra > 0:
                    detail = (detail + f" (+{extra} more)") if detail else f"+{extra} more"
                summary_text = f"{label}: {total} command(s) blocked"
                if detail:
                    summary_text = f"{summary_text} ({detail})"
                manual_notes.append(
                    _format_action_result(
                        f"blocked-{reason}",
                        summary_text
                    )
                )
            manual_notes.append(
                _format_action_result(
                    "commands-remediation",
                    "replace blocked commands with approved workflows (gpt-creator apply-block, python3 scripts/python/write_block.py, pnpm --filter …) before retrying"
                )
            )

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
                    _format_action_result(
                        "regex-guard",
                        f"warning — pattern {snippet!r} invalid; treated as literal match"
                    )
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
    elif mode == "prompt":
        if len(args) != 8:
            print("prompt requires 8 arguments", file=sys.stderr)
            sys.exit(1)
        sys.argv = [sys.argv[0]] + args
        import hashlib
        import json
        import math
        import os
        import pathlib
        import re
        import sqlite3
        import shutil
        import subprocess
        import tempfile
        import time
        from pathlib import Path
        from typing import Optional, List, Tuple, Set, Dict, Sequence

        from compose_sections import dedupe_and_coalesce, emit_preamble_once, format_sections

        try:
            from prompt_registry import (
                DEFAULT_REGISTRY_SUBDIR,
                ensure_prompt_registry,
                parse_source_env,
            )
        except ModuleNotFoundError:
            DEFAULT_REGISTRY_SUBDIR = Path("src") / "prompts" / "_registry"

            def ensure_prompt_registry(
                project_root: Path,
                *,
                registry_dir: Optional[Path] = None,
                source_dirs=None,
                clean: bool = False,
            ) -> Path:
                return (registry_dir or (project_root / DEFAULT_REGISTRY_SUBDIR)).resolve()

            def parse_source_env(project_root: Path, env_value: str | None):
                return []

        try:
            from wot_publish_prompt import publish_prompt
        except ModuleNotFoundError:
            def publish_prompt(*_args, **_kwargs):
                return None
        try:
            from prompt_safeguard import slim_prompt_markdown  # type: ignore
        except Exception:
            def slim_prompt_markdown(text: str) -> str:
                return text

        FREEFORM_SECTION_MAX_CHARS = int(os.getenv("GC_PROMPT_FREEFORM_MAX_CHARS", "12000") or "12000")
        PROMPT_SOURCE_MAX_BYTES = int(os.getenv("GC_PROMPT_SOURCE_MAX_BYTES", "262144") or "262144")
        INSTRUCTION_PROMPT_RUN_MARKER = "/.gpt-creator/staging/plan/work/"
        INSTRUCTION_PROMPT_CREATE_SDS_MARKER = "/.gpt-creator/staging/plan/create-sds/"
        INSTRUCTION_PROMPT_CREATE_JIRA_TASKS_MARKER = "/.gpt-creator/staging/plan/create-jira-tasks/"
        INSTRUCTION_PROMPT_BINDER_MARKER = "/.gpt-creator/cache/task-binder/"
        PROMPT_SNAPSHOT_MARKER = "/docs/automation/prompts/"
        HEAVY_SECTION_PATTERNS = [
            re.compile(r"^jira tasks$", re.IGNORECASE),
            re.compile(r"^0[\W_]*document control", re.IGNORECASE),
            re.compile(r"^product scope\s*&\s*functional requirements", re.IGNORECASE),
            re.compile(r"^data[, ]+integrations? [&and]+ interfaces", re.IGNORECASE),
            re.compile(r"acceptance\s*\(mem-a\)", re.IGNORECASE),
        ]

        def _atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_file = tempfile.NamedTemporaryFile(
                "w",
                encoding=encoding,
                newline="\n",
                dir=str(target.parent),
                delete=False,
            )
            temp_name = temp_file.name
            try:
                with temp_file:
                    temp_file.write(data)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    try:
                        os.remove(temp_name)
                    except OSError:
                        pass


        def _read_existing_input_digest(meta_path: Path) -> str:
            if not meta_path.exists():
                return ""
            try:
                with meta_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:
                return ""
            if not isinstance(payload, dict):
                return ""
            digest = payload.get("input_digest")
            return digest if isinstance(digest, str) else ""


        def _compute_input_digest(*parts) -> str:
            hasher = hashlib.sha256()
            for part in parts:
                if part is None:
                    continue
                if isinstance(part, bytes):
                    chunk = part
                else:
                    chunk = str(part).encode("utf-8", "replace")
                hasher.update(chunk)
                hasher.update(b"\0")
            return hasher.hexdigest()[:16]


        def _meta_same_as(meta_path: Path, sha_value: str) -> bool:
            if not meta_path.exists():
                return False
            try:
                with meta_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:
                return False
            if not isinstance(payload, dict):
                return False
            existing = payload.get("sha256")
            return isinstance(existing, str) and existing == sha_value


        def _normalize_heading_runtime(value: Optional[str]) -> str:
            if not value:
                return ""
            return re.sub(r"\s+", " ", value.strip()).lower()


        def _lines_to_sections(lines: List[str]) -> List[Tuple[str, str]]:
            sections: List[Tuple[str, str]] = []
            current_title: Optional[str] = None
            current_body: List[str] = []
            for raw_line in lines:
                if raw_line.startswith("## "):
                    if current_title is None and current_body:
                        sections.append(("", "\n".join(current_body)))
                        current_body = []
                    elif current_title is not None:
                        sections.append((current_title, "\n".join(current_body)))
                        current_body = []
                    current_title = raw_line[3:].strip()
                    continue
                current_body.append(raw_line)
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body)))
            elif current_body:
                sections.append(("", "\n".join(current_body)))
            processed: List[Tuple[str, str]] = []
            for title, body in sections:
                heading = title or ""
                body_text = (body or "").strip()
                normalized_heading = _normalize_heading_runtime(heading)
                heavy_section = False
                if heading:
                    for pattern in HEAVY_SECTION_PATTERNS:
                        if pattern.search(heading) or pattern.search(normalized_heading):
                            heavy_section = True
                            break
                if heavy_section:
                    processed.append((heading, "(omitted; consult the documentation catalog for the full content.)"))
                    continue
                if body_text and FREEFORM_SECTION_MAX_CHARS > 0 and len(body_text) > FREEFORM_SECTION_MAX_CHARS:
                    truncated = body_text[:FREEFORM_SECTION_MAX_CHARS].rstrip()
                    body_text = f"{truncated}\n... (section truncated; open source documentation for full details.)"
                processed.append((heading, body_text))
            return processed


        def _resolve_display_path(path_obj: Path) -> Path:
            try:
                return path_obj.resolve()
            except Exception:
                return path_obj


        def _select_display_path(candidates: List[Path]) -> str:
            filtered = [candidate for candidate in candidates if candidate is not None]
            for candidate in filtered:
                resolved = _resolve_display_path(candidate)
                if resolved.exists():
                    return str(resolved)
            if filtered:
                return str(_resolve_display_path(filtered[-1]))
            return ""


        def _first_existing_path(candidates: List[Path]) -> Optional[Path]:
            for candidate in candidates:
                if candidate is None:
                    continue
                try:
                    resolved = candidate.resolve()
                except Exception:
                    resolved = candidate
                if resolved.exists():
                    return resolved
            return None


        def _dedupe_preserve_order(items: Sequence[str]) -> List[str]:
            seen: Set[str] = set()
            result: List[str] = []
            for item in items:
                key = (item or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append(item.strip())
            return result


        def _tokenize_text_for_search(value: str) -> List[str]:
            tokens: List[str] = []
            for match in re.findall(r"[A-Za-z0-9_/.-]{3,}", value or ""):
                token = match.strip("._-/")
                if len(token) < 3:
                    continue
                tokens.append(token.lower())
            return tokens


        def _collect_search_terms(
            task_title: str,
            document_reference: str,
            tags: Sequence[str],
            acceptance_items: Sequence[str],
            story_title: str,
        ) -> List[str]:
            raw_terms: List[str] = []

            def add_term(term: str) -> None:
                if not term:
                    return
                stripped = term.strip()
                if len(stripped) < 3:
                    return
                raw_terms.append(stripped)

            for chunk in re.split(r"[\n,;]+", document_reference or ""):
                add_term(chunk)
            for tag in tags or []:
                add_term(str(tag))
            for line in (acceptance_items or [])[:3]:
                add_term(line)
            add_term(task_title or "")
            add_term(story_title or "")

            for token in _tokenize_text_for_search(task_title):
                add_term(token)
            for token in _tokenize_text_for_search(story_title):
                add_term(token)
            if document_reference:
                for token in _tokenize_text_for_search(document_reference):
                    add_term(token)

            return _dedupe_preserve_order(raw_terms)[:16]


        def _build_fts_query(terms: Sequence[str]) -> str:
            clauses: List[str] = []
            for term in terms:
                safe = term.replace('"', " ").strip()
                if not safe:
                    continue
                clauses.append(f'"{safe}"')
            return " OR ".join(clauses)


        def _run_fts_search(db_path: Optional[Path], terms: Sequence[str], limit: int) -> List[Dict[str, object]]:
            if not db_path or not db_path.exists() or not terms:
                return []
            query = _build_fts_query(terms)
            if not query:
                return []
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(
                        """
                        SELECT doc_id,
                               snippet(documentation_search, 1, '[', ']', ' … ', 32) AS excerpt
                          FROM documentation_search
                         WHERE documentation_search MATCH ?
                         LIMIT ?
                        """,
                        (query, limit),
                    ).fetchall()
            except sqlite3.Error:
                return []

            hits: List[Dict[str, object]] = []
            for row in rows:
                doc_id = (row["doc_id"] or "").strip()
                if not doc_id:
                    continue
                hits.append(
                    {
                        "doc_id": doc_id,
                        "method": "fts",
                        "snippet": (row["excerpt"] or "").strip(),
                    }
                )
            return hits


        def _hash_embedding_vector(text: str, dims: int) -> List[float]:
            digest = hashlib.sha256(text.encode("utf-8", "replace")).digest()
            values: List[float] = []
            seed = digest
            while len(values) < dims:
                for idx in range(0, len(seed), 4):
                    if len(values) >= dims:
                        break
                    chunk = seed[idx : idx + 4]
                    if len(chunk) < 4:
                        chunk = chunk.ljust(4, b"\0")
                    val = int.from_bytes(chunk, "big", signed=False)
                    values.append((val % 1000) / 1000.0)
                seed = hashlib.sha256(seed).digest()
            norm = math.sqrt(sum(val * val for val in values)) or 1.0
            return [val / norm for val in values]


        def _run_vector_search(
            vector_index_path: Optional[Path],
            terms: Sequence[str],
            limit: int,
            exclude: Set[str],
        ) -> List[Dict[str, object]]:
            if not vector_index_path or not vector_index_path.exists() or not terms or limit <= 0:
                return []
            query_text = " ".join(terms).strip()
            if not query_text:
                return []
            try:
                conn = sqlite3.connect(str(vector_index_path))
                conn.row_factory = sqlite3.Row
            except sqlite3.Error:
                return []

            hits: List[Tuple[float, Dict[str, object]]] = []
            try:
                rows = conn.execute(
                    "SELECT doc_id, section_id, surface, vector_json, dims FROM vectors"
                ).fetchall()
            except sqlite3.Error:
                conn.close()
                return []
            finally:
                conn.close()

            for row in rows:
                doc_id = (row["doc_id"] or "").strip()
                if not doc_id or doc_id in exclude:
                    continue
                vector_json = row["vector_json"]
                dims = row["dims"] or 0
                try:
                    vector = json.loads(vector_json or "[]")
                except Exception:
                    continue
                if dims <= 0:
                    dims = len(vector)
                if dims <= 0 or len(vector) != dims:
                    continue
                query_vector = _hash_embedding_vector(query_text, dims)
                if len(query_vector) != len(vector):
                    continue
                score = float(sum(a * b for a, b in zip(query_vector, vector)))
                hits.append(
                    (
                        score,
                        {
                            "doc_id": doc_id,
                            "method": "vector",
                            "score": score,
                            "surface": row["surface"],
                        },
                    )
                )

            hits.sort(key=lambda item: item[0], reverse=True)
            results: List[Dict[str, object]] = []
            for score, payload in hits:
                if len(results) >= limit:
                    break
                doc_id = payload.get("doc_id")
                if not doc_id or doc_id in exclude:
                    continue
                results.append(payload)
                exclude.add(doc_id)
            return results


        def _run_ripgrep_search(
            project_root: Optional[Path],
            terms: Sequence[str],
            limit: int,
            exclude: Set[str],
        ) -> List[Dict[str, object]]:
            if not project_root or not project_root.exists() or limit <= 0:
                return []
            if shutil.which("rg") is None:
                return []
            query_term = next((term for term in terms if len(term) >= 3), "")
            if not query_term:
                return []
            docs_dir = project_root / "docs"
            if not docs_dir.exists():
                return []
            cmd = [
                "rg",
                "--with-filename",
                "--no-heading",
                "--line-number",
                "--max-count",
                "2",
                "--max-filesize",
                "512K",
                query_term,
                str(docs_dir),
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return []

            if proc.returncode not in (0, 1):
                return []

            hits: List[Dict[str, object]] = []
            for line in proc.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                path_str, line_number, snippet = parts
                candidate_path = Path(path_str).resolve()
                entry = _build_doc_entry(candidate_path)
                if not entry:
                    continue
                doc_id = entry.get("doc_id")
                if not doc_id or doc_id in exclude:
                    continue
                hits.append(
                    {
                        "doc_id": doc_id,
                        "method": "ripgrep",
                        "line": line_number,
                        "snippet": snippet.strip(),
                    }
                )
                exclude.add(doc_id)
                if len(hits) >= limit:
                    break
            return hits


        DB_PATH, STORY_SLUG, TASK_INDEX, PROMPT_PATH, CONTEXT_TAIL_PATH, MODEL_NAME, PROJECT_ROOT, STAGING_DIR = sys.argv[1:9]
        TASK_INDEX = int(TASK_INDEX)


        def _build_doc_entry(path_obj: Path):
            try:
                stat = path_obj.stat()
            except OSError:
                return None
            mtime_ns = getattr(stat, "st_mtime_ns", None)
            if mtime_ns is None:
                mtime_ns = int(stat.st_mtime * 1_000_000_000)
            size = int(stat.st_size)
            try:
                resolved_str = str(path_obj.resolve())
            except Exception:
                resolved_str = str(path_obj)
            doc_id = "DOC-" + hashlib.sha256(resolved_str.encode("utf-8", "replace")).hexdigest()[:8].upper()
            existing = documents_store.get(doc_id)
            if isinstance(existing, dict):
                try:
                    existing_mtime = int(existing.get("mtime_ns", 0))
                except Exception:
                    existing_mtime = -1
                try:
                    existing_size = int(existing.get("size", -1))
                except Exception:
                    existing_size = -1
                if existing_mtime == int(mtime_ns) and existing_size == size:
                    entry = existing.copy()
                    entry["doc_id"] = doc_id
                    entry["rel_path"] = entry.get("rel_path") or _relative_path_for_prompt(path_obj)
                    return entry
            headings = []
            try:
                with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
                    for lineno, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        title = None
                        level = None
                        suffix = path_obj.suffix.lower()
                        if suffix in {".md", ".markdown"}:
                            match = re.match(r"^(#{1,4})\\s+(.*)$", stripped)
                            if match:
                                level = len(match.group(1))
                                title = match.group(2).strip()
                        if title is None:
                            match = re.match(r"^((?:\\d+\\.)+\\d*|\\d+|[A-Z][.)]|[IVXLCM]+\\.)\\s+(.*)$", stripped)
                            if match:
                                title = match.group(2).strip()
                                level = level or 2
                        if title:
                            headings.append({
                                "title": title,
                                "line": lineno,
                                "level": int(level or 1),
                            })
                        if len(headings) >= 80:
                            break
            except Exception:
                headings = []
            entry = {
                "doc_id": doc_id,
                "path": str(path_obj),
                "rel_path": _relative_path_for_prompt(path_obj),
                "mtime_ns": int(mtime_ns),
                "size": size,
                "headings": headings,
            }
            documents_store[doc_id] = {
                key: value for key, value in entry.items() if key != "doc_id"
            }
            doc_catalog_changed["value"] = True
            return entry


        def _load_doc_snippet(path_obj: Path, doc_entry: dict) -> str:
            doc_id = doc_entry.get("doc_id")
            if not doc_id:
                return ""
            cached = snippet_store.get(doc_id)
            current_mtime = doc_entry.get("mtime_ns")
            if isinstance(cached, dict) and cached.get("mtime_ns") == current_mtime:
                return cached.get("preview") or ""
            preview_lines: list[str] = []
            try:
                with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
                    for idx, line in enumerate(handle):
                        if idx >= 80:
                            break
                        stripped = line.strip()
                        if stripped:
                            preview_lines.append(stripped)
            except Exception:
                preview_lines = []
            snippet_text = _condense_snippet(preview_lines, "", max_chars=360)
            snippet_store[doc_id] = {"preview": snippet_text, "mtime_ns": current_mtime}
            doc_catalog_changed["value"] = True
            return snippet_text

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cwd_path = Path.cwd()
        project_root_path = cwd_path
        if PROJECT_ROOT:
            project_root_candidate = Path(PROJECT_ROOT)
            if not project_root_candidate.is_absolute():
                project_root_candidate = cwd_path / project_root_candidate
            try:
                project_root_path = project_root_candidate.resolve()
            except Exception:
                project_root_path = project_root_candidate

        staging_root: Optional[Path] = None
        if STAGING_DIR:
            staging_candidate = Path(STAGING_DIR)
            if not staging_candidate.is_absolute():
                staging_candidate = project_root_path / staging_candidate
            try:
                staging_root = staging_candidate.resolve()
            except Exception:
                staging_root = staging_candidate
        else:
            staging_root = project_root_path / ".gpt-creator" / "staging"

        plan_instruction_dir: Optional[Path] = None
        if staging_root:
            plan_candidate = staging_root / "plan"
            if plan_candidate.exists():
                plan_instruction_dir = plan_candidate

        registry_env_raw = os.getenv("GC_PROMPT_REGISTRY_DIR", "").strip()
        source_env_raw = os.getenv("GC_PROMPT_SOURCE_DIRS", "").strip()
        if registry_env_raw:
            registry_candidate = Path(registry_env_raw)
            if not registry_candidate.is_absolute():
                registry_candidate = project_root_path / registry_candidate
        else:
            registry_candidate = project_root_path / DEFAULT_REGISTRY_SUBDIR

        source_roots = parse_source_env(project_root_path, source_env_raw)
        try:
            ensure_prompt_registry(
                project_root_path,
                registry_dir=registry_candidate,
                source_dirs=source_roots,
                clean=os.getenv("GC_PROMPT_REGISTRY_REFRESH", "").strip().lower() in {"1", "true", "yes", "force"},
            )
        except Exception:
            registry_candidate = None

        instruction_prompts: List[Tuple[str, List[str]]] = []

        story_row = cur.execute(
            'SELECT story_id, story_title, epic_key, epic_title, sequence FROM stories WHERE story_slug = ?',
            (STORY_SLUG,)
        ).fetchone()
        if story_row is None:
            raise SystemExit(f"Story slug not found: {STORY_SLUG}")

        task_rows = cur.execute(
            'SELECT task_id, title, description, estimate, assignees_json, tags_json, acceptance_json, dependencies_json, '
            'tags_text, story_points, dependencies_text, assignee_text, document_reference, idempotency, rate_limits, rbac, '
            'messaging_workflows, performance_targets, observability, acceptance_text, endpoints, sample_create_request, '
            'sample_create_response, user_story_ref_id, epic_ref_id, status, last_progress_at, last_progress_run, '
            'last_log_path, last_output_path, last_prompt_path, last_notes_json, last_commands_json, last_apply_status, '
            'last_changes_applied, last_tokens_total, last_duration_seconds '
            'FROM tasks WHERE story_slug = ? ORDER BY position ASC',
            (STORY_SLUG,)
        ).fetchall()
        conn.close()

        if TASK_INDEX < 0 or TASK_INDEX >= len(task_rows):
            raise SystemExit(2)

        task = task_rows[TASK_INDEX]
        documentation_db_path = os.getenv("GC_DOCUMENTATION_DB_PATH", "").strip()
        doc_catalog_env_raw = os.getenv("GC_DOC_CATALOG_PATH", "").strip()
        doc_catalog_helper = (
            os.getenv("GC_DOC_CATALOG_PY", "").strip()
            or os.getenv("GC_DOC_CATALOG_HELPER", "").strip()
            or os.getenv("doc_catalog", "").strip()
        )
        doc_registry_helper = (
            os.getenv("GC_DOC_REGISTRY_PY", "").strip()
            or os.getenv("GC_DOC_REGISTRY_HELPER", "").strip()
            or os.getenv("doc_registry", "").strip()
        )
        doc_indexer_helper = (
            os.getenv("GC_DOC_INDEXER_PY", "").strip()
            or os.getenv("GC_DOC_INDEXER_HELPER", "").strip()
            or os.getenv("doc_indexer", "").strip()
        )
        has_doc_catalog_helper = bool(doc_catalog_helper)
        has_doc_registry_helper = bool(doc_registry_helper)
        has_doc_indexer_helper = bool(doc_indexer_helper)

        doc_library_candidates: List[Path] = []
        doc_index_candidates: List[Path] = []
        doc_catalog_candidates: List[Path] = []

        fallback_catalog_literal = ".gpt-creator/staging/plan/work/doc-catalog.json"

        if doc_catalog_env_raw:
            doc_catalog_candidates.append(Path(doc_catalog_env_raw))

        if staging_root:
            doc_library_candidates.extend([
                staging_root / "doc-library.md",
                staging_root / "plan" / "docs" / "doc-library.md",
            ])
            doc_index_candidates.extend([
                staging_root / "doc-index.md",
                staging_root / "plan" / "docs" / "doc-index.md",
            ])
            doc_catalog_candidates.append(staging_root / "plan" / "work" / "doc-catalog.json")

        doc_library_candidates.append(project_root_path / "docs" / "doc-library.md")
        doc_index_candidates.append(project_root_path / "docs" / "doc-index.md")
        if not doc_catalog_candidates:
            doc_catalog_candidates.append(project_root_path / ".gpt-creator" / "staging" / "plan" / "work" / "doc-catalog.json")

        doc_library_path_str = _select_display_path(doc_library_candidates)
        doc_index_path_str = _select_display_path(doc_index_candidates)
        doc_catalog_path_str = _select_display_path(doc_catalog_candidates)
        doc_catalog_pointer = doc_catalog_path_str or fallback_catalog_literal
        doc_library_shim_str = _select_display_path([project_root_path / "docs" / "doc-library.md"])
        doc_index_shim_str = _select_display_path([project_root_path / "docs" / "doc-index.md"])

        documentation_db_display = _select_display_path([Path(documentation_db_path)]) if documentation_db_path else ""

        vector_index_path = None
        vector_index_path_str = ""
        vector_index_env_raw = os.getenv("GC_DOC_VECTOR_INDEX_PATH", "").strip()
        vector_index_candidates: List[Path] = []
        if vector_index_env_raw:
            try:
                vector_index_candidates.append(Path(vector_index_env_raw))
            except Exception:
                pass
        if documentation_db_path:
            db_path_obj = Path(documentation_db_path)
            resolved_db = _resolve_display_path(db_path_obj)
            vector_index_candidates.append(resolved_db.parent / "documentation-vector-index.sqlite")
            vector_index_candidates.append(db_path_obj.parent / "documentation-vector-index.sqlite")
        if vector_index_candidates:
            vector_index_path = _first_existing_path(vector_index_candidates)
            vector_index_path_str = _select_display_path(vector_index_candidates)

        catalog_reference_docs: List[str] = []
        for filename in ("document-catalog-indexing.md", "document-catalog-metadata.md", "document-catalog-pipeline.md"):
            doc_candidate = project_root_path / "docs" / filename
            doc_candidate_str = _select_display_path([doc_candidate])
            if doc_candidate_str:
                catalog_reference_docs.append(f"`{doc_candidate_str}`")

        documentation_asset_lines: List[str] = []
        if doc_library_path_str:
            library_line = (
                f"- Library overview: `{doc_library_path_str}` — use the documentation catalog search/show helpers "
                "to inspect specific entries instead of opening the file directly."
            )
            if doc_library_shim_str and doc_library_shim_str != doc_library_path_str:
                library_line += f" Shim fallback lives at `{doc_library_shim_str}`."
            documentation_asset_lines.append(library_line)
        elif doc_library_shim_str:
            documentation_asset_lines.append(
                f"- Library overview (shim): `{doc_library_shim_str}` — rely on the documentation catalog search/show helpers rather than reading the file directly."
            )

        if doc_index_path_str:
            index_line = f"- Headings index: `{doc_index_path_str}` lists section anchors so you can jump straight to the right slice."
            if doc_index_shim_str and doc_index_shim_str != doc_index_path_str:
                index_line += f" Shim fallback lives at `{doc_index_shim_str}`."
            documentation_asset_lines.append(index_line)
        elif doc_index_shim_str:
            documentation_asset_lines.append(
                f"- Headings index (shim): `{doc_index_shim_str}` lists section anchors so you can jump straight to the right slice."
            )

        if doc_catalog_path_str:
            documentation_asset_lines.append(
                f"- JSON catalog (doc/snippet map) at `{doc_catalog_path_str}` keeps scripted lookups fast while prompts stay lean."
            )
            documentation_asset_lines.append(
                "- Path is also exported as `$GC_DOC_CATALOG_PATH`; quick listing: `python3 -c \"import json, os; data=json.load(open(os.environ['GC_DOC_CATALOG_PATH'])); print('\\n'.join(sorted(data.get('documents', {}))))\"`"
            )
        else:
            documentation_asset_lines.append(
                f"- JSON catalog (doc/snippet map) at `{doc_catalog_pointer}` keeps scripted lookups fast while prompts stay lean."
            )

        if catalog_reference_docs:
            documentation_asset_lines.append(
                f"- Deep-dive docs: {', '.join(catalog_reference_docs)} explain indexing, metadata, and pipelines powering these caches."
            )

        def parse_json_list(value):
            if not value:
                return []
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
            return []

        def parse_int_field(value):
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                try:
                    return int(float(str(value).strip()))
                except Exception:
                    return None

        def format_duration(seconds_value):
            seconds = parse_int_field(seconds_value)
            if seconds is None or seconds <= 0:
                return ""
            minutes, sec = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            parts = []
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if sec or not parts:
                parts.append(f"{sec}s")
            return " ".join(parts)


        DEFAULT_WORK_PROMPT = """## work-on-tasks Prompt
- Load the task details and acceptance criteria from the context section.
- Consult the documentation catalog or search hits before modifying files.
- Outline a concise plan (≤3 bullets focused on actions), execute the required edits, and capture verification steps with clear pass/fail decisions.
- Apply changes by editing files directly via shell commands (no diff/patch output).
- Record follow-up actions when blockers remain.
"""

        def clamp_text(text: str, limit: int) -> str:
            if limit <= 0 or not text:
                return text
            if len(text) <= limit:
                return text
            return text[: max(0, limit - 1)].rstrip() + "…"


        def _instruction_prompt_is_excluded(path_obj: Path, plan_dir: Optional[Path], project_root: Optional[Path]) -> bool:
            try:
                resolved = path_obj.resolve()
            except OSError:
                resolved = path_obj
            candidate_str = str(resolved).replace("\\", "/")
            if "/prompts/" not in candidate_str:
                return False
            if INSTRUCTION_PROMPT_RUN_MARKER in candidate_str and "/runs/" in candidate_str:
                return True
            if INSTRUCTION_PROMPT_CREATE_SDS_MARKER in candidate_str:
                return True
            if INSTRUCTION_PROMPT_CREATE_JIRA_TASKS_MARKER in candidate_str:
                return True
            if INSTRUCTION_PROMPT_BINDER_MARKER in candidate_str:
                return True
            if PROMPT_SNAPSHOT_MARKER in candidate_str:
                return True
            if plan_dir:
                try:
                    rel_plan = resolved.relative_to(plan_dir.resolve())
                    rel_parts = [part.lower() for part in rel_plan.parts]
                    if "runs" in rel_parts and "prompts" in rel_parts:
                        return True
                except Exception:
                    pass
            if project_root:
                try:
                    rel_project = resolved.relative_to(project_root.resolve())
                    rel_parts = [part.lower() for part in rel_project.parts]
                    if rel_parts[:3] == [".gpt-creator", "cache", "task-binder"]:
                        return True
                except Exception:
                    pass
            return False


        def collect_instruction_prompts(
            plan_dir: Optional[Path],
            project_root: Optional[Path],
            registry_dir: Optional[Path],
        ) -> List[Tuple[str, List[str]]]:
            prompts: List[Tuple[str, List[str]]] = []
            search_roots: List[Path] = []
            if registry_dir and registry_dir.exists():
                search_roots.append(registry_dir)
            if plan_dir and plan_dir.exists():
                search_roots.append(plan_dir)
            if not search_roots and project_root:
                for relative in ("src/prompts", "docs/prompts", ".gpt-creator/prompts"):
                    candidate = project_root / relative
                    if candidate.exists():
                        search_roots.append(candidate)
            if not search_roots:
                return prompts

            seen: Set[Path] = set()
            for base_dir in search_roots:
                try:
                    iterator = sorted(base_dir.rglob("*prompt.md"))
                except (OSError, RuntimeError):
                    continue
                for candidate in iterator:
                    try:
                        resolved = candidate.resolve()
                    except OSError:
                        resolved = candidate
                    if resolved in seen or not candidate.is_file():
                        continue
                    if _instruction_prompt_is_excluded(candidate, plan_dir, project_root):
                        continue
                    try:
                        size_bytes = candidate.stat().st_size
                    except OSError:
                        size_bytes = 0
                    if PROMPT_SOURCE_MAX_BYTES and size_bytes > PROMPT_SOURCE_MAX_BYTES:
                        continue
                    seen.add(resolved)
                    try:
                        raw = candidate.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        raw = candidate.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    text = raw.strip()
                    if not text:
                        continue
                    rel_repr = candidate.name
                    if project_root:
                        try:
                            rel_repr = str(candidate.relative_to(project_root)).replace("\\", "/")
                        except ValueError:
                            pass
                    if rel_repr == candidate.name and plan_dir:
                        try:
                            rel_repr = str(candidate.relative_to(plan_dir)).replace("\\", "/")
                        except ValueError:
                            rel_repr = candidate.name
                    prompts.append((rel_repr, text.splitlines()))
            return prompts

        instruction_prompts = collect_instruction_prompts(plan_instruction_dir, project_root_path, registry_candidate)

        if not instruction_prompts:
            fallback_prompt_paths = [
                project_root_path / "src" / "prompts" / "iterate" / "work_on_tasks.prompt.md",
                project_root_path / "docs" / "prompts" / "work_on_tasks.prompt.md",
            ]
            for prompt_path in fallback_prompt_paths:
                if not prompt_path.exists():
                    continue
                try:
                    prompt_text = prompt_path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if prompt_text.strip():
                    try:
                        rel_label = str(prompt_path.relative_to(project_root_path))
                    except ValueError:
                        rel_label = prompt_path.name
                    instruction_prompts = [(rel_label, prompt_text.strip().splitlines())]
                    break
            else:
                instruction_prompts = [("builtin/work_on_tasks.prompt.md", DEFAULT_WORK_PROMPT.strip().splitlines())]

        def build_log_excerpt(path_obj: Path, max_lines: int = 40, max_chars: int = 160) -> list[str]:
            try:
                raw = path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return [f"(unable to read log: {exc})"]
            lines_local = raw.splitlines()
            if not lines_local:
                return []
            excerpt = []
            if len(lines_local) > max_lines:
                trimmed = len(lines_local) - max_lines
                excerpt.append(f"... trimmed {trimmed} earlier line(s) ...")
                subset = lines_local[-max_lines:]
            else:
                subset = lines_local
            for line in subset:
                excerpt.append(clamp_text(line, max_chars))
            return excerpt

        def clean(value: str) -> str:
            return (value or '').strip()


        def project_display_name(root: str) -> str:
            if not root:
                return "Project"
            try:
                name = Path(root).name.strip()
            except Exception:
                name = ""
            if not name:
                return "Project"
            tokens = [token for token in re.split(r'[^A-Za-z0-9]+', name) if token]
            if not tokens:
                return "Project"
            words = []
            for token in tokens:
                if len(token) <= 3:
                    words.append(token.upper())
                elif token.isupper():
                    words.append(token)
                else:
                    words.append(token.capitalize())
            return ' '.join(words) or "Project"

        assignees = parse_json_list(task['assignees_json'])
        tags = parse_json_list(task['tags_json'])
        acceptance = parse_json_list(task['acceptance_json'])
        dependencies = parse_json_list(task['dependencies_json'])

        description = clean(task['description'])
        if description:
            description_lines = description.splitlines()
        else:
            description_lines = []

        tags_text = clean(task['tags_text'])
        story_points = clean(task['story_points'])
        dependencies_text = clean(task['dependencies_text'])
        assignee_text = clean(task['assignee_text'])
        document_reference = clean(task['document_reference'])
        idempotency_text = clean(task['idempotency'])
        rate_limits = clean(task['rate_limits'])
        rbac_text = clean(task['rbac'])
        messaging_workflows = clean(task['messaging_workflows'])
        performance_targets = clean(task['performance_targets'])
        observability_text = clean(task['observability'])
        acceptance_text_extra = (task['acceptance_text'] or '').strip() if task['acceptance_text'] else ''
        endpoints_text = (task['endpoints'] or '').strip() if task['endpoints'] else ''
        sample_create_request = (task['sample_create_request'] or '').strip() if task['sample_create_request'] else ''
        sample_create_response = (task['sample_create_response'] or '').strip() if task['sample_create_response'] else ''
        user_story_ref_id = clean(task['user_story_ref_id'])
        epic_ref_id = clean(task['epic_ref_id'])

        task_status = clean(task['status'])
        last_progress_at = clean(task['last_progress_at'])
        last_progress_run = clean(task['last_progress_run'])
        last_apply_status = clean(task['last_apply_status'])
        last_log_path = clean(task['last_log_path'])
        last_output_path = clean(task['last_output_path'])
        last_prompt_path = clean(task['last_prompt_path'])
        last_changes_applied = parse_int_field(task['last_changes_applied']) or 0
        last_tokens_total = parse_int_field(task['last_tokens_total'])
        last_duration_seconds = parse_int_field(task['last_duration_seconds'])
        last_notes = parse_json_list(task['last_notes_json'])
        last_commands = parse_json_list(task['last_commands_json'])

        project_display = project_display_name(PROJECT_ROOT)
        repo_path = PROJECT_ROOT or '.'
        try:
            prompt_dir = Path(PROMPT_PATH).resolve().parent
        except Exception:
            prompt_dir = Path(".").resolve()

        sample_limit_env = os.getenv("GC_PROMPT_SAMPLE_LINES", "").strip()
        try:
            sample_limit = int(sample_limit_env) if sample_limit_env else 80
        except ValueError:
            sample_limit = 80
        if sample_limit < 0:
            sample_limit = 0

        compact_mode = os.getenv("GC_PROMPT_COMPACT", "").strip().lower() not in {"", "0", "false"}

        lines = []
        lines.append(f"# You are Codex (model: {MODEL_NAME})")
        lines.append("")
        lines.append(f"You are assisting the {project_display} delivery team. Implement the task precisely using the repository at: {repo_path}")
        lines.append("")
        doc_helpers_available = bool(
            documentation_db_path
            and has_doc_catalog_helper
            and has_doc_registry_helper
            and has_doc_indexer_helper
        )
        if doc_helpers_available:
            lines.append("## Documentation Assets (local helpers)")
            lines.append("")
            catalog_line = "- Catalog DB: $GC_DOCUMENTATION_DB_PATH"
            if documentation_db_display:
                catalog_line += f" → `{documentation_db_display}`"
            lines.append(catalog_line)
            vector_line = "- Vector/semantic index: $GC_DOC_VECTOR_INDEX_PATH"
            if vector_index_path_str:
                vector_line += f" → `{vector_index_path_str}`"
            else:
                vector_line += " (generate via documentation scan when semantic lookup is required)"
            lines.append(vector_line)
            lines.append("")
            lines.append("## Documentation Catalog and Commands")
            lines.append("We maintain a documentation catalog SQLite database and related assets to help you locate relevant information efficiently. Prefer querying the catalog instead of searching files directly.")
            lines.append("Catalog structure and key tables:")
            lines.append(f"- Example query: sqlite3 \"$GC_DOCUMENTATION_DB_PATH\" \\")
            lines.append('  "SELECT doc_id,surface FROM documentation_search WHERE documentation_search MATCH \'lockout\' LIMIT 5;"')
            lines.append("- `documentation`: one row per document with metadata (doc_type, rel_path, title, tags_json, metadata_json, status, change_count).")
            lines.append("- `documentation_changes`: append-only audit history keyed by doc_id (change_type, sha256, description, context, recorded_at).")
            lines.append("- `documentation_sections`: hierarchical structure per document (section_id, parent_section_id, order_index, anchor, byte/token spans, summary).")
            lines.append("- `documentation_excerpts`: curated snippets for prompts (content, justification, token_length, optional embedding_id).")
            lines.append("- `documentation_summaries`: cached short/long summaries (summary_short/long, key_points_json, keywords_json, embedding_id).")
            lines.append("- `documentation_index_state`: surfaces pending semantic rebuild (status, indexed_at, usage_score, metadata_json).")
            lines.append("- `documentation_search` (FTS5): searchable text (surface, content) with doc_id/section_id; use MATCH with snippet() or ORDER BY bm25().")
            lines.append('- Schema quick look: sqlite3 "$GC_DOCUMENTATION_DB_PATH" ".tables" or ".schema documentation"')
            lines.append("- Vector DB ($GC_DOCUMENTATION_INDEX_PATH) table `vectors`: embeddings per surface (embedding_id PK, doc_id, section_id, vector_json, dims, metadata_json, updated_at).")
            lines.append("Common catalog commands:")
            lines.append('- List recent docs: python3 "$GC_DOC_CATALOG_PY" list --db "$GC_DOCUMENTATION_DB_PATH" --limit 10')
            lines.append('- Full-text search: python3 "$GC_DOC_CATALOG_PY" search --db "$GC_DOCUMENTATION_DB_PATH" --query "lockout" --limit 15')
            lines.append('- Show document by id: python3 "$GC_DOC_CATALOG_PY" show --db "$GC_DOCUMENTATION_DB_PATH" --doc-id <id>')
            lines.append('- Rebuild semantic index: python3 "$GC_DOC_INDEXER_PY" rebuild --db "$GC_DOCUMENTATION_DB_PATH" --out "$GC_DOC_VECTOR_INDEX_PATH"')
            lines.append('- Register or sync discovery TSV: python3 "$GC_DOC_REGISTRY_PY" register --db "$GC_DOCUMENTATION_DB_PATH" --tsv ".gpt-creator/manifests/<latest>.tsv"')

        else:
            lines.append("## Documentation Assets (sqlite3 fallback)")
            lines.append("")
            catalog_line = "- Catalog DB: $GC_DOCUMENTATION_DB_PATH"
            if documentation_db_display:
                catalog_line += f" → `{documentation_db_display}`"
            else:
                catalog_line += " (run `gpt-creator scan` if the catalog needs to be regenerated)"
            lines.append(catalog_line)
            vector_line = "- Vector/semantic index: $GC_DOC_VECTOR_INDEX_PATH"
            if vector_index_path_str:
                vector_line += f" → `{vector_index_path_str}`"
            lines.append(vector_line)
            lines.append("- FTS example:")
            lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \\')
            lines.append('    "SELECT doc_id, surface FROM documentation_search WHERE documentation_search MATCH \'lockout\' LIMIT 15;"')
            lines.append("- Latest changes:")
            lines.append('  sqlite3 "$GC_DOCUMENTATION_DB_PATH" \\')
            lines.append('    "SELECT doc_id, path, changed_at FROM documentation_changes ORDER BY changed_at DESC LIMIT 10;"')

        lines.append("")

        if documentation_asset_lines:
            lines.extend(documentation_asset_lines)
        else:
            lines.append("- (No documentation assets detected; ensure doc-library and doc-index are generated before editing.)")

        lines.append("")
        lines.append("## Story")

        epic_id = clean(story_row['epic_key'])
        epic_title = clean(story_row['epic_title'])
        story_id = clean(story_row['story_id'])
        story_title = clean(story_row['story_title'])
        sequence = story_row['sequence']

        if compact_mode:
            story_label = story_id or STORY_SLUG
            if story_label and story_title:
                summary = f"- {story_label} — {story_title}"
            elif story_label:
                summary = f"- {story_label}"
            elif story_title:
                summary = f"- {story_title}"
            else:
                summary = "- Story details unavailable"
            extras = []
            if epic_id or epic_title:
                epic_bits = [bit for bit in [epic_id, epic_title] if bit]
                extras.append("epic " + " — ".join(epic_bits))
            if sequence:
                extras.append(f"order {sequence}")
            if extras:
                summary += f" ({'; '.join(extras)})"
            lines.append(summary)
        else:
            if epic_id or epic_title:
                parts = [part for part in [epic_id, epic_title] if part]
                lines.append("- Epic: " + " — ".join(parts))
            if story_id or story_title:
                parts = [part for part in [story_id, story_title] if part]
                lines.append("- Story: " + " — ".join(parts))
            if sequence:
                lines.append(f"- Story order: {sequence}")

        lines.append("")
        lines.append("## Task")
        task_id = clean(task['task_id'])
        task_title = clean(task['title'])
        estimate = clean(task['estimate'])

        if compact_mode:
            task_label = task_id or f"Task {TASK_INDEX + 1}"
            summary = f"- {task_label}"
            if task_title:
                summary += f" — {task_title}"
            lines.append(summary)
            meta_bits = []
            if estimate:
                meta_bits.append(f"estimate {estimate}")
            if story_points and story_points != estimate:
                meta_bits.append(f"story points {story_points}")
            if assignees or assignee_text:
                assigned = ", ".join(assignees) if assignees else assignee_text
                meta_bits.append(f"assignees {assigned}")
            if tags:
                tags_summary = ", ".join(tags[:3])
                if len(tags) > 3:
                    tags_summary += "…"
                meta_bits.append(f"tags {tags_summary}")
            elif tags_text:
                meta_bits.append(f"tags {tags_text}")
            if document_reference:
                meta_bits.append(f"doc {document_reference}")
            if rate_limits:
                meta_bits.append(f"rate limits {rate_limits}")
            if meta_bits:
                lines.append(f"- Details: {'; '.join(meta_bits)}")
        else:
            if task_id:
                lines.append(f"- Task ID: {task_id}")
            if task_title:
                lines.append(f"- Title: {task_title}")
            if estimate:
                lines.append(f"- Estimate: {estimate}")
            if assignees:
                lines.append("- Assignees: " + ", ".join(assignees))
            elif assignee_text:
                lines.append(f"- Assignee: {assignee_text}")
            if tags:
                lines.append("- Tags: " + ", ".join(tags))
            elif tags_text:
                lines.append(f"- Tags: {tags_text}")
            if story_points and story_points != estimate:
                lines.append(f"- Story points: {story_points}")
            elif story_points and not estimate:
                lines.append(f"- Story points: {story_points}")
            if document_reference:
                lines.append(f"- Document reference: {document_reference}")
            if idempotency_text:
                lines.append(f"- Idempotency: {idempotency_text}")
            if rate_limits:
                lines.append(f"- Rate limits: {rate_limits}")
            if rbac_text:
                lines.append(f"- RBAC: {rbac_text}")
            if messaging_workflows:
                lines.append(f"- Messaging & workflows: {messaging_workflows}")
            if performance_targets:
                lines.append(f"- Performance targets: {performance_targets}")
            if observability_text:
                lines.append(f"- Observability: {observability_text}")
            if user_story_ref_id and user_story_ref_id.lower() != story_id.lower():
                lines.append(f"- User story reference ID: {user_story_ref_id}")
            if epic_ref_id and epic_ref_id.lower() != epic_id.lower():
                lines.append(f"- Epic reference ID: {epic_ref_id}")

        lines.append("")
        lines.append("### Description")
        if description_lines:
            lines.extend(description_lines)
        else:
            lines.append("(No additional description provided.)")

        if acceptance:
            lines.append("")
            lines.append("### Acceptance Criteria")
            for item in acceptance:
                lines.append(f"- {item}")
        elif acceptance_text_extra:
            lines.append("")
            lines.append("### Acceptance Criteria")
            lines.extend(acceptance_text_extra.splitlines())

        if dependencies:
            lines.append("")
            lines.append("### Dependencies")
            for dep in dependencies:
                lines.append(f"- {dep}")
        elif dependencies_text:
            lines.append("")
            lines.append("### Dependencies")
            lines.extend(dependencies_text.splitlines())

        if endpoints_text:
            lines.append("")
            lines.append("### Endpoints")
            lines.extend(endpoints_text.splitlines())

        doc_snippets_enabled = os.getenv("GC_PROMPT_DOC_SNIPPETS", "").strip().lower() not in {"", "0", "false"}

        has_previous_attempt = any([
            last_progress_at,
            last_apply_status,
            last_log_path,
            last_output_path,
            last_notes,
            last_commands,
        ])

        if has_previous_attempt:
            def resolve_history_path(raw_path: str) -> Optional[Path]:
                if not raw_path:
                    return None
                candidate = Path(raw_path)
                if candidate.is_absolute():
                    candidates = [candidate]
                else:
                    candidates = []
                    for base in [prompt_dir, project_root_path, staging_root]:
                        if not base:
                            continue
                        base_path = base if isinstance(base, Path) else Path(base)
                        candidates.append(base_path / candidate)
                    candidates.append(candidate)
                for option in candidates:
                    try:
                        resolved = option.resolve()
                    except Exception:
                        resolved = option
                    if resolved.exists():
                        return resolved
                return candidates[0] if candidates else candidate

            def render_relative(path_obj: Path) -> str:
                for root in filter(None, [project_root_path, staging_root]):
                    if isinstance(root, Path):
                        try:
                            return str(path_obj.relative_to(root))
                        except ValueError:
                            continue
                return str(path_obj)

            lines.append("")
            lines.append("### Previous Attempt Summary")

            status_bits = []
            if task_status:
                status_bits.append(task_status)
            if last_apply_status:
                status_bits.append(f"apply:{last_apply_status}")
            if last_changes_applied:
                status_bits.append(f"changes:{last_changes_applied}")
            if status_bits:
                lines.append(f"- Status: {', '.join(status_bits)}")

            metrics_bits = []
            if last_progress_at:
                metrics_bits.append(f"at {last_progress_at}")
            if last_progress_run:
                metrics_bits.append(f"run {last_progress_run}")
            if last_tokens_total is not None:
                metrics_bits.append(f"tokens {last_tokens_total}")
            duration_text = format_duration(last_duration_seconds)
            if duration_text:
                metrics_bits.append(f"duration {duration_text}")
            if metrics_bits:
                lines.append(f"- Metrics: {', '.join(metrics_bits)}")

            if last_notes:
                lines.append("- Notes:")
                for note in last_notes[:4]:
                    lines.append(f"  - {clamp_text(note, 220)}")

            if last_commands:
                lines.append("- Prior command attempts:")
                for cmd in last_commands[:3]:
                    lines.append(f"  - {clamp_text(cmd, 160)}")

            log_excerpt_lines: list[str] = []
            log_display = ""
            if last_log_path:
                resolved_path = resolve_history_path(last_log_path)
                if isinstance(resolved_path, Path) and resolved_path.exists():
                    log_display = render_relative(resolved_path)
                    log_excerpt_lines = build_log_excerpt(resolved_path)
                else:
                    log_display = last_log_path
            if log_display:
                lines.append(f"- Log: {log_display}")
                if log_excerpt_lines:
                    lines.append("```text")
                    lines.extend(log_excerpt_lines)
                    lines.append("```")

            if last_output_path:
                output_path_resolved = resolve_history_path(last_output_path)
                if isinstance(output_path_resolved, Path) and output_path_resolved.exists():
                    lines.append(f"- Output: {render_relative(output_path_resolved)}")
                else:
                    lines.append(f"- Output: {last_output_path}")

            if last_prompt_path:
                prompt_path_resolved = resolve_history_path(last_prompt_path)
                if isinstance(prompt_path_resolved, Path) and prompt_path_resolved.exists():
                    lines.append(f"- Prompt: {render_relative(prompt_path_resolved)}")
                else:
                    lines.append(f"- Prompt: {last_prompt_path}")

        def _split_items(raw: str):
            if not raw:
                return []
            items = re.split(r'[\n;,]+', raw)
            return [item.strip() for item in items if item and item.strip()]

        def _collect_candidate_files(ref: str):
            candidates = []
            if not ref:
                return candidates
            ref_stripped = ref.strip()
            ref_lower = ref_stripped.lower()

            def add_path(candidate: Path):
                try:
                    resolved = candidate.resolve()
                except Exception:
                    resolved = candidate
                if resolved.is_file():
                    if resolved not in candidates:
                        candidates.append(resolved)

            # Direct path attempts relative to project or staging roots
            for base in filter(None, [project_root_path, staging_root]):
                candidate = base / ref_stripped
                if candidate.is_file():
                    add_path(candidate)
            # If ref looks like filename only, search staging dir for matches
            if staging_root and ("." in ref_stripped or "/" not in ref_stripped):
                for match in staging_root.rglob(ref_stripped):
                    add_path(match)

            keyword_map = {
                "sds": ["sds.*"],
                "pdr": ["pdr.*"],
                "openapi": ["openapi.*"],
                "swagger": ["openapi.*"],
                "erd": ["*.mmd"],
                "mermaid": ["*.mmd"],
                "schema": ["*.sql", "*.yaml", "*.yml"],
            }
            if staging_root:
                for keyword, patterns in keyword_map.items():
                    if keyword in ref_lower:
                        for pattern in patterns:
                            for match in staging_root.glob(pattern):
                                add_path(match)

            return candidates

        def classify_directory_crawl(command: str) -> Optional[str]:
            if not command:
                return None
            stripped = command.strip()
            if not stripped:
                return None
            tokens = stripped.split()
            if not tokens:
                return None
            cmd = tokens[0]
            args = tokens[1:]
            non_option_args = [tok for tok in args if not tok.startswith('-')]
            if cmd == 'ls':
                if not non_option_args:
                    return "ls with no explicit target"
                return None
            if cmd == 'find':
                target = non_option_args[0] if non_option_args else ''
                if not target or target in {'.', './', '..'}:
                    return "find without explicit target"
                return None
            if cmd == 'rg':
                if '--files' in tokens:
                    return "rg --files directory scan"
                return None
            if cmd == 'fd':
                return "fd directory scan"
            if cmd == 'tree':
                if not non_option_args:
                    return "tree with no explicit target"
                return None
            return None

        def resolve_workdir(cwd: str, project_root_path: Optional[pathlib.Path]) -> pathlib.Path:
            if cwd:
                candidate = pathlib.Path(cwd)
                if candidate.is_absolute():
                    return candidate
                base = project_root_path or pathlib.Path.cwd()
                return base / candidate
            return project_root_path or pathlib.Path.cwd()

        def _extract_snippet(path: Path, term: str, limit: int):
            if limit <= 0:
                return ([], False)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return ([f"(failed to read {path.name}: {exc})"], False)
            lines_local = text.splitlines()
            if not lines_local:
                return ([], False)
            search_terms: list[str] = []
            if term:
                search_terms.append(term.strip())
                search_terms.extend(
                    [token for token in re.split(r'[^a-z0-9/_\-.]+', term.lower()) if len(token) >= 3]
                )

            match_index = None
            for needle in search_terms:
                if not needle:
                    continue
                needle_lower = needle.lower()
                for idx, line in enumerate(lines_local):
                    if needle_lower in line.lower():
                        match_index = idx
                        break
                if match_index is not None:
                    break

            if match_index is None:
                start = 0
            else:
                start = max(0, match_index - max(5, limit // 2))
            end = min(len(lines_local), start + limit)
            snippet = lines_local[start:end]
            truncated = end < len(lines_local)
            if match_index is not None and start > 0:
                snippet.insert(0, "... (preceding lines omitted)")
            if truncated:
                snippet.append("... (additional content truncated)")
            return (snippet, truncated)

        def _minify_payload(value: str) -> str:
            if not value:
                return ""
            raw = value.strip()
            if not raw:
                return ""
            try:
                parsed = json.loads(raw)
            except Exception:
                return raw
            try:
                return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
            except Exception:
                return raw

        def _chunk_text(text: str, width: int = 160) -> list[str]:
            if not text:
                return []
            return [text[i:i + width] for i in range(0, len(text), width)]

        def _normalise_space(text: str) -> str:
            return re.sub(r"\s+", " ", text or "").strip()

        def _condense_snippet(snippet_lines, term, max_chars=420):
            core = " ".join(line.strip() for line in snippet_lines if line.strip())
            if not core:
                return ""
            core = _normalise_space(core)
            if term:
                lowered = core.lower()
                idx = lowered.find(term.lower())
                if idx > 0:
                    start = max(0, idx - 180)
                    core = core[start:]
            sentences = re.split(r'(?<=[.!?])\s+', core)
            assembled: list[str] = []
            total = 0
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                assembled.append(sentence)
                total += len(sentence)
                if total >= max_chars:
                    break
            summary = " ".join(assembled) if assembled else core
            summary = summary.strip()
            if len(summary) > max_chars:
                summary = summary[:max_chars].rstrip() + "…"
            return summary

        def append_sample_section(title: str, value: str):
            if not value:
                return
            lines.append("")
            heading = f"### {title}"
            payload = _minify_payload(value)
            if sample_limit <= 0:
                digest_src = payload.encode("utf-8", "replace")
                digest = hashlib.sha256(digest_src).hexdigest()[:12]
                preview = payload[:120]
                if payload and len(payload) > 120:
                    preview = preview.rstrip() + "…"
                lines.append(f"{heading} (digest — pass --sample-lines N to view payload)")
                if preview:
                    preview_clean = preview.replace("\n", " ").strip()
                    lines.append(f"- preview: `{preview_clean}`")
                source_lines = len(value.splitlines()) or 1
                lines.append(f"- original lines: {source_lines}; minified chars: {len(payload)}")
                lines.append(f"- sha256: {digest}")
                return

            sample_chunks = _chunk_text(payload)
            truncated = 0
            if sample_limit and len(sample_chunks) > sample_limit:
                truncated = len(sample_chunks) - sample_limit
                sample_chunks = sample_chunks[:sample_limit]
                heading = f"{heading} (first {sample_limit} chunk{'s' if sample_limit != 1 else ''} of minified payload)"

            lines.append(heading)
            if sample_chunks:
                lines.extend(sample_chunks)
            else:
                lines.append("(payload empty after normalisation)")
            if truncated:
                lines.append(f"... ({truncated} additional chunk{'s' if truncated != 1 else ''} truncated)")
                lines.append("... (raise --sample-lines to include more of the payload)")

        if sample_create_request:
            append_sample_section("Sample Create Request", sample_create_request)

        if sample_create_response:
            append_sample_section("Sample Create Response", sample_create_response)

        doc_catalog_entries = []
        doc_catalog_path = os.getenv("GC_DOC_CATALOG_PATH", "").strip()
        doc_catalog_data = {"version": 1, "documents": {}, "snippets": {}}
        doc_catalog_changed = {"value": False}
        if doc_catalog_path:
            catalog_path_obj = Path(doc_catalog_path)
            if catalog_path_obj.exists():
                try:
                    loaded = json.loads(catalog_path_obj.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        docs_section = loaded.get("documents")
                        if isinstance(docs_section, dict):
                            doc_catalog_data["documents"] = docs_section
                        for key, value in loaded.items():
                            if key != "documents":
                                doc_catalog_data[key] = value
                except Exception:
                    pass
        documents_store = doc_catalog_data.setdefault("documents", {})
        snippet_store = doc_catalog_data.setdefault("snippets", {})
        documentation_db_path = os.getenv("GC_DOCUMENTATION_DB_PATH", "").strip()
        doc_catalog_entries_from_db = False
        if documentation_db_path:
            registry_rows = []
            try:
                registry_conn = sqlite3.connect(documentation_db_path)
                registry_conn.row_factory = sqlite3.Row
                registry_cur = registry_conn.cursor()
                registry_cur.execute(
                    """
                    SELECT
                      doc_id,
                      doc_type,
                      COALESCE(staging_path, source_path) AS resolved_path,
                      rel_path,
                      title,
                      size_bytes,
                      mtime_ns,
                      sha256,
                      tags_json,
                      metadata_json
                    FROM documentation
                    WHERE status = 'active'
                    ORDER BY doc_type, COALESCE(rel_path, file_name, resolved_path)
                    """
                )
                registry_rows = registry_cur.fetchall()
            except Exception:
                registry_rows = []
            finally:
                try:
                    registry_conn.close()
                except Exception:
                    pass
            for row in registry_rows:
                path_value = (row["resolved_path"] or "").strip()
                rel_path = (row["rel_path"] or path_value or "").strip()
                metadata_raw = row["metadata_json"]
                headings_payload = []
                if metadata_raw:
                    try:
                        metadata_obj = json.loads(metadata_raw)
                        candidate_headings = metadata_obj.get("headings")
                        if isinstance(candidate_headings, list):
                            headings_payload = candidate_headings
                    except Exception:
                        pass
                snippet_text = ""
                candidate_path = Path(path_value) if path_value else None
                doc_entry_payload = {
                    "doc_id": row["doc_id"],
                    "rel_path": rel_path,
                    "headings": headings_payload,
                    "mtime_ns": row["mtime_ns"] or 0,
                    "size": row["size_bytes"] or 0,
                }
                if candidate_path and candidate_path.exists():
                    snippet_text = _load_doc_snippet(candidate_path, doc_entry_payload)
                    if not headings_payload:
                        fallback = _build_doc_entry(candidate_path)
                        if fallback:
                            headings_payload = fallback.get("headings", [])
                            doc_entry_payload["headings"] = headings_payload
                            snippet_text = _load_doc_snippet(candidate_path, doc_entry_payload)
                preview_headings = []
                for heading in headings_payload[:12]:
                    if isinstance(heading, dict):
                        title = heading.get("title") or ""
                        line = heading.get("line")
                        if line:
                            preview_headings.append(f"{title} (line {line})")
                        else:
                            preview_headings.append(title)
                    else:
                        preview_headings.append(str(heading))
                doc_catalog_entries.append(
                    {
                        "doc_id": row["doc_id"],
                        "rel_path": rel_path,
                        "headings": preview_headings,
                        "snippet": snippet_text,
                    }
                )
            if doc_catalog_entries:
                doc_catalog_entries_from_db = True

        def _relative_path_for_prompt(path_obj: Path) -> str:
            for base in filter(None, [project_root_path, staging_root]):
                if not base:
                    continue
                try:
                    return str(path_obj.relative_to(base))
                except ValueError:
                    continue
            return str(path_obj)

        if (not doc_catalog_entries_from_db) and doc_snippets_enabled and (staging_root or project_root_path):
            seen_paths = set()
            references = _split_items(document_reference)
            endpoints_list = _split_items(endpoints_text)
            candidates = []
            for reference in references:
                for candidate in _collect_candidate_files(reference):
                    try:
                        candidate_resolved = candidate.resolve()
                    except Exception:
                        candidate_resolved = candidate
                    key = str(candidate_resolved)
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    candidates.append(candidate_resolved)
            if staging_root and endpoints_list:
                openapi_candidates = list(staging_root.glob("openapi.*"))
                for candidate in openapi_candidates:
                    try:
                        candidate_resolved = candidate.resolve()
                    except Exception:
                        candidate_resolved = candidate
                    key = str(candidate_resolved)
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    candidates.append(candidate_resolved)
            for path_obj in candidates:
                if not path_obj.exists() or not path_obj.is_file():
                    continue
                doc_entry = _build_doc_entry(path_obj)
                if not doc_entry:
                    continue
                snippet_text = _load_doc_snippet(path_obj, doc_entry)
                preview_headings = []
                for heading in doc_entry.get("headings", [])[:12]:
                    title = heading.get("title") or ""
                    line_no = heading.get("line")
                    if line_no:
                        preview_headings.append(f"{title} (line {line_no})")
                    else:
                        preview_headings.append(title)
                doc_catalog_entries.append({
                    "doc_id": doc_entry["doc_id"],
                    "rel_path": doc_entry["rel_path"],
                    "headings": preview_headings,
                    "snippet": snippet_text,
                })

        if doc_catalog_path and doc_catalog_changed["value"]:
            try:
                Path(doc_catalog_path).write_text(json.dumps(doc_catalog_data, indent=2), encoding="utf-8")
            except Exception:
                pass

        search_terms = _collect_search_terms(
            task_title,
            document_reference,
            tags,
            acceptance,
            story_title,
        )
        doc_search_hits: List[Dict[str, object]] = []
        if search_terms:
            seen_doc_ids: Set[str] = {
                entry.get("doc_id", "").strip()
                for entry in doc_catalog_entries
                if entry.get("doc_id")
            }
            seen_doc_ids.discard("")
            db_path_obj: Optional[Path] = None
            if documentation_db_path:
                try:
                    candidate_path = Path(documentation_db_path)
                    if candidate_path.exists():
                        db_path_obj = candidate_path.resolve()
                    else:
                        db_path_obj = None
                except Exception:
                    db_path_obj = Path(documentation_db_path)
            doc_search_hits.extend(_run_fts_search(db_path_obj, search_terms, 12))
            for hit in list(doc_search_hits):
                doc_id = (hit.get("doc_id") or "").strip()
                if not doc_id:
                    doc_search_hits.remove(hit)
                    continue
                seen_doc_ids.add(doc_id)
            remaining_hits = 12 - len(doc_search_hits)
            if remaining_hits > 0:
                doc_search_hits.extend(_run_vector_search(vector_index_path, search_terms, remaining_hits, seen_doc_ids))
            remaining_hits = 12 - len(doc_search_hits)
            if remaining_hits > 0:
                doc_search_hits.extend(_run_ripgrep_search(project_root_path, search_terms, remaining_hits, seen_doc_ids))

        search_summary_payload: List[Dict[str, object]] = []
        if doc_search_hits:
            lines.append("")
            lines.append("## Documentation Search Hits")
            for hit in doc_search_hits[:12]:
                doc_id = (hit.get("doc_id") or "").strip()
                if not doc_id:
                    continue
                entry = documents_store.get(doc_id, {})
                rel_path = entry.get("rel_path") or entry.get("path") or doc_id
                method = hit.get("method", "fts")
                snippet_text = _normalise_space(hit.get("snippet") or "")
                lines.append(f"- {doc_id} [{method}] — {rel_path}")
                if snippet_text:
                    lines.append(f"  Snippet: {snippet_text[:280]}")
                search_summary_payload.append(
                    {
                        "doc_id": doc_id,
                        "method": method,
                        "rel_path": rel_path,
                        "snippet": snippet_text[:500],
                    }
                )
            task_ref = task_id or f"{STORY_SLUG}:{TASK_INDEX + 1}"
            if task_ref:
                search_map = doc_catalog_data.setdefault("search_hits", {})
                search_map[task_ref] = search_summary_payload
                doc_catalog_changed["value"] = True

        if doc_catalog_entries:
            lines.append("")
            lines.append("## Documentation Catalog")
            lines.append(
                "Use the catalog below to pick a section, then run "
                "`python3 \"$GC_DOC_CATALOG_PY\" show --db \"$GC_DOCUMENTATION_DB_PATH\" --doc-id <ID>` for a narrow excerpt. "
                "Avoid reading the raw documentation files directly."
            )
            for entry in doc_catalog_entries[:6]:
                rel_path = entry['rel_path']
                lines.append(f"- {entry['doc_id']} — {rel_path}")
                headings_preview = entry.get("headings") or []
                if headings_preview:
                    lines.append("  Sections:")
                    for heading in headings_preview[:6]:
                        lines.append(f"    • {heading}")
                else:
                    lines.append(
                        "  (No headings detected; use the documentation catalog search/show helpers to locate the relevant section instead of opening the file directly.)"
                    )
                snippet_text = (entry.get("snippet") or "").strip()
                if snippet_text:
                    snippet_clean = _normalise_space(snippet_text)[:280].rstrip()
                    lines.append(f"  Snippet: {snippet_clean}")
                lines.append("")

        guard_entries = []

        command_failure_cache = os.getenv("GC_COMMAND_FAILURE_CACHE", "").strip()
        failure_entries = []
        if command_failure_cache:
            cache_path = Path(command_failure_cache)
            if cache_path.exists():
                try:
                    cache_raw = cache_path.read_text(encoding='utf-8')
                    cache_data = json.loads(cache_raw) if cache_raw.strip() else {}
                except Exception:
                    cache_data = {}
                if isinstance(cache_data, dict):
                    for value in cache_data.values():
                        try:
                            failure_count = int(value.get("count") or 0)
                        except Exception:
                            failure_count = 0
                        if failure_count < 2:
                            continue
                        command_text = str(value.get("command") or "").strip()
                        if not command_text:
                            continue
                        summary_text = (value.get("last_summary") or value.get("summary") or "").strip()
                        summary_text = re.sub(r'\s+', ' ', summary_text)
                        exit_code_val = value.get("exit")
                        last_seen_val = value.get("last_seen") or ""
                        failure_entries.append((last_seen_val, failure_count, exit_code_val, command_text, summary_text))
                    failure_entries.sort(key=lambda item: item[0], reverse=True)

        if failure_entries:
            lines.append("")
            lines.append("## Known Command Failures")
            lines.append("The following commands have already failed; do not rerun them until the underlying issue is addressed. Summarise the cached failure instead of executing the command again.")
            max_failures = 4
            for _, failure_count, exit_code_val, command_text, summary_text in failure_entries[:max_failures]:
                exit_label = f"exit {exit_code_val}" if exit_code_val not in (None, "", 0) else "failed"
                plural = "s" if failure_count != 1 else ""
                if summary_text and len(summary_text) > 200:
                    summary_text = summary_text[:197] + "..."
                suffix = f" — {summary_text}" if summary_text else ""
                lines.append(f"- `{command_text}` ({exit_label}, {failure_count} attempt{plural}){suffix}")
                remediation_note = failure_remediation_notes.get(command_text.strip())
                if not remediation_note:
                    remediation_note = remediation_message(command_text, failure_count, exit_code_val)
                if remediation_note:
                    lines.append(f"  -> {remediation_note}")

        stream_cache = os.getenv("GC_COMMAND_STREAM_CACHE", "").strip()
        stream_entries = []
        if stream_cache:
            stream_path = Path(stream_cache)
            if stream_path.exists():
                try:
                    stream_raw = stream_path.read_text(encoding="utf-8")
                    stream_data = json.loads(stream_raw) if stream_raw.strip() else {}
                except Exception:
                    stream_data = {}
                if isinstance(stream_data, dict):
                    sorted_entries = sorted(
                        stream_data.values(),
                        key=lambda item: item.get("last_seen", ""),
                        reverse=True,
                    )
                    for entry in sorted_entries[:4]:
                        summary_text = (entry.get("summary") or "").strip()
                        advice_text = (entry.get("advice") or "").strip()
                        try:
                            occurrences = int(entry.get("count") or 0)
                        except Exception:
                            occurrences = 0
                        if summary_text:
                            summary_text = re.sub(r"\s+", " ", summary_text)
                            advice_text = re.sub(r"\s+", " ", advice_text)
                            stream_entries.append((summary_text, advice_text, occurrences))

        scan_cache = os.getenv("GC_COMMAND_SCAN_CACHE", "").strip()
        scan_entries = []
        if scan_cache:
            scan_path = Path(scan_cache)
            if scan_path.exists():
                try:
                    scan_raw = scan_path.read_text(encoding="utf-8")
                    scan_data = json.loads(scan_raw) if scan_raw.strip() else {}
                except Exception:
                    scan_data = {}
                if isinstance(scan_data, dict):
                    sorted_scans = sorted(
                        scan_data.values(),
                        key=lambda item: item.get("last_seen", ""),
                        reverse=True,
                    )
                    for entry in sorted_scans[:4]:
                        command_text = (entry.get("command") or "").strip()
                        preview_lines = entry.get("lines") or []
                        if not command_text or not preview_lines:
                            continue
                        cwd_display = (entry.get("cwd_display") or entry.get("cwd") or "").strip()
                        message_text = (entry.get("message") or "").strip()
                        try:
                            occurrences = int(entry.get("count") or 0)
                        except Exception:
                            occurrences = 0
                        try:
                            line_count_val = int(entry.get("line_count") or len(preview_lines))
                        except Exception:
                            line_count_val = len(preview_lines)
                        truncated_flag = bool(entry.get("truncated"))
                        cleaned_lines = []
                        for raw_line in preview_lines[:6]:
                            cleaned = (raw_line or "").strip()
                            if cleaned:
                                cleaned_lines.append(cleaned)
                        if not cleaned_lines and line_count_val > 0:
                            cleaned_lines.append("(no cached output)")
                        scan_entries.append({
                            "command": command_text,
                            "cwd": cwd_display,
                            "message": message_text,
                            "occurrences": occurrences,
                            "lines": cleaned_lines,
                            "line_count": line_count_val,
                            "truncated": truncated_flag or (line_count_val > len(cleaned_lines)),
                        })

        if stream_entries:
            lines.append("")
            lines.append("## Command Efficiency Alerts")
            lines.append("Recent runs paged files with sequential sed/cat chunks. Pivot to targeted searches or cached viewers instead of streaming large slices.")
            for summary_text, advice_text, occurrences in stream_entries:
                entry_line = summary_text
                if occurrences > 1:
                    entry_line += f" (seen {occurrences}x)"
                if advice_text:
                    entry_line += f" — {advice_text}"
                lines.append(f"- {entry_line}")

        if scan_entries:
            lines.append("")
            lines.append("## Workspace Directory Snapshots")
            lines.append("Reuse these cached listings instead of rerunning ls/find on the same paths; refresh only if the tree changes.")
            for entry in scan_entries:
                summary_line = f"- `{entry['command']}`"
                details = []
                cwd_display = entry.get("cwd") or ""
                if cwd_display:
                    details.append(f"cwd {cwd_display}")
                occurrences = entry.get("occurrences") or 0
                if isinstance(occurrences, int) and occurrences > 1:
                    details.append(f"seen {occurrences}x")
                message_text = entry.get("message") or ""
                if message_text:
                    details.append(message_text)
                if details:
                    summary_line += " — " + "; ".join(details)
                lines.append(summary_line)
                preview_lines = entry.get("lines") or []
                if preview_lines:
                    preview_text = ", ".join(preview_lines)
                    if len(preview_text) > 200:
                        preview_text = preview_text[:197] + "..."
                    lines.append(f"    {preview_text}")
                else:
                    lines.append("    (no cached output)")
                line_count_val = entry.get("line_count")
                extra_count = 0
                if isinstance(line_count_val, int):
                    extra_count = max(0, line_count_val - len(preview_lines))
                if extra_count > 0:
                    lines.append(f"    ... (+{extra_count} more)")
                elif entry.get("truncated"):
                    lines.append("    ... (truncated)")

        file_cache = os.getenv("GC_COMMAND_FILE_CACHE", "").strip()
        build_entries = []
        file_entries = []
        if file_cache:
            file_cache_path = Path(file_cache)
            if file_cache_path.exists():
                try:
                    file_raw = file_cache_path.read_text(encoding="utf-8")
                    file_data = json.loads(file_raw) if file_raw.strip() else {}
                except Exception:
                    file_data = {}
                if isinstance(file_data, dict):
                    sorted_files = sorted(
                        file_data.values(),
                        key=lambda item: item.get("last_seen", ""),
                        reverse=True,
                    )
                    max_file_entries = 6
                    max_build_entries = 4
                    for entry in sorted_files:
                        if len(file_entries) >= max_file_entries and len(build_entries) >= max_build_entries:
                            break
                        summary_text = (entry.get("summary") or "").strip()
                        excerpt_text = (entry.get("excerpt") or "").strip()
                        try:
                            occurrences = int(entry.get("count") or 0)
                        except Exception:
                            occurrences = 0
                        rel_path = (entry.get("rel_path") or entry.get("path") or "").strip()
                        range_value = entry.get("range")
                        mode_value = entry.get("mode")
                        category = entry.get("category") or ""
                        if summary_text:
                            summary_text = re.sub(r"\s+", " ", summary_text)
                            excerpt_text = re.sub(r"\s+", " ", excerpt_text)
                            payload = {
                                "summary": summary_text,
                                "excerpt": excerpt_text,
                                "occurrences": occurrences,
                                "rel_path": rel_path,
                                "range": range_value,
                                "mode": mode_value,
                            }
                            if category == "build-artifact":
                                if len(build_entries) < max_build_entries:
                                    build_entries.append(payload)
                                continue
                            file_entries.append(payload)

        if build_entries:
            lines.append("")
            lines.append("## Build Artifacts (opt-in)")
            lines.append("Compiled outputs in dist/build/coverage directories are suppressed; inspect sources first and only open these artifacts when absolutely necessary.")
            for entry in build_entries:
                summary_text = entry.get("summary") or ""
                rel_path = entry.get("rel_path") or ""
                occurrences = entry.get("occurrences") or 0
                info_line = summary_text
                if rel_path:
                    info_line += f" [{rel_path}]"
                if isinstance(occurrences, int) and occurrences > 1:
                    info_line += f" (seen {occurrences}x)"
                lines.append(f"- {info_line}")
                if rel_path:
                    lines.append(
                        f"  -> If a compiled artifact is required for `{rel_path}`, rely on the designated build tool or artifact viewer; otherwise focus on the source file."
                    )

        if file_entries:
            lines.append("")
            lines.append("## Cached File Excerpts")
            lines.append(
                "Reuse the snippets below instead of repeating cat/sed on the same file; refresh only if the file changed. "
                "When you need another slice, query the documentation catalog or open just the specific code file segment you plan to modify."
            )
            for entry in file_entries:
                summary_text = entry.get("summary") or ""
                excerpt_text = entry.get("excerpt") or ""
                occurrences = entry.get("occurrences") or 0
                entry_line = summary_text
                if isinstance(occurrences, int) and occurrences > 1:
                    entry_line += f" (seen {occurrences}x)"
                lines.append(f"- {entry_line}")
                if excerpt_text:
                    preview = excerpt_text.strip()
                    if len(preview) > 160:
                        preview = preview[:157] + "..."
                    lines.append(f"  -> {preview}")
                rel_path = entry.get("rel_path") or ""
                range_value = entry.get("range")
                command_hint = ""
                if rel_path:
                    if isinstance(range_value, (list, tuple)) and len(range_value) == 2:
                        try:
                            start_line = int(range_value[0])
                            end_line = int(range_value[1])
                        except Exception:
                            start_line = end_line = None
                        if start_line is not None and end_line is not None:
                            command_hint = f"sed -n '{start_line},{end_line}p' {rel_path}"
                    if not command_hint:
                        command_hint = f"sed -n '1,120p' {rel_path}"
                if command_hint:
                    lines.append(f"  -> Reopen via `{command_hint}`")

        if guard_entries:
            lines.append("")
            lines.append("## Command Guard Alerts")
            lines.append("Resolve these issues before rerunning commands that have already failed; focus on remediation instead of immediate retries.")
            for entry in guard_entries[:4]:
                command_label = (entry.get("command") or "pnpm").strip() or "pnpm"
                issues = entry.get("issues") or []
                summary = "; ".join(issues) if issues else "Pre-check violation detected."
                lines.append(f"- {command_label} — {summary}")

        lines.append("")
        lines.append("## Instructions")
        response_guidance = [
            "### Response Format",
            "- Organize your reply with the headings `Plan`, `Focus`, `Commands`, and `Notes` (in that order).",
            "- Keep each section to short bullet items or terse sentences; skip JSON, code fences, and closing summaries.",
            "- Make repository edits by listing the exact shell commands you will run under `Commands` (use `bash` to write files when needed).",
            "- Do not generate diffs or patches; apply edits directly through those shell commands.",
            "- Primary objective: ship the code required by the task acceptance criteria; avoid documentation rewrites or reorganizing prompts.",
            "- If an acceptance criterion demands heavy setup or environments the agent cannot access, acknowledge the gap and continue focusing on the core code changes.",
            "- In `Focus`, call out the files or symbols you are touching so reviewers understand the blast radius.",
            "- Capture blockers, follow-ups, or verification results in `Notes`.",
            "- Review `Known Command Failures` and `Command Guard Alerts` before retrying a command; prefer remediation steps over blind reruns.",
            "- Use the documentation catalog helpers (`python3 \"$GC_DOC_CATALOG_PY\" search/show --db \"$GC_DOCUMENTATION_DB_PATH\" ...`) for SDS/PDR references instead of opening doc files directly.",
            "- End the `Notes` section with `STATUS: completed`, `STATUS: needs-retry`, or `STATUS: failed` so automation can classify the run.",
        ]
        lines.extend(response_guidance)

        if compact_mode:
            lines.append("- Prefer pnpm for scripts; mention commands that cannot run because of network limits.")
            lines.append("- When you need documentation context, query the catalog (search/show) with precise section names like `\"SDS 7.3\"`; do not read doc files from the repo.")
            lines.append("- Avoid repo-wide listings/searches; open only the code files you intend to edit and keep `sed`/`cat` ranges tight.")
            lines.append("- Track file views; if you begin paging sequential ranges, pause and confirm the slice truly supports the active step.")
            lines.append("- Before running `pnpm test` or `pnpm build`, confirm dependencies are installed and prior pnpm commands succeeded; fix failures before retrying.")
        else:
            lines.append("- Prefer pnpm for scripts; note commands that cannot run because of network limits.")
            lines.append("- Route all documentation lookups through the catalog search/show helpers; never crawl SDS/PDR files directly.")
            lines.append("- Avoid broad repo sweeps; open only the code files tied to your current plan steps and keep the slices minimal.")

        lines.append("")
        lines.append("## Guardrails")
        lines.append("- Stay within this task's scope; avoid spinning up unrelated plans or subprojects.")
        lines.append("- Consult only the referenced docs or clearly relevant files; skip broad repo sweeps.")
        lines.append("- Keep command usage lean and focused on assets needed for the acceptance criteria.")
        lines.append("- Do not run directory-wide listings/searches outside the declared `focus`; revise the plan + focus first.")
        lines.append(
            "- Tackle documentation edits only after the related code changes land, and only when the documentation would be inaccurate without the update."
        )
        lines.append("- Wrap up once deliverables are met; record blockers or follow-ups succinctly in `notes`.")
        if instruction_prompts:
            lines.append("")
            lines.append("### Supplemental Instructions (pointers only)")
            pointer_target = doc_catalog_pointer or fallback_catalog_literal
            lines.append(f"See JSON catalog at: `{pointer_target}`")
            lines.append("Use the catalog + FTS search to pull only the slices you need; do not inline entire instruction prompts.")

        if CONTEXT_TAIL_PATH:
            context_path = Path(CONTEXT_TAIL_PATH)
            if context_path.exists():
                tail_text = context_path.read_text(encoding='utf-8').splitlines()
                tail_mode = os.getenv("GC_CONTEXT_TAIL_MODE", "digest").strip().lower()
                tail_limit = os.getenv("GC_CONTEXT_TAIL_LIMIT", "").strip()
                if tail_mode == "digest":
                    heading = "## Shared Context Digest"
                elif tail_mode == "raw":
                    heading = "## Shared Context Tail"
                    if tail_limit and tail_limit.isdigit():
                        heading += f" (last {int(tail_limit)} line{'s' if int(tail_limit) != 1 else ''})"
                else:
                    heading = "## Shared Context"
                lines.append("")
                lines.append(heading)
                lines.append("")
                lines.extend(tail_text)

        section_pairs = _lines_to_sections(lines)
        section_pairs = emit_preamble_once(section_pairs)
        section_pairs = dedupe_and_coalesce(section_pairs)
        formatted_sections = format_sections(section_pairs)
        lines = formatted_sections.rstrip("\n").split("\n") if formatted_sections.strip() else []

        final_prompt_text = "\n".join(lines) + "\n"
        final_prompt_text = slim_prompt_markdown(final_prompt_text)
        prompt_path = Path(PROMPT_PATH)
        meta_path = Path(str(prompt_path) + ".meta.json")
        input_digest = _compute_input_digest(
            STORY_SLUG,
            TASK_INDEX,
            task_id,
            MODEL_NAME,
            final_prompt_text,
        )
        prompt_sha = hashlib.sha256(final_prompt_text.encode("utf-8", "ignore")).hexdigest()
        existing_digest = _read_existing_input_digest(meta_path)
        meta_same = prompt_path.exists() and meta_path.exists() and _meta_same_as(meta_path, prompt_sha)
        if not (prompt_path.exists() and existing_digest == input_digest and meta_same):
            _atomic_write_text(prompt_path, final_prompt_text)
            meta_payload = {
                "story_slug": STORY_SLUG,
                "task_id": task_id,
                "task_title": task_title,
                "task_index": TASK_INDEX,
                "model": MODEL_NAME,
                "bytes": len(final_prompt_text),
                "input_digest": input_digest,
                "prompt_path": str(prompt_path),
                "sha256": prompt_sha,
                "written_at": int(time.time()),
            }
            _atomic_write_text(meta_path, json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n")

        if os.getenv("GC_PROMPT_PUBLISH_DISABLE", "").strip().lower() not in {"1", "true", "yes"}:
            try:
                publish_prompt(prompt_path, meta_path, project_root_path)
            except Exception:
                pass

        story_points_meta = story_points or ""
        print(f"{task_id}\t{task_title}\t{story_points_meta}")
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
