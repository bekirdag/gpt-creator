# Zsh completion for gpt-creator
# To load: compdef _gpt_creator gpt-creator

_gpt_creator() {
  local -a subcmds
  subcmds=(
    'create-project:Create a new project at path'
    'scan:Discover inputs'
    'normalize:Stage & rename inputs'
    'plan:Create build plan'
    'generate:Generate code (api|web|admin|db|docker|all)'
    'db:DB ops (provision|import|seed)'
    'run:Run via docker compose'
    'refresh-stack:Tear down, rebuild, and seed the Docker stack'
    'verify:Acceptance/NFR checks'
    'create-sds:Generate a System Design Specification from the staged PDR'
    'create-pdr:Generate a Product Requirements Document from the staged RFP'
    'create-jira-tasks:Generate Jira epics/stories/tasks from documentation'
    'migrate-tasks:Rebuild tasks.db from generated JSON'
    'refine-tasks:Refine tasks stored in the SQLite backlog'
    'create-tasks:Convert Jira tasks into a SQLite backlog'
    'work-on-tasks:Execute tasks from the SQLite backlog with Codex'
    'task-convert:[deprecated] Alias for create-tasks'
    'iterate:[deprecated] Legacy Jira loop'
    'help:Show help'
    'version:Show version'
  )

  _arguments -C \
    '(-h --help)'{-h,--help}'[Show help]' \
    '(-v --version)'{-v,--version}'[Show version]' \
    '--project=[Project root]:dir:_files -/' \
    '1: :->cmd' \
    '*::arg:->args'

  local cmd=$words[1]
  if (( CURRENT == 2 )); then
    _describe -t commands 'gpt-creator commands' subcmds
    return
  fi

  case "$cmd" in
    generate)
      _values 'facet' api web admin db docker all
      ;;
    db)
      _values 'db-action' provision import seed
      ;;
    run)
      _values 'run-action' up down logs open
      ;;
    verify)
      _values 'verify-kind' acceptance nfr all
      ;;
    create-pdr)
      _arguments \
        '--model=[Codex model name]' \
        '--dry-run[Prepare prompts without calling Codex]' \
        '--force[Regenerate all stages]'
      ;;
    create-sds)
      _arguments \
        '--model=[Codex model name]' \
        '--dry-run[Prepare prompts without calling Codex]' \
        '--force[Regenerate all stages]'
      ;;
    create-jira-tasks)
      _arguments \
        '--model=[Codex model name]' \
        '--force[Rebuild tasks.db from scratch]' \
        '--dry-run[Prepare prompts without calling Codex]'
      ;;
    migrate-tasks)
      _arguments \
        '--force[Rebuild tasks.db from JSON artifacts]'
      ;;
    refine-tasks)
      _arguments \
        '--story=[Limit refinement to a single story slug]' \
        '--model=[Codex model name]' \
        '--dry-run[Prepare prompts without calling Codex]' \
        '--force[Reset refinement progress and reprocess all tasks]'
      ;;
    create-tasks|task-convert)
      _arguments \
        '--jira=[Jira tasks file]:file:_files' \
        '--force[Rebuild all story JSONs]'
      ;;
    work-on-tasks)
      _arguments \
        '--story=[Start from story id or slug]' \
        '--from-story=[Alias for --story]' \
        '--fresh[Ignore saved progress]' \
        '--no-verify[Skip final verify run]' \
        '--keep-artifacts[Retain Codex prompt/output artifacts]' \
        '--memory-cycle[Process one task per cycle and restart automatically]' \
        '--batch-size=[Process at most this many tasks in one run]' \
        '--sleep-between=[Pause seconds between tasks]'
      ;;
    iterate)
      _arguments \
        '--jira=[Jira tasks file]:file:_files'
      ;;
    refresh-stack)
      _arguments \
        '--compose=[docker-compose file to use]:file:_files' \
        '--sql=[SQL dump to import]:file:_files' \
        '--seed=[Seed SQL file]:file:_files' \
        '--no-import[Skip database import]' \
        '--no-seed[Skip seeding]'
      ;;
    create-project)
      _arguments \
        ':project-dir:_files -/'
      ;;
    *)
      ;;
  esac
}

compdef _gpt_creator gpt-creator
