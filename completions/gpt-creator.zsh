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
    'iterate:Loop over Jira tasks'
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
