#!/usr/bin/env python3
import hashlib
import sys


def main(argv):
    if len(argv) < 2:
        raise SystemExit("Usage: make_attempt_signature.py <payload>")

    payload = argv[1].encode("utf-8", "ignore")
    digest = hashlib.sha256(payload).hexdigest()
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
