# Bash completion for gpt-creator

_gpt_creator()
{
  local cur prev words cword
  COMPREPLY=()
  _get_comp_words_by_ref -n : cur prev words cword 2>/dev/null || {
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
  }

  local subcmds="create-project scan normalize plan generate db run verify create-tasks work-on-tasks iterate help version"
  local global_opts="--project -h --help -v --version"

  # find the subcommand (first non-option token)
  local cmd=""
  for w in "${COMP_WORDS[@]:1}"; do
    [[ "$w" == -* ]] && continue
    cmd="$w"; break
  done

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "${subcmds} ${global_opts}" -- "$cur") )
    return 0
  fi

  case "$cmd" in
    create-project)
      # complete directories
      COMPREPLY=( $(compgen -d -- "$cur") )
      ;;
    scan|normalize|plan|iterate|verify|run|db|generate|create-tasks|work-on-tasks|task-convert)
      case "$prev" in
        --project) COMPREPLY=( $(compgen -d -- "$cur") ); return 0;;
        --jira) COMPREPLY=( $(compgen -f -- "$cur") ); return 0;;
      esac
      case "$cmd" in
        create-tasks|task-convert)
          COMPREPLY=( $(compgen -W "--project --jira --force ${global_opts}" -- "$cur") )
          ;;
        work-on-tasks)
          COMPREPLY=( $(compgen -W "--project --story --from-story --fresh --no-verify --keep-artifacts --batch-size --sleep-between ${global_opts}" -- "$cur") )
          ;;
        generate)
          COMPREPLY=( $(compgen -W "api web admin db docker all ${global_opts}" -- "$cur") )
          ;;
        db)
          COMPREPLY=( $(compgen -W "provision import seed ${global_opts}" -- "$cur") )
          ;;
        run)
          COMPREPLY=( $(compgen -W "up down logs open ${global_opts}" -- "$cur") )
          ;;
        verify)
          COMPREPLY=( $(compgen -W "acceptance nfr all ${global_opts}" -- "$cur") )
          ;;
        iterate)
          [[ "$prev" == "--jira" ]] && { COMPREPLY=( $(compgen -f -- "$cur") ); return 0; }
          COMPREPLY=( $(compgen -W "--jira ${global_opts}" -- "$cur") )
          ;;
        *)
          COMPREPLY=( $(compgen -W "${global_opts}" -- "$cur") )
          ;;
      esac
      ;;
    *)
      COMPREPLY=( $(compgen -W "${subcmds} ${global_opts}" -- "$cur") )
      ;;
  esac
}

# Fallback if bash-completion isn't loaded
if declare -F _get_comp_words_by_ref >/dev/null 2>&1; then
  complete -F _gpt_creator gpt-creator
else
  complete -o filenames -F _gpt_creator gpt-creator
fi
