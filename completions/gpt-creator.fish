# Fish completion for gpt-creator

set -l subcmds create-project scan normalize plan generate db run refresh-stack verify create-tasks work-on-tasks iterate help version
complete -c gpt-creator -f -n "not __fish_seen_subcommand_from $subcmds" -a "$subcmds" -d "Commands"

# global flags
complete -c gpt-creator -s h -l help -d "Show help"
complete -c gpt-creator -s v -l version -d "Show version"
complete -c gpt-creator -l project -r -d "Project root"

# create-project
complete -c gpt-creator -n "__fish_seen_subcommand_from create-project" -a "(__fish_complete_directories)" -d "Project directory"

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

# task-convert (deprecated alias)
complete -c gpt-creator -n "__fish_seen_subcommand_from task-convert" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from task-convert" -l force -d "Rebuild tasks database (legacy alias)"

# work-on-tasks
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l story -r -d "Start from story id or slug"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l from-story -r -d "Alias for --story"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l fresh -d "Ignore saved progress"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l no-verify -d "Skip verify"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l keep-artifacts -d "Retain Codex prompt/output artifacts"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l memory-cycle -d "Restart after each task and prune caches"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l batch-size -r -d "Process at most this many tasks"
complete -c gpt-creator -n "__fish_seen_subcommand_from work-on-tasks" -l sleep-between -r -d "Pause seconds between tasks"

# iterate (deprecated)
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l project -r

# scan/normalize/plan
for sub in scan normalize plan
  complete -c gpt-creator -n "__fish_seen_subcommand_from $sub" -l project -r
end
