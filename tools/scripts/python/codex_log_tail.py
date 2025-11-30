import base64
import hashlib
import os
import sys
from typing import Tuple


def read_file_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except Exception:
        return b""


def extract_last_turn_block(text: str) -> Tuple[str, int]:
    lines = text.splitlines()
    blocks = []
    buffer = []
    in_block = False
    for line in lines:
        if line.startswith("[") and " turn diff:" in line:
            if in_block and buffer:
                blocks.append("\n".join(buffer))
                buffer = []
            buffer = [line]
            in_block = True
            continue
        if in_block and line.startswith("["):
            if buffer:
                blocks.append("\n".join(buffer))
            buffer = []
            in_block = False
        if in_block:
            buffer.append(line)
    if in_block and buffer:
        blocks.append("\n".join(buffer))
    if blocks:
        return blocks[-1], len(blocks)
    return "", 0


def main() -> int:
    if len(sys.argv) < 2:
        print("none")
        print("")
        print("")
        print("0")
        return 0

    path = sys.argv[1]
    slice_env = os.environ.get("GC_DIFF_GUARD_STDOUT_SLICE", "2048") or "2048"
    try:
        slice_bytes = int(slice_env)
    except ValueError:
        slice_bytes = 2048

    data = read_file_bytes(path)
    if not data:
        print("none")
        print("")
        print("")
        print("0")
        return 0

    tail = data[-slice_bytes:] if slice_bytes > 0 else data
    tail_hash = hashlib.sha1(tail).hexdigest() if tail else "none"

    try:
        tail_text = tail.decode("utf-8", errors="replace")
    except Exception:
        tail_text = ""

    tail_b64 = (
        base64.b64encode(tail_text.encode("utf-8")).decode("ascii") if tail_text else ""
    )

    last_block, block_count = extract_last_turn_block(tail_text)
    turn_hash = hashlib.sha1(last_block.encode("utf-8")).hexdigest() if last_block else ""

    print(tail_hash)
    print(tail_b64)
    print(turn_hash)
    print(str(block_count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
