from __future__ import annotations

from typing import List


def run_apply(args: List[str]) -> None:
    if len(args) != 2:
        print("apply requires 2 arguments", file=sys.stderr)
        sys.exit(1)
    sys.argv = [sys.argv[0]] + args
    import fnmatch
    import json
    import logging
    import os
    import re
    import shlex
    import shlex
    import shutil
    import subprocess
    import tempfile
    from datetime import datetime
    from pathlib import Path
    from subprocess import CompletedProcess
    from collections import OrderedDict
    from typing import Optional, List, Tuple, Set, Dict, Sequence

    _original_re_compile = re.compile
    _original_re__compile = getattr(re, "_compile", None)
    invalid_regex_patterns = []
    HEREDOC_TOKEN = "<" * 2
    START_PATCH_MARKER = f"apply_patch {HEREDOC_TOKEN}'PATCH'"
    END_PATCH_MARKER = "PATCH"
    COMMAND_BLOCK_PATTERN = re.compile(
        r'\b(sudo|chown)\b|rm\s+-rf\s+/|chmod\s+[0-7]{3}\s+/|curl\s+http|wget\s+http',
        flags=re.IGNORECASE,
    )
    COMMAND_WHITELIST_PATTERN = re.compile(
        r'^(git|pnpm|npm|node|bash|sh|python3|python|sqlite3|jq|sed|awk|perl|cat|tee|mv|cp|mkdir|touch|ls|gpt-creator|gc_assert)\b'
    )
    HEREDOC_LABEL_PATTERN = re.compile(r"<<\s*['\"]?([A-Za-z0-9_]+)['\"]?")
    JEST_PATTERN = re.compile(r'\bjest(?:\.js)?\b', flags=re.IGNORECASE)
    PNPM_JEST_PATTERN = re.compile(r'\bpnpm\s+test\b.*\bjest\b', flags=re.IGNORECASE)
    RUN_IN_BAND_PATTERN = re.compile(r'\b--runinband\b', flags=re.IGNORECASE)
    VITEST_PATTERN = re.compile(r'\bvitest\b', flags=re.IGNORECASE)
    THREADS_FLAG_PATTERN = re.compile(r'\b--threads(?:=|\b)', flags=re.IGNORECASE)
    TSC_PATTERN = re.compile(r'(?<![A-Za-z0-9_.-])tsc(?:\.js)?(?![A-Za-z0-9_.-])')

    class UnclosedHeredocError(Exception):
        def __init__(self, delimiter: str, command_lead: str):
            super().__init__(delimiter)
            self.delimiter = delimiter
            self.command_lead = command_lead

    def _coalesce_command_entries(entries: Sequence[str]) -> List[str]:
        commands: List[str] = []
        buffer: List[str] = []
        delimiter: Optional[str] = None
        for entry in entries:
            if not isinstance(entry, str):
                continue
            line = entry.rstrip('\n')
            if delimiter is None and not line.strip():
                continue
            buffer.append(line)
            if delimiter is not None:
                stripped = line.strip()
                if stripped == delimiter:
                    commands.append("\n".join(buffer))
                    buffer = []
                    delimiter = None
                    continue
                if stripped.startswith(delimiter):
                    remainder = stripped[len(delimiter):].strip()
                    if not remainder or set(remainder) <= {"'", '"'}:
                        commands.append("\n".join(buffer))
                        buffer = []
                        delimiter = None
                        continue
                continue
            match = HEREDOC_LABEL_PATTERN.search(line)
            if match:
                delimiter = match.group(1)
                continue
            commands.append("\n".join(buffer))
            buffer = []
        if delimiter is not None:
            command_lead = buffer[0] if buffer else ""
            joined = "\n".join(buffer)
            if joined and ("..." in joined or "\u2026" in joined):
                commands.append(joined)
            else:
                raise UnclosedHeredocError(delimiter, command_lead)
            buffer = []
            delimiter = None
        if buffer:
            commands.append("\n".join(buffer))
        return commands

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
                invalid_regex_patterns.append(fragment)
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
    try:
        SED_MAX_WINDOW = int(os.getenv("WORK_ON_TASKS_SED_MAX_WINDOW", "200") or "200")
    except ValueError:
        SED_MAX_WINDOW = 200
    NOTE_CHAR_LIMIT = 300
    NOTE_REASONING_BUDGET_CHARS = 6000
    MAX_CONSECUTIVE_NON_ACTION_NOTES = 2
    COMMAND_LABEL_LIMIT = 96
    MAX_BLOCKED_COMMAND_DETAILS = 5
    BLOCK_REASON_LABELS = {
        'heredoc': 'raw heredoc writes',
        'heredoc-unterminated': 'unterminated heredoc commands',
        'python-non3': 'python (use python3)',
        'missing-helper': 'missing apply-block helper',
        'sed-window': 'oversized sed slices',
        'doc-search': 'documentation search',
        'show-file-range': 'show-file missing --range',
        'duplicate': 'duplicate commands',
        'policy': 'policy guardrails',
        'non-whitelist': 'non-whitelisted commands',
        'multiline': 'multi-line commands unsupported',
        'redirection': 'redirection/process substitution',
        'placeholder-ellipsis': 'incomplete command placeholder',
        'quote-mismatch': 'command quote mismatch',
        'repeat-failure': 'repeated command failure',
    }
    FATAL_BLOCK_REASONS = {
        'heredoc',
        'heredoc-unterminated',
        'missing-helper',
        'policy',
        'non-whitelist',
        'repeat-failure',
        'quote-mismatch',
        'redirection',
        'python-non3',
    }
    SAFE_BLOCKED_COMMAND_REASONS = {'heredoc', 'heredoc-unterminated', 'placeholder-ellipsis'}
    SCRIPT_PREFIX_CANDIDATES = (
        "cat <<",
        "tee <<",
        "python <<",
        "python3 <<",
        "bash <<",
        "sh <<",
        "apply_patch <<",
        "gpt-creator apply_block <<",
    )
    SCRIPT_FENCE_PATTERN = re.compile(r"```[a-z0-9_-]*", re.IGNORECASE)
    SCRIPT_HEREDOC_PATTERN = re.compile(r"<<-?\s*(?:'|\")?[A-Za-z0-9_+\-]+(?:'|\")?", re.MULTILINE)
    REDIRECTION_PATTERN = re.compile(r'(?<!\\)(?:>>|>\||\$\(|<\()')
    SHELL_META_CHARS = set('|&;()<>*$`\\\n')

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

    def _normalize_doc_path_label(label: str) -> str:
        if not label:
            return ""
        text = str(label).strip()
        if not text:
            return ""
        if text.startswith("WRITE "):
            text = text[6:].strip()
        if "\t" in text:
            text = text.split("\t", 1)[0].strip()
        text = re.sub(r"\s+\([^()]+\)\s*$", "", text).strip()
        if ":" in text:
            prefix, suffix = text.rsplit(":", 1)
            if suffix.isdigit():
                text = prefix
        text = text.strip().strip('\'"')
        text = text.replace("\\", "/")
        text = text.lstrip("./")
        return text

    def _path_is_doc_file(path: str) -> bool:
        normalized = _normalize_doc_path_label(path)
        if not normalized:
            return False
        lowered = normalized.lower()
        if lowered in DOC_PATH_EXACT:
            return True
        if any(lowered.startswith(prefix) for prefix in DOC_PATH_PREFIXES):
            return True
        if any(lowered.endswith(suffix) for suffix in DOC_SUFFIXES):
            return True
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
        if not normalized:
            return normalized
        bullet_prefixes = ('- ', '* ', '• ', '— ', '– ', '+ ')
        for prefix in bullet_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].lstrip()
                break
        else:
            bullet_match = re.match(r'^(?:\d+\.|\d+\)|[A-Za-z]\)|[ivxlcdm]+\.)\s+', normalized, flags=re.IGNORECASE)
            if bullet_match:
                normalized = normalized[bullet_match.end():].lstrip()
        if normalized.startswith('`'):
            closing = normalized.find('`', 1)
            if closing != -1:
                inner = normalized[1:closing].strip()
                if inner:
                    normalized = inner
                else:
                    normalized = normalized[closing + 1:].strip()
        while len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'`', '"', "'"}:
            normalized = normalized[1:-1].strip()

        def _single_quote(body: str) -> str:
            if not body:
                return "''"
            return "'" + body.replace("'", "'\"'\"'") + "'"

        def _normalize_rg(command: str) -> str:
            try:
                tokens = shlex.split(command)
            except ValueError:
                return command
            if not tokens or tokens[0] != 'rg':
                return command

            def _consume_value(it):
                try:
                    return next(it)
                except StopIteration:
                    return None

            options: List[str] = []
            pattern: Optional[str] = None
            paths: List[str] = []
            pending: List[str] = []
            iterator = iter(tokens[1:])
            for token in iterator:
                if token == '--':
                    pending.extend(iterator)
                    break
                if pattern is None and token.startswith('-'):
                    options.append(token)
                    if token in RG_OPTIONS_EXPECT_VALUE:
                        value = _consume_value(iterator)
                        if value is not None:
                            options.append(value)
                    continue
                if pattern is None:
                    pattern = token
                    continue
                pending.append(token)
            if pattern is None:
                return command

            pending_iter = iter(pending)
            for token in pending_iter:
                if token == '--':
                    paths.extend(list(pending_iter))
                    break
                if token.startswith('-') and token != '-':
                    options.append(token)
                    if token in RG_OPTIONS_EXPECT_VALUE:
                        value = _consume_value(pending_iter)
                        if value is not None:
                            options.append(value)
                    continue
                paths.append(token)

            new_tokens: List[str] = ['rg']
            new_tokens.extend(options)
            new_tokens.append(pattern)
            if paths:
                new_tokens.append('--')
                new_tokens.extend(paths)
            return shlex.join(new_tokens)

        # Many plans wrap commands as: bash -lc "cmd with \"nested\" quotes".
        # When quotes inside the script are not escaped the inner bash fails with
        # "unexpected EOF while looking for matching \"". Auto-escape them so that
        # nested quoting cannot break command execution.
        match = re.match(r'^(bash|sh)\s+-[lc]\s+(.+)$', normalized)
        if match:
            try:
                parts = shlex.split(normalized)
            except ValueError:
                parts = None
            script_original = match.group(2).strip()
            script_body = ""
            if parts and len(parts) >= 3:
                script_body = ' '.join(parts[2:])
            else:
                script_body = script_original
            script_body = script_body.strip()
            if script_body.startswith('\\"') and script_body.endswith('\\"') and len(script_body) >= 4:
                script_body = script_body[2:-2]
            elif script_body.startswith('"') and script_body.endswith('"') and len(script_body) >= 2:
                script_body = script_body[1:-1]
            script_body = script_body.replace('\\"', '"')
            script_body = _normalize_rg(script_body)
            normalized = f"{match.group(1)} -lc {_single_quote(script_body)}"
            return normalized

        normalized = _normalize_rg(normalized)
        return normalized

    def _sanitize_command_escapes(command: str) -> str:
        if '\\' not in command:
            return command
        repaired = command.replace('\\"', '"')
        repaired = repaired.replace("\\'", "'")
        return repaired

    def _is_valid_bash_wrapper(command: str) -> bool:
        stripped = command.strip()
        match = re.match(r'^(bash|sh)\s+-[lc]\s+(.+)$', stripped)
        if not match:
            return True
        script = match.group(2).strip()
        if not script:
            return False
        if not (script.startswith('"') and script.endswith('"')):
            return False
        if script.startswith('\\"') or script.endswith('\\"'):
            return False
        return True

    def _hydrate_literal_command(text: str) -> str:
        """Convert common escaped control sequences to real characters for bash/sh wrappers."""
        if '\\' not in text or '\n' in text:
            return text
        stripped = text.lstrip()
        if not re.match(r'(bash|sh)\b', stripped):
            return text
        needs_hydration = any(seq in text for seq in ('\\n', '\\t', '\\r'))
        if not needs_hydration:
            return text
        result_chars: List[str] = []
        idx = 0
        length = len(text)
        while idx < length:
            ch = text[idx]
            if ch == '\\' and idx + 1 < length:
                nxt = text[idx + 1]
                if nxt == 'n':
                    result_chars.append('\n')
                    idx += 2
                    continue
                if nxt == 't':
                    result_chars.append('\t')
                    idx += 2
                    continue
                if nxt == 'r':
                    result_chars.append('\r')
                    idx += 2
                    continue
            result_chars.append(ch)
            idx += 1
        return ''.join(result_chars)

    def _script_contains_wide_sed(script: str, threshold: int = SED_MAX_WINDOW) -> Tuple[bool, int, str]:
        if not script:
            return (False, 0, '')
        segments = re.split(r'[;&]\s*', script)
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            exceeds, window = _sed_window_exceeds(segment, threshold=threshold)
            if exceeds:
                return (True, window, segment)
        return (False, 0, '')

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

    def _extract_python_heredoc(script: str) -> Optional[str]:
        if not script:
            return None
        lines = script.splitlines()
        if not lines:
            return None
        first = lines[0].strip()
        pattern = (
            r"python3\s+(?:-\s+)?"
            + re.escape(HEREDOC_TOKEN)
            + r"(?P<quote>['\"]?)(?P<label>[A-Za-z0-9_]+)(?P=quote)"
        )
        match = re.fullmatch(pattern, first)
        if not match:
            return None
        label = match.group('label')
        body: List[str] = []
        terminator_index: Optional[int] = None
        for idx, line in enumerate(lines[1:], start=1):
            if line.strip() == label:
                terminator_index = idx
                break
            body.append(line)
        if terminator_index is None:
            return None
        trailing = lines[terminator_index + 1:]
        if any(chunk.strip() for chunk in trailing):
            return None
        code = '\n'.join(body)
        return code

    def _extract_simple_sed(command: str) -> Optional[Tuple[int, int, str]]:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if not tokens or tokens[0] != 'sed':
            return None
        start_line: Optional[int] = None
        end_line: Optional[int] = None
        target_path: Optional[str] = None
        for token in tokens[1:]:
            cleaned = token.strip().strip('\'"')
            if not cleaned:
                continue
            if cleaned == '-n':
                continue
            range_match = re.fullmatch(r'(\d+),(\d+)p', cleaned)
            if range_match:
                start_line = int(range_match.group(1))
                end_line = int(range_match.group(2))
                continue
            if cleaned.startswith('-'):
                continue
            target_path = cleaned
        if start_line is None or end_line is None or target_path is None:
            return None
        return (start_line, end_line, target_path)

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

    command_archive_dir: Optional[Path] = None
    command_archive_counter = 0
    truncated_command_cache: Dict[str, str] = {}

    def _truncate_command_text(command: str, limit: int = COMMAND_LABEL_LIMIT) -> str:
        nonlocal command_archive_dir, command_archive_counter
        snippet = command.strip()
        if len(snippet) <= limit:
            return snippet
        cached = truncated_command_cache.get(snippet)
        if cached:
            return cached
        if command_archive_dir is None:
            command_archive_dir = project_root / "logs" / "notes"
            command_archive_dir.mkdir(parents=True, exist_ok=True)
        command_archive_counter += 1
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        filename = f"command_{timestamp}_{command_archive_counter:02d}.txt"
        archive_path = command_archive_dir / filename
        archive_path.write_text(snippet + "\n", encoding='utf-8')
        try:
            rendered = str(archive_path.relative_to(project_root))
        except Exception:
            rendered = str(archive_path)
        truncated_command_cache[snippet] = rendered
        return rendered

    def _format_action_result(action: str, result: str) -> str:
        return f"Action: {action.strip()} | Result: {result.strip()}"


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

    try:
        raw_text_original = output_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raw_text_original = output_path.read_text(encoding='utf-8', errors='replace')
    raw = raw_text_original.strip()
    canonical_response_text = raw_text_original
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

    CODE_SAMPLE_PATTERN = re.compile(
        r"```|^\s*(?:const|let|var|function|class|def|describe|it|expect|public\s+static)\b",
        re.MULTILINE,
    )
    code_sample_detected = bool(CODE_SAMPLE_PATTERN.search(raw))

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

        def _infer_patch_path(block: str) -> Optional[str]:
            candidate: Optional[str] = None
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith('*** '):
                    header = stripped[4:].strip()
                    if header.lower().startswith('update file:'):
                        candidate = header.split(':', 1)[-1].strip() or candidate
                        continue
                    if header.lower().startswith('add file:'):
                        candidate = header.split(':', 1)[-1].strip() or candidate
                        continue
                    if header.lower().startswith('delete file:'):
                        candidate = header.split(':', 1)[-1].strip() or candidate
                        continue
                    if header.lower().startswith('move to:'):
                        moved = header.split(':', 1)[-1].strip()
                        if moved:
                            candidate = moved
                        continue
                if stripped.startswith('+++ b/'):
                    candidate = stripped[6:].strip()
                    if candidate == '/dev/null':
                        candidate = None
                    else:
                        break
                elif stripped.startswith('diff --git '):
                    parts = stripped.split()
                    if len(parts) >= 4:
                        proposed = parts[3][2:].strip()
                        if proposed and proposed != '/dev/null':
                            candidate = proposed
                            break
            return candidate

        for block in blocks:
            block_text = block.strip("\n")
            if not block_text:
                continue
            if not block_text.endswith('\n'):
                block_text += '\n'
            candidate = _infer_patch_path(block_text)
            change_entry: Dict[str, Any] = {
                'type': 'patch',
                'diff': block_text,
            }
            if candidate:
                change_entry['path'] = candidate
            if candidate and candidate not in inferred_focus:
                inferred_focus.append(candidate)
            changes_from_blocks.append(change_entry)
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

    REQUIRED_RESPONSE_SECTIONS = ("plan", "focus", "commands", "notes")

    def _extract_section_lines(text: str):
        headings = set(REQUIRED_RESPONSE_SECTIONS) | {"changes"}
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
                candidate = stripped.rstrip(':').strip()
                normalized = candidate.strip("*_# ").lower()
                if normalized in headings:
                    current = normalized
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

    logger = logging.getLogger("gc-runner.apply")

    parse_failure_detected = False

    payload = _try_parse_json_payload(raw)
    if payload is None:
        payload = _parse_apply_patch_payload(raw)
    if payload is None:
        payload = _parse_freeform_payload(raw)
    if payload is None:
        parse_failure_detected = True
        logger.warning(
            "Agent output could not be parsed into actionable instructions; proceeding with empty payload."
        )
        payload = {
            'plan': [],
            'focus': [],
            'changes': [],
            'commands': [],
            'notes': [],
        }

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

    def _extract_commands_from_text(text):
        commands: List[str] = []
        if not isinstance(text, str):
            return commands
        in_fence = False
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            candidate = stripped
            if not candidate:
                continue
            if candidate.startswith("`") and candidate.endswith("`") and len(candidate) > 2:
                candidate = candidate.strip("`")
            candidate = re.sub(r'^[\-\*•]+\s*', '', candidate)
            if COMMAND_WHITELIST_PATTERN.match(candidate):
                commands.append(candidate)
                continue
            if in_fence and COMMAND_WHITELIST_PATTERN.match(candidate):
                commands.append(candidate)
                continue
            inline_match = re.search(r"bash\s+-lc\s+\"[^\"]+\"", stripped)
            if inline_match:
                commands.append(inline_match.group(0))
        return commands

    def _extract_plan_commands(entry):
        commands: List[str] = []
        if isinstance(entry, dict):
            possible = entry.get('commands')
            if isinstance(possible, list):
                commands.extend(item for item in possible if isinstance(item, str))
        elif isinstance(entry, str):
            commands.extend(_extract_commands_from_text(entry))
        return commands

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

    plan_command_suggestions: List[str] = []
    plan_entries = payload.get('plan')
    if isinstance(plan_entries, list):
        for entry in plan_entries:
            plan_command_suggestions.extend(_extract_plan_commands(entry))
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

    if plan_command_suggestions:
        deduped_commands: List[str] = []
        seen_commands: Set[str] = set()
        for cmd in plan_command_suggestions:
            if not isinstance(cmd, str):
                continue
            trimmed_cmd = cmd.strip()
            if not trimmed_cmd:
                continue
            if not COMMAND_WHITELIST_PATTERN.match(trimmed_cmd):
                continue
            if trimmed_cmd in seen_commands:
                continue
            seen_commands.add(trimmed_cmd)
            deduped_commands.append(trimmed_cmd)
        if deduped_commands:
            existing_commands = payload.get('commands')
            if isinstance(existing_commands, list):
                existing_commands.extend(cmd for cmd in deduped_commands if cmd not in existing_commands)
            elif existing_commands is None:
                payload['commands'] = deduped_commands
            elif isinstance(existing_commands, str):
                merged = [existing_commands] + [cmd for cmd in deduped_commands if cmd != existing_commands]
                payload['commands'] = merged
            else:
                payload['commands'] = deduped_commands

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

    payload_dict: Dict[str, object] = payload if isinstance(payload, dict) else {}

    def _clean_str(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    active_task_id = _clean_str(payload_dict.get('task_id')) or _clean_str(
        os.environ.get("GC_ACTIVE_TASK_ID") or os.environ.get("GC_BUDGET_TASK_ID")
    )
    task_db_id = active_task_id
    task_slug = _clean_str(payload_dict.get('story_slug')) or _clean_str(
        os.environ.get("GC_ACTIVE_TASK_SLUG") or os.environ.get("GC_ACTIVE_STORY_SLUG")
    )
    task_number = _clean_str(payload_dict.get('task_number')) or _clean_str(
        os.environ.get("GC_ACTIVE_TASK_NUMBER") or os.environ.get("GC_ACTIVE_TASK_INDEX")
    )
    existing_task_branch = _clean_str(payload_dict.get('work_branch')) or _clean_str(
        os.environ.get("GC_ACTIVE_TASK_BRANCH")
    )
    existing_task_branch_base = _clean_str(payload_dict.get('work_branch_base')) or _clean_str(
        os.environ.get("GC_ACTIVE_TASK_BRANCH_BASE")
    )

    def _resolve_tasks_db_path() -> Optional[Path]:
        candidates: List[Path] = []
        env_candidates = (
            os.environ.get("GC_TASK_DB_PATH"),
            os.environ.get("GC_TASKS_DB_PATH"),
            os.environ.get("WORK_ON_TASKS_DB_PATH"),
            os.environ.get("GC_BACKLOG_DB_PATH"),
        )
        for raw in env_candidates:
            cleaned = _clean_str(raw)
            if not cleaned:
                continue
            candidate = Path(cleaned)
            if not candidate.is_absolute():
                candidate = (project_root / cleaned).resolve()
            candidates.append(candidate)
        candidates.extend([
            project_root / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db",
            project_root / ".gpt-creator" / "tasks.db",
        ])
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate
            except Exception:
                continue
        return None

    tasks_db_path = _resolve_tasks_db_path()

    def _run_git_command(args: Sequence[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            cwd=str(project_root),
            check=False,
        )

    def _push_branch_to_remote(branch: str, context: str) -> Tuple[bool, str]:
        push_remote = os.environ.get("WORK_ON_TASKS_PUSH_REMOTE", "origin").strip() or "origin"
        push_proc = _run_git_command(['push', '--set-upstream', push_remote, branch])
        if push_proc.returncode == 0:
            return True, _format_action_result(
                "branch",
                f"info — pushed {branch} to {push_remote} ({context})"
            )
        stderr_text = (push_proc.stderr or "").strip()
        return False, _format_action_result(
            "branch",
            f"warning — push of {branch} to {push_remote} failed ({context}): {stderr_text or 'see stderr'}"
        )

    def _is_remote_access_error(stderr_text: str, stdout_text: str = "") -> bool:
        haystack = f"{stderr_text}\n{stdout_text}".lower()
        tokens = (
            "error: user:",
            "error: no healthy upstream",
            "connection refused",
            "connection reset",
            "permission denied",
            "could not read from remote repository",
            "fatal: unable to access",
        )
        return any(token in haystack for token in tokens if token)

    def _is_missing_remote_ref_error(stderr_text: str) -> bool:
        lowered = (stderr_text or "").lower()
        if not lowered:
            return False
        patterns = (
            "couldn't find remote ref",
            "remote ref does not exist",
            "remote ref cannot be resolved",
            "remote ref not found",
        )
        return any(pattern in lowered for pattern in patterns)

    main_branch_name = os.environ.get("WORK_ON_TASKS_MAIN_BRANCH", "main").strip() or "main"
    dev_branch_name = os.environ.get("WORK_ON_TASKS_DEV_BRANCH", "dev").strip() or "dev"

    def _get_current_branch() -> str:
        proc = _run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'])
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    def _branch_ref_exists(ref: str) -> bool:
        probe = _run_git_command(['show-ref', '--verify', '--quiet', ref])
        return probe.returncode == 0

    def _local_branch_exists(branch: str) -> bool:
        return _branch_ref_exists(f"refs/heads/{branch}")

    def _remote_branch_exists(branch: str) -> bool:
        probe = _run_git_command(['ls-remote', '--heads', 'origin', branch])
        return probe.returncode == 0 and bool((probe.stdout or "").strip())

    def _sanitize_branch_component(text: str) -> str:
        token = _clean_str(text).lower()
        token = re.sub(r'[^a-z0-9]+', '-', token)
        token = token.strip('-')
        return token or "task"

    def _build_task_branch_name() -> str:
        identifier_candidates = [
            task_db_id,
            task_slug,
            task_number,
        ]
        for candidate in identifier_candidates:
            component = _sanitize_branch_component(candidate)
            if component:
                return component
        fallback_slug = _sanitize_branch_component(task_slug or "task")
        index_hint = _clean_str(os.environ.get("GC_ACTIVE_TASK_INDEX"))
        if index_hint.isdigit():
            try:
                ordinal = int(index_hint)
                return f"{fallback_slug}-{ordinal + 1}"
            except ValueError:
                pass
        return fallback_slug or "task"

    def _update_task_branch_record(task_row_id: Optional[str], branch: Optional[str], base_branch: Optional[str]) -> None:
        global sqlite3
        if not task_row_id or tasks_db_path is None:
            return
        try:
            if not tasks_db_path.exists():
                return
        except Exception:
            return
        try:
            with sqlite3.connect(str(tasks_db_path)) as branch_conn:
                branch_conn.execute(
                    "UPDATE tasks SET work_branch = ?, work_branch_base = ?, work_branch_updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                    (branch, base_branch, task_row_id),
                )
                branch_conn.commit()
        except sqlite3.Error:
            pass

    def _record_task_artifact(task_row_id: Optional[str], artifact_type: str, artifact_path_text: str) -> None:
        global sqlite3
        if not task_row_id or not artifact_path_text or tasks_db_path is None:
            return
        try:
            if not tasks_db_path.exists():
                return
        except Exception:
            return
        try:
            with sqlite3.connect(str(tasks_db_path)) as artifact_conn:
                artifact_conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS task_artifacts (
                        task_id TEXT NOT NULL,
                        artifact_type TEXT NOT NULL,
                        artifact_path TEXT NOT NULL,
                        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                artifact_conn.execute(
                    "INSERT INTO task_artifacts (task_id, artifact_type, artifact_path) VALUES (?, ?, ?)",
                    (task_row_id, artifact_type, artifact_path_text),
                )
                artifact_conn.commit()
        except sqlite3.Error:
            pass

    def _ensure_dev_branch_exists() -> Tuple[bool, List[str]]:
        notes: List[str] = []
        if _local_branch_exists(dev_branch_name):
            return True, notes
        start_ref: Optional[str] = None
        if _local_branch_exists(main_branch_name):
            start_ref = main_branch_name
        else:
            fetch_main = _run_git_command(['fetch', 'origin', main_branch_name])
            if fetch_main.returncode == 0:
                start_ref = f"origin/{main_branch_name}"
        if start_ref is None:
            head = _run_git_command(['rev-parse', '--verify', 'HEAD'])
            if head.returncode == 0:
                start_ref = head.stdout.strip()
        create_args = ['branch', dev_branch_name]
        if start_ref:
            create_args.append(start_ref)
        create_proc = _run_git_command(create_args)
        if create_proc.returncode != 0:
            stderr_text = (create_proc.stderr or "").strip()
            notes.append(
                _format_action_result(
                    "branch",
                    f"blocked — unable to create dev branch {dev_branch_name}: {stderr_text or 'see stderr'}"
                )
            )
            return False, notes
        push_proc = _run_git_command(['push', '-u', 'origin', dev_branch_name])
        if push_proc.returncode == 0:
            notes.append(
                _format_action_result(
                    "branch",
                    f"info — created dev branch {dev_branch_name} from {start_ref or 'HEAD'} and pushed to origin"
                )
            )
        else:
            notes.append(
                _format_action_result(
                    "branch",
                    f"warning — dev branch {dev_branch_name} created locally but push failed; sync manually"
                )
            )
        return True, notes

    written = []
    patched = []
    noop_entries = []
    manual_notes = []

    def _append_guard_note(code: str, message: str) -> None:
        manual_notes.append(_format_action_result(code, message))
        _record_guard_event(code, message)
    error_records: List[str] = []
    required_scripts: List[str] = []
    reports_base = project_root / ".gpt-creator" / "reports"
    dev_ready, dev_branch_notes = _ensure_dev_branch_exists()
    manual_notes.extend(dev_branch_notes)

    def _env_flag(name: str, *, default: bool = False) -> bool:
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default
        normalized = raw_value.strip().lower()
        if not normalized:
            return default
        return normalized in {"1", "true", "yes", "on"}

    branch_management_enabled = _env_flag("WORK_ON_TASKS_BRANCH_MANAGEMENT", default=True)
    branch_delete_on_complete = _env_flag("WORK_ON_TASKS_DELETE_BRANCH_ON_COMPLETE", default=True)
    branch_ready = False
    active_task_branch: Optional[str] = None
    base_task_branch: Optional[str] = None
    initial_repository_branch = dev_branch_name if branch_management_enabled else _get_current_branch()
    forced_canonical_status: Optional[str] = None
    forced_legacy_status: Optional[str] = None
    branch_setup_retry_needed = False

    def _is_checkout_blocked_by_local_changes(error_text: str) -> bool:
        lowered = (error_text or "").lower()
        if not lowered:
            return False
        patterns = (
            "would be overwritten by checkout",
            "please commit your changes or stash them",
            "you have local changes to the following files",
            "untracked working tree files would be overwritten",
        )
        return any(pattern in lowered for pattern in patterns)

    def _checkout_dev_branch() -> List[str]:
        notes: List[str] = []
        nonlocal branch_management_enabled, branch_setup_retry_needed
        if not branch_management_enabled:
            return notes
        branch_setup_retry_needed = False
        current_branch = _get_current_branch()
        if current_branch == dev_branch_name:
            update = _run_git_command(['pull', '--ff-only', 'origin', dev_branch_name])
            if update.returncode == 0 and (update.stdout or update.stderr):
                notes.append(
                    _format_action_result(
                        "branch",
                        f"info — updated dev branch {dev_branch_name} from origin"
                    )
                )
            return notes
        checkout = _run_git_command(['checkout', dev_branch_name])
        if checkout.returncode != 0:
            stderr_text = (checkout.stderr or "").strip()
            lower_error = stderr_text.lower()
            if "did not match any file" in lower_error:
                additional_ready, ensure_notes = _ensure_dev_branch_exists()
                notes.extend(ensure_notes)
                if additional_ready:
                    checkout = _run_git_command(['checkout', dev_branch_name])
                    if checkout.returncode == 0:
                        notes.append(
                            _format_action_result(
                                "branch",
                                f"info — created missing dev branch {dev_branch_name} and checked it out"
                            )
                        )
                        return notes
                    stderr_text = (checkout.stderr or "").strip()
            if _is_checkout_blocked_by_local_changes(stderr_text):
                branch_setup_retry_needed = True
                notes.append(
                    _format_action_result(
                        "branch",
                        f"warning — deferred checkout of dev branch {dev_branch_name} until pending changes are cleaned up ({stderr_text or 'dirty working tree'})"
                    )
                )
            else:
                notes.append(
                    _format_action_result(
                        "branch",
                        f"blocked — unable to checkout dev branch {dev_branch_name}: {stderr_text or 'see stderr'}"
                    )
                )
            branch_management_enabled = False
            return notes
        _run_git_command(['pull', '--ff-only', 'origin', dev_branch_name])
        notes.append(
            _format_action_result(
                "branch",
                f"info — switched to dev branch {dev_branch_name}"
            )
        )
        return notes

    def _prepare_task_branch_if_needed() -> List[str]:
        notes: List[str] = []
        nonlocal branch_management_enabled, branch_ready, active_task_branch, base_task_branch
        if not branch_management_enabled:
            return notes
        branch_name = existing_task_branch or _build_task_branch_name()
        base_branch = existing_task_branch_base or dev_branch_name
        current_branch = _get_current_branch()
        if not current_branch:
            current_branch = base_branch

        def record_failure(message: str) -> None:
            nonlocal branch_management_enabled, branch_ready
            notes.append(
                _format_action_result(
                    "branch",
                    f"blocked — {message}"
                )
            )
            branch_management_enabled = False
            branch_ready = False

        def _create_branch_from_base(note_message: str) -> bool:
            checkout_base = _run_git_command(['checkout', base_branch])
            if checkout_base.returncode != 0:
                stderr_text = (checkout_base.stderr or "").strip()
                record_failure(f"{note_message}: unable to checkout base branch {base_branch}: {stderr_text or 'see stderr'}")
                return False
            _run_git_command(['pull', '--ff-only', 'origin', base_branch])
            create = _run_git_command(['checkout', '-b', branch_name])
            if create.returncode != 0:
                stderr_text = (create.stderr or "").strip()
                record_failure(f"{note_message}: unable to create branch {branch_name}: {stderr_text or 'see stderr'}")
                return False
            notes.append(
                _format_action_result(
                    "branch",
                    f"info — {note_message}"
                )
            )
            _, push_note = _push_branch_to_remote(branch_name, note_message)
            notes.append(push_note)
            return True

        if current_branch != branch_name:
            if _local_branch_exists(branch_name):
                checkout = _run_git_command(['checkout', branch_name])
                if checkout.returncode != 0:
                    stderr_text = (checkout.stderr or "").strip()
                    record_failure(f"unable to checkout existing branch {branch_name}: {stderr_text or 'see stderr'}")
                    return notes
                if not _remote_branch_exists(branch_name):
                    _, push_note = _push_branch_to_remote(branch_name, "upstream missing; syncing branch")
                    notes.append(push_note)
            elif _remote_branch_exists(branch_name):
                fetch = _run_git_command(['fetch', 'origin', branch_name])
                if fetch.returncode != 0:
                    stderr_text = (fetch.stderr or "").strip()
                    if _is_missing_remote_ref_error(stderr_text):
                        if not _create_branch_from_base(f"remote branch {branch_name} missing; created new branch from {base_branch}"):
                            return notes
                    else:
                        record_failure(f"git fetch origin {branch_name} failed: {stderr_text or 'see stderr'}")
                        return notes
                else:
                    create = _run_git_command(['checkout', '-b', branch_name, f'origin/{branch_name}'])
                    if create.returncode != 0:
                        stderr_text = (create.stderr or "").strip()
                        record_failure(f"unable to checkout remote branch {branch_name}: {stderr_text or 'see stderr'}")
                        return notes
                    notes.append(
                        _format_action_result(
                            "branch",
                            f"info — resumed branch {branch_name} from origin/{branch_name}"
                        )
                    )
            else:
                if not _create_branch_from_base(f"started new branch {branch_name} from {base_branch}"):
                    return notes
        else:
            notes.append(
                _format_action_result(
                    "branch",
                    f"info — continuing on branch {branch_name}"
                )
            )
            if not _remote_branch_exists(branch_name):
                _, push_note = _push_branch_to_remote(branch_name, "upstream missing; syncing branch")
                notes.append(push_note)

        active_task_branch = branch_name
        base_task_branch = base_branch
        branch_ready = True
        os.environ["GC_ACTIVE_TASK_BRANCH"] = branch_name
        _update_task_branch_record(task_db_id, branch_name, base_branch)
        return notes

    manual_notes.extend(_checkout_dev_branch())
    manual_notes.extend(_prepare_task_branch_if_needed())

    def _sanitize_for_path(value: str) -> str:
        token = (value or "").strip()
        if not token:
            return "task"
        token = token.lower()
        token = re.sub(r"[^\w.-]+", "-", token)
        token = token.strip("-_.")
        return token or "task"

    task_label_components = [
        active_task_id,
        task_slug,
        task_number,
    ]
    task_label = next((component for component in task_label_components if component), "task")
    sanitized_task_label = _sanitize_for_path(str(task_label))
    run_timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    report_root = reports_base / sanitized_task_label / run_timestamp
    report_rel_path = ""
    errors_log_path: Optional[Path] = None
    next_commands_path: Optional[Path] = None
    commands_log_path: Optional[Path] = None
    tests_log_path: Optional[Path] = None
    acceptance_log_path: Optional[Path] = None
    final_report_path: Optional[Path] = None
    latest_report_path: Optional[Path] = None
    status_json_path: Optional[Path] = None
    latest_status_path: Optional[Path] = None
    command_history: List[Dict[str, object]] = []
    acceptance_items: List[str] = []
    acceptance_source_path: Optional[Path] = None

    def _relativize_path(path: Optional[Path]) -> str:
        if path is None:
            return ""
        try:
            return str(path.relative_to(project_root))
        except Exception:
            return str(path)

    def _ensure_report_dir() -> None:
        nonlocal errors_log_path
        nonlocal next_commands_path
        nonlocal commands_log_path
        nonlocal tests_log_path
        nonlocal acceptance_log_path
        nonlocal final_report_path
        nonlocal latest_report_path
        nonlocal status_json_path
        nonlocal latest_status_path
        nonlocal report_rel_path
        try:
            reports_base.mkdir(parents=True, exist_ok=True)
            report_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        errors_log_path = report_root / "errors.log"
        next_commands_path = report_root / "next-commands.txt"
        commands_log_path = report_root / "commands.log"
        tests_log_path = report_root / "tests.log"
        acceptance_log_path = report_root / "acceptance.txt"
        final_report_path = report_root / "task_report.md"
        latest_report_path = reports_base / "last_task_report.md"
        status_json_path = report_root / "status.json"
        latest_status_path = reports_base / "last_status.json"
        for target in (
            errors_log_path,
            next_commands_path,
            commands_log_path,
            tests_log_path,
            acceptance_log_path,
        ):
            try:
                if target:
                    target.write_text("", encoding="utf-8")
            except Exception:
                continue
        if status_json_path:
            try:
                status_json_path.write_text("{}", encoding="utf-8")
            except Exception:
                pass
        report_rel_path = _relativize_path(report_root)

    def _append_error_record(message: str) -> None:
        clean = message.strip()
        if not clean:
            return
        if clean not in error_records:
            error_records.append(clean)
        if errors_log_path is None:
            return
        try:
            with errors_log_path.open("a", encoding="utf-8") as handle:
                handle.write(clean + "\n")
        except Exception:
            return

    def _append_required_script(script: str) -> None:
        stripped = script.strip()
        if not stripped:
            return
        if stripped not in required_scripts:
            required_scripts.append(stripped)
        if next_commands_path is None:
            return
        try:
            with next_commands_path.open("a", encoding="utf-8") as handle:
                handle.write(stripped + "\n")
        except Exception:
            return

    script_archive_dir: Optional[Path] = None
    script_archive_counter = 0
    script_display_cache: Dict[str, str] = {}

    def _looks_like_script_blob(value: str) -> bool:
        if not isinstance(value, str):
            return False
        if "\n" not in value:
            return False
        stripped = value.lstrip()
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in SCRIPT_PREFIX_CANDIDATES):
            return True
        if stripped.startswith("#!") and "\n" in stripped:
            return True
        if stripped.startswith("```") or SCRIPT_FENCE_PATTERN.search(stripped):
            return True
        if SCRIPT_HEREDOC_PATTERN.search(value):
            return True
        return False

    def _archive_script_blob(raw_text: str, *, section: str) -> Optional[str]:
        nonlocal script_archive_dir, script_archive_counter
        if not isinstance(raw_text, str) or not raw_text:
            return None
        cached = script_display_cache.get(raw_text)
        if cached:
            return cached
        target_dir = project_root / "logs" / "scripts"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        script_archive_dir = target_dir
        script_archive_counter += 1
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        file_name = f"script_{timestamp}_{script_archive_counter:02d}.txt"
        target_path = target_dir / file_name
        payload_text = raw_text if raw_text.endswith("\n") else raw_text + "\n"
        try:
            target_path.write_text(payload_text, encoding="utf-8")
        except Exception:
            return None
        rel_path = _relativize_path(target_path)
        display_text = f"(script archived at {rel_path})"
        script_display_cache[raw_text] = display_text
        _append_guard_note(
            "script-archived",
            f"info — archived {section} script to {rel_path}; reference the logged file instead of embedding the code."
        )
        return display_text

    def _sanitize_section_scripts(section_name: str) -> None:
        entries = payload.get(section_name)
        if not isinstance(entries, list):
            return
        updated_entries: List[object] = []
        changed = False
        for entry in entries:
            if isinstance(entry, str) and _looks_like_script_blob(entry):
                archived_label = _archive_script_blob(entry, section=section_name)
                if archived_label:
                    updated_entries.append(archived_label)
                    changed = True
                    continue
            updated_entries.append(entry)
        if changed:
            payload[section_name] = updated_entries  # type: ignore[assignment]

    def _display_safe_command(command: str) -> str:
        if not isinstance(command, str):
            return str(command)
        cached = script_display_cache.get(command)
        if cached:
            return cached
        if _looks_like_script_blob(command):
            archived_label = _archive_script_blob(command, section="commands")
            if archived_label:
                return archived_label
        return command.replace("\n", "\\n")

    def _write_final_report(contents: str) -> None:
        targets: List[Path] = []
        if final_report_path is not None:
            targets.append(final_report_path)
        if latest_report_path is not None:
            targets.append(latest_report_path)
        for target in targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
            except Exception:
                continue

    def _compose_end_report(
        status: str,
        commands: Sequence[str],
        logs_directory: str,
        log_paths: Dict[str, str],
        acceptance_entries: Sequence[str],
    ) -> Tuple[str, str]:
        headline = status.strip() or "unknown"
        note_lines: List[str] = [
            "END OF TASK REPORT",
            f"Status: {headline}",
        ]
        if error_records:
            note_lines.append("Errors:")
            for item in error_records[:5]:
                note_lines.append(f"- {item}")
            if len(error_records) > 5:
                note_lines.append(f"- … ({len(error_records) - 5} more)")
        else:
            note_lines.append("Errors: none")
        scripts_section = required_scripts[:] if required_scripts else list(dict.fromkeys(commands))
        note_lines.append("Next scripts:")
        if scripts_section:
            for cmd in scripts_section[:5]:
                note_lines.append(f"- {cmd}")
            if len(scripts_section) > 5:
                note_lines.append(f"- … ({len(scripts_section) - 5} more)")
        else:
            note_lines.append("- (none)")

        if logs_directory:
            note_lines.append(f"Logs directory: {logs_directory}")
        if log_paths.get("errors"):
            note_lines.append(f"Errors log: {log_paths['errors']}")
        if log_paths.get("next_commands"):
            note_lines.append(f"Next-commands log: {log_paths['next_commands']}")
        if log_paths.get("commands"):
            note_lines.append(f"Commands log: {log_paths['commands']}")
        if log_paths.get("tests"):
            note_lines.append(f"Tests log: {log_paths['tests']}")
        if log_paths.get("acceptance"):
            note_lines.append(f"Acceptance log: {log_paths['acceptance']}")
        if log_paths.get("report"):
            note_lines.append(f"Report snapshot: {log_paths['report']}")

        file_lines: List[str] = [
            "## END OF TASK REPORT",
            "",
            f"Status: {headline}",
            "",
            "### Errors",
        ]
        if error_records:
            for item in error_records:
                file_lines.append(f"- {item}")
        else:
            file_lines.append("- none")
        file_lines.append("")
        file_lines.append("### Next Scripts")
        if scripts_section:
            for cmd in scripts_section:
                file_lines.append(f"- {cmd}")
        else:
            file_lines.append("- (none)")
        if logs_directory or any(log_paths.values()):
            file_lines.append("")
            file_lines.append("### Logs")
            if logs_directory:
                file_lines.append(f"- directory: {logs_directory}")
            for label, rel_path in log_paths.items():
                if label == "directory":
                    continue
                if not rel_path:
                    continue
                file_lines.append(f"- {label.replace('_', ' ')}: {rel_path}")
        file_lines.append("")
        file_lines.append("### Acceptance Criteria")
        if acceptance_entries:
            for entry in acceptance_entries:
                file_lines.append(f"- {entry}")
        else:
            file_lines.append("- (not available)")
        file_lines.append("")
        file_lines.append("Logged at: " + datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))

        return "\n".join(note_lines), "\n".join(file_lines) + "\n"

    def _maybe_truncate(text: str, limit: int = 20000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... (truncated; original length {len(text)} chars)"

    def _append_command_log(
        command: str,
        exit_code: int,
        stdout_text: str,
        stderr_text: str,
        is_test: bool,
    ) -> None:
        nonlocal command_history
        if commands_log_path is not None:
            entry_lines = [
                f"$ {command}",
                f"exit_code: {exit_code}",
            ]
            if stdout_text:
                entry_lines.append("stdout:")
                entry_lines.append(_maybe_truncate(stdout_text.rstrip("\n")))
            if stderr_text:
                entry_lines.append("stderr:")
                entry_lines.append(_maybe_truncate(stderr_text.rstrip("\n")))
            entry_lines.append("---")
            try:
                with commands_log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(entry_lines) + "\n")
            except Exception:
                pass
        if is_test and tests_log_path is not None:
            test_lines = [
                f"$ {command}",
                f"exit_code: {exit_code}",
            ]
            if stdout_text:
                test_lines.append("stdout:")
                test_lines.append(_maybe_truncate(stdout_text.rstrip("\n")))
            if stderr_text:
                test_lines.append("stderr:")
                test_lines.append(_maybe_truncate(stderr_text.rstrip("\n")))
            test_lines.append("---")
            try:
                with tests_log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(test_lines) + "\n")
            except Exception:
                pass
        command_history.append(
            {
                "command": command,
                "exit_code": exit_code,
                "is_test": bool(is_test),
            }
        )

    def _atomic_write_history(path: Path, data: str) -> None:
        tmp_file = None
        tmp_name = ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            tmp_file = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=str(path.parent),
            )
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_name = tmp_file.name
            tmp_file.close()
            os.replace(tmp_name, path)
        except Exception:
            if tmp_file is not None:
                try:
                    tmp_file.close()
                except Exception:
                    pass
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            raise

    def _normalize_section_entries(entries: Sequence[object]) -> List[str]:
        normalized: List[str] = []
        for entry in entries or []:
            if isinstance(entry, str):
                normalized.append(entry)
            elif entry is None:
                continue
            else:
                try:
                    normalized.append(json.dumps(entry, ensure_ascii=False))
                except TypeError:
                    normalized.append(str(entry))
        return normalized

    def _has_structured_response_sections(text: str) -> bool:
        if not text or not text.strip():
            return False
        sections = _extract_section_lines(text)
        if not sections:
            return False
        for required in REQUIRED_RESPONSE_SECTIONS:
            if required not in sections:
                return False
        heading_order: List[int] = []
        seen_labels: Set[str] = set()
        for line in text.splitlines():
            candidate = line.strip().rstrip(':').strip()
            normalized = candidate.strip("*_# ").lower()
            if normalized in REQUIRED_RESPONSE_SECTIONS and normalized not in seen_labels:
                seen_labels.add(normalized)
                heading_order.append(REQUIRED_RESPONSE_SECTIONS.index(normalized))
        return heading_order[:len(REQUIRED_RESPONSE_SECTIONS)] == list(range(len(REQUIRED_RESPONSE_SECTIONS)))

    def _render_structured_response(
        plan_entries: Sequence[object],
        focus_entries: Sequence[object],
        command_entries: Sequence[object],
        note_entries: Sequence[object],
    ) -> str:
        buffer: List[str] = []
        _append_section_block(buffer, "Plan", _normalize_section_entries(plan_entries))
        _append_section_block(buffer, "Focus", _normalize_section_entries(focus_entries))
        _append_section_block(
            buffer,
            "Commands",
            _normalize_section_entries(command_entries),
            preserve_indent=True,
        )
        _append_section_block(buffer, "Notes", _normalize_section_entries(note_entries))
        while buffer and buffer[-1] == "":
            buffer.pop()
        return ("\n".join(buffer).rstrip() + "\n") if buffer else ""

    guard_events: List[Dict[str, str]] = []

    def _record_guard_event(code: str, detail: str) -> None:
        guard_events.append(
            {
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "code": code,
                "detail": detail,
            }
        )

    HEREDOC_PLACEHOLDER_PATTERN = re.compile(r"<<-?\s*(?:'|\")?([A-Za-z0-9_+\-]+)(?:'|\")?")

    def _find_unterminated_heredoc_marker(command: str) -> Optional[str]:
        if not command or "<<" not in command:
            return None
        for match in HEREDOC_PLACEHOLDER_PATTERN.finditer(command):
            label = match.group(1)
            tail = command[match.end():]
            closing_pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.MULTILINE)
            if not closing_pattern.search(tail):
                return label
        return None

    def _rewrite_command_placeholders(commands: Sequence[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
        updated: List[str] = []
        placeholders: List[Tuple[str, str]] = []
        for raw in commands:
            if not isinstance(raw, str):
                updated.append(raw)
                continue
            reason = None
            if "..." in raw or "…" in raw:
                reason = "ellipsis"
            else:
                label = _find_unterminated_heredoc_marker(raw)
                if label:
                    reason = f"missing terminator for {label}"
            if reason:
                snippet = _truncate_command_text(raw)
                updated.append(f"# TODO – replace placeholder ({reason}): {snippet}")
                placeholders.append((snippet, reason))
            else:
                updated.append(raw)
        return updated, placeholders

    def _append_section_block(
        buffer: List[str],
        title: str,
        entries: Sequence[str],
        *,
        preserve_indent: bool = False,
    ) -> None:
        buffer.append(title)
        if entries:
            for item in entries:
                if isinstance(item, str):
                    text = item.rstrip()
                    if not preserve_indent:
                        text = text.strip()
                else:
                    text = str(item)
                buffer.append(f"- {text}")
        else:
            buffer.append("- (none)")
        buffer.append("")

    def _flush_guard_events() -> None:
        if not guard_events:
            return
        guard_dir = project_root / "logs" / "guardrails"
        try:
            guard_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        events_path = guard_dir / "events.jsonl"
        counts: Dict[str, int] = {}
        try:
            with events_path.open("a", encoding="utf-8") as handle:
                for event in guard_events:
                    enriched = dict(event)
                    enriched.update(
                        {
                            "task_id": active_task_id,
                            "task_number": task_number,
                            "story_slug": task_slug,
                            "run": run_timestamp,
                        }
                    )
                    handle.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                    counts[event["code"]] = counts.get(event["code"], 0) + 1
        except Exception:
            return
        rel_path = _relativize_path(events_path)
        summary = ", ".join(f"{code}={count}" for code, count in sorted(counts.items()))
        manual_notes.append(
            _format_action_result(
                "guard-telemetry",
                f"recorded {len(guard_events)} guard event(s): {summary}; see {rel_path}",
            )
        )

    def _persist_agent_sections(
        plan_entries: Sequence[object],
        focus_entries: Sequence[object],
        command_entries: Sequence[object],
        note_entries: Sequence[object],
        raw_text: str,
        canonical_status: str,
    ) -> None:
        output_hint = os.environ.get("GC_ACTIVE_TASK_OUTPUT", "").strip()
        run_hint = (os.environ.get("RUN_DIR") or os.environ.get("GC_RUN_DIR") or "").strip()
        base_dir: Optional[Path] = None
        if output_hint:
            try:
                output_obj = Path(output_hint)
                base_dir = output_obj.parent.parent
            except Exception:
                base_dir = None
        if base_dir is None and run_hint:
            try:
                base_dir = Path(run_hint)
            except Exception:
                base_dir = None
        if base_dir is None:
            return
        try:
            base_dir = base_dir.resolve()
        except Exception:
            pass
        history_root = base_dir / "history"
        task_number = (os.environ.get("GC_ACTIVE_TASK_NUMBER") or "").strip()
        story_slug = (os.environ.get("GC_ACTIVE_TASK_SLUG") or "").strip()
        task_id_env = os.environ.get("GC_ACTIVE_TASK_ID") or os.environ.get("GC_BUDGET_TASK_ID") or ""
        task_id = task_id_env.strip()
        run_stamp = (os.environ.get("GC_ACTIVE_RUN_STAMP") or "").strip()
        attempt_counter = (os.environ.get("GC_RETRY_ATTEMPTS") or "").strip()
        label_parts = []
        if task_number:
            label_parts.append(f"task-{task_number}")
        if story_slug:
            label_parts.append(story_slug)
        if task_id:
            label_parts.append(task_id)
        label_source = "-".join(part for part in label_parts if part) or "task"
        task_dir_name = _sanitize_for_path(label_source) or "task"
        history_dir = history_root / task_dir_name
        plan_list = _normalize_section_entries(plan_entries)
        focus_list = _normalize_section_entries(focus_entries)
        command_list = _normalize_section_entries(command_entries)
        note_list = _normalize_section_entries(note_entries)
        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%dT%H%M%S")
        suffix = f"{timestamp}{now.microsecond:06d}"
        summary_path = history_dir / f"summary_{suffix}.md"
        raw_path = history_dir / f"output_{suffix}.md"
        meta_path = history_dir / f"summary_{suffix}.meta.txt"
        summary_lines: List[str] = [
            f"# Task Summary — {task_number or '(unknown)'}",
            "",
            f"- Story: {story_slug or '(unknown)'}",
            f"- Task ID: {task_id or '(unknown)'}",
            f"- Run: {run_stamp or '(unspecified)'}",
            f"- Attempt: {attempt_counter or '1'}",
            f"- Status: {canonical_status or 'UNKNOWN'}",
            "",
        ]
        _append_section_block(summary_lines, "Plan", plan_list)
        _append_section_block(summary_lines, "Focus", focus_list)
        _append_section_block(summary_lines, "Commands", command_list, preserve_indent=True)
        _append_section_block(summary_lines, "Notes", note_list)
        summary_text = "\n".join(summary_lines).rstrip() + "\n"
        raw_body = raw_text if raw_text.endswith("\n") else raw_text + ("\n" if raw_text else "\n")
        try:
            history_dir.mkdir(parents=True, exist_ok=True)
            def _render_section_content(entries: Sequence[str], *, preserve_indent: bool = False) -> str:
                lines: List[str] = []
                if entries:
                    for item in entries:
                        text = str(item)
                        text = text.rstrip()
                        if not preserve_indent:
                            text = text.strip()
                        lines.append(f"- {text}")
                else:
                    lines.append("- (none)")
                lines.append("")
                body = "\n".join(lines)
                return body if body.endswith("\n") else body + "\n"

            artifact_task_id = task_id or task_db_id

            def _store_section_artifact(label: str, entries: Sequence[str], *, preserve_indent: bool = False) -> None:
                file_stub = f"{label.lower()}_{suffix}.md"
                section_path = history_dir / file_stub
                latest_section_path = history_dir / f"latest.{label.lower()}.md"
                content = _render_section_content(entries, preserve_indent=preserve_indent)
                _atomic_write_history(section_path, content)
                _atomic_write_history(latest_section_path, content)
                rel_section = _relativize_path(section_path)
                if artifact_task_id:
                    _record_task_artifact(artifact_task_id, label.lower(), rel_section)

            _store_section_artifact("Plan", plan_list)
            _store_section_artifact("Focus", focus_list)
            _store_section_artifact("Commands", command_list, preserve_indent=True)
            _store_section_artifact("Notes", note_list)
            _atomic_write_history(summary_path, summary_text)
            if artifact_task_id:
                _record_task_artifact(artifact_task_id, "summary", _relativize_path(summary_path))
            _atomic_write_history(history_dir / "latest.summary.md", summary_text)
            _atomic_write_history(raw_path, raw_body)
            if artifact_task_id:
                _record_task_artifact(artifact_task_id, "output", _relativize_path(raw_path))
            _atomic_write_history(history_dir / "latest.output.md", raw_body)
            meta_lines = [
                f"recorded_at: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                f"status: {canonical_status or 'UNKNOWN'}",
                f"task_id: {task_id or '(unknown)'}",
                f"task_number: {task_number or '(unknown)'}",
                f"story_slug: {story_slug or '(unknown)'}",
                f"run_stamp: {run_stamp or '(unspecified)'}",
                f"attempt: {attempt_counter or '1'}",
                f"summary_path: {_relativize_path(summary_path)}",
                f"raw_path: {_relativize_path(raw_path)}",
                "",
            ]
            def _append_plain_section(name: str, entries: Sequence[str]) -> None:
                meta_lines.append(f"{name}:")
                if entries:
                    for item in entries:
                        meta_lines.append(f"- {item}")
                else:
                    meta_lines.append("- (none)")
                meta_lines.append("")
            _append_plain_section("plan", plan_list)
            _append_plain_section("focus", focus_list)
            _append_plain_section("commands", command_list)
            _append_plain_section("notes", note_list)
            meta_text = "\n".join(meta_lines).rstrip() + "\n"
            _atomic_write_history(meta_path, meta_text)
            if artifact_task_id:
                _record_task_artifact(artifact_task_id, "summary-meta", _relativize_path(meta_path))
            _atomic_write_history(history_dir / "latest.summary.txt", meta_text)
            rel_summary = _relativize_path(summary_path)
            manual_notes.append(
                _format_action_result(
                    "run-history",
                    f"note — cached plan/focus snapshot at {rel_summary}"
                )
            )
        except Exception as exc:
            manual_notes.append(
                _format_action_result(
                    "run-history",
                    f"warning — unable to cache agent summary: {exc}"
                )
            )

    def _normalize_acceptance_entry(text: str) -> str:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^[\-\*\d\)\(.\s]+", "", cleaned)
        return cleaned.strip()

    def _extract_acceptance_from_text(text: str) -> List[str]:
        if not text:
            return []
        lines = text.splitlines()
        capture = False
        items: List[str] = []
        for line in lines:
            if re.match(r"^#{1,6}\s+Acceptance Criteria\s*$", line.strip(), re.IGNORECASE):
                capture = True
                continue
            if capture and re.match(r"^#{1,6}\s+\S", line.strip()):
                break
            if capture:
                stripped = line.strip()
                if not stripped:
                    continue
                bullet_match = re.match(r"^[-*\u2022]\s*(.+)$", stripped)
                if bullet_match:
                    item = _normalize_acceptance_entry(bullet_match.group(1))
                    if item:
                        items.append(item)
                    continue
                ordinal_match = re.match(r"^\d+[\).]\s*(.+)$", stripped)
                if ordinal_match:
                    item = _normalize_acceptance_entry(ordinal_match.group(1))
                    if item:
                        items.append(item)
                    continue
                fallback = _normalize_acceptance_entry(stripped)
                if fallback:
                    items.append(fallback)
        return items

    def _collect_acceptance_requirements(payload_obj: Dict[str, object]) -> Tuple[List[str], Optional[Path]]:
        collected: List[str] = []
        seen: Set[str] = set()

        def _extend_from_value(value: object) -> None:
            nonlocal collected, seen
            entries: List[str] = []
            if isinstance(value, list):
                entries = [str(item) for item in value]
            elif isinstance(value, str):
                raw_lines = re.split(r"[\r\n]+", value)
                entries = [line for line in raw_lines if line.strip()]
            if not entries:
                return
            for entry in entries:
                normalized = _normalize_acceptance_entry(entry)
                key = normalized.lower()
                if normalized and key not in seen:
                    seen.add(key)
                    collected.append(normalized)

        candidate_keys = (
            'acceptance',
            'acceptance_criteria',
            'acceptanceCriteria',
            'acceptanceRequirements',
            'acceptance_requirements',
        )

        if isinstance(payload_obj, dict):
            for key in candidate_keys:
                _extend_from_value(payload_obj.get(key))
            for nested_key in ('task', 'context', 'details'):
                nested = payload_obj.get(nested_key)
                if isinstance(nested, dict):
                    for key in candidate_keys:
                        _extend_from_value(nested.get(key))

        prompt_source: Optional[Path] = None
        prompt_env = os.environ.get("GC_ACTIVE_TASK_PROMPT", "").strip()
        if prompt_env:
            prompt_candidate = Path(prompt_env)
            if not prompt_candidate.is_absolute():
                prompt_candidate = project_root / prompt_env
            if prompt_candidate.exists():
                prompt_source = prompt_candidate
                try:
                    prompt_text = prompt_candidate.read_text(encoding="utf-8")
                except Exception:
                    prompt_text = ""
                for entry in _extract_acceptance_from_text(prompt_text):
                    key = entry.lower()
                    if entry and key not in seen:
                        seen.add(key)
                        collected.append(entry)

        return collected, prompt_source

    def _write_acceptance_log(items: Sequence[str]) -> None:
        if acceptance_log_path is None:
            return
        try:
            acceptance_log_path.write_text(
                "\n".join(f"- {entry}" for entry in items) + ("\n" if items else ""),
                encoding="utf-8",
            )
        except Exception:
            return

    def _looks_like_test_command(command: str) -> bool:
        lowered = command.lower()
        patterns = (
            " test",
            "test:",
            "pytest",
            "jest",
            "vitest",
            "go test",
            "npm test",
            "pnpm test",
            "yarn test",
            "cargo test",
            "mvn test",
            "gradlew test",
            "dotnet test",
        )
        return any(token in lowered for token in patterns)

    def _write_status_snapshot(
        status_value: str,
        logs_directory: str,
        acceptance_source: Optional[Path],
    ) -> None:
        if status_json_path is None:
            return
        logs_map = {
            "directory": logs_directory,
            "errors": _relativize_path(errors_log_path),
            "next_commands": _relativize_path(next_commands_path),
            "commands": _relativize_path(commands_log_path),
            "tests": _relativize_path(tests_log_path),
            "acceptance": _relativize_path(acceptance_log_path),
            "report": _relativize_path(final_report_path),
            "status": _relativize_path(status_json_path),
        }
        snapshot = {
            "task": {
                "id": active_task_id,
                "slug": task_slug,
                "number": task_number,
            },
            "status": status_value,
            "timestamp": run_timestamp,
            "logs": logs_map,
            "commands": command_history,
            "acceptance": {
                "items": acceptance_items,
                "source_path": _relativize_path(acceptance_source) if acceptance_source else "",
                "log_path": _relativize_path(acceptance_log_path),
            },
        }
        try:
            status_json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if latest_status_path is not None:
                latest_status_path.parent.mkdir(parents=True, exist_ok=True)
                latest_status_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            return

    _ensure_report_dir()

    acceptance_items, acceptance_source_path = _collect_acceptance_requirements(payload)
    _write_acceptance_log(acceptance_items)

    required_scripts_env = os.environ.get("WORK_ON_TASKS_REQUIRED_SCRIPTS", "")
    if required_scripts_env:
        for candidate in re.split(r"[;\n,]", required_scripts_env):
            candidate = candidate.strip()
            if candidate:
                _append_required_script(candidate)

    if code_sample_detected:
        _append_guard_note(
            "code-sample-detected",
            "warning — response contained source/test snippets; restate steps without including code"
        )
    if parse_failure_detected:
        _append_guard_note(
            "agent-output-parse",
            "warning — response unparsable; skipped task instructions and continued to next item"
        )

    existing_notes = payload.get('notes')
    long_note_dir: Optional[Path] = None
    long_note_counter = 0
    if isinstance(existing_notes, list):
        cleaned_notes: List[str] = []
        reasoning_chars = 0
        longform_flag = False
        non_action_streak = 0
        stop_prompt_sent = False
        autoformatted_notes = 0
        last_lint_remaining: Optional[int] = None
        for entry in existing_notes:
            if not isinstance(entry, str):
                continue
            if _looks_like_script_blob(entry):
                archived_label = _archive_script_blob(entry, section="notes")
                if archived_label:
                    cleaned_notes.append(
                        _format_action_result("script-archive", f"logged under {archived_label}")
                    )
                    continue
            text = entry.strip()
            if not text:
                continue
            reasoning_chars += len(text)
            has_action = _has_action_token(text)
            if not has_action:
                text, auto_fmt_applied = _autoformat_note_entry(text)
                if auto_fmt_applied:
                    has_action = True
                    autoformatted_notes += 1
            if len(text) > NOTE_CHAR_LIMIT and not has_action:
                longform_flag = True
                full_text = text
                long_note_counter += 1
                if long_note_dir is None:
                    long_note_dir = project_root / "logs" / "notes"
                    long_note_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
                suffix = f"{long_note_counter:02d}"
                note_filename = f"note_{timestamp}_{suffix}.txt"
                archived_path = long_note_dir / note_filename
                archived_path.write_text(full_text, encoding='utf-8')
                try:
                    rel_path = archived_path.relative_to(project_root)
                    text = str(rel_path)
                except Exception:
                    text = str(archived_path)
            cleaned_notes.append(text)
            if has_action:
                non_action_streak = 0
            else:
                non_action_streak += 1
                remaining = max(0, MAX_CONSECUTIVE_NON_ACTION_NOTES - non_action_streak)
                if remaining <= 1 and last_lint_remaining != remaining:
                    countdown = max(0, remaining)
                    plural = '' if countdown == 1 else 's'
                    warning_message = (
                        "warning — "
                        + ("only 1 narration note" if countdown == 1 else f"{countdown} narration note{plural}" if countdown > 1 else "next narration note")
                        + " before the Plan/Focus/Commands/Notes guard triggers; switch back to Action/Result bullets now"
                    )
                    _append_guard_note(
                        "notes-lint-warning",
                        warning_message,
                    )
                    last_lint_remaining = countdown
                if (
                    non_action_streak > MAX_CONSECUTIVE_NON_ACTION_NOTES
                    and not stop_prompt_sent
                ):
                    _append_guard_note(
                        "notes-stop-and-plan",
                        "blocked — convert narration into actionable checklist tied to upcoming commands before continuing"
                    )
                    stop_prompt_sent = True
        payload['notes'] = cleaned_notes
        if autoformatted_notes:
            suffix = "s" if autoformatted_notes > 1 else ""
            _append_guard_note(
                "notes-autoformat",
                f"normalized {autoformatted_notes} narrative note{suffix} into Action/Result format to satisfy the response guard",
            )
        if longform_flag:
            _append_guard_note(
                "notes-trim-longform",
                "blocked — detected long-form notes; saved full content under logs/notes/*.txt and kept note entries referencing those paths. Restate as Action/Result bullets pointing to the archived files."
            )
        if reasoning_chars > NOTE_REASONING_BUDGET_CHARS:
            _append_guard_note(
                "notes-reasoning-budget",
                "warning — cumulative reasoning exceeded ~1.5k tokens; keep subsequent updates concise and command-linked"
            )
    elif existing_notes is not None:
        payload['notes'] = []

    if not _has_structured_response_sections(canonical_response_text):
        canonical_response_text = _render_structured_response(
            payload.get('plan') or [],
            payload.get('focus') or [],
            payload.get('commands') or [],
            payload.get('notes') or [],
        ) or canonical_response_text
        if canonical_response_text != raw_text_original:
            _append_guard_note(
                "response-autoformat",
                "info — original reply lacked Plan/Focus/Commands/Notes headings; generated canonical template automatically",
            )
    actual_changes = 0
    documentation_only_run = False
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

    PLAN_ARTIFACT_CANDIDATES: Tuple[str, ...] = (
        "PLAN.md",
        "Plan.md",
        "plan.md",
        "PLAN",
        "Plan",
        "plan",
    )

    def _remove_plan_artifacts(trigger_label: str = "") -> None:
        removed: List[str] = []
        for candidate_name in PLAN_ARTIFACT_CANDIDATES:
            try:
                candidate_path = ensure_within_root(Path(candidate_name))
            except Exception:
                continue
            try:
                if not candidate_path.exists():
                    continue
                if candidate_path.is_symlink() or candidate_path.is_file():
                    candidate_path.unlink()
                elif candidate_path.is_dir():
                    shutil.rmtree(candidate_path)
                else:
                    candidate_path.unlink()
                removed.append(candidate_name)
            except FileNotFoundError:
                continue
            except OSError as exc:
                _append_guard_note(
                    "plan-guard",
                    f"warning — unable to remove forbidden {candidate_name}: {exc}"
                )
        if removed:
            unique = ", ".join(sorted(set(removed)))
            suffix = f" after {trigger_label}" if trigger_label else ""
            _append_guard_note(
                "plan-guard",
                f"auto-removed forbidden PLAN artifact(s): {unique}{suffix}"
            )

    _remove_plan_artifacts("startup")

    def _run_python_heredoc(code: str) -> CompletedProcess:
        script_text = code if code.endswith('\n') else code + '\n'
        tmp_path = None
        helper_path = project_root / "scripts" / "python" / "run_snippet.py"
        try:
            tmp_file = tempfile.NamedTemporaryFile('w', suffix='.py', delete=False)
            tmp_path = Path(tmp_file.name)
            tmp_file.write(script_text)
            tmp_file.flush()
            tmp_file.close()
            exec_args = ['python3']
            if helper_path.exists():
                exec_args.extend([str(helper_path), str(tmp_path)])
            else:
                exec_args.append(str(tmp_path))
            proc = subprocess.run(
                exec_args,
                capture_output=True,
                text=True,
                cwd=str(project_root),
                timeout=apply_timeout,
                check=False,
            )
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return proc

    def _run_shell_script(script: str) -> CompletedProcess:
        shebang = "#!/usr/bin/env bash\n"
        header = "set -euo pipefail\nIFS=$' \\n\\t'\n"
        body = script if script.endswith('\n') else script + '\n'
        tmp_path = None
        try:
            tmp_file = tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False, dir=str(project_root))
            tmp_path = Path(tmp_file.name)
            tmp_file.write(shebang)
            tmp_file.write(header)
            tmp_file.write(body)
            tmp_file.flush()
            tmp_file.close()
            try:
                os.chmod(tmp_path, 0o700)
            except OSError:
                pass
            proc = subprocess.run(
                ['bash', str(tmp_path)],
                capture_output=True,
                text=True,
                cwd=str(project_root),
                timeout=apply_timeout,
                check=False,
            )
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return proc

    def _can_run_direct(command: str) -> bool:
        return not any(ch in command for ch in SHELL_META_CHARS)

    def _ensure_test_serialization(
        command_text: str, tokens: Optional[List[str]]
    ) -> Tuple[str, Optional[List[str]]]:
        if not tokens:
            return command_text, tokens
        mutated = False
        normalized = command_text.lower()
        new_tokens: List[str] = list(tokens)

        if (JEST_PATTERN.search(command_text) or PNPM_JEST_PATTERN.search(normalized)) and not RUN_IN_BAND_PATTERN.search(normalized):
            new_tokens.append("--runInBand")
            mutated = True

        if VITEST_PATTERN.search(normalized):
            has_threads_flag = any(
                THREADS_FLAG_PATTERN.match(tok) for tok in new_tokens
            )
            if not has_threads_flag:
                new_tokens.extend(["--threads", "1"])
                mutated = True

        if not mutated:
            return command_text, tokens

        serialized = " ".join(shlex.quote(tok) for tok in new_tokens)
        return serialized, new_tokens

    def _rewrite_tsc_command(
        command_text: str, tokens: Optional[List[str]]
    ) -> Tuple[str, Optional[List[str]]]:
        if not tokens or not TSC_PATTERN.search(command_text):
            return command_text, tokens

        new_tokens: List[str] = list(tokens)

        def _has_flag(name: str) -> bool:
            lower_name = name.lower()
            for tok in new_tokens:
                lt = tok.lower()
                if lt == lower_name or lt.startswith(f"{lower_name}="):
                    return True
            return False

        if not _has_flag("--skipLibCheck"):
            new_tokens.append("--skipLibCheck")
        # Always force pretty false at the end so diagnostics stay compact.
        new_tokens.extend(["--pretty", "false"])
        # Always ensure we emit even on errors.
        new_tokens.extend(["--noEmitOnError", "false"])

        rewritten = " ".join(shlex.quote(tok) for tok in new_tokens)
        return rewritten, new_tokens

    def _apply_mock_shims(
        command_text: str, tokens: Optional[List[str]]
    ) -> Tuple[str, Optional[List[str]]]:
        if os.environ.get("GC_MOCK_DEPS", "0") != "1" or not tokens:
            return command_text, tokens

        def _matches_runner(token: str, target: str) -> bool:
            normalized = token.lower().replace("\\", "/")
            if normalized == target:
                return True
            if normalized.endswith(f"/{target}"):
                return True
            if normalized.endswith(f"{target}.js"):
                return True
            return False

        mutated = False
        new_tokens: List[str] = list(tokens)
        if any(_matches_runner(tok, "jest") for tok in new_tokens):
            if not any(tok.lower() == "--runinband" for tok in new_tokens):
                new_tokens.append("--runInBand")
                mutated = True
        if any(_matches_runner(tok, "vitest") for tok in new_tokens):
            if not any(tok.lower().startswith("--threads") for tok in new_tokens):
                new_tokens.extend(["--threads", "1"])
                mutated = True

        if not mutated:
            return command_text, tokens
        decorated = " ".join(shlex.quote(tok) for tok in new_tokens)
        return decorated, new_tokens

    def _normalize_rg_command(
        command_text: str, tokens: Optional[List[str]]
    ) -> Tuple[str, Optional[List[str]]]:
        if not tokens or not tokens:
            return command_text, tokens
        if tokens[0] != "rg":
            return command_text, tokens
        if "--" in tokens:
            return command_text, tokens
        idx = 1
        while idx < len(tokens) and tokens[idx].startswith("-"):
            idx += 1
        if idx >= len(tokens):
            return command_text, tokens
        pattern_index = idx
        normalized = tokens[:pattern_index + 1]
        changed = False
        idx += 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok.startswith("-"):
                changed = True
            else:
                normalized.append(tok)
            idx += 1
        if not changed:
            return command_text, tokens
        rewritten_command = " ".join(shlex.quote(tok) for tok in normalized)
        return rewritten_command, normalized

    def _rewrite_command_pipeline(
        command_text: str, tokens: Optional[List[str]]
    ) -> Tuple[str, Optional[List[str]]]:
        current_text, current_tokens = _ensure_test_serialization(command_text, tokens)
        current_text, current_tokens = _rewrite_tsc_command(current_text, current_tokens)
        current_text, current_tokens = _normalize_rg_command(current_text, current_tokens)
        current_text, current_tokens = _apply_mock_shims(current_text, current_tokens)
        return current_text, current_tokens

    def _parse_replacement_script(source: str):
        import ast

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None, None, None

        path_value = None
        old_value = None
        new_value = None

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id
                    if name == "path":
                        call = node.value
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Name)
                            and call.func.id == "Path"
                            and call.args
                        ):
                            try:
                                path_value = ast.literal_eval(call.args[0])
                            except Exception:
                                path_value = None
                    elif name in {"old", "new"}:
                        try:
                            value = ast.literal_eval(node.value)
                        except Exception:
                            value = None
                        if name == "old":
                            old_value = value
                        else:
                            new_value = value
        return path_value, old_value, new_value

    def _handle_pattern_not_found(code: Optional[str], stdout_text: str, stderr_text: str) -> Optional[str]:
        if code is None:
            return None
        combined = f"{stdout_text}\n{stderr_text}".lower()
        if "pattern not found" not in combined:
            return None
        path_str, old_value, new_value = _parse_replacement_script(code)
        if not path_str:
            return None
        try:
            target_path = ensure_within_root(Path(path_str))
            content = target_path.read_text(encoding='utf-8')
        except Exception:
            return None
        if old_value and isinstance(old_value, str) and old_value in content:
            return None
        if new_value and isinstance(new_value, str) and new_value not in content:
            return None
        return f"skipped — pattern already updated in {path_str}"

    def _handle_permission_error(command: str, stdout_text: str, stderr_text: str) -> Optional[str]:
        combined = f"{stdout_text}\n{stderr_text}".lower()
        if "eacces" not in combined:
            return None
        lowered_command = command.lower()
        if "prisma:generate" in lowered_command:
            return "skipped — Prisma generate blocked by sandbox permissions; rerun outside this environment"
        return None

    def _handle_build_failure(command: str, stdout_text: str, stderr_text: str) -> Optional[str]:
        lowered_command = command.lower()
        if "pnpm" not in lowered_command or "build" not in lowered_command:
            return None
        combined = f"{stdout_text}\n{stderr_text}".lower()
        if "error ts" in combined or "typescript" in combined or "diagnostic" in combined:
            return "skipped — pnpm build blocked by existing TypeScript errors; run package-specific builds or address baseline issues"
        return None

    def _handle_jest_baseline_failure(command: str, stdout_text: str, stderr_text: str) -> Optional[str]:
        lowered_command = command.lower()
        if "pnpm" not in lowered_command or "test" not in lowered_command:
            return None
        combined = f"{stdout_text}\n{stderr_text}".lower()
        if "cannot find module '../auth/session-role.util'" in combined:
            return "skipped — Jest suite blocked by missing compiled session-role util; rebuild dist or adjust imports before retrying"
        if "jest encountered an unexpected token" in combined and "auth.service.js" in combined:
            return "skipped — Jest suite blocked by stale dist/auth artifacts; clean dist output before rerunning tests"
        if "jest worker process" in combined and "exitcode=0" in combined:
            return "skipped — Jest workers crashed immediately in this environment; rerun locally once the worker issue is resolved"
        return None

    def _resolve_task_commit_ref() -> str:
        task_id = os.environ.get("GC_ACTIVE_TASK_ID") or os.environ.get("GC_BUDGET_TASK_ID")
        if task_id:
            return task_id
        slug = os.environ.get("GC_ACTIVE_TASK_SLUG") or os.environ.get("GC_ACTIVE_STORY_SLUG")
        task_number = os.environ.get("GC_ACTIVE_TASK_NUMBER")
        if slug and task_number:
            return f"{slug}-{task_number}"
        task_index = os.environ.get("GC_ACTIVE_TASK_INDEX")
        if slug and task_index and task_index.isdigit():
            try:
                ordinal = int(task_index) + 1
            except ValueError:
                ordinal = task_index
            return f"{slug}-{ordinal}"
        return "work-on-tasks"

    def _auto_commit_and_push_if_needed(changes_detected: int) -> Tuple[bool, List[str]]:
        _ = changes_detected  # retained for backward compatibility; behavior no longer gated by this count
        notes: List[str] = []
        if os.environ.get("WORK_ON_TASKS_AUTO_COMMIT", "1") == "0":
            notes.append(
                _format_action_result(
                    "auto-commit",
                    "skip — WORK_ON_TASKS_AUTO_COMMIT=0"
                )
            )
            return True, notes
        safe_check = _run_git_command(['config', '--global', '--get-all', 'safe.directory'])
        safe_listing = (safe_check.stdout or "").splitlines() if safe_check.returncode == 0 else []
        if str(project_root) not in safe_listing:
            _run_git_command(['config', '--global', '--add', 'safe.directory', str(project_root)])

        def _ensure_git_identity() -> None:
            identity_defaults = (
                ("user.name", os.environ.get("WORK_ON_TASKS_GIT_NAME", "automation")),
                ("user.email", os.environ.get("WORK_ON_TASKS_GIT_EMAIL", "automation@local")),
            )
            for key, default_value in identity_defaults:
                probe = _run_git_command(['config', '--get', key])
                if probe.returncode != 0 or not (probe.stdout or "").strip():
                    _run_git_command(['config', key, default_value])

        _ensure_git_identity()
        add_proc = _run_git_command(['add', '-A'])
        if add_proc.returncode != 0:
            stderr_text = (add_proc.stderr or "").strip()
            notes.append(
                _format_action_result(
                    "git add -A",
                    f"failed — exit {add_proc.returncode}; {stderr_text or 'see stderr'}"
                )
            )
            return False, notes
        commit_message = os.environ.get("WORK_ON_TASKS_COMMIT_MESSAGE")
        if not commit_message:
            task_ref = _resolve_task_commit_ref()
            commit_suffix = os.environ.get("WORK_ON_TASKS_COMMIT_SUFFIX", "automated changes")
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            commit_message = f"{task_ref}: {commit_suffix} ({timestamp} UTC)"
        commit_proc = _run_git_command(['commit', '--allow-empty', '-m', commit_message])
        if commit_proc.returncode != 0:
            stderr_text = (commit_proc.stderr or "").strip()
            notes.append(
                _format_action_result(
                    "git commit",
                    f"failed — exit {commit_proc.returncode}; {stderr_text or 'see stderr'}"
                )
            )
            return False, notes
        notes.append(
            _format_action_result(
                "git commit",
                f"success — {commit_message}"
            )
        )
        push_remote = os.environ.get("WORK_ON_TASKS_PUSH_REMOTE", "origin")
        branch_proc = _run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'])
        branch_name = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
        if branch_proc.returncode != 0 or not branch_name:
            stderr_text = (branch_proc.stderr or "").strip()
            notes.append(
                _format_action_result(
                    "git rev-parse --abbrev-ref HEAD",
                    f"failed — exit {branch_proc.returncode}; {stderr_text or 'see stderr'}"
                )
            )
            return False, notes
        push_proc = _run_git_command(['push', push_remote, branch_name])
        if push_proc.returncode != 0:
            stderr_text = (push_proc.stderr or "").strip()
            stdout_text = (push_proc.stdout or "").strip()
            if _is_remote_access_error(stderr_text, stdout_text):
                summary = stderr_text or stdout_text or "see stderr"
                if len(summary) > 240:
                    summary = summary[:237].rstrip() + "…"
                notes.append(
                    _format_action_result(
                        f"git push {push_remote} {branch_name}",
                        f"skipped — remote {push_remote} unreachable ({summary}); commit remains local"
                    )
                )
                notes.append(
                    _format_action_result(
                        "manual-push-reminder",
                        f"once network/credentials are fixed, run `git push {push_remote} {branch_name}` manually."
                    )
                )
                return True, notes
            notes.append(
                _format_action_result(
                    f"git push {push_remote} {branch_name}",
                    f"failed — exit {push_proc.returncode}; {stderr_text or 'see stderr'}"
                )
            )
            rebase_proc = _run_git_command(['pull', '--rebase', '--autostash', push_remote, branch_name])
            if rebase_proc.returncode == 0:
                retry_proc = _run_git_command(['push', push_remote, branch_name])
                if retry_proc.returncode == 0:
                    notes.append(
                        _format_action_result(
                            f"git push {push_remote} {branch_name} (after rebase)",
                            "success"
                        )
                    )
                    return True, notes
                retry_stderr = (retry_proc.stderr or "").strip()
                notes.append(
                    _format_action_result(
                        f"git push {push_remote} {branch_name} (after rebase)",
                        f"failed — exit {retry_proc.returncode}; {retry_stderr or 'see stderr'}"
                    )
                )
            else:
                rebase_stderr = (rebase_proc.stderr or "").strip()
                notes.append(
                    _format_action_result(
                        f"git pull --rebase --autostash {push_remote} {branch_name}",
                        f"failed — exit {rebase_proc.returncode}; {rebase_stderr or 'see stderr'}"
                    )
                )
            timestamp_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            fallback_branch = f"{branch_name}-fallback-{timestamp_suffix}"
            fallback_proc = _run_git_command(['push', push_remote, f"HEAD:refs/heads/{fallback_branch}"])
            if fallback_proc.returncode == 0:
                notes.append(
                    _format_action_result(
                        f"git push {push_remote} HEAD:refs/heads/{fallback_branch}",
                        "success (fallback branch)"
                    )
                )
                return True, notes
            fallback_stderr = (fallback_proc.stderr or "").strip()
            notes.append(
                _format_action_result(
                    f"git push {push_remote} HEAD:refs/heads/{fallback_branch}",
                    f"failed — exit {fallback_proc.returncode}; {fallback_stderr or 'see stderr'}"
                )
            )
            return False, notes
        notes.append(
            _format_action_result(
                f"git push {push_remote} {branch_name}",
                "success"
            )
        )
        return True, notes

    def _resolve_alt_path(rel_path: str) -> Optional[str]:
        if not rel_path:
            return None
        if rel_path.startswith(("/", "~")):
            return None
        rel_clean = rel_path.lstrip("./")
        if rel_clean.startswith("../"):
            return None
        if any(ch in rel_clean for ch in "*?[]"):
            return None
        candidate_strings = []
        if rel_clean:
            candidate_strings.append(rel_clean)
        prefixes = (
            "apps/api/src/",
            "apps/api/test/",
            "apps/api/prisma/",
            "apps/api/",
        )
        for prefix in prefixes:
            candidate_strings.append(prefix + rel_clean)
        seen_candidates = set()
        for candidate in candidate_strings:
            if candidate in seen_candidates:
                continue
            seen_candidates.add(candidate)
            try:
                resolved = ensure_within_root(Path(candidate))
            except Exception:
                continue
            if resolved.exists():
                return candidate
        return None

    def _rewrite_path_token(token: str) -> str:
        if "/" not in token:
            return token
        if token.startswith("--") or token.startswith("-"):
            return token
        if token.startswith("$"):
            return token
        leading = ""
        trimmed = token
        if trimmed.startswith("./"):
            leading = "./"
            trimmed = trimmed[2:]
        alt = _resolve_alt_path(trimmed)
        if alt and alt != trimmed:
            return leading + alt
        return token

    def _rewrite_tokens(tokens: List[str]) -> Tuple[List[str], bool]:
        changed = False
        rewritten: List[str] = []
        for token in tokens:
            new_token = _rewrite_path_token(token)
            if new_token != token:
                changed = True
            rewritten.append(new_token)
        return rewritten, changed

    def _apply_tool_fallbacks(tokens: List[str]) -> Tuple[List[str], bool]:
        if not tokens:
            return tokens, False
        if tokens[0] == 'rg' and shutil.which('rg') is None:
            fallback = ['grep', '-nR', '--']
            fallback.extend(tokens[1:])
            return fallback, True
        return tokens, False

    def _rewrite_script_paths(script_text: str) -> str:
        try:
            script_tokens = shlex.split(script_text)
        except ValueError:
            return script_text
        rewritten_tokens, changed = _rewrite_tokens(script_tokens)
        if not changed:
            return script_text
        return " ".join(shlex.quote(tok) for tok in rewritten_tokens)

    def _run_simple_sed(start: int, end: int, rel_path: str) -> CompletedProcess:
        effective_path = _resolve_alt_path(rel_path) or rel_path
        try:
            target = ensure_within_root(Path(effective_path))
        except Exception as exc:
            return CompletedProcess(
                args=['sed', '-n', f'{start},{end}p', rel_path],
                returncode=1,
                stdout='',
                stderr=str(exc),
            )
        if not target.exists() or not target.is_file():
            return CompletedProcess(
                args=['sed', '-n', f'{start},{end}p', rel_path],
                returncode=1,
                stdout='',
                stderr=f"{rel_path}: not found or not a file",
            )
        start_idx = max(start - 1, 0)
        end_idx = max(end, start_idx)
        lines = target.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
        if start_idx >= len(lines):
            snippet = ''
        else:
            end_idx = min(end_idx, len(lines))
            snippet = ''.join(lines[start_idx:end_idx])
        return CompletedProcess(
            args=['sed', '-n', f'{start},{end}p', rel_path],
            returncode=0,
            stdout=snippet,
            stderr='',
        )

    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            manual_notes.append(
                _format_action_result(f"change[{index}]", "blocked — expected object payload")
            )
            command_failure_detected = True
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
                command_failure_detected = True
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
                command_failure_detected = True
                continue
            change['type'] = 'patch'
        elif ctype == 'file':
            if not path:
                manual_notes.append(
                    _format_action_result(f"change[{index}]", "blocked — path missing or empty")
                )
                command_failure_detected = True
                continue
            content_value = change.get('content')
            if not isinstance(content_value, str):
                manual_notes.append(
                    _format_action_result(f"change[{index}]", "blocked — file content missing or not text")
                )
                command_failure_detected = True
                continue
            change['type'] = 'file'
        else:
            descriptor = (raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else 'unknown')
            manual_notes.append(
                _format_action_result(f"change[{index}]", f"blocked — unknown type '{descriptor}'")
            )
            command_failure_detected = True
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
            _remove_plan_artifacts(f"change[{index}] {rel_path}")
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
                    _remove_plan_artifacts(f"change[{index}] {path}")
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
                            _remove_plan_artifacts(f"change[{index}] {path}")
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
                                _remove_plan_artifacts(f"change[{index}] {path}")
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
                        _remove_plan_artifacts(f"change[{index}] {path}")
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
                    _remove_plan_artifacts(f"change[{index}] {path}")
                    continue
                patched.append(path + ' (patch)')
                change_bytes[path] = diff_bytes
                actual_changes += 1
                _remove_plan_artifacts(f"change[{index}] {path}")
            else:
                patched.append(path)
                change_bytes[path] = diff_bytes
                actual_changes += 1
                _remove_plan_artifacts(f"change[{index}] {path}")

    _remove_plan_artifacts("post-changes")

    commands_field = payload.get('commands')
    command_placeholder_details: List[Tuple[str, str]] = []
    if isinstance(commands_field, list) and commands_field:
        updated_commands, placeholder_details = _rewrite_command_placeholders(commands_field)
        if placeholder_details:
            payload['commands'] = updated_commands
            commands_field = updated_commands
            command_placeholder_details = placeholder_details
    original_command_report: List[str] = []
    if isinstance(commands_field, list):
        original_command_report = [item for item in commands_field if isinstance(item, str)]
    command_entries = original_command_report[:]
    command_coalesce_error: Optional[UnclosedHeredocError] = None
    if command_entries:
        try:
            command_entries = _coalesce_command_entries(command_entries)
        except UnclosedHeredocError as exc:
            command_coalesce_error = exc
            command_entries = []
    executed_commands: List[str] = []
    commands_to_report: Set[str] = set()
    seen_commands: Set[str] = set()
    blocked_command_counts: Dict[str, Dict[str, object]] = {}
    blocked_command_total = 0
    blocked_command_requires_reporting = False

    REQUIRED_GITIGNORE_LINES = [
        "# gpt-creator",
        ".gpt-creator/tmp/",
        ".gpt-creator/logs/",
        ".gpt-creator/cache/",
        ".gpt-creator/staging/",
    ]

    def _ensure_gitignore_entries(root: Path) -> bool:
        gitignore_path = root / ".gitignore"
        try:
            existing_lines = gitignore_path.read_text(encoding='utf-8').splitlines()
        except FileNotFoundError:
            existing_lines = []
        normalized = {line.strip() for line in existing_lines}
        changed = False
        for entry in REQUIRED_GITIGNORE_LINES:
            key = entry.strip()
            if key not in normalized:
                existing_lines.append(entry)
                normalized.add(key)
                changed = True
        if changed:
            gitignore_path.write_text("\n".join(existing_lines) + "\n", encoding='utf-8')
        return changed

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

    def _configure_prisma_override_env() -> None:
        override_root = project_root / '.gpt-creator' / 'prisma-engines'
        override_tmp = override_root / 'tmp'
        try:
            override_tmp.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        os.environ.setdefault('PRISMA_ENGINES_OVERRIDE', str(override_root))
        os.environ.setdefault('TMPDIR', str(override_tmp))

    _configure_prisma_override_env()

    def _git_changes_since_task_branch(root: Path) -> Optional[int]:
        base_file = root / ".gpt-creator" / "state" / "base-sha"
        if not base_file.exists():
            return None
        try:
            base_sha = base_file.read_text(encoding='utf-8').strip()
        except Exception:
            return None
        if not base_sha:
            return None
        try:
            proc = subprocess.run(
                ['git', 'diff', '--name-only', base_sha, 'HEAD'],
                capture_output=True,
                text=True,
                cwd=str(root),
                check=False,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        count = sum(1 for line in proc.stdout.splitlines() if line.strip())
        return count

    def _git_has_head(root: Path) -> bool:
        try:
            proc = subprocess.run(
                ['git', 'rev-parse', '--verify', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=str(root),
                check=False,
            )
        except Exception:
            return False
        return proc.returncode == 0

    def _working_tree_clean(root: Path) -> bool:
        try:
            proc = subprocess.run(
                ['git', 'status', '--porcelain=v1', '--untracked-files=all'],
                capture_output=True,
                text=True,
                cwd=str(root),
                check=False,
            )
        except Exception:
            return False
        if proc.returncode != 0:
            return False
        return proc.stdout.strip() == ""

    def _auto_snapshot_dirty_tree(root: Path) -> Tuple[bool, str]:
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        commit_message = f"chore(gpt-creator): auto snapshot before work-on-tasks {timestamp}"
        snapshot_label = f"work-on-tasks auto snapshot {timestamp}"
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", "gpt-creator automation")
        env.setdefault("GIT_AUTHOR_EMAIL", "automation@gpt-creator")
        env.setdefault("GIT_COMMITTER_NAME", "gpt-creator automation")
        env.setdefault("GIT_COMMITTER_EMAIL", "automation@gpt-creator")

        try:
            stage_proc = subprocess.run(
                ['git', 'add', '--all'],
                capture_output=True,
                text=True,
                cwd=str(root),
                check=False,
            )
        except Exception as exc:
            return False, f"auto snapshot staging failed ({exc})"
        if stage_proc.returncode != 0:
            detail = stage_proc.stderr.strip() or stage_proc.stdout.strip() or f"exit {stage_proc.returncode}"
            return False, f"unable to stage pending edits automatically ({detail})"

        try:
            diff_cached = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'],
                cwd=str(root),
                check=False,
            )
        except Exception as exc:
            return False, f"auto snapshot diff check failed ({exc})"

        if diff_cached.returncode == 0:
            if _working_tree_clean(root):
                return True, "working tree already clean after staging"
        else:
            try:
                commit_proc = subprocess.run(
                    ['git', 'commit', '-m', commit_message],
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    env=env,
                    check=False,
                )
            except Exception as exc:
                commit_proc = None
                commit_error = f"{exc}"
            else:
                commit_error = commit_proc.stderr.strip() if commit_proc else ""
            if commit_proc and commit_proc.returncode == 0:
                rev_proc = subprocess.run(
                    ['git', 'rev-parse', '--short', 'HEAD'],
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    check=False,
                )
                rev_label = ""
                if rev_proc.returncode == 0:
                    rev_label = rev_proc.stdout.strip()
                detail = f"auto snapshot commit created ({commit_message})"
                if rev_label:
                    detail += f" [{rev_label}]"
                return True, detail
            # Commit failed; reset staged files before falling back to stash.
            if _git_has_head(root):
                subprocess.run(['git', 'reset', '--mixed', 'HEAD'], cwd=str(root), check=False)
            else:
                subprocess.run(['git', 'reset', '--mixed'], cwd=str(root), check=False)
        # Stash fallback
        try:
            stash_proc = subprocess.run(
                ['git', 'stash', 'push', '--include-untracked', '--message', snapshot_label],
                capture_output=True,
                text=True,
                cwd=str(root),
                check=False,
            )
        except Exception as exc:
            return False, f"auto stash failed ({exc})"
        if stash_proc.returncode == 0 and _working_tree_clean(root):
            return True, f"auto stash created ({snapshot_label})"
        detail = stash_proc.stderr.strip() or stash_proc.stdout.strip() or f"exit {stash_proc.returncode}"
        return False, f"auto stash incomplete ({detail})"

    gitignore_auto_added = False
    if _ensure_gitignore_entries(project_root):
        gitignore_auto_added = True
        manual_notes.append(
            _format_action_result(
                ".gitignore",
                "note — ensured gpt-creator artifacts are ignored"
            )
        )
    if gitignore_auto_added:
        gitignore_label = ".gitignore (auto)"
        if gitignore_label not in patched:
            patched.append(gitignore_label)
        try:
            gitignore_size = (project_root / ".gitignore").stat().st_size
        except Exception:
            gitignore_size = 0
        change_bytes[".gitignore"] = gitignore_size
        actual_changes += 1
    command_diff_before = _git_diff_name_status(project_root)
    command_untracked_before = _git_untracked_files(project_root)
    preexisting_pending_changes = False
    pending_changes_before: List[str] = []
    dirty_tree_blocked = False
    workspace_block_reason: Optional[str] = None
    allow_dirty_tree = _env_flag("WORK_ON_TASKS_ALLOW_DIRTY", default=False)
    dirty_autofix_enabled = _env_flag("WORK_ON_TASKS_DIRTY_AUTOFIX", default=True)
    dirty_ignore_raw = os.environ.get("WORK_ON_TASKS_DIRTY_IGNORE", ".gpt-creator/**:.gitignore")
    dirty_ignore_patterns = [pattern for pattern in (segment.strip() for segment in dirty_ignore_raw.split(":")) if pattern]

    dependency_clone_paths, dependency_owner_conflicts = _scan_dependency_directories(project_root)
    if dependency_clone_paths:
        sample = [
            _friendly_relpath(path, project_root)
            for path in dependency_clone_paths[:4]
        ]
        if len(dependency_clone_paths) > 4:
            sample.append("…")
        sample_text = ", ".join(sample) if sample else "repository root"
        manual_notes.append(
            _format_action_result(
                "dependency-clones",
                "blocked — remove manual copies/backups of dependency caches (node_modules/vendor/venv/etc). "
                f"Found: {sample_text}. Use the package manager instead of duplicating third-party directories."
            )
        )
        dirty_tree_blocked = True
        workspace_block_reason = workspace_block_reason or 'blocked-dependency-clones'
    if dependency_owner_conflicts:
        owner_samples = []
        for path, owner in dependency_owner_conflicts[:4]:
            owner_samples.append(f"{_friendly_relpath(path, project_root)} owned by {owner}")
        if len(dependency_owner_conflicts) > 4:
            owner_samples.append("…")
        owner_text = "; ".join(owner_samples) if owner_samples else "unknown"
        manual_notes.append(
            _format_action_result(
                "dependency-ownership",
                "blocked — dependency cache ownership mismatch. Ensure gpt-creator and the agent run as the same unix user "
                f"(e.g., chown -R $(whoami) path). Offending paths: {owner_text}"
            )
        )
        dirty_tree_blocked = True
        if workspace_block_reason is None:
            workspace_block_reason = 'blocked-dependency-ownership'

    def _should_ignore_dirty_entry(path_fragment: str) -> bool:
        if not dirty_ignore_patterns:
            return False
        normalized_path = path_fragment.lstrip("./")
        return any(fnmatch.fnmatch(normalized_path, pattern) for pattern in dirty_ignore_patterns)

    def _collect_pending_changes(diff_map: Dict[str, str], untracked: Set[str]) -> List[str]:
        entries: List[str] = []
        if diff_map:
            for path, status in sorted(diff_map.items()):
                label = status.strip().upper() or "M"
                if _should_ignore_dirty_entry(path):
                    continue
                entries.append(f"{label} {path}")
        if untracked:
            for path in sorted(untracked):
                if _should_ignore_dirty_entry(path):
                    continue
                entries.append(f"?? {path}")
        return entries

    pending_changes_before = _collect_pending_changes(command_diff_before, command_untracked_before)
    if pending_changes_before and not allow_dirty_tree and dirty_autofix_enabled:
        autofix_ok, autofix_detail = _auto_snapshot_dirty_tree(project_root)
        if autofix_ok:
            manual_notes.append(
                _format_action_result(
                    "dirty-tree-autofix",
                    f"info — {autofix_detail}"
                )
            )
            command_diff_before = _git_diff_name_status(project_root)
            command_untracked_before = _git_untracked_files(project_root)
            pending_changes_before = _collect_pending_changes(command_diff_before, command_untracked_before)
        else:
            manual_notes.append(
                _format_action_result(
                    "dirty-tree-autofix",
                    f"warning — {autofix_detail}"
                )
            )
    cache_key = str(project_root_resolved)
    if pending_changes_before:
        snapshot = tuple(pending_changes_before)
        last_snapshot = LAST_PENDING_CHANGES.get(cache_key)
        preview_items = pending_changes_before[:6]
        summary = '; '.join(preview_items)
        if len(pending_changes_before) > 6:
            summary += '; …'
        if allow_dirty_tree:
            warning_message = f"warning — working tree already dirty before commands; recap these files: {summary}"
            if last_snapshot != snapshot:
                manual_notes.append(
                    _format_action_result(
                        "pending-changes",
                        warning_message
                    )
                )
            if last_snapshot != snapshot:
                LAST_PENDING_CHANGES[cache_key] = snapshot
        else:
            dirty_tree_blocked = True
            if workspace_block_reason is None:
                workspace_block_reason = 'blocked-dirty-tree'
            blocking_message = (
                "blocked — working tree is dirty before running task commands; clean or stash local edits, "
                "or set WORK_ON_TASKS_ALLOW_DIRTY=1 if you intentionally want to proceed. "
                f"Affected paths: {summary}"
            )
            manual_notes.append(
                _format_action_result(
                    "pending-changes",
                    blocking_message
                )
            )
            LAST_PENDING_CHANGES[cache_key] = snapshot
    else:
        LAST_PENDING_CHANGES.pop(cache_key, None)
    if pending_changes_before:
        preexisting_pending_changes = True

    if branch_setup_retry_needed and not dirty_tree_blocked:
        if pending_changes_before:
            manual_notes.append(
                _format_action_result(
                    "branch",
                    "warning — dev checkout still blocked by pending changes; rerun after cleaning the working tree"
                )
            )
            branch_setup_retry_needed = False
        else:
            branch_management_enabled = True
            branch_ready = False
            manual_notes.append(
                _format_action_result(
                    "branch",
                    f"info — retrying dev checkout for clean working tree on {dev_branch_name}"
                )
            )
            manual_notes.extend(_checkout_dev_branch())
            if branch_management_enabled:
                manual_notes.extend(_prepare_task_branch_if_needed())
            branch_setup_retry_needed = False

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

    def _summarize_command_failure(stdout_text: str, stderr_text: str, limit: int = 160) -> str:
        snippet = stderr_text.strip() or stdout_text.strip()
        if not snippet:
            return ""
        lines = [line.strip() for line in snippet.splitlines() if line.strip()]
        if not lines:
            return ""
        summary = lines[0]
        if len(summary) > limit:
            summary = summary[: limit - 1] + "…"
        return summary

    skip_command_processing = command_coalesce_error is not None
    if dirty_tree_blocked:
        skip_command_processing = True
        command_entries = []
    if command_coalesce_error is not None:
        delimiter_label = command_coalesce_error.delimiter
        command_lead = (command_coalesce_error.command_lead or "").strip()
        label_source = command_lead or f"<<{delimiter_label}"
        manual_notes.append(
            _format_action_result(
                _truncate_command_text(label_source),
                f"blocked — heredoc labeled {delimiter_label!r} missing closing line; restate the command with a terminating {delimiter_label} line"
            )
        )
        if command_lead:
            _record_blocked_command('heredoc-unterminated', command_lead)
    if command_entries and not skip_command_processing:
        filtered_commands: List[str] = []
        precheck_non_whitelisted: List[str] = []
        for raw_cmd in command_entries:
            if not isinstance(raw_cmd, str):
                continue
            trimmed = _normalize_command_wrapper(raw_cmd)
            trimmed = _sanitize_command_escapes(trimmed)
            if not trimmed:
                continue
            if not _is_valid_bash_wrapper(trimmed):
                _record_blocked_command('quote-mismatch', raw_cmd)
                continue
            if COMMAND_WHITELIST_PATTERN.match(trimmed):
                filtered_commands.append(raw_cmd)
            else:
                precheck_non_whitelisted.append(trimmed)
        if precheck_non_whitelisted:
            sample = _truncate_command_text(precheck_non_whitelisted[0])
            hint = ""
            if any(cmd.strip().startswith("nl ") or " sed " in cmd or "| sed" in cmd for cmd in precheck_non_whitelisted):
                hint = " Use `python3 tools/scripts/python/show_file_excerpt.py <path> --start 1 --end 120` instead of `nl|sed` pipelines."
            manual_notes.append(
                _format_action_result(
                    "command-precheck",
                    f"blocked — filtered {len(precheck_non_whitelisted)} non-whitelisted command(s) (first: {sample}).{hint}"
                )
            )
            manual_notes.append(
                _format_action_result(
                    "command-precheck-remediation",
                    "remove or replace non-whitelisted commands; allowed prefixes include bash, python3, pnpm, git, gpt-creator apply-block"
                )
            )
        command_entries = filtered_commands
        if not command_entries:
            skip_command_processing = True

    command_failure_detected = False
    branch_merge_completed = False

    if command_placeholder_details:
        first_snippet, first_reason = command_placeholder_details[0]
        fix_hint = ""
        if "missing terminator" in first_reason:
            fix_hint = " Fix: end heredocs with the same label, e.g., run: cat <<'EOF' > file … EOF."
        _append_guard_note(
            "commands-placeholder-detected",
            f"auto-replaced {len(command_placeholder_details)} placeholder command(s) with '# TODO' entries; first snippet: {first_snippet} ({first_reason}).{fix_hint}"
        )
        skip_command_processing = False
        # Placeholder detection is informational; do not convert the run to retryable.

    def _working_tree_clean() -> bool:
        status = _run_git_command(['status', '--porcelain'])
        return status.returncode == 0 and not (status.stdout or "").strip()

    def _restore_base_branch_after_run() -> None:
        if not branch_ready or not base_task_branch:
            return
        current_branch = _get_current_branch()
        if current_branch == base_task_branch:
            return
        if not _working_tree_clean():
            manual_notes.append(
                _format_action_result(
                    "branch",
                    "warning — cannot return to base branch due to pending changes; resolve before next run"
                )
            )
            return
        checkout = _run_git_command(['checkout', base_task_branch])
        if checkout.returncode == 0:
            manual_notes.append(
                _format_action_result(
                    "branch",
                    f"info — returned to base branch {base_task_branch}"
                )
            )

    def _merge_branch_into_base_if_complete(status: str) -> None:
        nonlocal branch_merge_completed, command_failure_detected, forced_canonical_status, forced_legacy_status
        if not branch_ready or not active_task_branch or not base_task_branch:
            return
        if active_task_branch == base_task_branch:
            return
        if status != 'COMPLETED':
            return
        if not _working_tree_clean():
            manual_notes.append(
                _format_action_result(
                    "branch",
                    "warning — skipping merge to base due to pending changes; rerun after cleaning up"
                )
            )
            return
        checkout = _run_git_command(['checkout', base_task_branch])
        if checkout.returncode != 0:
            stderr_text = (checkout.stderr or "").strip()
            manual_notes.append(
                _format_action_result(
                    "branch",
                    f"failed — unable to checkout base branch {base_task_branch}: {stderr_text or 'see stderr'}"
                )
            )
            command_failure_detected = True
            forced_canonical_status = 'RETRYABLE'
            forced_legacy_status = 'retryable'
            return
        merge_proc = _run_git_command(['merge', '--no-ff', '--no-edit', active_task_branch])
        if merge_proc.returncode != 0:
            _run_git_command(['merge', '--abort'])
            stderr_text = (merge_proc.stderr or "").strip()
            manual_notes.append(
                _format_action_result(
                    "branch",
                    f"failed — merge of {active_task_branch} into {base_task_branch} encountered conflicts: {stderr_text or 'see stderr'}"
                )
            )
            command_failure_detected = True
            forced_canonical_status = 'RETRYABLE'
            forced_legacy_status = 'retryable'
            return
        push_ok, push_note = _push_branch_to_remote(base_task_branch, "post-merge base sync")
        manual_notes.append(push_note)
        if not push_ok:
            command_failure_detected = True
            forced_canonical_status = 'RETRYABLE'
            forced_legacy_status = 'retryable'
            return
        branch_merge_completed = True
        manual_notes.append(
            _format_action_result(
                "branch",
                f"success — merged {active_task_branch} into {base_task_branch} and pushed"
            )
        )
        _update_task_branch_record(task_db_id, None, None)
        if branch_delete_on_complete:
            delete_local = _run_git_command(['branch', '-D', active_task_branch])
            if delete_local.returncode == 0:
                manual_notes.append(
                    _format_action_result(
                        "branch",
                        f"note — deleted local branch {active_task_branch}"
                    )
                )
            delete_remote = _run_git_command(['push', 'origin', '--delete', active_task_branch])
            if delete_remote.returncode == 0:
                manual_notes.append(
                    _format_action_result(
                        "branch",
                        f"note — deleted remote branch {active_task_branch}"
                )
            )
    if dirty_tree_blocked:
        command_failure_detected = True

    def _sync_active_branch_post_run(context: str) -> None:
        nonlocal command_failure_detected
        if not branch_management_enabled or not branch_ready or not active_task_branch:
            return
        if branch_merge_completed and branch_delete_on_complete:
            return
        push_ok, push_note = _push_branch_to_remote(active_task_branch, context)
        manual_notes.append(push_note)
        if not push_ok:
            command_failure_detected = True

    failed_command_cache: Dict[str, Dict[str, object]] = {}
    if isinstance(command_entries, list) and command_entries and not skip_command_processing:
        baseline_status = _git_status_porcelain(project_root)
        for raw_cmd in command_entries:
            if not isinstance(raw_cmd, str):
                continue
            command = _normalize_command_wrapper(raw_cmd)
            command = _sanitize_command_escapes(command)
            if not command:
                continue
            if not _is_valid_bash_wrapper(command):
                _record_blocked_command('quote-mismatch', raw_cmd)
                continue
            command = _hydrate_literal_command(command)
            if '\n' in command and HEREDOC_LABEL_PATTERN.search(command) is None:
                _record_blocked_command('multiline', command)
                manual_notes.append(
                    _format_action_result(
                        _truncate_command_text(command),
                        "blocked — multi-line commands must use a heredoc with matching terminator; restate as single-line or add <<LABEL/terminator pair"
                    )
                )
                continue
            try:
                command_tokens = shlex.split(command)
            except ValueError:
                command_tokens = command.split()
            command_changed = False
            lower_command = command.lower()
            first_token = command_tokens[0] if command_tokens else ""
            script_text = ""
            python_heredoc_code: Optional[str] = None
            sed_request: Optional[Tuple[int, int, str]] = None
            if '...' in command or '…' in command:
                _record_blocked_command('placeholder-ellipsis', command)
                continue
            canonical_command = command.strip()
            cached_failure = failed_command_cache.get(canonical_command)
            if cached_failure:
                reason = cached_failure.get('summary') or f"exit {cached_failure.get('exit_code')}"
                manual_notes.append(
                    _format_action_result(
                        _truncate_command_text(command),
                        f"blocked — command already failed earlier ({reason}); adjust it before retrying"
                    )
                )
                _record_blocked_command('repeat-failure', command)
                continue
            if first_token in {"bash", "sh"} and len(command_tokens) >= 3 and command_tokens[1] in {"-lc", "-c"}:
                script_text = command_tokens[2]
                rewritten_script = _rewrite_script_paths(script_text)
                if rewritten_script != script_text:
                    script_text = rewritten_script
                    command_tokens = command_tokens[:]
                    command_tokens[2] = script_text
                    command_changed = True
                python_heredoc_code = _extract_python_heredoc(script_text)
            else:
                rewritten_tokens, tokens_changed = _rewrite_tokens(command_tokens)
                fallback_tokens, fallback_changed = _apply_tool_fallbacks(rewritten_tokens)
                command_tokens = fallback_tokens
                if tokens_changed or fallback_changed:
                    command_changed = True
            if command_changed:
                command = " ".join(shlex.quote(tok) for tok in command_tokens)
                lower_command = command.lower()
                first_token = command_tokens[0] if command_tokens else ""
                if first_token in {"bash", "sh"} and len(command_tokens) >= 3:
                    script_text = command_tokens[2]
                else:
                    script_text = ""
            if REDIRECTION_PATTERN.search(command):
                _record_blocked_command('redirection', command)
                continue
            if first_token in {"bash", "sh"} and python_heredoc_code is None and script_text:
                sed_request = _extract_simple_sed(script_text)
            elif first_token == "sed":
                sed_request = _extract_simple_sed(" ".join(command_tokens))
            if first_token == "cat":
                if HEREDOC_TOKEN in command:
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
            if sed_request is None:
                if first_token == "sed":
                    exceeds_window, window_span = _sed_window_exceeds(command)
                    if exceeds_window:
                        _record_blocked_command('sed-window', command)
                        continue
                elif first_token in {"bash", "sh"} and script_text:
                    has_wide_sed, window_span, offending_segment = _script_contains_wide_sed(script_text)
                    if has_wide_sed:
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
            command, command_tokens = _rewrite_command_pipeline(command, command_tokens)
            first_token = command_tokens[0] if command_tokens else first_token
            if python_heredoc_code is None and first_token == "python3":
                python_heredoc_code = _extract_python_heredoc(command)
            command_to_run = command
            try:
                if python_heredoc_code is not None:
                    proc_cmd = _run_python_heredoc(python_heredoc_code)
                elif sed_request is not None:
                    proc_cmd = _run_simple_sed(*sed_request)
                elif override_exec is not None:
                    proc_cmd = subprocess.run(
                        list(override_exec),
                        capture_output=True,
                        text=True,
                        cwd=str(project_root),
                        timeout=apply_timeout,
                        check=False,
                    )
                else:
                    if _can_run_direct(command_to_run) and command_tokens:
                        proc_cmd = subprocess.run(
                            command_tokens,
                            capture_output=True,
                            text=True,
                            cwd=str(project_root),
                            timeout=apply_timeout,
                            check=False,
                        )
                    else:
                        proc_cmd = _run_shell_script(command_to_run)
            except Exception as exc:
                manual_notes.append(
                    _format_action_result(
                        _truncate_command_text(command),
                        f"failed — {exc}"
                    )
                )
                continue
            stdout_text = proc_cmd.stdout or ""
            stderr_text = proc_cmd.stderr or ""
            if stdout_text:
                sys.stdout.write(stdout_text)
            if stderr_text:
                sys.stderr.write(stderr_text)
            executed_commands.append(command)
            is_test_command = _looks_like_test_command(command)
            _append_command_log(command, proc_cmd.returncode, stdout_text, stderr_text, is_test_command)
            _remove_plan_artifacts(f"command {_truncate_command_text(command)}")
            if proc_cmd.returncode != 0:
                failure_summary = _summarize_command_failure(stdout_text, stderr_text)
                failed_command_cache[canonical_command] = {
                    'exit_code': proc_cmd.returncode,
                    'summary': failure_summary,
                }
                if first_token == "gc_assert" and proc_cmd.returncode == 1:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            "info — schema evidence not found (continuing)"
                        )
                    )
                    continue
                handled_note = _handle_pattern_not_found(python_heredoc_code, stdout_text, stderr_text)
                if handled_note is not None:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            handled_note
                        )
                    )
                    continue
                permission_note = _handle_permission_error(command, stdout_text, stderr_text)
                if permission_note is not None:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            permission_note
                        )
                    )
                    continue
                build_note = _handle_build_failure(command, stdout_text, stderr_text)
                if build_note is not None:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            build_note
                        )
                    )
                    continue
                jest_note = _handle_jest_baseline_failure(command, stdout_text, stderr_text)
                if jest_note is not None:
                    manual_notes.append(
                        _format_action_result(
                            _truncate_command_text(command),
                            jest_note
                        )
                    )
                    continue
                commands_to_report.add(command)
                note = _format_action_result(
                    _truncate_command_text(command),
                    f"failed — exit {proc_cmd.returncode}; revise before retrying"
                )
                summary_parts = []
                stdout_summary = _summarize_stream("stdout", stdout_text)
                stderr_summary = _summarize_stream("stderr", stderr_text)
                if stdout_summary:
                    summary_parts.append(stdout_summary)
                if stderr_summary:
                    summary_parts.append(stderr_summary)
                failure_detail = note
                if summary_parts:
                    failure_detail = note + "\n" + '\n'.join(summary_parts)
                manual_notes.append(failure_detail)
                _append_error_record(failure_detail)
                _append_required_script(command)
            else:
                manual_notes.append(
                    _format_action_result(
                        _truncate_command_text(command),
                        "success"
                    )
                )
        post_status = _git_status_porcelain(project_root)
        delta_status = _status_delta(baseline_status, post_status)
        if delta_status:
            commands_to_report.add(command)
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
            branch_delta = _git_changes_since_task_branch(project_root)
            if branch_delta and branch_delta > 0:
                manual_notes.append(
                    _format_action_result(
                        "post-command-delta",
                        f"info — {branch_delta} files changed via task baseline; treating commands as modifying the repo."
                    )
                )
                actual_changes += branch_delta
            else:
                documentation_only_run = True
                manual_notes.append(
                    _format_action_result(
                        "post-command-delta",
                        "info — commands ran but left the repository unchanged; if the current code already satisfies the requirements, report the task as completed-no-changes instead of rerunning."
                    )
                )

    if executed_commands:
        payload['commands'] = executed_commands[:]
    _remove_plan_artifacts("post-commands")

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
        fatal_reasons_present = False
        safe_block_only = True
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
            fatal_entry = reason in FATAL_BLOCK_REASONS and reason not in SAFE_BLOCKED_COMMAND_REASONS
            if reason not in SAFE_BLOCKED_COMMAND_REASONS:
                safe_block_only = False
            if fatal_entry:
                fatal_reasons_present = True
            prefix = "blocked" if fatal_entry else "warning"
            manual_notes.append(
                _format_action_result(
                    f"{prefix}-{reason}",
                    summary_text
                )
            )
        if 'sed-window' in blocked_command_counts or 'doc-search' in blocked_command_counts:
            manual_notes.append(
                _format_action_result(
                    "command-summary-guidance",
                    "summarize findings instead of dumping large files; prefer QA catalog links or `gpt-creator show-file --range start:end`"
                )
            )
        if 'placeholder-ellipsis' in blocked_command_counts:
            manual_notes.append(
                _format_action_result(
                    "commands-placeholders",
                    "warning — placeholder command(s) detected; TODO entries were inserted automatically; rerun guards once real commands are ready"
                )
            )
        if fatal_reasons_present:
            manual_notes.append(
                _format_action_result(
                    "commands-remediation",
                    "replace blocked commands with approved workflows (gpt-creator apply-block, python3 tools/scripts/python/write_block.py, pnpm --filter …) before retrying"
                )
            )
        blocked_command_requires_reporting = not safe_block_only

    declared_commands: List[str] = payload.get('commands') or []
    commands_missing = False
    commands_drift_fatal = False
    allow_drift = os.environ.get("WORK_ON_TASKS_ALLOW_DRIFT", "1") == "1"
    if not dirty_tree_blocked:
        if executed_commands:
            missing_logged = [cmd for cmd in commands_to_report if cmd not in executed_commands]
            if missing_logged:
                commands_missing = True
                joined = '; '.join(_truncate_command_text(cmd) for cmd in missing_logged[:3])
                if len(missing_logged) > 3:
                    joined += '; …'
                manual_notes.append(
                    _format_action_result(
                        "commands-log-mismatch",
                        f"blocked — the following executed command(s) were not captured in the auto-generated log: {joined}"
                    )
                )
                if not allow_drift:
                    commands_drift_fatal = True
        elif original_command_report:
            missing_logged = [cmd for cmd in commands_to_report if cmd not in original_command_report]
            if missing_logged:
                commands_missing = True
                joined = '; '.join(_truncate_command_text(cmd) for cmd in missing_logged[:3])
                if len(missing_logged) > 3:
                    joined += '; …'
                manual_notes.append(
                    _format_action_result(
                        "commands-log-mismatch",
                        f"blocked — the following executed command(s) were not listed under `Commands`: {joined}"
                    )
                )
                if not allow_drift:
                    commands_drift_fatal = True
        elif commands_to_report or blocked_command_requires_reporting or written or patched or change_bytes or command_failure_detected:
            commands_missing = True
            manual_notes.append(
                _format_action_result(
                    "commands-log-missing",
                    "blocked — repository shows edits or executed commands but none were reported under `Commands`; rerun and list each command that edited files, ran tools, or staged changes."
                )
            )
            if not allow_drift:
                commands_drift_fatal = True

    staging_root: Optional[Path] = None

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
            _append_guard_note(
                "regex-guard",
                f"warning — pattern {snippet!r} invalid; treated as literal match"
            )

    def _refresh_documentation_assets(doc_paths: Sequence[str]) -> List[str]:
        notes: List[str] = []
        normalized_candidates = []
        seen_norm: Dict[str, None] = {}
        for candidate in doc_paths:
            normalized = _normalize_doc_path_label(candidate)
            if not normalized or not _path_is_doc_file(normalized):
                continue
            if normalized in seen_norm:
                continue
            seen_norm[normalized] = None
            normalized_candidates.append(normalized)
        if not normalized_candidates:
            return notes
        python_bin = sys.executable or "python3"
        lib_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        existing_py_path = env.get("PYTHONPATH", "")
        lib_root_str = str(lib_root)
        if existing_py_path:
            paths = existing_py_path.split(os.pathsep)
            if lib_root_str not in paths:
                env["PYTHONPATH"] = lib_root_str + os.pathsep + existing_py_path
        else:
            env["PYTHONPATH"] = lib_root_str
        base_staging = staging_root or (project_root / ".gpt-creator" / "staging")
        try:
            base_staging.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        plan_dir = base_staging / "plan"
        work_dir = plan_dir / "work"
        docs_dir = plan_dir / "docs"
        for directory in (plan_dir, work_dir, docs_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        doc_catalog_json_path = work_dir / "doc-catalog.json"
        doc_library_path = docs_dir / "doc-library.md"
        doc_index_path = docs_dir / "doc-index.md"
        runtime_dir = base_staging.parent if base_staging.parent else (project_root / ".gpt-creator")

        def _shorten(text: str, limit: int = 200) -> str:
            snippet = (text or "").strip()
            if len(snippet) > limit:
                snippet = snippet[: limit - 1].rstrip() + "…"
            return snippet

        catalog_cmd: List[str]
        doc_catalog_helper_local = (
            os.getenv("GC_DOC_CATALOG_HELPER", "").strip()
            or os.getenv("doc_catalog", "").strip()
        )
        default_doc_catalog = Path("tools/scripts/python/doc_catalog_refresh.py").resolve()
        doc_indexer_helper_local = (
            globals().get("doc_indexer_helper")
            or os.getenv("GC_DOC_INDEXER_PY", "").strip()
            or os.getenv("GC_DOC_INDEXER_HELPER", "").strip()
            or os.getenv("doc_indexer", "").strip()
        )
        helper_path = doc_catalog_helper_local or (str(default_doc_catalog) if default_doc_catalog.exists() else "")
        if helper_path:
            catalog_cmd = [
                python_bin,
                helper_path,
                "--project-root",
                str(project_root),
                "--staging-dir",
                str(base_staging),
                "--out-json",
                str(doc_catalog_json_path),
                "--out-library",
                str(doc_library_path),
                "--out-index",
                str(doc_index_path),
            ]
        else:
            catalog_cmd = [
                python_bin,
                "-m",
                "lib.doc_catalog",
                "--project-root",
                str(project_root),
                "--staging-dir",
                str(base_staging),
                "--out-json",
                str(doc_catalog_json_path),
                "--out-library",
                str(doc_library_path),
                "--out-index",
                str(doc_index_path),
            ]
        try:
            catalog_proc = subprocess.run(
                catalog_cmd,
                cwd=str(project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError as exc:
            notes.append(
                _format_action_result(
                    "doc-catalog-refresh",
                    f"warning — unable to refresh documentation catalog ({exc})",
                )
            )
            return notes
        if catalog_proc.returncode != 0:
            diagnostics = catalog_proc.stderr.strip() or catalog_proc.stdout.strip()
            notes.append(
                _format_action_result(
                    "doc-catalog-refresh",
                    f"warning — doc catalog refresh failed (exit {catalog_proc.returncode}); {_shorten(diagnostics)}",
                )
            )
            notes.append(
                _format_action_result(
                    "doc-catalog-refresh-remediation",
                    "run `python3 tools/scripts/python/doc_catalog_query.py list --limit 10` or `gpt-creator scan` to regenerate the catalog before retrying",
                )
            )
            return notes
        preview = ", ".join(normalized_candidates[:3])
        if len(normalized_candidates) > 3:
            preview += ", …"
        count_label = f"{len(normalized_candidates)} doc{'s' if len(normalized_candidates) != 1 else ''}"
        display = preview or count_label
        notes.append(
            _format_action_result(
                "doc-catalog-refresh",
                f"ok — refreshed documentation catalog ({display})",
            )
        )

        doc_ids_for_index: Set[str] = set()
        try:
            if doc_catalog_json_path.exists():
                catalog_raw = doc_catalog_json_path.read_text(encoding="utf-8")
                catalog_payload = json.loads(catalog_raw) if catalog_raw.strip() else {}
            else:
                catalog_payload = {}
        except Exception:
            catalog_payload = {}
        documents_section = catalog_payload.get("documents") if isinstance(catalog_payload, dict) else {}
        normalized_lower = [item.lower() for item in normalized_candidates]
        if isinstance(documents_section, dict):
            for doc_id, payload in documents_section.items():
                rel_path = str(payload.get("rel_path") or "").replace("\\", "/").lstrip("./").lower()
                abs_path = str(payload.get("path") or "").replace("\\", "/").lower()
                for candidate in normalized_lower:
                    if rel_path and rel_path == candidate:
                        doc_ids_for_index.add(doc_id)
                        break
                    if abs_path and abs_path.endswith(candidate):
                        doc_ids_for_index.add(doc_id)
                        break

        pipeline_cmd = [
            python_bin,
            "-m",
            "lib.doc_pipeline",
            "--project-root",
            str(project_root),
            "--runtime-dir",
            str(runtime_dir),
        ]
        try:
            pipeline_proc = subprocess.run(
                pipeline_cmd,
                cwd=str(project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError as exc:
            notes.append(
                _format_action_result(
                    "doc-pipeline-refresh",
                    f"warning — unable to refresh documentation summaries ({exc})",
                )
            )
            pipeline_proc = None
        if pipeline_proc:
            if pipeline_proc.returncode == 0:
                notes.append(
                    _format_action_result(
                        "doc-pipeline-refresh",
                        "ok — regenerated documentation summaries/excerpts",
                    )
                )
            else:
                diagnostics = pipeline_proc.stderr.strip() or pipeline_proc.stdout.strip()
                notes.append(
                    _format_action_result(
                        "doc-pipeline-refresh",
                        f"warning — documentation pipeline failed (exit {pipeline_proc.returncode}); {_shorten(diagnostics)}",
                    )
                )

        indexer_cmd: List[str]
        if doc_indexer_helper_local:
            indexer_cmd = [
                python_bin,
                doc_indexer_helper_local,
                "--runtime-dir",
                str(runtime_dir),
            ]
        else:
            indexer_cmd = [
                python_bin,
                "-m",
                "lib.doc_indexer",
                "--runtime-dir",
                str(runtime_dir),
            ]
        for doc_id in sorted(doc_ids_for_index):
            indexer_cmd.extend(["--doc-id", doc_id])
        try:
            indexer_proc = subprocess.run(
                indexer_cmd,
                cwd=str(project_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError as exc:
            notes.append(
                _format_action_result(
                    "doc-index-refresh",
                    f"warning — unable to rebuild documentation indexes ({exc})",
                )
            )
            return notes
        if indexer_proc.returncode == 0:
            index_scope = f"{len(doc_ids_for_index) or 'all'} doc{'s' if len(doc_ids_for_index) not in (0, 1) else ''}"
            notes.append(
                _format_action_result(
                    "doc-index-refresh",
                    f"ok — rebuilt documentation search/vector indexes ({index_scope})",
                )
            )
        else:
            diagnostics = indexer_proc.stderr.strip() or indexer_proc.stdout.strip()
            notes.append(
                _format_action_result(
                    "doc-index-refresh",
                    f"warning — documentation index rebuild failed (exit {indexer_proc.returncode}); {_shorten(diagnostics)}",
                )
            )
        return notes

    doc_change_candidates: List[str] = []
    for candidate_path in change_bytes.keys():
        if _path_is_doc_file(candidate_path):
            doc_change_candidates.append(candidate_path)
    for candidate_path in written:
        if _path_is_doc_file(candidate_path):
            doc_change_candidates.append(candidate_path)
    for candidate_path in patched:
        if _path_is_doc_file(candidate_path):
            doc_change_candidates.append(candidate_path)
    if doc_change_candidates:
        manual_notes.extend(_refresh_documentation_assets(doc_change_candidates))

    force_commit_env = os.environ.get("WORK_ON_TASKS_FORCE_COMMIT", "1")
    force_commit_policy = force_commit_env.strip().lower() not in {"0", "false", "no"}
    should_attempt_commit = (
        force_commit_policy
        and branch_management_enabled
        and branch_ready
        and not dirty_tree_blocked
    )
    auto_commit_ok = False
    if should_attempt_commit:
        auto_commit_ok, auto_commit_notes = _auto_commit_and_push_if_needed(actual_changes)
        manual_notes.extend(auto_commit_notes)
        if not auto_commit_ok:
            command_failure_detected = True
    else:
        reason = "commit skipped — "
        if not force_commit_policy:
            reason += "WORK_ON_TASKS_FORCE_COMMIT=0"
        elif dirty_tree_blocked:
            reason += "dirty tree detected before run"
        elif not branch_management_enabled:
            reason += "branch management disabled"
        elif not branch_ready:
            reason += "task branch unavailable"
        else:
            reason += "unknown condition"
        manual_notes.append(_format_action_result("git commit", reason))

    if (not should_attempt_commit) or (should_attempt_commit and not auto_commit_ok):
        _sync_active_branch_post_run("post-run sync")

    strict_validation = os.environ.get("WORK_ON_TASKS_STRICT_VALIDATION", "").strip().lower() in {"1", "true", "yes"}
    if dirty_tree_blocked:
        forced_canonical_status = 'BLOCKED'
        forced_legacy_status = workspace_block_reason or 'blocked-dirty-tree'
    elif strict_validation:
        if command_failure_detected:
            forced_canonical_status = 'RETRYABLE'
            forced_legacy_status = 'retryable'
        elif commands_missing:
            forced_canonical_status = 'RETRYABLE'
            forced_legacy_status = 'retryable'
    elif command_failure_detected:
        forced_canonical_status = 'RETRYABLE'
        forced_legacy_status = 'retryable'
    if actual_changes > 0:
        legacy_status = 'ok'
        canonical_status = 'COMPLETED'
    else:
        legacy_status = 'noop'
        canonical_status = 'COMPLETED-NO-CHANGES'
    if forced_canonical_status:
        canonical_status = forced_canonical_status
        legacy_status = forced_legacy_status or legacy_status
    if (
        documentation_only_run
        and canonical_status == 'RETRYABLE'
        and not dirty_tree_blocked
    ):
        canonical_status = 'COMPLETED-NO-CHANGES'
        legacy_status = 'noop'
        manual_notes.append(
            _format_action_result(
                "documentation-only-status",
                "info — verification-only session detected; marking task completed-no-changes so QA/CR can reopen if needed."
            )
        )

    if canonical_status == 'COMPLETED':
        _merge_branch_into_base_if_complete(canonical_status)
        if branch_merge_completed:
            _restore_base_branch_after_run()
    for section_name in ("plan", "focus", "commands", "notes"):
        _sanitize_section_scripts(section_name)
    raw_commands_field = payload.get('commands') or []
    summary_commands: List[str] = []
    if isinstance(raw_commands_field, list):
        for cmd in raw_commands_field:
            if not isinstance(cmd, str):
                continue
            summary_commands.append(_display_safe_command(cmd))
    _persist_agent_sections(
        payload.get('plan') or [],
        payload.get('focus') or [],
        payload.get('commands') or [],
        payload.get('notes') or [],
        canonical_response_text,
        canonical_status,
    )

    _flush_guard_events()

    for entry in manual_notes:
        lowered_entry = entry.lower()
        if any(token in lowered_entry for token in ("failed —", "blocked —", "warning —")):
            _append_error_record(entry)

    summary_notes = (payload.get('notes') or []) + manual_notes
    status_note = f"STATUS: {canonical_status}"
    if status_note not in summary_notes:
        summary_notes.append(status_note)
    base_report_commands = executed_commands if executed_commands else raw_commands_field
    display_report_commands: List[str] = []
    if isinstance(base_report_commands, list):
        for cmd in base_report_commands:
            if not isinstance(cmd, str):
                continue
            display_report_commands.append(_display_safe_command(cmd))
    if not display_report_commands:
        display_report_commands = summary_commands[:]
    logs_directory = report_rel_path
    log_paths = {
        "directory": logs_directory,
        "errors": _relativize_path(errors_log_path),
        "next_commands": _relativize_path(next_commands_path),
        "commands": _relativize_path(commands_log_path),
        "tests": _relativize_path(tests_log_path),
        "acceptance": _relativize_path(acceptance_log_path),
        "report": _relativize_path(final_report_path),
        "status": _relativize_path(status_json_path),
    }
    artifact_task_id = task_db_id or active_task_id
    if artifact_task_id:
        for label, rel_path in log_paths.items():
            if not rel_path:
                continue
            artifact_label = "logs-directory" if label == "directory" else f"log-{label}"
            _record_task_artifact(artifact_task_id, artifact_label, rel_path)
    end_report_note, end_report_file = _compose_end_report(
        canonical_status,
        display_report_commands,
        logs_directory,
        log_paths,
        acceptance_items,
    )
    if end_report_note not in summary_notes:
        summary_notes.append(end_report_note)
    _write_final_report(end_report_file)
    _write_status_snapshot(canonical_status, logs_directory, acceptance_source_path)
    summary = {
        'written': written,
        'patched': patched,
        'noop': noop_entries,
        'commands': summary_commands,
        'notes': summary_notes,
    }
    print(f'STATUS {legacy_status}')
    print(f'STATUS: {canonical_status}')
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
    if status_json_path is not None:
        meta_path_rel = _relativize_path(status_json_path)
        if meta_path_rel:
            print(f"META {meta_path_rel}")
    if commands_drift_fatal:
        print(
            "ERROR executed commands diverged from declared log; set WORK_ON_TASKS_ALLOW_DRIFT=1 to override.",
            file=sys.stderr,
        )
        sys.exit(1)
