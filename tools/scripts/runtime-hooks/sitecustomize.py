#!/usr/bin/env python3
"""Global Python trap: report unhandled errors to parent finalizer."""
import asyncio
import os
import signal
import sys
import traceback

_parent = int(os.environ.get("GC_PARENT_PID") or 0)


def _signal_parent():
    if _parent > 0:
        try:
            os.kill(_parent, signal.SIGUSR1)
        except Exception:
            pass


def _excepthook(exc_type, exc, tb):
    try:
        sys.stderr.write(f"[gc-child-unhandled:python] pid={os.getpid()}\n")
        traceback.print_exception(exc_type, exc, tb)
        sys.stderr.flush()
    except Exception:
        pass
    _signal_parent()


sys.excepthook = _excepthook


try:
    loop = asyncio.get_event_loop()

    def _async_handler(loop, context):
        try:
            msg = context.get("message") or repr(context.get("exception"))
            sys.stderr.write(f"[gc-child-unhandled:asyncio] {msg}\n")
            sys.stderr.flush()
        except Exception:
            pass
        _signal_parent()

    loop.set_exception_handler(_async_handler)
except Exception:
    pass
