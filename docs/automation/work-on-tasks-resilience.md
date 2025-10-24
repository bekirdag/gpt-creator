# Work-on-Tasks Run Resilience

Manual interrupts or dropped terminals can halt `gpt-creator work-on-tasks` before the backlog finishes. Use the practices below to keep long executions stable:

- **Run inside a session manager**: start `tmux`, `screen`, or an equivalent multiplexer before launching long Codex runs so network hiccups or closed laptops do not kill the process.
- **Avoid `Ctrl-C`**: let the command finish naturally. If you must stop, signal the wrapper script below so the active task can finalise cleanly.
- **Resume just the interrupted task**: use `gpt-creator work-on-tasks --from-task <story-slug:position> --batch-size 1 --memory-cycle` to retry only the failed unit instead of replaying the whole backlog.
- **Handle CLI timeouts**: when Codex returns exit 124 (idle/timeout), rerun only the impacted task with the same `--from-task` parameters; the rest of the backlog stays marked complete.
- **Use the helper script**: `scripts/work-on-tasks-retry.sh` wraps the CLI with signal trapping, tmux reminders, and a timeout-aware retry loop.

## Helper Script

The `scripts/work-on-tasks-retry.sh` wrapper retries the most recent task safely:

```bash
scripts/work-on-tasks-retry.sh story-slug:003 --project /path/to/project
```

The script:

- Warns when it is not invoked inside `tmux`/`screen`.
- Runs `gpt-creator work-on-tasks --from-task <ref> --batch-size 1 --memory-cycle`.
- Traps `INT`/`TERM` and forwards the signal to the CLI so it can persist progress before exiting.
- Automatically retries once when the CLI exits with status 124 (timeout).

Use this helper after a timeout or dropped session to target the exact task that needs another attempt.

Following these steps prevents stray interrupts from derailing an entire work session and keeps recovery focused on the single task that needs attention.
