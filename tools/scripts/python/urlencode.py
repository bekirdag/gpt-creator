#!/usr/bin/env python3
"""URL-encode a value for use in query parameters."""

import sys
from urllib.parse import quote


def main(argv) -> None:
    value = argv[1] if len(argv) > 1 else ""
    print(quote(value))


if __name__ == "__main__":
    main(sys.argv)
