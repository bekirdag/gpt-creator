# Fish completion for gpt-creator

set -l subcmds create-project bootstrap scan normalize plan generate db run refresh-stack verify create-pdr create-sds create-db-dump create-jira-tasks migrate-tasks refine-tasks create-tasks backlog work-on-tasks reports iterate help version
complete -c gpt-creator -f -n "not __fish_seen_subcommand_from $subcmds" -a "$subcmds" -d "Commands"

# global flags
complete -c gpt-creator -s h -l help -d "Show help"
complete -c gpt-creator -s v -l version -d "Show version"
complete -c gpt-creator -l project -r -d "Project root"
complete -c gpt-creator -l reports-on -d "Enable automatic crash/stall reporting"
complete -c gpt-creator -l reports-off -d "Disable automatic crash/stall reporting"
complete -c gpt-creator -l reports-idle-timeout -r -d "Idle timeout in seconds" -a "300 600 900 1800"

# create-project
complete -c gpt-creator -n "__fish_seen_subcommand_from create-project" -a "(__fish_complete_directories)" -d "Project directory"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-project" -l template -r -d "Project template name or auto"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-project" -l skip-template -d "Skip project template scaffolding"

# bootstrap
complete -c gpt-creator -n "__fish_seen_subcommand_from bootstrap" -l template -r -d "Project template name or auto"
complete -c gpt-creator -n "__fish_seen_subcommand_from bootstrap" -l skip-template -d "Skip project template scaffolding"
complete -c gpt-creator -n "__fish_seen_subcommand_from bootstrap" -l fresh -d "Restart pipeline from scratch"
complete -c gpt-creator -n "__fish_seen_subcommand_from bootstrap" -l rfp -r -d "Path to RFP file" -a "(__fish_complete_path)"

# generate
complete -c gpt-creator -n "__fish_seen_subcommand_from generate" -a "api web admin db docker all" -d "Facet"
complete -c gpt-creator -n "__fish_seen_subcommand_from generate" -l project -r

# db
complete -c gpt-creator -n "__fish_seen_subcommand_from db" -a "provision import seed" -d "DB action"
complete -c gpt-creator -n "__fish_seen_subcommand_from db" -l project -r

# run
complete -c gpt-creator -n "__fish_seen_subcommand_from run" -a "up down logs open" -d "Run action"
complete -c gpt-creator -n "__fish_seen_subcommand_from run" -l project -r

# refresh-stack
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l project -r -d "Project root"
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l compose -r -d "docker-compose file"
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l sql -r -d "SQL dump"
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l seed -r -d "Seed SQL file"
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l no-import -d "Skip schema import"
complete -c gpt-creator -n "__fish_seen_subcommand_from refresh-stack" -l no-seed -d "Skip seeding"

# verify
complete -c gpt-creator -n "__fish_seen_subcommand_from verify" -a "acceptance nfr all" -d "Verify kind"
complete -c gpt-creator -n "__fish_seen_subcommand_from verify" -l project -r

# create-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from create-tasks" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-tasks" -l force -d "Rebuild tasks database (ignore saved progress)"

# backlog
complete -c gpt-creator -n "__fish_seen_subcommand_from backlog" -l project -r -d "Project root"

# create-pdr
complete -c gpt-creator -n "__fish_seen_subcommand_from create-pdr" -l model -r -d "Codex model"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-pdr" -l dry-run -d "Do not call Codex"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-pdr" -l force -d "Regenerate all stages"

# create-sds
complete -c gpt-creator -n "__fish_seen_subcommand_from create-sds" -l model -r -d "Codex model"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-sds" -l dry-run -d "Do not call Codex"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-sds" -l force -d "Regenerate all stages"

# create-db-dump
complete -c gpt-creator -n "__fish_seen_subcommand_from create-db-dump" -l model -r -d "Codex model"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-db-dump" -l dry-run -d "Do not call Codex"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-db-dump" -l force -d "Regenerate schema and seed dumps"

# create-jira-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from create-jira-tasks" -l model -r -d "Codex model"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-jira-tasks" -l force -d "Rebuild tasks.db"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-jira-tasks" -l dry-run -d "Do not call Codex"

# migrate-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from migrate-tasks" -l force -d "Rebuild tasks.db from JSON"

# refine-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from refine-tasks" -l story -r -d "Limit refinement to a story slug"
complete -c gpt-creator -n "__fish_seen_subcommand_from refine-tasks" -l model -r -d "Codex model"
complete -c gpt-creator -n "__fish_seen_subcommand_from refine-tasks" -l dry-run -d "Do not call Codex"
complete -c gpt-creator -n "__fish_seen_subcommand_from refine-tasks" -l force -d "Reset refinement progress"

# task-convert (deprecated alias)
complete -c gpt-creator -n "__fish_seen_subcommand_from task-convert" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from task-convert" -l force -d "Rebuild tasks database (legacy alias)"

# work-on-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l story -r -d "Start from story id or slug"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l from-story -r -d "Alias for --story"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l force -d "Reset stored progress and restart from the first story"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l fresh -d "Ignore saved progress"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l no-verify -d "Skip verify"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l keep-artifacts -d "Retain Codex prompt/output artifacts"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l memory-cycle -d "Restart after each task and prune caches"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l batch-size -r -d "Process at most this many tasks"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l sleep-between -r -d "Pause seconds between tasks"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-lines -r -d "Tail only the last N lines of shared context"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-none -d "Skip attaching shared context to prompts"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-mode -r -d "Shared context strategy (digest|raw)" -a "digest raw"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-file-lines -r -d "Limit each shared-context file to N lines"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-skip -r -d "Glob pattern to exclude from shared context"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l prompt-compact -d "Use a compact instruction/schema block in prompts"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l prompt-expanded -d "Use the legacy verbose instruction/schema block"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l context-doc-snippets -d "Pull scoped excerpts for referenced docs/endpoints"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l sample-lines -r -d "Include at most N lines from sample payloads"

# iterate (deprecated)
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l project -r

# reports
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -a "list backlog auto show work audit" -d "Report commands"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l project -r -d "Project root"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l open -d "Open report in editor"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l branch -r -d "Working branch name"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l no-push -d "Skip push instructions"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l push -d "Force push instructions"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l prompt-only -d "Only create Codex prompt"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l reporter -r -d "Filter by reporter"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l close-invalid -d "Close GitHub auto-reports that fail authenticity checks"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l no-close-invalid -d "Do not close invalid GitHub auto-reports"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l include-closed -d "Include closed GitHub auto-reports in the audit"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l limit -r -d "Maximum GitHub issues to audit" -a "10 20 50 100"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l digests -r -d "Trusted CLI digest manifest" -a "(__fish_complete_path)"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l allow -r -d "Inline VERSION=SHA256 override"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l label-invalid -r -d "Label applied to invalid reports"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l no-label-invalid -d "Skip labeling invalid reports"
complete -c gpt-creator -n "__fish_seen_subcommand_from reports" -l comment -r -d "Comment to add when closing invalid reports"

# scan/normalize/plan
for sub in scan normalize plan
  complete -c gpt-creator -n "__fish_seen_subcommand_from $sub" -l project -r
end
