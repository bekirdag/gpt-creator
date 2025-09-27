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
    'verify:Acceptance/NFR checks'
    'create-tasks:Convert Jira tasks into per-story JSONs'
    'work-on-tasks:Execute story JSON tasks with Codex'
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
    create-project)
      _arguments \
        ':project-dir:_files -/'
      ;;
    *)
      ;;
  esac
}

compdef _gpt_creator gpt-creator
