#!/usr/bin/env python3
import sys


def main() -> int:
    data = sys.stdin.read()
    i = 0
    while i < len(data) and data[i].isspace():
        i += 1
    if i >= len(data) or data[i] != "{":
        sys.stderr.write("E: output is not a pure JSON object (non-JSON prefix)\n")
        return 3
    j = len(data) - 1
    while j >= 0 and data[j].isspace():
        j -= 1
    if j < 0 or data[j] != "}":
        sys.stderr.write("E: trailing non-JSON content detected\n")
        return 3
    sys.stdout.write(data[i : j + 1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
