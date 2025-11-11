# Branching mode
- Env: GC_GIT_BRANCHING=1, GC_GIT_REMOTE=origin, GC_GIT_DEV_BRANCH=dev.
- Flow: init → begin_task_branch → finalize_task_branch (commit+push task branch, merge into dev, fast-forward/push main).
- Remote sync: every new task branch plus dev & main are pushed to `$GC_GIT_REMOTE`.
- Safety: ff-only pulls, --no-ff merges into dev, leaves feature branch on failure.
