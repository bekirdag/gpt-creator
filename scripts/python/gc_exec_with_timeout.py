#!/usr/bin/env python3
"""Execute a command with timeout, idle monitoring, and diff repeat detection."""

import hashlib
import os
import re
import select
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import pty


def to_int(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


timeout = to_int(sys.argv[1] if len(sys.argv) > 1 else "0")
stdin_path = sys.argv[2] if len(sys.argv) > 2 else ""
log_path = sys.argv[3] if len(sys.argv) > 3 else ""
cmd = sys.argv[4:]
max_duration = to_int(os.environ.get("GC_CODEX_EXEC_MAX_DURATION", "0"))
idle_ping_interval = to_int(os.environ.get("GC_CODEX_IDLE_PING_INTERVAL", "180"))
idle_ping_max = to_int(os.environ.get("GC_CODEX_IDLE_PING_MAX", "3"))
idle_ping_count = 0
next_idle_ping = idle_ping_interval if idle_ping_interval > 0 else 0


def describe_command(args):
    if not args:
        return "command"
    first = os.path.basename(args[0])
    tail = []
    for token in args[1:3]:
        if token.strip():
            tail.append(token)
    if tail:
        first = f"{first} {' '.join(tail)}"
    if len(args) > 3:
        first += " …"
    return first


cmd_label = describe_command(cmd)

if not cmd:
    sys.exit(1)

stdin = None
if stdin_path:
    try:
        stdin = open(stdin_path, "rb")
    except FileNotFoundError:
        print(f"{stdin_path}: No such file or directory", file=sys.stderr, flush=True)
        sys.exit(1)

log = None
if log_path:
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    log = open(log_path, "w", encoding="utf-8", buffering=1)

diff_cache = {}
diff_dir = None
diff_counter = 0
capturing_diff = False
diff_header = ""
diff_lines = []
diff_repeat_limit = to_int(os.environ.get("GC_CODEX_DIFF_REPEAT_LIMIT", "6"))
diff_repeat_counts = {}
diff_recent = deque(maxlen=max(5, diff_repeat_limit if diff_repeat_limit > 0 else 5))
last_diff_digest = None
last_diff_streak = 0
abort_now = False
abort_reason = ""
abort_repeat_count = 0
turn_limit = to_int(os.environ.get("GC_CODEX_MAX_TURNS", "0"))
turn_count = 0


def normalize_diff_for_digest(diff_text: str) -> str:
    lines = []
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("index "):
            continue
        line = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", raw_line)
        lines.append(line)
    return "\n".join(lines)


def ensure_diff_dir():
    global diff_dir
    if diff_dir is None and log_path:
        base = Path(log_path)
        diff_dir_path = base.parent / f"{base.name}.diffs"
        diff_dir_path.mkdir(parents=True, exist_ok=True)
        diff_dir = diff_dir_path
    return diff_dir


def emit(text: str) -> None:
    if not text:
        return
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except OSError:
        pass
    if log:
        try:
            log.write(text)
            log.flush()
        except OSError:
            pass


def is_diff_line(line: str) -> bool:
    if line == "":
        return True
    prefixes = (
        "diff --git ",
        "index ",
        "@@",
        "--- ",
        "+++ ",
        "+",
        "-",
        " ",
        "Binary files ",
        "No newline at end of file",
        "rename ",
        "similarity index",
        "dissimilarity index",
        "copy from",
        "copy to",
        "new file mode",
        "deleted file mode",
        "old mode",
        "new mode",
    )
    return any(line.startswith(prefix) for prefix in prefixes)


def flush_diff():
    global capturing_diff, diff_header, diff_lines, diff_counter
    global abort_now, abort_reason, abort_repeat_count, timed_out, timeout_type
    global diff_recent, last_diff_digest, last_diff_streak
    if not diff_header:
        capturing_diff = False
        diff_lines = []
        return
    diff_text = "".join(diff_lines)
    normalized_diff = normalize_diff_for_digest(diff_text)
    digest_source = normalized_diff if normalized_diff.strip() else diff_text
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    count = diff_repeat_counts.get(digest, 0) + 1
    diff_repeat_counts[digest] = count
    if last_diff_digest == digest:
        last_diff_streak = last_diff_streak + 1
    else:
        last_diff_digest = digest
        last_diff_streak = 1
    diff_recent.append(digest)
    recent_occurrences = diff_recent.count(digest)
    oscillates = False
    if len(diff_recent) >= 3:
        a, b, c = diff_recent[-3], diff_recent[-2], diff_recent[-1]
        if a == c and a != b:
            oscillates = True
    diff_dir_path = ensure_diff_dir()
    base_dir = diff_dir_path.parent if diff_dir_path is not None else os.getcwd()
    base_dir_str = str(base_dir)
    if digest in diff_cache:
        stored_path = diff_cache[digest]
        if stored_path:
            rel = os.path.relpath(str(stored_path), base_dir_str)
            emit(f"{diff_header.strip()} (repeat #{count}) see {rel}\n")
        else:
            emit(f"{diff_header.strip()} (repeat #{count} diff cached earlier)\n")
    else:
        if diff_dir_path is not None:
            diff_counter += 1
            stored_path = diff_dir_path / f"turn-{diff_counter:03d}-{digest}.patch"
            stored_path.write_text(diff_text, encoding="utf-8")
            diff_cache[digest] = stored_path
            rel = os.path.relpath(str(stored_path), base_dir_str)
            emit(f"{diff_header.strip()} stored patch {rel}\n")
        else:
            diff_cache[digest] = None
            emit(f"{diff_header.strip()} (diff of {len(diff_text)} bytes captured)\n")
    if diff_repeat_limit and diff_repeat_limit > 0 and not abort_now:
        triggered = False
        if last_diff_streak >= diff_repeat_limit:
            abort_reason = f"turn diff repeated {last_diff_streak} times consecutively"
            abort_repeat_count = last_diff_streak
            timeout_type = "diff-repeat"
            triggered = True
        elif len(diff_recent) >= diff_repeat_limit and recent_occurrences >= diff_repeat_limit:
            abort_reason = f"turn diff repeated {recent_occurrences} times within last {len(diff_recent)} turns"
            abort_repeat_count = recent_occurrences
            timeout_type = "diff-repeat"
            triggered = True
        elif oscillates:
            abort_reason = "turn diff oscillation detected (A→B→A pattern)"
            timeout_type = "diff-oscillation"
            triggered = True
        if triggered:
            abort_now = True
            timed_out = True
    capturing_diff = False
    diff_header = ""
    diff_lines.clear()


buffer = ""


def process_line(line: str):
    global capturing_diff, diff_header, diff_lines
    global abort_now, turn_count, abort_reason, timed_out, timeout_type
    stripped = line.rstrip("\n")
    lowered = stripped.lower()
    if turn_limit:
        turn_pos = lowered.find("turn ")
        if turn_pos != -1:
            prev_char = lowered[turn_pos - 1] if turn_pos > 0 else ""
            if turn_pos == 0 or prev_char in {"", " ", "\t", "]"}:
                turn_count += 1
                if turn_count >= turn_limit and not abort_now:
                    abort_now = True
                    timeout_type = "turn-limit"
                    abort_reason = f"turn limit {turn_limit} reached"
                    timed_out = True
                    return
    if capturing_diff:
        if is_diff_line(stripped):
            diff_lines.append(line)
            return
        flush_diff()
        if abort_now:
            return
    if stripped.lower().startswith("turn diff"):
        capturing_diff = True
        diff_header = stripped
        diff_lines = []
        return
    emit(line)


def process_text(text: str):
    global buffer
    global abort_now
    buffer += text
    while True:
        if "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            process_line(line + "\n")
            if abort_now:
                break
        else:
            break


preexec = os.setsid if hasattr(os, "setsid") else None

master_fd = None
slave_fd = None

try:
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=stdin,
        stdout=slave_fd,
        stderr=slave_fd,
        bufsize=0,
        preexec_fn=preexec,
        close_fds=True,
    )
    os.close(slave_fd)
    slave_fd = None
except FileNotFoundError:
    if slave_fd is not None:
        os.close(slave_fd)
    if master_fd is not None:
        os.close(master_fd)
    emit(f"{cmd[0]} not found\n")
    if log:
        log.close()
    sys.exit(127)
except Exception:
    if slave_fd is not None:
        os.close(slave_fd)
    if master_fd is not None:
        os.close(master_fd)
    raise

start = time.monotonic()
last_activity = start
timed_out = False
timeout_type = None

if master_fd is None:
    if stdin:
        stdin.close()
    if log:
        log.close()
    sys.exit(1)

fd = master_fd

interrupted = False

try:
    while True:
        now = time.monotonic()
        elapsed = now - start
        if max_duration and elapsed >= max_duration:
            timed_out = True
            timeout_type = "hard"
            break
        if timeout:
            idle_for = now - last_activity
            if (
                idle_ping_interval
                and idle_ping_max
                and next_idle_ping
                and idle_ping_count < idle_ping_max
                and idle_for >= next_idle_ping
                and not abort_now
            ):
                idle_ping_count += 1
                elapsed_sec = int(elapsed)
                idle_sec = int(idle_for)
                emit(
                    f"[gc] Waiting on {cmd_label}: no output for {idle_sec}s (elapsed {elapsed_sec}s)\n"
                )
                last_activity = time.monotonic()
                idle_for = 0.0
                if idle_ping_count < idle_ping_max:
                    next_idle_ping = idle_ping_interval
                else:
                    next_idle_ping = 0
            if idle_for >= timeout:
                timed_out = True
                timeout_type = "idle"
                break
            remaining = timeout - idle_for
            wait_time = remaining if remaining < 0.2 else 0.2
        else:
            wait_time = 0.2
        ready, _, _ = select.select([fd], [], [], wait_time)
        if ready:
            try:
                chunk = os.read(fd, 8192)
            except OSError:
                chunk = b""
            if chunk:
                text = chunk.decode("utf-8", errors="replace")
                process_text(text)
                last_activity = time.monotonic()
                if idle_ping_interval:
                    idle_ping_count = 0
                    next_idle_ping = idle_ping_interval if idle_ping_interval > 0 else 0
                if abort_now:
                    break
            else:
                break
        else:
            if proc.poll() is not None:
                break
        if abort_now:
            break
    if not timed_out and not abort_now:
        while True:
            try:
                chunk = os.read(fd, 8192)
            except OSError:
                chunk = b""
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            process_text(text)
            if idle_ping_interval:
                idle_ping_count = 0
                next_idle_ping = idle_ping_interval if idle_ping_interval > 0 else 0
            if abort_now:
                break
except KeyboardInterrupt:
    interrupted = True
    abort_now = True
    try:
        if preexec:
            os.killpg(proc.pid, signal.SIGINT)
        else:
            proc.send_signal(signal.SIGINT)
    except ProcessLookupError:
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        try:
            if preexec:
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except ProcessLookupError:
            pass
finally:
    if stdin:
        stdin.close()
    if master_fd is not None:
        try:
            os.close(master_fd)
        except OSError:
            pass
        master_fd = None

if buffer:
    process_line(buffer)
    buffer = ""

flush_diff()
if abort_now and not timed_out:
    timed_out = True

if timed_out:
    try:
        if preexec:
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        try:
            if preexec:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        proc.wait()
    if timeout_type == "hard":
        emit(f"\n[gc] Command exceeded max runtime of {max_duration} seconds\n")
    elif timeout_type == "diff-repeat":
        limit_msg = diff_repeat_limit if diff_repeat_limit else abort_repeat_count
        emit(
            f"\n[gc] Command emitted the same diff {abort_repeat_count or limit_msg} times; aborting to prevent an infinite loop\n"
        )
    elif timeout_type == "diff-oscillation":
        emit(
            "\n[gc] Command diff output oscillated between patterns (A→B→A); aborting to prevent an infinite loop\n"
        )
    elif timeout_type == "turn-limit":
        emit(
            f"\n[gc] Command exceeded the maximum of {turn_limit} Codex turns; aborting to prevent an infinite loop\n"
        )
    else:
        emit(f"\n[gc] Command produced no output for {timeout} seconds\n")
    if log:
        log.flush()
        log.close()
    if timeout_type in {"diff-repeat", "diff-oscillation"}:
        sys.exit(125)
    elif timeout_type == "turn-limit":
        sys.exit(126)
    else:
        sys.exit(124)
elif interrupted:
    if log:
        log.flush()
        log.close()
    emit("\n[gc] Command interrupted by user (KeyboardInterrupt)\n")
    sys.exit(130)

exit_code = proc.poll()
if exit_code is None:
    exit_code = proc.wait()

if log:
    log.flush()
    log.close()

sys.exit(exit_code)
