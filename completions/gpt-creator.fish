# Fish completion for gpt-creator

set -l subcmds create-project scan normalize plan generate db run verify iterate help version
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

# verify
complete -c gpt-creator -n "__fish_seen_subcommand_from verify" -a "acceptance nfr all" -d "Verify kind"
complete -c gpt-creator -n "__fish_seen_subcommand_from verify" -l project -r

# iterate
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l jira -r -d "Jira tasks file"
complete -c gpt-creator -n "__fish_seen_subcommand_from iterate" -l project -r

# scan/normalize/plan
for sub in scan normalize plan
  complete -c gpt-creator -n "__fish_seen_subcommand_from $sub" -l project -r
end
