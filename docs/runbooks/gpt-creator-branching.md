# Branching mode
- Env: GC_GIT_BRANCHING=1, GC_GIT_REMOTE=origin, GC_GIT_DEV_BRANCH=dev.
- Flow: init → begin_task_branch → finalize_task_branch (commit+push, merge on success).
- Safety: ff-only pulls, --no-ff merges, leaves feature branch on failure.
