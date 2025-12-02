# Branching mode
- Env: GC_GIT_BRANCHING=1, GC_GIT_REMOTE=origin, GC_GIT_DEV_BRANCH=dev.
- Flow: init → begin_task_branch → finalize_task_branch (autosnap dirty trees before switching to dev/task branches, commit+push task branch, merge into dev, push dev).
- Remote sync: every task branch is pushed, and `dev` is pushed after merge even when no file deltas are detected.
- Safety: ff-only pulls, --no-ff merges into dev, leaves feature branch on failure.
- Task branch naming: branches default to the sanitized task id (for example `adm-04-us-05-t5`) without any prefix. Export `GC_GIT_TASK_PREFIX="task/"` before invoking `work-on-tasks` if the `task/<id>` style mentioned in the plan is desired.
- Merge policy: `finalize_task_branch` merges into `dev` whenever the run status normalises to `SUCCESS`, `COMPLETE`, `COMPLETED`, `COMPLETED_OK`, `COMPLETED_NO_CHANGES`, `READY_TO_REVIEW`, or `READY_TO_REVIEW_NO_CHANGES` (merges may be no-ops when the branch already matches `dev`).
- Author identity: autosnap/final commits set `GC_GIT_AUTOMATION_AUTHOR_NAME` / `GC_GIT_AUTOMATION_AUTHOR_EMAIL` (defaults: `gpt-creator automation` / `automation@gpt-creator`) so branch switches always start from a clean tree.
