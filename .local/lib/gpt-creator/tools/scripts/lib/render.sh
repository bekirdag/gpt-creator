#!/usr/bin/env bash
# Rendering helpers for task banners, badges, and panels.

gc_format_duration_compact() {
  local total="${1:-0}"
  if [[ ! "$total" =~ ^[0-9]+$ ]]; then
    total=0
  fi
  local hours=$(( total / 3600 ))
  local minutes=$(( (total % 3600) / 60 ))
  local seconds=$(( total % 60 ))
  local parts=()
  if (( hours > 0 )); then
    parts+=("${hours}H")
  fi
  if (( minutes > 0 || hours > 0 )); then
    parts+=("${minutes}M")
  fi
  parts+=("${seconds}S")
  printf '%s' "${parts[*]}"
}

gc_format_tokens_compact() {
  local raw="${1:-0}"
  if [[ ! "$raw" =~ ^[0-9]+$ ]]; then
    raw=0
  fi
  printf '%s' "$(printf '%d' "$raw" | sed ':a;s/\\B[0-9]\\{3\\}\\>/,&/;ta')"
}

gc_log_tokens_used() {
  local total="${1:-0}"
  local prompt="${2:-0}"
  local completion="${3:-0}"
  if [[ ! "$total" =~ ^[0-9]+$ ]] || (( total <= 0 )); then
    return
  fi
  printf 'tokens used\n%s\n' "$(gc_format_tokens_compact "$total")"
  if [[ "$prompt" =~ ^[0-9]+$ ]] && (( prompt > 0 )); then
    printf 'prompt tokens\n%s\n' "$(gc_format_tokens_compact "$prompt")"
  fi
  if [[ "$completion" =~ ^[0-9]+$ ]] && (( completion > 0 )); then
    printf 'completion tokens\n%s\n' "$(gc_format_tokens_compact "$completion")"
  fi
}

gc_render_task_banner() {
  local header_position="top"
  case "$1" in
    --header-bottom)
      header_position="bottom"
      shift
      ;;
    --header-top)
      shift
      ;;
  esac

  local header="${1:?header text required}"
  shift
  local -a lines=("$@")

  if [[ "$header" == "START OF A NEW TASK" ]] || [[ "$header" == "END OF THE TASK WORK" ]]; then
    local content_width="${#header}"
    local line
    for line in "${lines[@]}"; do
      if (( ${#line} > content_width )); then
        content_width=${#line}
      fi
    done
    local inner_width=$(( content_width + 6 ))
    local shading
    printf -v shading '%*s' "$inner_width" ''
    shading="${shading// /═}"
    local top_border="╔${shading}╗"
    local mid_border="╠${shading}╣"
    local bottom_border="╚${shading}╝"
    local shade_line="$shading"
    local header_line
    printf -v header_line "║  %-${content_width}s  ║" "$header"
    if [[ "$header" == "START OF A NEW TASK" ]]; then
      info "$top_border"
      info "$header_line"
      info "$mid_border"
      for line in "${lines[@]}"; do
        printf -v line "║  %-${content_width}s  ║" "$line"
        info "$line"
      done
      info "$bottom_border"
    else
      info "$top_border"
      for line in "${lines[@]}"; do
        printf -v line "║  %-${content_width}s  ║" "$line"
        info "$line"
      done
      info "$bottom_border"
      info "$shade_line"
      info "$header_line"
      info "$shade_line"
    fi
    return
  fi

  local min_width=23
  local banner_margin=4
  local header_padding_extra=8
  local inner_width="$min_width"

  local line
  for line in "${lines[@]}"; do
    local length=${#line}
    local candidate=$(( length + banner_margin ))
    if (( candidate > inner_width )); then
      inner_width=$candidate
    fi
  done

  local header_width=$(( inner_width + header_padding_extra ))
  if (( header_width < ${#header} + 2 )); then
    header_width=$(( ${#header} + 2 ))
  fi

  local shade_line
  printf -v shade_line '%*s' "$header_width" ''
  shade_line="${shade_line// /░}"

  local header_pad_left=$(( (header_width - ${#header}) / 2 ))
  local header_pad_right=$(( header_width - header_pad_left - ${#header} ))
  (( header_pad_left < 0 )) && header_pad_left=0
  (( header_pad_right < 0 )) && header_pad_right=0
  local header_line_left header_line_right
  printf -v header_line_left '%*s' "$header_pad_left" ''
  printf -v header_line_right '%*s' "$header_pad_right" ''
  local header_line="${header_line_left// /░}${header}${header_line_right// /░}"

  local border_inner
  printf -v border_inner '%*s' "$inner_width" ''
  local border_line="|${border_inner// /-}|"

  if [[ "$header_position" == "top" ]]; then
    info "$shade_line"
    info "$header_line"
    info "$shade_line"
  fi

  info "$border_line"
  for line in "${lines[@]}"; do
    local line_length=${#line}
    local pad_total=$(( inner_width - line_length ))
    (( pad_total < 0 )) && pad_total=0
    local pad_left=$(( pad_total / 2 ))
    local pad_right=$(( pad_total - pad_left ))
    local padded_line
    printf -v padded_line '|%*s%s%*s|' "$pad_left" '' "$line" "$pad_right" ''
    info "$padded_line"
    info "$border_line"
  done

  if [[ "$header_position" == "bottom" ]]; then
    printf '\n'
    info "$shade_line"
    info "$header_line"
    info "$shade_line"
  fi
}

gc_numclean() {
  local raw="${1:-}"
  raw="${raw//,/}"
  raw="${raw// /}"
  printf '%s' "$raw"
}

gc_story_points_percent() {
  local value="${1:-0}"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    value=0
  fi
  if (( value < 0 )); then
    value=0
  elif (( value > 13 )); then
    value=13
  fi
  awk -v s="$value" 'BEGIN{printf "%.1f",(s/13)*100}'
}

gc_render_bar() {
  local pct="${1:-0}"
  local width="${2:-20}"
  if [[ ! "$pct" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    pct=0
  fi
  if [[ ! "$width" =~ ^[0-9]+$ ]] || (( width <= 0 )); then
    width=20
  fi
  local filled
  filled="$(awk -v p="$pct" -v w="$width" 'BEGIN{if(p<0)p=0;if(p>100)p=100;printf \"%d\", int((p/100)*w + 0.5)}')"
  [[ "$filled" =~ ^[0-9]+$ ]] || filled=0
  local i=0
  while (( i < width )); do
    if (( i < filled )); then
      printf '%s█%s' "${gc_color_bar_fill:-}" "${gc_color_bar_fill:+$c_reset}"
    else
      printf '%s░%s' "${gc_color_bar_empty:-}" "${gc_color_bar_empty:+$c_reset}"
    fi
    (( i++ ))
  done
}

gc_render_task_badge() {
  local label="${1:-N/A}"
  local color="${2:-39}"
  local border_color="${gc_color_border:-$'\\033[38;5;240m'}"
  local accent
  printf -v accent '\\033[1;38;5;%sm' "$color"
  printf '%s%s %s %s%s' "$border_color" "$accent" "$label" "$border_color" "$c_reset"
}

gc_renderer_cache_path() {
  local base="${GC_DIR:-}"
  if [[ -z "$base" && -n "${PROJECT_ROOT:-}" ]]; then
    base="${PROJECT_ROOT}/.gpt-creator"
  elif [[ -z "$base" ]]; then
    base="${PWD}/.gpt-creator"
  fi
  printf '%s\n' "${base%/}/renderers/render_gpt_creator.sh"
}

gc_renderer_path_if_enabled() {
  if [[ -n "${GC_RENDERER_DISABLED:-}" ]]; then
    return 1
  fi

  local -a candidates=()
  local -a copy_sources=()

  if [[ -n "${GC_RENDER_GPT_CREATOR:-}" ]]; then
    candidates+=("${GC_RENDER_GPT_CREATOR}")
  fi

  local cache_path
  cache_path="$(gc_renderer_cache_path)"
  if [[ -n "$cache_path" ]]; then
    candidates+=("$cache_path")
  fi

  if [[ -n "${CLI_ROOT:-}" ]]; then
    local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
    if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
      scripts_root="${CLI_ROOT}/scripts"
    fi
    copy_sources+=("${CLI_ROOT}/render_gpt_creator.sh")
    copy_sources+=("${CLI_ROOT}/bin/render_gpt_creator.sh")
    copy_sources+=("${scripts_root}/render_task_footer.sh")
    candidates+=("${copy_sources[@]}")
  fi

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if [[ -n "$cache_path" ]]; then
    local source
    for source in "${copy_sources[@]}"; do
      if [[ -n "$source" && -r "$source" ]]; then
        local cache_dir
        cache_dir="$(dirname "$cache_path")"
        mkdir -p "$cache_dir" 2>/dev/null || true
        if cp "$source" "$cache_path"; then
          chmod +x "$cache_path" 2>/dev/null || true
          printf '%s\n' "$cache_path"
          return 0
        fi
      fi
    done
  fi

  return 1
}

gc_renderer_available() {
  gc_renderer_path_if_enabled >/dev/null
}

gc_render_with_renderer() {
  local renderer_path=""
  if ! renderer_path="$(gc_renderer_path_if_enabled)"; then
    "$@"
    return $?
  fi

  local render_strict="${GC_RENDER_GPT_CREATOR_STRICT:-0}"

  local tmpfile
  tmpfile="$(mktemp "${TMPDIR:-/tmp}/gc-render.XXXXXX")" || {
    "$@"
    return $?
  }

  if ! "$@" >"$tmpfile"; then
    local status=$?
    cat "$tmpfile"
    rm -f "$tmpfile"
    return $status
  fi

  if "$renderer_path" <"$tmpfile"; then
    rm -f "$tmpfile"
    return 0
  else
    local render_status=$?
    if [[ "$render_strict" == "1" ]]; then
      printf '%s!%s Renderer failed via %s (exit=%s). Raw output suppressed; fix the renderer or run it manually for debugging.\\n' \
        "$c_yellow" "$c_reset" "$renderer_path" "$render_status" >&2
      rm -f "$tmpfile"
      return 0
    fi

    cat "$tmpfile"
    rm -f "$tmpfile"
    return 0
  fi
}

gc_status_color_seq() {
  local status="${1:-}"
  status="${status,,}"
  case "$status" in
    completed|complete|success|ok|passed)
      printf '%s' "$c_green"
      ;;
    blocked*|failed|dead-letter|permanent-fail|error|aborted|interrupted)
      printf '%s' "$c_red"
      ;;
    in-progress|running|pending)
      printf '%s' "$c_cyan"
      ;;
    *)
      printf '%s' "$c_yellow"
      ;;
  esac
}

gc_render_task_start_panel() {
  local task_id="${1:-N/A}"
  local alias_line="${2:-}"
  local summary_line="${3:-}"
  local model_line="${4:-}"
  local provider_line="${5:-}"
  local workdir_line="${6:-}"
  local reasoning_line="${7:-}"
  local session_line="${8:-}"
  local step_line="${9:-}"

  local renderer_path="" renderer_output=""
  if renderer_path="$(gc_renderer_path_if_enabled)"; then
    local -a start_lines=()
    start_lines+=("|-----------------------|")
    start_lines+=("|     START TASK ID     |")
    start_lines+=("|-----------------------|")
    if [[ -n "$task_id" ]]; then
      start_lines+=("|    ${task_id}    |")
    else
      start_lines+=("|        N/A         |")
    fi
    start_lines+=("|-----------------------|")
    local alias_display="$alias_line"
    if [[ -z "$alias_display" ]]; then
      alias_display="Working on task ${task_id:-N/A}"
    fi
    start_lines+=("→ ${alias_display}")
    if [[ -n "$summary_line" ]]; then
      start_lines+=("  ${summary_line}")
    fi
    local step_token="${step_line:-patch}"
    local reasoning_token="${reasoning_line:-auto}"
    start_lines+=("meta (step=${step_token}) (model=${model_line:-N/A}) (reasoning=${reasoning_token})")
    [[ -n "$model_line" ]] && start_lines+=("model: ${model_line}")
    [[ -n "$provider_line" ]] && start_lines+=("provider: ${provider_line}")
    [[ -n "$workdir_line" ]] && start_lines+=("workdir: ${workdir_line}")
    [[ -n "$reasoning_line" ]] && start_lines+=("reasoning effort: ${reasoning_line}")
    [[ -n "$session_line" ]] && start_lines+=("session id: ${session_line}")
    if renderer_output="$(
      {
        local line
        for line in "${start_lines[@]}"; do
          printf '%s\n' "$line"
        done
      } | "$renderer_path"
    )"; then
      if [[ -n "$renderer_output" ]]; then
        printf '%s' "$renderer_output"
        return
      fi
    else
      local render_status=$?
      printf '[warn] Renderer failed via %s (exit=%s); falling back to plain task header.\n' \
        "$renderer_path" "$render_status" >&2
      GC_RENDERER_DISABLED=1
    fi
  fi

  printf '\\n%s╭────────────────────────────────────────────────────────────╮%s\\n' "${gc_color_border:-}" "$c_reset"
  printf '│  %sSTART OF TASK%s                                           │\\n' "${gc_color_title:-}" "$c_reset"
  printf '%s╰────────────────────────────────────────────────────────────╯%s\\n' "${gc_color_border:-}" "$c_reset"

  printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Start Task ID:" "$c_reset" "$task_id"
  [[ -n "$alias_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Alias:" "$c_reset" "$alias_line"
  [[ -n "$summary_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Summary:" "$c_reset" "$summary_line"
  [[ -n "$model_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Model:" "$c_reset" "$model_line"
  [[ -n "$provider_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Provider:" "$c_reset" "$provider_line"
  [[ -n "$workdir_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Workdir:" "$c_reset" "$workdir_line"
  [[ -n "$reasoning_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Reasoning:" "$c_reset" "$reasoning_line"
  [[ -n "$session_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Session:" "$c_reset" "$session_line"
  [[ -n "$step_line" ]] && printf '%s%-16s%s %s\\n' "${gc_color_label:-}" "Step:" "$c_reset" "$step_line"

  printf '\\n%s░░░░░ START OF A NEW TASK ░░░░░%s\\n\\n' "${gc_color_muted:-}" "$c_reset"
}

gc_render_task_end_panel() {
  local task_id="${1:-N/A}"
  local status="${2:-unknown}"
  local terminal="${3:-N/A}"
  local time_spent="${4:-0S}"
  local story_points_display="${5:-—}"
  local story_points_raw="${6:-0}"
  local tokens_used="${7:-0}"
  local tokens_estimate="${8:-0}"
  local tokens_display="${9:-}"
  local tokens_estimate_display="${10:-}"
  local failure_class="${11:-}"
  local detail_line="${12:-}"

  if [[ -z "$tokens_display" ]]; then
    tokens_display="$(gc_format_tokens_compact "$tokens_used")"
  fi
  if [[ -z "$tokens_estimate_display" ]]; then
    tokens_estimate_display="$(gc_format_tokens_compact "$tokens_estimate")"
  fi

  local tokens_numeric="$tokens_used"
  local est_numeric="$tokens_estimate"
  if [[ ! "$tokens_numeric" =~ ^[0-9]+$ ]]; then
    tokens_numeric="$(gc_numclean "$tokens_display")"
  fi
  if [[ ! "$est_numeric" =~ ^[0-9]+$ ]]; then
    est_numeric="$(gc_numclean "$tokens_estimate_display")"
  fi
  [[ "$tokens_numeric" =~ ^[0-9]+$ ]] || tokens_numeric=0
  [[ "$est_numeric" =~ ^[0-9]+$ ]] || est_numeric=0

  local ratio_pct="0.0"
  local ratio_multiplier="0.00"
  if (( est_numeric > 0 )); then
    ratio_pct="$(awk -v a="$tokens_numeric" -v b="$est_numeric" 'BEGIN{printf \"%.1f\", (a/b)*100}')"
    ratio_multiplier="$(awk -v a="$tokens_numeric" -v b="$est_numeric" 'BEGIN{if(b>0){printf \"%.2f\", a/b}else{printf \"0.00\"} }')"
  fi

  local sp_pct
  sp_pct="$(gc_story_points_percent "$story_points_raw")"

  local renderer_path=""
  local renderer_output=""
  if renderer_path="$(gc_renderer_path_if_enabled)"; then
    if renderer_output="$("$renderer_path" <<EOF
{ "task_id": "${task_id}", "status": "${status}", "terminal": "${terminal}", "time": "${time_spent}", "story_points": "${story_points_display}", "tokens_used": "${tokens_display}", "tokens_estimate": "${tokens_estimate_display}", "failure": "${failure_class}", "detail": "${detail_line}" }
EOF
)"; then
      if [[ -n "$renderer_output" ]]; then
        printf '%s\n' "$renderer_output"
        return
      fi
    else
      local render_status=$?
      printf '[warn] Renderer failed via %s (exit=%s); falling back to plain task footer.\n' \
        "$renderer_path" "$render_status" >&2
      GC_RENDERER_DISABLED=1
    fi
  fi

  local status_col="75"
  local normalized_status="${status,,}"
  case "$normalized_status" in
    completed|complete|success|ok) status_col=75 ;;
    blocked*|failed|dead-letter|permanent-fail|error|aborted|interrupted) status_col=196 ;;
    in-progress|running|pending) status_col=45 ;;
    *) status_col=226 ;;
  esac

  local terminal_col="220"
  local terminal_lower="${terminal,,}"
  case "$terminal_lower" in
    yes|y|true|1) terminal_col=160 ;;
    no|n|false|0) terminal_col=35 ;;
  esac

  printf '\n'
  gc_render_task_badge "TASK ${task_id:-N/A}" 45
  printf '\n'
  if [[ -n "$status" ]]; then
    gc_render_task_badge "STATUS ${status}" "$status_col"
    printf ' '
  fi
  if [[ -n "$terminal" ]]; then
    gc_render_task_badge "TERMINAL ${terminal}" "$terminal_col"
    printf ' '
  fi
  if [[ -n "$story_points_display" ]]; then
    gc_render_task_badge "SP ${story_points_display}" 39
    printf ' '
  fi
  gc_render_task_badge "TIME ${time_spent}" 221
  printf '\n'

  printf '%sTokens used:%s %s (est %s, x%s)\n' "${gc_color_label:-}" "$c_reset" "$tokens_display" "$tokens_estimate_display" "$ratio_multiplier"
  printf '%sStory points:%s %s (%s%%)\n' "${gc_color_label:-}" "$c_reset" "$story_points_display" "$sp_pct"
  printf '%sStatus:%s %s | Terminal: %s\n' "${gc_color_label:-}" "$c_reset" "$status" "$terminal"
  if [[ -n "$failure_class" && "$failure_class" != "NONE" ]]; then
    printf '%sFailure:%s %s\n' "${gc_color_label:-}" "$c_reset" "$failure_class"
  fi
  if [[ -n "$detail_line" ]]; then
    printf '%sDetail:%s %s\n' "${gc_color_label:-}" "$c_reset" "$detail_line"
  fi
  printf '\n%s░░░░░ END OF THE TASK WORK ░░░░░%s\n\n' "${gc_color_muted:-}" "$c_reset"
}
