from __future__ import annotations

import logging
import re
from typing import Pattern

_log = logging.getLogger(__name__)


def compile_user_pattern(fragment: str, *, flags: int = 0, allow_regex: bool = False) -> Pattern[str]:
    """
    Compile a user-supplied fragment safely.

    When allow_regex is False (default) the fragment is treated as a literal by escaping it.
    If compilation still fails, fall back to an escaped literal and log a warning.
    """
    pattern = fragment if allow_regex else re.escape(fragment)
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        _log.warning("Invalid regex %r (%s); falling back to literal.", fragment, exc)
        return re.compile(re.escape(fragment), flags)
