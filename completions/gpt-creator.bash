# Bash completion for gpt-creator

_gpt_creator()
{
  local cur prev words cword
  COMPREPLY=()
  _get_comp_words_by_ref -n : cur prev words cword 2>/dev/null || {
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
  }

  local subcmds="create-project bootstrap scan normalize plan generate db run refresh-stack verify create-pdr create-sds create-db-dump create-jira-tasks migrate-tasks refine-tasks create-tasks backlog estimate sweep-artifacts work-on-tasks reports iterate help version"
  local global_opts="--project -h --help -v --version --reports-on --reports-off --reports-idle-timeout"

  # find the subcommand (first non-option token)
  local cmd=""
  for w in "${COMP_WORDS[@]:1}"; do
    [[ "$w" == -* ]] && continue
    cmd="$w"; break
  done

  if [[ "$prev" == "--reports-idle-timeout" ]]; then
    COMPREPLY=( $(compgen -W "300 600 900 1800" -- "$cur") )
    return 0
  fi

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "${subcmds} ${global_opts}" -- "$cur") )
    return 0
  fi

  case "$cmd" in
    create-project)
      case "$prev" in
        --template)
          COMPREPLY=( $(compgen -W "auto skip" -- "$cur") )
          return 0
          ;;
      esac
      local opts="--template --skip-template"
      COMPREPLY=( $(compgen -W "$opts" -- "$cur") $(compgen -d -- "$cur") )
      ;;
    scan|normalize|plan|iterate|verify|run|refresh-stack|db|generate|create-pdr|create-sds|create-db-dump|create-jira-tasks|migrate-tasks|refine-tasks|create-tasks|backlog|estimate|sweep-artifacts|work-on-tasks|task-convert|bootstrap)
      case "$prev" in
        --project) COMPREPLY=( $(compgen -d -- "$cur") ); return 0;;
        --jira) COMPREPLY=( $(compgen -f -- "$cur") ); return 0;;
      esac
      case "$cmd" in
        create-pdr)
          COMPREPLY=( $(compgen -W "--project --model --dry-run --force ${global_opts}" -- "$cur") )
          ;;
        create-sds)
          COMPREPLY=( $(compgen -W "--project --model --dry-run --force ${global_opts}" -- "$cur") )
          ;;
        create-db-dump)
          COMPREPLY=( $(compgen -W "--project --model --dry-run --force ${global_opts}" -- "$cur") )
          ;;
        bootstrap)
          case "$prev" in
            --template) COMPREPLY=( $(compgen -W "auto skip" -- "$cur") ); return 0;;
          esac
          local opts="--template --skip-template --rfp --fresh"
          if [[ $prev == --rfp ]]; then
            COMPREPLY=( $(compgen -f -- "$cur") )
            return 0
          fi
          COMPREPLY=( $(compgen -W "$opts" -- "$cur") $(compgen -d -- "$cur") )
          ;;
        create-jira-tasks)
          COMPREPLY=( $(compgen -W "--project --model --force --dry-run ${global_opts}" -- "$cur") )
          ;;
        migrate-tasks)
          COMPREPLY=( $(compgen -W "--project --force ${global_opts}" -- "$cur") )
          ;;
        refine-tasks)
          COMPREPLY=( $(compgen -W "--project --story --model --dry-run --force ${global_opts}" -- "$cur") )
          ;;
        create-tasks|task-convert)
          COMPREPLY=( $(compgen -W "--project --jira --force ${global_opts}" -- "$cur") )
          ;;
        backlog)
          case "$prev" in
            --project|--root) COMPREPLY=( $(compgen -d -- "$cur") ); return 0;;
            --type) COMPREPLY=( $(compgen -W "epics stories" -- "$cur") ); return 0;;
            --item-children) COMPREPLY=(); return 0;;
            --task-details) COMPREPLY=(); return 0;;
          esac
          COMPREPLY=( $(compgen -W "--project --root --type --item-children --progress --task-details ${global_opts}" -- "$cur") )
          ;;
        estimate)
          COMPREPLY=( $(compgen -W "--project ${global_opts}" -- "$cur") )
          ;;
        sweep-artifacts)
          COMPREPLY=( $(compgen -W "--project ${global_opts}" -- "$cur") $(compgen -d -- "$cur") )
          ;;
        show-file)
          case "$prev" in
            --project) COMPREPLY=( $(compgen -d -- "$cur") ); return 0;;
            --range|--head|--tail|--max-lines) COMPREPLY=(); return 0;;
          esac
          COMPREPLY=( $(compgen -W "--project --range --head --tail --max-lines --diff --refresh ${global_opts}" -- "$cur") $(compgen -f -- "$cur") )
          ;;
        work-on-tasks)
          COMPREPLY=( $(compgen -W "--project --story --from-story --from-task --fresh-from --task --fresh --force --no-verify --keep-artifacts --memory-cycle --batch-size --sleep-between --context-lines --context-none --context-file-lines --context-skip --prompt-compact --prompt-expanded --context-doc-snippets --no-context-doc-snippets --sample-lines --idle-timeout ${global_opts}" -- "$cur") )
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
        refresh-stack)
          case "$prev" in
            --compose|--sql|--seed) COMPREPLY=( $(compgen -f -- "$cur") ); return 0;;
          esac
          COMPREPLY=( $(compgen -W "--project --compose --sql --seed --no-import --no-seed ${global_opts}" -- "$cur") )
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
    reports)
      case "$prev" in
        --project) COMPREPLY=( $(compgen -d -- "$cur") ); return 0;;
        --digests) COMPREPLY=( $(compgen -f -- "$cur") ); return 0;;
        --limit) COMPREPLY=( $(compgen -W "10 20 50 100" -- "$cur") ); return 0;;
        --allow) COMPREPLY=(); return 0;;
        --label-invalid) COMPREPLY=(); return 0;;
        --comment) COMPREPLY=(); return 0;;
      esac
      local opts="list backlog auto show work audit --project --open --branch --no-push --push --prompt-only --reporter --close-invalid --no-close-invalid --include-closed --limit --digests --allow --label-invalid --no-label-invalid --comment ${global_opts}"
      COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
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
