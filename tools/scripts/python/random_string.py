#!/usr/bin/env python3
"""Generate a pseudo-random alphanumeric string for shell helpers."""

import secrets
import string


def main() -> None:
    alphabet = string.ascii_letters + string.digits
    token = "".join(secrets.choice(alphabet) for _ in range(32))
    print(token)


if __name__ == "__main__":
    main()

