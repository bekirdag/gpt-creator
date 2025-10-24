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
    'create-db-dump:Generate MySQL schema and seed dumps from the SDS'
    'create-pdr:Generate a Product Requirements Document from the staged RFP'
    'bootstrap:End-to-end build from RFP to running stack'
    'create-jira-tasks:Generate Jira epics/stories/tasks from documentation'
    'migrate-tasks:Rebuild tasks.db from generated JSON'
    'refine-tasks:Refine tasks stored in the SQLite backlog'
    'create-tasks:Convert Jira tasks into a SQLite backlog'
    'backlog:Render backlog summaries from the tasks database'
    'estimate:Estimate backlog completion time from story points'
    'sweep-artifacts:Sweep legacy progress artifacts into .gpt-creator'
    'work-on-tasks:Execute tasks from the SQLite backlog with Codex'
    'reports:List or show captured issue reports'
    'task-convert:[deprecated] Alias for create-tasks'
    'iterate:[deprecated] Legacy Jira loop'
    'help:Show help'
    'version:Show version'
  )

  _arguments -C \
    '(-h --help)'{-h,--help}'[Show help]' \
    '(-v --version)'{-v,--version}'[Show version]' \
    '--project=[Project root]:dir:_files -/' \
    '--reports-on[Enable automatic crash/stall reporting]' \
    '--reports-off[Disable automatic crash/stall reporting]' \
    '--reports-idle-timeout=[Idle timeout seconds]:seconds:(300 600 900 1800)' \
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
    create-db-dump)
      _arguments \
        '--model=[Codex model name]' \
        '--dry-run[Prepare prompts without calling Codex]' \
        '--force[Regenerate schema and seed dumps]'
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
    backlog)
      _arguments \
        '--root=[Project root]:dir:_files -/' \
        '--type=[Backlog listing type]:type:(epics stories)' \
        '--item-children=[Epic or story identifier]' \
        '--progress[Show overall backlog progress]' \
        '--task-details=[Task identifier]'
      ;;
    sweep-artifacts)
      _arguments \
        '--project=[Project root]:dir:_files -/' \
        '*:project dir:_files -/'
      ;;
    show-file)
      _arguments \
        '--project=[Project root]:dir:_files -/' \
        '--range=[Line range (A:B)]' \
        '--head=[Show first N lines]' \
        '--tail=[Show last N lines]' \
        '--max-lines=[Default line budget when no range/head/tail provided]' \
        '--diff[Show diff against cached snapshot]' \
        '--refresh[Force cache refresh]' \
        '1:file:_files'
      ;;
    work-on-tasks)
      _arguments \
        '--story=[Start from story id or slug]' \
        '--from-story=[Alias for --story]' \
        '--from-task=[Resume from a specific task id or story:position reference]' \
        '--fresh-from=[Alias for --from-task]' \
        '--task=[Alias for --from-task]' \
        '--force[Reset stored progress and restart from the first story]' \
        '--fresh[Ignore saved progress]' \
        '--no-verify[Skip final verify run]' \
        '--keep-artifacts[Retain Codex prompt/output artifacts]' \
        '--memory-cycle[Process one task per cycle and restart automatically]' \
        '--batch-size=[Process at most this many tasks in one run]' \
        '--sleep-between=[Pause seconds between tasks]' \
        '--context-lines=[Include the last N lines of shared context in each prompt]' \
        '--context-none[Skip attaching shared context to prompts]' \
        '--context-file-lines=[Limit each shared-context file to N lines before truncation]' \
        '--context-skip=[Glob pattern to exclude from shared context]' \
        '--prompt-compact[Use a shorter instruction/schema block in prompts]' \
        '--prompt-expanded[Use the legacy verbose instruction/schema block]' \
        '--context-doc-snippets[(default) Pull scoped excerpts for referenced docs/endpoints]' \
        '--no-context-doc-snippets[Disable doc-snippet mode and include staged docs verbatim]' \
        '--sample-lines=[Include at most N lines from sample payloads]' \
        '--idle-timeout=[Abort if no task progress for N seconds]'
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
        '--template=[Template name or auto]:template:(auto skip)' \
        '--skip-template[Skip applying a project template]' \
        '1:project-dir:_files -/'
      ;;
    bootstrap)
      _arguments \
        '--template=[Template name or auto]:template:(auto skip)' \
        '--skip-template[Skip project template scaffolding]' \
        '--rfp=[Path to RFP file]:file:_files' \
        '--fresh[Restart the bootstrap pipeline from scratch]' \
        '1:project-dir:_files -/'
      ;;
    reports)
      _arguments \
        '--project=[Project root]:dir:_files -/' \
        '--open[Open report in $EDITOR_CMD]' \
        '--branch=[Working branch name]' \
        '--no-push[Skip automatic push instructions]' \
        '--push[Force push instructions]' \
        '--prompt-only[Generate the Codex prompt without executing it]' \
        '--reporter=[Filter reports by reporter name]' \
        '--close-invalid[Close GitHub auto-reports that fail authenticity checks]' \
        '--no-close-invalid[Do not close invalid GitHub auto-reports]' \
        '--include-closed[Include closed GitHub auto-reports in the audit]' \
        '--limit=[Maximum number of GitHub issues to audit]:count:' \
        '--digests=[Path to trusted CLI digest manifest]:file:_files' \
        '--allow=[Inline VERSION=SHA256 override for trusted CLI digests]' \
        '--label-invalid=[Label to apply when closing invalid reports]' \
        '--no-label-invalid[Do not add a label when closing invalid reports]' \
        '--comment=[Custom comment when closing invalid reports]' \
        '*:slug-or-mode:(list backlog auto show work audit)'
      ;;
    *)
      ;;
  esac
}

compdef _gpt_creator gpt-creator
