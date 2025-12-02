# Branching mode
- Env: GC_GIT_BRANCHING=1, GC_GIT_REMOTE=origin, GC_GIT_DEV_BRANCH=dev.
- Flow: init → begin_task_branch → finalize_task_branch (commit+push task branch, merge into dev, fast-forward/push main).
- Remote sync: every new task branch plus dev & main are pushed to `$GC_GIT_REMOTE`.
- Safety: ff-only pulls, --no-ff merges into dev, leaves feature branch on failure.
- Task branch naming: branches default to the sanitized task id (for example `adm-04-us-05-t5`) without any prefix. Export `GC_GIT_TASK_PREFIX="task/"` before invoking `work-on-tasks` if the `task/<id>` style mentioned in the plan is desired.
- Merge gating: `finalize_task_branch` only merges into `dev` when the run status normalises to one of `SUCCESS`, `COMPLETED`, or `COMPLETED_OK` *and* at least one file changed relative to the branch base snapshot. `COMPLETED_NO_CHANGES` / `COMPLETED-NO-CHANGES` purposely skip merges so no-op tasks fall through without touching `dev`; if you want those statuses to merge, extend `gc_git_status_ok` (in `scripts/lib/git-branches.sh`) or relax the changed-file check.
