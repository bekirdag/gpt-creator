import base64
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
from typing import Iterable, List, Optional


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        log_path = tmp / "sample.log"
        usage_path = tmp / "usage.log"
        sample_log = textwrap.dedent(
            """
            [2024-01-01T00:00:00] exec /bin/bash -lc 'echo hi' in /tmp
            [2024-01-01T00:00:00] /bin/bash -lc 'echo hi' succeeded
            hi
            """
        ).strip()
        log_path.write_text(sample_log + "\n", encoding="utf-8")

        script_path = pathlib.Path(__file__).resolve()
        env = os.environ.copy()
        env.setdefault("PROJECT_ROOT", tmpdir)
        cmd = [
            sys.executable,
            str(script_path),
            str(log_path),
            str(usage_path),
            "2024-01-01T00:00:00",
            "self-test-task",
            "gpt-5-self-test",
            "prompt.txt",
            "0",
            "",
            "",
            "",
            "",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            print("self-test failed: recorder exited with non-zero status", file=sys.stderr)
            return 1
        if not usage_path.exists():
            print("self-test failed: usage log not created", file=sys.stderr)
            return 1
        usage_lines = [line for line in usage_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not usage_lines:
            print("self-test failed: usage log empty", file=sys.stderr)
            return 1
        try:
            record = json.loads(usage_lines[0])
        except json.JSONDecodeError:
            print("self-test failed: usage line not valid JSON", file=sys.stderr)
            return 1
        required = {"timestamp", "task", "usage_captured", "exit_code"}
        if not required.issubset(record):
            print(f"self-test failed: missing required keys {sorted(required - set(record))}", file=sys.stderr)
            return 1
    print("self-test ok")
    return 0


if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
    raise SystemExit(run_self_test())

if len(sys.argv) < 8:
    raise SystemExit(
        "usage: record_codex_usage.py <log_path> <usage_path> <timestamp> <task> <model> "
        "<prompt_file> <exit_code> [<cmd_cache> <stream_cache> <file_cache> <scan_cache>]"
    )

log_path = pathlib.Path(sys.argv[1])
usage_path = pathlib.Path(sys.argv[2])
timestamp = sys.argv[3]
task = sys.argv[4] or None
model = sys.argv[5] or None
prompt_file = sys.argv[6] or None
exit_code = int(sys.argv[7])
cmd_cache_arg = sys.argv[8] if len(sys.argv) > 8 else ""
cmd_cache_path = pathlib.Path(cmd_cache_arg) if cmd_cache_arg else None
stream_cache_arg = sys.argv[9] if len(sys.argv) > 9 else ""
stream_cache_path = pathlib.Path(stream_cache_arg) if stream_cache_arg else None
file_cache_arg = sys.argv[10] if len(sys.argv) > 10 else ""
file_cache_path = pathlib.Path(file_cache_arg) if file_cache_arg else None
scan_cache_arg = sys.argv[11] if len(sys.argv) > 11 else ""
scan_cache_path = pathlib.Path(scan_cache_arg) if scan_cache_arg else None

if log_path.exists():
    raw_text = log_path.read_text(encoding="utf-8", errors="ignore")
else:
    raw_text = ""

fields = {}
def parse_number(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty")
    cleaned = cleaned.strip("[]{}()")
    cleaned = cleaned.lstrip("≈~<>≤≥=")
    cleaned = cleaned.replace(",", "").replace("_", "").replace(" ", "")
    if not cleaned:
        raise ValueError("empty")
    suffix = ""
    if cleaned and cleaned[-1].lower() in ("k", "m", "b", "g", "t"):
        suffix = cleaned[-1].lower()
        cleaned = cleaned[:-1]
    if not cleaned:
        raise ValueError("empty")
    number_match = re.match(r"^[-+]?(?:\d+|\d*\.\d+)$", cleaned)
    if not number_match:
        raise ValueError("unparsable")
    value = float(cleaned)
    multipliers = {
        "": 1,
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "g": 1_000_000_000,
        "t": 1_000_000_000_000,
    }
    factor = multipliers.get(suffix, 1)
    return int(round(value * factor))

def capture(field: str, value: str) -> None:
    if not value:
        return
    try:
        fields[field] = parse_number(value)
    except Exception:
        pass

number_pattern = r'((?:\d[\d,._]*|\d*\.\d+)(?:[kKmMbBgGtT]?))'
line_patterns = [
    ("total_tokens", re.compile(r'tokens[\s_\-]*used[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("total_tokens", re.compile(r'tokens[\s_\-]*consumed[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("total_tokens", re.compile(r'total[\s_\-]*tokens?(?:\s*(?:used|consumed))?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("prompt_tokens", re.compile(r'prompt[\s_\-]*tokens?(?:\s*(?:used|consumed))?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("completion_tokens", re.compile(r'completion[\s_\-]*tokens?(?:\s*(?:used|consumed))?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("cached_tokens", re.compile(r'cached[\s_\-]*tokens?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("prompt_tokens", re.compile(r'input[\s_\-]*tokens?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("completion_tokens", re.compile(r'output[\s_\-]*tokens?["\']?[^0-9]{0,16}' + number_pattern, re.IGNORECASE)),
    ("prompt_tokens", re.compile(r'\bprompt\s*=\s*' + number_pattern, re.IGNORECASE)),
    ("completion_tokens", re.compile(r'\bcompletion\s*=\s*' + number_pattern, re.IGNORECASE)),
    ("total_tokens", re.compile(r'\btotal\s*=\s*' + number_pattern, re.IGNORECASE)),
    ("cached_tokens", re.compile(r'\bcached\s*=\s*' + number_pattern, re.IGNORECASE)),
]

for line in raw_text.splitlines():
    if not line:
        continue
    for field, pattern in line_patterns:
        for match in pattern.finditer(line):
            capture(field, match.group(1))

if "total_tokens" not in fields:
    prompt_val = fields.get("prompt_tokens")
    completion_val = fields.get("completion_tokens")
    if prompt_val is not None or completion_val is not None:
        total = (prompt_val or 0) + (completion_val or 0)
        fields["total_tokens"] = total

record = {
    "timestamp": timestamp,
    "task": task,
    "model": model,
    "prompt_file": prompt_file,
    "exit_code": exit_code,
    "usage_captured": bool(fields),
}

for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "billable_units", "request_units"):
    if key in fields:
        record[key] = fields[key]

limit_needles = [
    "usage limit",
    "usage-limit",
    "usage cap",
    "usage-cap",
    "quota exceeded",
    "quota has been reached",
    "exceeded your current quota",
    "exceeded your quota",
    "quota reached",
    "credit balance is too low",
    "billing hard limit",
    "hard usage limit",
    "usage credits exhausted",
]

limit_message = None
if raw_text:
    for line in raw_text.splitlines():
        lower = line.lower()
        if not lower.strip():
            continue
        if any(needle in lower for needle in limit_needles):
            limit_message = line.strip()
            break

if limit_message:
    record["limit_detected"] = True
    record["limit_message"] = limit_message

command_failure_lines = []
command_stream_lines = []
command_file_lines = []
command_scan_lines = []
command_guard_lines = []
guard_entries = []
failure_remediation_notes = {}

command_sequence: List[dict] = []
failures = {}

cached_failure_cache = {}
cached_failure_counts = {}
cached_failure_details = {}
if cmd_cache_path:
    try:
        cache_raw = cmd_cache_path.read_text(encoding="utf-8")
        cached_failure_cache = json.loads(cache_raw) if cache_raw.strip() else {}
        if not isinstance(cached_failure_cache, dict):
            cached_failure_cache = {}
    except Exception:
        cached_failure_cache = {}

if cached_failure_cache:
    for value in cached_failure_cache.values():
        if not isinstance(value, dict):
            continue
        command_text = value.get("command")
        if not isinstance(command_text, str):
            continue
        try:
            count = int(value.get("count") or 0)
        except Exception:
            count = 0
        if count < 0:
            count = 0
        cached_failure_counts[command_text] = count
        cached_failure_details.setdefault(command_text, value)
if raw_text:
    lines_list = raw_text.splitlines()
    total_lines = len(lines_list)
    exec_pattern = re.compile(
        r"exec\s+[^\s]+\s+-lc\s+(?:'(?P<sqcmd>[^']*)'|\"(?P<dqcmd>[^\"]*)\"|(?P<plain>\S+))(?:\s+in\s+(?P<cwd>\S+))?"
    )
    result_pattern = re.compile(
        r"^\[(?P<ts>[^]]+)\]\s+[^\s]+\s+-lc\s+(?:(?P<sq>'(?P<sqcmd>[^']*)')|(?P<dq>\"(?P<dqcmd>[^\"]*)\")|(?P<plain>\S+))\s+(?P<outcome>succeeded|exited)\s*(?P<rest>.*)$"
    )
    timestamp_pattern = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]")
    line_timestamp_pattern = re.compile(r"^\[(?P<ts>[^]]+)\]")
    project_root_hint = os.getenv("PROJECT_ROOT", "")
    try:
        project_root_path = pathlib.Path(project_root_hint).resolve() if project_root_hint else None
    except (OSError, RuntimeError, ValueError):
        project_root_path = None

def resolve_workdir(cwd: str, project_root_path: Optional[pathlib.Path]) -> pathlib.Path:
    if cwd:
        candidate = pathlib.Path(cwd)
        if candidate.is_absolute():
            return candidate
        base = project_root_path or pathlib.Path.cwd()
        return base / candidate
    return project_root_path or pathlib.Path.cwd()

def iter_command_entries(sequence: Optional[List[dict]]) -> Iterable[dict]:
    if not isinstance(sequence, list):
        return
    for item in sequence:
        if isinstance(item, dict):
            yield item

def normalise_candidate_path(raw: str, cwd: str) -> Optional[pathlib.Path]:
    candidate = (raw or "").strip()
    if not candidate:
        return None
    candidate = candidate.split("|", 1)[0]
    candidate = candidate.split(">", 1)[0]
    candidate = candidate.split("<", 1)[0]
    candidate = candidate.split(";", 1)[0]
    candidate = candidate.strip()
    if candidate.startswith(("'", '"')) and candidate.endswith(candidate[0]) and len(candidate) >= 2:
        candidate = candidate[1:-1].strip()
    if not candidate:
        return None
    candidate = os.path.expanduser(candidate)
    if os.path.isabs(candidate):
        path_obj = pathlib.Path(candidate)
    else:
        base = pathlib.Path(cwd) if cwd else project_root_path
        if base:
            path_obj = base / candidate
        else:
            path_obj = pathlib.Path(candidate)
    try:
        resolved = path_obj.resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = path_obj
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved

    def build_file_info(path_obj: pathlib.Path, start: Optional[int], end: Optional[int], mode: str) -> Optional[dict]:
        try:
            stat = path_obj.stat()
        except OSError:
            return None
        mtime_ns = getattr(stat, "st_mtime_ns", None)
        if mtime_ns is None:
            mtime_ns = int(stat.st_mtime * 1_000_000_000)
        size = int(stat.st_size)
        rel_path = str(path_obj)
        if project_root_path:
            try:
                rel_path = str(path_obj.relative_to(project_root_path))
            except ValueError:
                rel_path = str(path_obj)
        max_chars = 2000
        max_lines = 80
        excerpt_lines: List[str] = []
        if start is not None and end is not None:
            lower = max(1, min(start, end))
            upper = max(lower, max(start, end))
            try:
                with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
                    for idx, line in enumerate(handle, start=1):
                        if idx < lower:
                            continue
                        if idx > upper:
                            break
                        excerpt_lines.append(line.rstrip("\n"))
                        if len(excerpt_lines) >= max_lines:
                            break
            except OSError:
                excerpt_lines = []
            summary = f"{rel_path} lines {lower}-{upper}"
            range_value = [lower, upper]
        else:
            try:
                with path_obj.open("r", encoding="utf-8", errors="replace") as handle:
                    for _, line in zip(range(max_lines), handle):
                        excerpt_lines.append(line.rstrip("\n"))
            except OSError:
                excerpt_lines = []
            summary = f"{rel_path} (sample)"
            range_value = None
        excerpt_text = "\n".join(excerpt_lines)
        if len(excerpt_text) > max_chars:
            excerpt_text = excerpt_text[: max_chars - 3].rstrip() + "..."
        return {
            "path": str(path_obj),
            "rel_path": rel_path,
            "range": range_value,
            "mode": mode,
            "excerpt": excerpt_text,
            "mtime_ns": int(mtime_ns),
            "size": size,
            "summary": summary,
        }

    sed_chunk_pattern = re.compile(
        r"^sed\s+-n\s+['\"]?(?P<start>\d+)\s*,\s*(?P<end>\d+)[pP]['\"]?\s+(?P<path>[^|;]+)"
    )
    cat_pattern = re.compile(r"^cat\s+(?P<path>[^>|;&]+)$")

    def parse_file_read(command: str, cwd: str) -> Optional[dict]:
        command = (command or "").strip()
        if not command:
            return None
        sed_match = sed_chunk_pattern.match(command)
        if sed_match:
            path_obj = normalise_candidate_path(sed_match.group("path"), cwd)
            if not path_obj:
                return None
            try:
                start_val = int(sed_match.group("start"))
                end_val = int(sed_match.group("end"))
            except (TypeError, ValueError):
                return None
            return build_file_info(path_obj, start_val, end_val, "sed")
        cat_match = cat_pattern.match(command)
        if cat_match:
            path_obj = normalise_candidate_path(cat_match.group("path"), cwd)
            if not path_obj:
                return None
            return build_file_info(path_obj, None, None, "cat")
        return None

    failures = {}
    command_sequence = []
    i = 0
    while i < total_lines:
        line = lines_list[i]
        exec_match = exec_pattern.search(line)
        if exec_match:
            raw_cmd = (
                exec_match.group("sqcmd")
                or exec_match.group("dqcmd")
                or exec_match.group("plain")
                or ""
            )
            command_text = raw_cmd.strip()
            command_cwd = exec_match.group("cwd") or ""
            ts_match = line_timestamp_pattern.match(line)
            command_timestamp = ts_match.group("ts") if ts_match else ""
            current_entry = None
            if command_text:
                current_entry = {
                    "command": command_text,
                    "timestamp": command_timestamp,
                    "cwd": command_cwd,
                }
                command_sequence.append(current_entry)
            j = i + 1
            while j < total_lines:
                result_line = lines_list[j]
                result_match = result_pattern.match(result_line)
                if result_match:
                    outcome = result_match.group("outcome")
                    exit_value = 0
                    if outcome == "exited":
                        rest_text = result_match.group("rest") or ""
                        code_match = re.search(r"(-?\d+)", rest_text)
                        if code_match:
                            try:
                                exit_value = int(code_match.group(1))
                            except Exception:
                                exit_value = 1
                        else:
                            exit_value = 1
                    output_lines = []
                    k = j + 1
                    while k < total_lines and not timestamp_pattern.match(lines_list[k]):
                        output_lines.append(lines_list[k])
                        k += 1
                    summary_text = "\n".join(output_lines).strip()
                    stored_lines = output_lines[:80]
                    truncated_flag = len(output_lines) > len(stored_lines)
                    preview_text = "\n".join(stored_lines).strip()
                    if len(preview_text) > 2000:
                        preview_text = preview_text[:1997] + "..."
                        truncated_flag = True
                    if current_entry is not None:
                        current_entry["output_lines"] = stored_lines
                        current_entry["output_line_count"] = len(output_lines)
                        current_entry["output_truncated"] = truncated_flag
                        current_entry["output"] = preview_text
                    if exit_value != 0:
                        trimmed_summary = summary_text
                        if trimmed_summary.count("\n") > 30:
                            summary_rows = trimmed_summary.splitlines()
                            trimmed_summary = "\n".join(summary_rows[:30])
                            trimmed_summary += "\n... (output truncated) ..."
                        if len(trimmed_summary) > 1800:
                            trimmed_summary = trimmed_summary[:1797] + "..."
                        digest_source = f"{project_root_hint}\n{command_text}\n{exit_value}\n{trimmed_summary}"
                        digest = hashlib.sha256(digest_source.encode("utf-8", "ignore")).hexdigest()[:12]
                        entry = failures.get(digest)
                        if entry:
                            entry["count"] += 1
                        else:
                            entry = {
                                "command": command_text,
                                "exit": exit_value,
                                "summary": trimmed_summary,
                                "count": 1,
                                "digest": digest,
                            }
                        failures[digest] = entry
                    i = k - 1
                    break
                elif timestamp_pattern.match(result_line):
                    i = j - 1
                    break
                else:
                    j += 1
        i += 1

    sed_chunk_pattern = re.compile(
        r"^sed\s+-n\s+['\"]?(?P<start>\d+)\s*,\s*(?P<end>\d+)[pP]['\"]?\s+(?P<path>[^|;]+)"
    )

    def parse_sed_chunk(command: str):
        match = sed_chunk_pattern.match(command)
        if not match:
            return None
        try:
            start = int(match.group("start"))
            end = int(match.group("end"))
        except Exception:
            return None
        path = match.group("path").strip()
        path = path.split("|", 1)[0].strip()
        path = path.split(";", 1)[0].strip()
        if path.startswith(("'", '"')) and path.endswith(path[0]) and len(path) >= 2:
            path = path[1:-1]
        if not path:
            return None
        return {"file": path, "start": start, "end": end}

    build_artifact_dirs = {"dist", "dist-tests", "build", "coverage", "out", "tmp", ".next", "node_modules", "public-build"}

    def is_build_artifact_path(rel_path: str) -> bool:
        if not rel_path:
            return False
        normalized = rel_path.replace("\\", "/").strip("/")
        if not normalized:
            return False
        parts = [part for part in normalized.split("/") if part]
        for idx, part in enumerate(parts):
            if part in build_artifact_dirs:
                if part == "dist" and idx > 0 and parts[idx - 1] == "src":
                    continue
                return True
        return False

    def finalize_sequence(seq, results):
        if not seq:
            return
        coverage_lines = seq["coverage_end"] - seq["coverage_start"] + 1
        if seq["count"] >= 2 and coverage_lines >= 180:
            seq["coverage_lines"] = coverage_lines
            results.append(seq)

    stream_sequences = []
    current_seq = None
    gap_threshold = 40
    sequence_iterable = command_sequence if isinstance(command_sequence, list) else []
    try:
        for entry in sequence_iterable:
            if not isinstance(entry, dict):
                continue
            try:
                command_text = (entry.get("command") or "").strip()
                try:
                    workdir_path = resolve_workdir(entry.get("cwd") or "", project_root_path)
                except Exception:
                    workdir_path = project_root_path or pathlib.Path.cwd()
                pnpm_issues = []
                if command_text:
                    try:
                        parts = shlex.split(command_text)
                    except ValueError:
                        parts = command_text.split()
                    if parts and parts[0] == "pnpm":
                        task_token = ""
                        idx = 1
                        skip_next = False
                        while idx < len(parts):
                            token = parts[idx]
                            if skip_next:
                                skip_next = False
                                idx += 1
                                continue
                            if token in {"-C", "--dir", "--filter", "-F"}:
                                skip_next = True
                                idx += 1
                                continue
                            if token.startswith("-"):
                                idx += 1
                                continue
                            task_token = token
                            idx += 1
                            break
                        if task_token == "run" and idx < len(parts):
                            task_token = parts[idx]
                        pnpm_task = task_token
                        if pnpm_task in {"test", "build"}:
                            modules_paths = [
                                workdir_path / "node_modules",
                                workdir_path / "node_modules" / ".pnpm",
                            ]
                            if project_root_path:
                                modules_paths.extend([
                                    project_root_path / "node_modules",
                                    project_root_path / "node_modules" / ".pnpm",
                                ])
                            modules_present = any(path.exists() for path in modules_paths)
                            if not modules_present:
                                pnpm_issues.append("node_modules missing; run `pnpm install` before invoking pnpm test/build.")
                            failure_entry = cached_failure_details.get(command_text)
                            if failure_entry:
                                try:
                                    prev_count = int(failure_entry.get("count") or 0)
                                except Exception:
                                    prev_count = 0
                                if prev_count > 0:
                                    summary = (failure_entry.get("last_summary") or failure_entry.get("summary") or "").strip()
                                    pnpm_issues.append(
                                        f"Command previously failed {prev_count} time(s){': ' + summary if summary else ''}"
                                    )
                            for value in cached_failure_cache.values():
                                if not isinstance(value, dict):
                                    continue
                                cmd_text = value.get("command")
                                if isinstance(cmd_text, str) and cmd_text.strip().startswith("pnpm install"):
                                    try:
                                        install_fail_count = int(value.get("count") or 0)
                                    except Exception:
                                        install_fail_count = 0
                                    if install_fail_count > 0:
                                        install_summary = (value.get("last_summary") or value.get("summary") or "").strip()
                                        pnpm_issues.append(
                                            f"`pnpm install` previously failed {install_fail_count} time(s){': ' + install_summary if install_summary else ''}"
                                        )
                                    break
                        if pnpm_issues:
                            digest_source = f"{project_root_hint}\n{command_text}\n{entry.get('cwd') or ''}"
                            guard_digest = hashlib.sha256(digest_source.encode('utf-8', 'ignore')).hexdigest()[:12]
                            encoded_command = base64.b64encode(command_text.encode('utf-8')).decode('ascii') if command_text else ""
                            guard_message = ' '.join(pnpm_issues)
                            encoded_message = base64.b64encode(guard_message.encode('utf-8')).decode('ascii') if guard_message else ""
                            command_guard_lines.append(
                                f"CMDGUARD\t{guard_digest}\t0\t{len(pnpm_issues)}\t{encoded_command}\t{encoded_message}"
                            )
                            guard_entries.append({
                                "command": command_text,
                                "issues": list(pnpm_issues),
                            })
                parsed = parse_sed_chunk(command_text)
                if not parsed:
                    if current_seq:
                        finalize_sequence(current_seq, stream_sequences)
                        current_seq = None
                    continue
                start = min(parsed["start"], parsed["end"])
                end = max(parsed["start"], parsed["end"])
                length = max(0, end - start + 1)
                if length <= 0:
                    if current_seq:
                        finalize_sequence(current_seq, stream_sequences)
                        current_seq = None
                    continue
                if current_seq and current_seq["file"] == parsed["file"]:
                    prev = current_seq["entries"][-1]
                    gap = start - prev["end"]
                    if gap <= gap_threshold or start <= prev["end"]:
                        current_seq["entries"].append(
                            {"start": start, "end": end, "command": command_text, "length": length}
                        )
                        current_seq["coverage_start"] = min(current_seq["coverage_start"], start)
                        current_seq["coverage_end"] = max(current_seq["coverage_end"], end)
                        current_seq["total_lines"] += length
                        current_seq["count"] += 1
                        continue
                    finalize_sequence(current_seq, stream_sequences)
                current_seq = {
                    "file": parsed["file"],
                    "entries": [{"start": start, "end": end, "command": command_text, "length": length}],
                    "coverage_start": start,
                    "coverage_end": end,
                    "total_lines": length,
                    "count": 1,
                }
            except Exception as entry_error:
                print(f"USAGE_LOG_WARNING\tcommand_sequence_entry_error\t{entry_error}", file=sys.stderr)
                continue
    except Exception as stream_error:
        print(f"USAGE_LOG_WARNING\tcommand_sequence_processing_failed\t{stream_error}", file=sys.stderr)
        stream_sequences = []
        current_seq = None
    if current_seq:
        finalize_sequence(current_seq, stream_sequences)

    file_cache_data = {}
    if file_cache_path:
        try:
            contents = file_cache_path.read_text(encoding="utf-8")
            file_cache_data = json.loads(contents) if contents.strip() else {}
            if not isinstance(file_cache_data, dict):
                file_cache_data = {}
        except Exception:
            file_cache_data = {}

    for entry in iter_command_entries(command_sequence):
        try:
            parsed_read = parse_file_read(entry.get("command"), entry.get("cwd") or "")
            if not parsed_read:
                continue
            digest_source_parts = [
                parsed_read.get("path", ""),
                parsed_read.get("mode", ""),
                str(parsed_read.get("range") or "full"),
                str(parsed_read.get("mtime_ns") or 0),
            ]
            digest_source = "::".join(digest_source_parts)
            digest = hashlib.sha256(digest_source.encode("utf-8", "ignore")).hexdigest()[:12]
            existing_entry = None
            if file_cache_data:
                existing_entry = file_cache_data.get(digest)
            prev_count = 0
            repeat_flag = False
            if isinstance(existing_entry, dict):
                try:
                    prev_count = int(existing_entry.get("count") or 0)
                except Exception:
                    prev_count = 0
                repeat_flag = prev_count > 0
            new_count = prev_count + 1
            record_entry = existing_entry or {}
            if not record_entry.get("first_seen"):
                record_entry["first_seen"] = timestamp
            record_entry["last_seen"] = timestamp
            record_entry["path"] = parsed_read.get("path")
            record_entry["rel_path"] = parsed_read.get("rel_path")
            record_entry["range"] = parsed_read.get("range")
            record_entry["mode"] = parsed_read.get("mode")
            record_entry["count"] = new_count
            record_entry["mtime_ns"] = parsed_read.get("mtime_ns")
            record_entry["size"] = parsed_read.get("size")
            record_entry["summary"] = parsed_read.get("summary")
            record_entry["excerpt"] = parsed_read.get("excerpt")
            record_entry["last_task"] = task
            rel_hint = record_entry.get("rel_path") or parsed_read.get("rel_path") or ""
            abs_hint = record_entry.get("path") or parsed_read.get("path") or ""
            build_artifact = False
            if rel_hint and is_build_artifact_path(rel_hint):
                build_artifact = True
            elif abs_hint:
                try:
                    abs_path_obj = pathlib.Path(abs_hint)
                    if project_root_path:
                        try:
                            rel_from_root = abs_path_obj.resolve().relative_to(project_root_path)
                            if is_build_artifact_path(str(rel_from_root)):
                                build_artifact = True
                        except Exception:
                            if is_build_artifact_path(str(abs_path_obj)):
                                build_artifact = True
                    else:
                        if is_build_artifact_path(str(abs_path_obj)):
                            build_artifact = True
                except Exception:
                    build_artifact = False
            if build_artifact:
                record_entry["category"] = "build-artifact"
                parsed_read["category"] = "build-artifact"
                parsed_read["excerpt"] = ""
                record_entry["excerpt"] = ""
            file_cache_data[digest] = record_entry
            summary_text = parsed_read.get("summary") or ""
            excerpt_text = parsed_read.get("excerpt") or ""
            encoded_summary = base64.b64encode(summary_text.encode("utf-8")).decode("ascii")
            encoded_excerpt = base64.b64encode(excerpt_text.encode("utf-8")).decode("ascii") if excerpt_text else ""
            repeat_flag_int = 1 if repeat_flag else 0
            command_file_lines.append(
                f"CMDFILE\t{digest}\t{repeat_flag_int}\t{new_count}\t{encoded_summary}\t{encoded_excerpt}"
            )
        except Exception as file_entry_error:
            print(f"USAGE_LOG_WARNING\tfile_cache_entry_error\t{file_entry_error}", file=sys.stderr)
            continue

    scan_cache_data = {}
    if scan_cache_path:
        try:
            contents = scan_cache_path.read_text(encoding="utf-8")
            scan_cache_data = json.loads(contents) if contents.strip() else {}
            if not isinstance(scan_cache_data, dict):
                scan_cache_data = {}
        except Exception:
            scan_cache_data = {}

    for entry in iter_command_entries(command_sequence):
        try:
            classification = classify_directory_crawl(entry.get("command") or "")
            if not classification:
                continue
            digest_source = f"{project_root_hint}\n{entry.get('command') or ''}\n{entry.get('cwd') or ''}"
            digest = hashlib.sha256(digest_source.encode("utf-8", "ignore")).hexdigest()[:12]
            prev_count = 0
            repeat_flag = False
            existing_entry = None
            if scan_cache_data:
                existing_entry = scan_cache_data.get(digest)
                if isinstance(existing_entry, dict):
                    try:
                        prev_count = int(existing_entry.get("count") or 0)
                    except Exception:
                        prev_count = 0
                    repeat_flag = prev_count > 0
                else:
                    existing_entry = None
            new_count = prev_count + 1
            record_entry = existing_entry or {}
            if not record_entry.get("first_seen"):
                record_entry["first_seen"] = timestamp
            record_entry["last_seen"] = timestamp
            command_text = entry.get("command") or ""
            record_entry["command"] = command_text
            cwd_raw = entry.get("cwd") or ""
            record_entry["cwd"] = cwd_raw
            cwd_display = cwd_raw
            if project_root_path:
                try:
                    resolved_cwd = resolve_workdir(cwd_raw, project_root_path)
                except Exception:
                    resolved_cwd = None
                if resolved_cwd:
                    try:
                        rel_cwd = resolved_cwd.relative_to(project_root_path)
                        cwd_display = "." if str(rel_cwd) in {"", "."} else str(rel_cwd)
                    except Exception:
                        try:
                            cwd_display = str(resolved_cwd)
                        except Exception:
                            cwd_display = cwd_raw
            record_entry["cwd_display"] = cwd_display
            record_entry["count"] = new_count
            record_entry["message"] = classification
            output_lines = entry.get("output_lines") or []
            try:
                line_count = int(entry.get("output_line_count") or len(output_lines))
            except Exception:
                line_count = len(output_lines)
            truncated_flag = bool(entry.get("output_truncated"))
            if output_lines:
                max_preview_lines = 12
                preview_lines = []
                for raw_line in output_lines[:max_preview_lines]:
                    preview_lines.append((raw_line or "").strip())
                record_entry["lines"] = preview_lines
                record_entry["line_count"] = line_count
                record_entry["truncated"] = int(truncated_flag or len(output_lines) > max_preview_lines)
                preview_text = (entry.get("output") or "\n".join(preview_lines)).strip()
                if len(preview_text) > 480:
                    preview_text = preview_text[:477] + "..."
                    record_entry["truncated"] = 1
                record_entry["preview"] = preview_text
            else:
                if "lines" not in record_entry:
                    record_entry["lines"] = []
                if "line_count" not in record_entry or line_count:
                    record_entry["line_count"] = line_count
                if truncated_flag:
                    record_entry["truncated"] = 1
                if "preview" not in record_entry:
                    record_entry["preview"] = ""
            scan_cache_data[digest] = record_entry
            encoded_command = base64.b64encode(command_text.encode("utf-8")).decode("ascii") if command_text else ""
            encoded_message = base64.b64encode(classification.encode("utf-8")).decode("ascii")
            repeat_flag_int = 1 if repeat_flag else 0
            command_scan_lines.append(
                f"CMDSCAN\t{digest}\t{repeat_flag_int}\t{new_count}\t{encoded_command}\t{encoded_message}"
            )
        except Exception as scan_entry_error:
            print(f"USAGE_LOG_WARNING\tcommand_scan_entry_error\t{scan_entry_error}", file=sys.stderr)
            continue

    if scan_cache_path:
        if len(scan_cache_data) > 80:
            sorted_items = sorted(
                scan_cache_data.items(),
                key=lambda item: item[1].get("last_seen", ""),
                reverse=True,
            )
            scan_cache_data = dict(sorted_items[:80])
        try:
            scan_cache_path.parent.mkdir(parents=True, exist_ok=True)
            scan_cache_path.write_text(json.dumps(scan_cache_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def remediation_message(command_text, failure_count=1, exit_code=None):
        cmd = (command_text or "").strip()
        lower = cmd.lower()
        base = "Investigate the failure output above and fix the root cause."
        if "pnpm" in lower and "build" in lower:
            base = "Review the pnpm build errors and update the source code or configuration."
        elif "pnpm" in lower and "test" in lower:
            base = "Fix the failing tests or prerequisites before running this test command again."
        elif "pnpm" in lower and "install" in lower:
            base = "Resolve the installation issue (dependency or network) before retrying `pnpm install`."
        elif "pnpm" in lower:
            base = "Resolve the pnpm command failure before rerunning."
        elif "npm" in lower and "run" in lower:
            base = "Fix the npm script failure before rerunning the command." 
        elif lower.startswith("go test") or " go test" in lower:
            base = "Correct the Go test failure before re-running `go test`."
        elif "pytest" in lower:
            base = "Fix the pytest errors before rerunning the tests."
        elif "make " in lower:
            base = "Address the make target failure before rerunning."
        if failure_count and failure_count > 1:
            suffix = f" It has already failed {failure_count} time(s); do not rerun until the fix is applied and documented."
        else:
            suffix = " Do not rerun until the fix is applied and documented."
        return base + suffix

    if failures:
        cache_data = dict(cached_failure_cache)
        for digest, entry in failures.items():
            summary_line = entry.get("summary") or ""
            summary_line = re.sub(r'\s+\n', '\n', summary_line)
            summary_line = re.sub(r'\n\s+', '\n', summary_line).strip()
            entry["summary"] = summary_line
            if cmd_cache_path:
                existing = cache_data.get(digest)
                if isinstance(existing, dict):
                    prev_count = int(existing.get("count", 0))
                    existing["count"] = prev_count + entry["count"]
                    existing["last_seen"] = timestamp
                    existing["last_summary"] = summary_line
                    existing["command"] = entry["command"]
                    existing["exit"] = entry["exit"]
                    if "first_seen" not in existing:
                        existing["first_seen"] = timestamp
                    entry["repeat"] = prev_count > 0
                    entry["total_failures"] = existing["count"]
                else:
                    cache_data[digest] = {
                        "command": entry["command"],
                        "exit": entry["exit"],
                        "summary": summary_line,
                        "count": entry["count"],
                        "first_seen": timestamp,
                        "last_seen": timestamp,
                        "last_summary": summary_line,
                    }
                    entry["repeat"] = False
                    entry["total_failures"] = entry["count"]
            else:
                entry["repeat"] = False
                entry["total_failures"] = entry["count"]

        if cmd_cache_path:
            if len(cache_data) > 50:
                sorted_items = sorted(
                    cache_data.items(),
                    key=lambda item: item[1].get("last_seen", ""),
                    reverse=True,
                )
                cache_data = dict(sorted_items[:50])
            try:
                cmd_cache_path.parent.mkdir(parents=True, exist_ok=True)
                cmd_cache_path.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
            except Exception:
                pass

        guard_failure_commands = set()
        for entry in failures.values():
            summary_single = entry.get("summary") or ""
            summary_single = re.sub(r"\s+", " ", summary_single).strip()
            if len(summary_single) > 240:
                summary_single = summary_single[:237] + "..."
            encoded_command = base64.b64encode(entry["command"].encode("utf-8")).decode("ascii")
            encoded_summary = (
                base64.b64encode(summary_single.encode("utf-8")).decode("ascii") if summary_single else ""
            )
            repeat_flag = 1 if entry.get("repeat") else 0
            total_failures = entry.get("total_failures", entry["count"])
            remediation_note = remediation_message(entry.get("command"), total_failures, entry.get("exit"))
            command_text_clean = (entry.get("command") or "").strip()
            if command_text_clean:
                failure_remediation_notes[command_text_clean] = remediation_note
                if command_text_clean not in guard_failure_commands:
                    issues = [remediation_note]
                    if summary_single:
                        issues.append(f"Last failure: {summary_single}")
                    guard_digest_source = f"{project_root_hint}\n{command_text_clean}\nremediation"
                    guard_digest = hashlib.sha256(guard_digest_source.encode("utf-8", "ignore")).hexdigest()[:12]
                    encoded_guard_command = base64.b64encode(command_text_clean.encode("utf-8")).decode("ascii")
                    encoded_guard_message = base64.b64encode("; ".join(issues).encode("utf-8")).decode("ascii")
                    repeat_flag_guard = 1 if total_failures and total_failures > 1 else 0
                    command_guard_lines.append(
                        f"CMDGUARD\t{guard_digest}\t{repeat_flag_guard}\t{len(issues)}\t{encoded_guard_command}\t{encoded_guard_message}"
                    )
                    guard_entries.append({
                        "command": command_text_clean,
                        "issues": issues,
                    })
                    guard_failure_commands.add(command_text_clean)
            command_failure_lines.append(
                f"CMDFAIL\t{repeat_flag}\t{total_failures}\t{entry['exit']}\t{entry['digest']}\t{encoded_command}\t{encoded_summary}"
            )

    if stream_sequences:
        stream_cache_data = {}
        if stream_cache_path:
            try:
                contents = stream_cache_path.read_text(encoding="utf-8")
                stream_cache_data = json.loads(contents) if contents.strip() else {}
                if not isinstance(stream_cache_data, dict):
                    stream_cache_data = {}
            except Exception:
                stream_cache_data = {}
        for seq in stream_sequences:
            coverage_start = seq["coverage_start"]
            coverage_end = seq["coverage_end"]
            coverage_lines = seq["coverage_lines"]
            command_examples = [item["command"] for item in seq["entries"][:3]]
            summary_text = (
                f"{seq['file']}: sequential sed chunks {coverage_start}-{coverage_end} covering ~{coverage_lines} lines via {seq['count']} commands."
            )
            if command_examples:
                summary_text += f" Example: {command_examples[0]}"
                if len(command_examples) > 1:
                    summary_text += f" → {command_examples[1]}"
            advice_text = (
                f"Switch to targeted search (e.g. rg -n '<term>' {seq['file']} -C20) or "
                f"use gpt-creator show-file {seq['file']} --range {coverage_start}:{min(coverage_end, coverage_start + 200)} "
                "to inspect slices without streaming entire files."
            )
            digest_source = f"{project_root_hint}\n{seq['file']}\n{coverage_start}-{coverage_end}"
            digest = hashlib.sha256(digest_source.encode("utf-8", "ignore")).hexdigest()[:12]
            prev_count = 0
            repeat_flag = False
            existing_entry = None
            if stream_cache_path:
                existing_entry = stream_cache_data.get(digest)
                if isinstance(existing_entry, dict):
                    try:
                        prev_count = int(existing_entry.get("count", 0))
                    except Exception:
                        prev_count = 0
                    repeat_flag = prev_count > 0
                else:
                    existing_entry = None
            new_count = prev_count + 1
            if stream_cache_path:
                record_entry = existing_entry or {}
                if not record_entry.get("first_seen"):
                    record_entry["first_seen"] = timestamp
                record_entry["last_seen"] = timestamp
                record_entry["file"] = seq["file"]
                record_entry["coverage"] = [coverage_start, coverage_end]
                record_entry["count"] = new_count
                record_entry["summary"] = summary_text
                record_entry["advice"] = advice_text
                record_entry["commands"] = command_examples
                stream_cache_data[digest] = record_entry
            encoded_summary = base64.b64encode(summary_text.encode("utf-8")).decode("ascii")
            encoded_advice = base64.b64encode(advice_text.encode("utf-8")).decode("ascii") if advice_text else ""
            repeat_flag_int = 1 if repeat_flag else 0
            command_stream_lines.append(
                f"CMDSTREAM\t{digest}\t{repeat_flag_int}\t{new_count}\t{encoded_summary}\t{encoded_advice}"
            )
        if stream_cache_path:
            if len(stream_cache_data) > 50:
                sorted_items = sorted(
                    stream_cache_data.items(),
                    key=lambda item: item[1].get("last_seen", ""),
                    reverse=True,
                )
                stream_cache_data = dict(sorted_items[:50])
            try:
                stream_cache_path.parent.mkdir(parents=True, exist_ok=True)
                stream_cache_path.write_text(json.dumps(stream_cache_data, indent=2), encoding="utf-8")
            except Exception:
                pass

    if file_cache_path:
        if len(file_cache_data) > 120:
            sorted_items = sorted(
                file_cache_data.items(),
                key=lambda item: item[1].get("last_seen", ""),
                reverse=True,
            )
            file_cache_data = dict(sorted_items[:120])
        try:
            file_cache_path.parent.mkdir(parents=True, exist_ok=True)
            file_cache_path.write_text(json.dumps(file_cache_data, indent=2), encoding="utf-8")
        except Exception:
            pass

usage_path.parent.mkdir(parents=True, exist_ok=True)
with usage_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
    fh.write("\n")

for entry_line in command_failure_lines:
    print(entry_line)

for entry_line in command_stream_lines:
    print(entry_line)

for entry_line in command_scan_lines:
    print(entry_line)

for entry_line in command_guard_lines:
    print(entry_line)

for entry_line in command_file_lines:
    print(entry_line)

if fields:
    prompt_value = int(fields.get("prompt_tokens") or 0)
    completion_value = int(fields.get("completion_tokens") or 0)
    total_value = int(fields.get("total_tokens") or (prompt_value + completion_value))
    print(f"USAGE\t{prompt_value}\t{completion_value}\t{total_value}")

if limit_message:
    print(f"LIMIT_DETECTED\t{limit_message}")
