#!/usr/bin/env bash
# render_gpt_creator.sh
# Pretty-prints gpt-creator CLI output with colors, badges, and gradient bars.
# Usage examples:
#   gpt-creator estimate --project ~/apps/yoga                   | ./render_gpt_creator.sh
#   gpt-creator backlog --project ~/apps/yoga --progress         | ./render_gpt_creator.sh
#   gpt-creator backlog --project ~/apps/yoga --item-children ADM-11 | ./render_gpt_creator.sh
#   tail -n 300 run.log | ./render_gpt_creator.sh

set -euo pipefail

# ============================ ANSI helpers ============================
c()      { printf "\033[%sm" "$1"; }
fg()     { printf "\033[38;5;%sm" "$1"; }
reset()  { printf "\033[0m"; }
dim()    { printf "\033[2m"; }
rep()    { local n="$1" ch="${2:- }"; printf "%*s" "$n" "" | tr ' ' "$ch"; }

# 0..100 → 256-color gradient (red→yellow→green)
gradient_256() {
  local pct="${1%.*}"
  (( pct < 0 )) && pct=0
  (( pct > 100 )) && pct=100
  if (( pct <= 50 )); then
    awk -v p="$pct" 'BEGIN{printf "%d", 196 + int(p*(220-196)/50)}'
  else
    awk -v p="$pct" 'BEGIN{printf "%d", 220 - int((p-50)*(220-46)/50)}'
  fi
}

# Inline progress bar
bar() {
  local pct="$1" width="${2:-28}"
  local fill
  fill=$(awk -v p="$pct" -v w="$width" 'BEGIN{printf "%d", (p/100.0)*w + 0.5}')
  (( fill < 0 )) && fill=0
  (( fill > width )) && fill="$width"
  local empty=$(( width - fill ))
  local col
  col="$(gradient_256 "$pct")"
  printf "[%s" "$(fg "$col")"
  rep "$fill" "#"
  reset
  rep "$empty" "─"
  printf "] %s%5.1f%%%s" "$(fg "$col")" "$pct" "$(reset)"
}

fancy_progress_bar() {
  local pct="${1:-0}"
  local width="${2:-30}"
  local label="${3:-Complete}"
  if [[ ! "$pct" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    pct=0
  fi
  if [[ ! "$width" =~ ^[0-9]+$ ]] || (( width <= 0 )); then
    width=30
  fi
  local color
  if (( $(awk "BEGIN{print ($pct >= 70)}") )); then
    color="1;32"
  elif (( $(awk "BEGIN{print ($pct >= 30)}") )); then
    color="1;38;5;214"
  else
    color="1;31"
  fi
  local fill
  fill=$(awk -v p="$pct" -v w="$width" 'BEGIN{
    if(p<0)p=0;
    if(p>100)p=100;
    printf "%d", int((p/100.0)*w + 0.5)
  }')
  [[ "$fill" =~ ^[0-9]+$ ]] || fill=0
  (( fill > width )) && fill=$width
  local empty=$((width - fill))

  printf "["
  if (( fill > 0 )); then
    printf "%s" "$(c "$color")"
    rep "$fill" "#"
    reset
  fi
  if (( empty > 0 )); then
    printf "%s" "$(c "1;90")"
    rep "$empty" "─"
    reset
  fi
  printf "]"
  printf "  %s%5.1f%%%s %s%s%s\n" "$(c "$color")" "$pct" "$(reset)" "$(c "$color")" "$label" "$(reset)"
}

progress_color_code() {
  local pct="${1:-0}"
  if [[ ! "$pct" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    pct="$(printf '%s' "$pct" | tr -cd '0-9.')"
  fi
  [[ -z "$pct" ]] && pct=0
  if (( $(awk "BEGIN{print ($pct >= 70)}") )); then
    printf "1;32"
  elif (( $(awk "BEGIN{print ($pct >= 30)}") )); then
    printf "1;38;5;214"
  else
    printf "1;31"
  fi
}

colorize_pct_string() {
  local raw="${1:-0%}"
  local clean
  clean="$(printf '%s' "$raw" | tr -cd '0-9.')"
  [[ -z "$clean" ]] && clean="0"
  local color
  color="$(progress_color_code "$clean")"
  printf "%s%s%s" "$(c "$color")" "$raw" "$(reset)"
}

status_color_code() {
  local status="${1:-}"
  local lower="${status,,}"
  case "$lower" in
    complete*|done*|success*) printf "1;32" ;;
    in-progress*|running*) printf "1;38;5;214" ;;
    pending*|blocked*|retry*|failed*) printf "1;31" ;;
    *) printf "1;37" ;;
  esac
}

render_box_header() {
  local title="${1:-GPT-Creator}"
  local max_width="${2:-60}"
  local border_color="${3:-$(c "1;38;5;213")}"   # vibrant magenta
  local title_color="${4:-$(c "1;38;5;51")}"     # electric cyan

  local cols width inner pad left right trimmed tlen
  cols="$(tput cols 2>/dev/null || echo 80)"
  [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
  (( max_width <= 0 )) && max_width=60
  width="$max_width"
  if (( cols < width )); then width="$cols"; fi
  if (( width < 40 )); then width=40; fi
  inner=$(( width - 2 ))

  trimmed="$title"
  tlen=${#trimmed}
  if (( tlen > inner )); then
    trimmed="${trimmed:0:inner}"
    tlen=${#trimmed}
  fi
  pad=$(( inner - tlen ))
  (( pad < 0 )) && pad=0
  left=$(( pad / 2 ))
  right=$(( pad - left ))

  local tl="╭" tr="╮" bl="╰" br="╯"
  local horiz left_pad right_pad
  printf -v horiz '%*s' "$inner" ''
  horiz="${horiz// /─}"
  printf -v left_pad '%*s' "$left" ''
  printf -v right_pad '%*s' "$right" ''

  printf "\n%s%s" "$border_color" "$tl"
  printf "%s" "$horiz"
  printf "%s%s\n" "$tr" "$(reset)"

  printf "%s│%s" "$border_color" "$(reset)"
  printf "%s" "$left_pad"
  printf "%s%s%s" "$title_color" "$trimmed" "$(reset)"
  printf "%s" "$right_pad"
  printf "%s│%s\n" "$border_color" "$(reset)"

  printf "%s%s" "$border_color" "$bl"
  printf "%s" "$horiz"
  printf "%s%s\n" "$br" "$(reset)"
}

render_backlog_header() {
  local text="$1"
  local width="${2:-66}"
  local border_color="${3:-$(c "1;38;5;214")}"
  local title_color="${4:-$(c "1;38;5;39")}"
  local inner=$((width - 2))
  local text_len="${#text}"
  (( inner < 0 )) && inner=0
  local pad=$((inner - 4))
  if (( pad < text_len )); then
    inner=$((text_len + 4))
    pad=$text_len
  fi
  local hyphens
  printf -v hyphens '%*s' "$inner" ''
  hyphens="${hyphens// /─}"
  printf "\n%s╭%s╮%s\n" "$border_color" "$hyphens" "$(reset)"
  printf "│  %s%-*s%s │\n" "$title_color" "$pad" "$text" "$(reset)"
  printf "%s╰%s╯%s\n" "$border_color" "$hyphens" "$(reset)"
}

draw_table() {
  local width_spec="${1:-}"
  local type_spec="${2:-}"
  local zebra="${3:-1}"
  local border_color="${TABLE_BORDER_COLOR:-$(c "1;38;5;213")}"
  local header_color="${TABLE_HEADER_COLOR:-$(c "1;38;5;45")}"
  local header_weight="${TABLE_HEADER_WEIGHT:-$(c 1)}"
  local row_even_color="${TABLE_ROW_EVEN_COLOR:-$(c "1;38;5;250")}"
  local row_odd_color="${TABLE_ROW_ODD_COLOR:-$(c "1;38;5;254")}"
  local percent_hi="${TABLE_PERCENT_HIGH:-$(c "1;32")}"
  local percent_mid="${TABLE_PERCENT_MID:-$(c "1;38;5;214")}"
  local percent_lo="${TABLE_PERCENT_LOW:-$(c "1;31")}"
  local status_pending="${TABLE_STATUS_PENDING:-$(c "1;37")}"
  local status_progress="${TABLE_STATUS_PROGRESS:-$(c "1;38;5;214")}"
  local status_done="${TABLE_STATUS_DONE:-$(c "1;32")}"
  local status_blocked="${TABLE_STATUS_BLOCKED:-$(c "1;31")}"
  local reset_code
  reset_code="$(reset)"

  awk -v widths="$width_spec" -v types="$type_spec" -v zebra="$zebra" \
      -v border="$border_color" -v header_color="$header_color" -v header_weight="$header_weight" \
      -v reset="$reset_code" -v row_even="$row_even_color" -v row_odd="$row_odd_color" \
      -v pct_hi="$percent_hi" -v pct_mid="$percent_mid" -v pct_lo="$percent_lo" \
      -v status_pending="$status_pending" -v status_prog="$status_progress" \
      -v status_done="$status_done" -v status_blocked="$status_blocked" \
      -v TL="╭" -v TM="┬" -v TR="╮" -v ML="├" -v MM="┼" -v MR="┤" \
      -v BL="╰" -v BM="┴" -v BR="╯" -v H="─" -v V="│" '
  function trim(str,    t) {
    t = str
    sub(/^[[:space:]]+/, "", t)
    sub(/[[:space:]]+$/, "", t)
    return t
  }
  function fit(str, limit,    val, len) {
    val = trim(str)
    len = length(val)
    if (len <= limit) { return val }
    if (limit <= 1)   { return substr(val, 1, limit) }
    return substr(val, 1, limit - 1) "…"
  }
  function repeat(ch, count,    out, idx) {
    out = ""
    for (idx = 0; idx < count; idx++) {
      out = out ch
    }
    return out
  }
  function build_rule(left, mid, right,    line, col) {
    line = left
    for (col = 1; col <= col_count; col++) {
      line = line repeat(H, col_width[col] + 2)
      line = line (col < col_count ? mid : right)
    }
    return line
  }
  function percent_color(val,    clean) {
    clean = val
    gsub(/[^0-9.]/, "", clean)
    if (clean == "") clean = 0
    clean += 0.0
    if (clean >= 70) return pct_hi
    else if (clean >= 30) return pct_mid
    return pct_lo
  }
  function status_color(val,    lower) {
    lower = tolower(val)
    if      (lower ~ /(complete|done|success)/) return status_done
    else if (lower ~ /(in[- ]?progress|running|active)/) return status_prog
    else if (lower ~ /(blocked|fail|error|retry|need|pending)/) return status_blocked
    return status_pending
  }
  function cell_color(idx, val, row_idx,    type) {
    if (row_idx == 0) return header_color header_weight
    type = col_type[idx]
    if (type == "percent") return percent_color(val)
    if (type == "status")  return status_color(val)
    if (zebra == 0) return row_even
    return (row_idx % 2 ? row_odd : row_even)
  }
  function print_row(line, row_idx,    fields, count, col, cell, color, width) {
    count = split(line, fields, FS)
    printf "%s%s%s", border, V, reset
    for (col = 1; col <= col_count; col++) {
      width = col_width[col]
      cell = (col <= count ? fields[col] : "")
      cell = fit(cell, width)
      color = cell_color(col, cell, row_idx)
      printf "%s %-" width "s %s", color, cell, reset
      printf "%s%s%s", border, V, reset
    }
    printf "\n"
  }
  BEGIN {
    FS = "\t"
    width_count = split(widths, width_vals, ",")
    split(types, col_type, ",")
    auto_width = (width_count == 0 || widths == "")
    rows = 0
    max_fields = 0
  }
  {
    rows++
    row_data[rows] = $0
    if (NF > max_fields) max_fields = NF
    for (i = 1; i <= NF; i++) {
      val = trim($i)
      len = length(val)
      if (len > max_len[i]) max_len[i] = len
    }
  }
  END {
    if (rows == 0) exit
    col_count = (auto_width ? max_fields : width_count)
    if (col_count == 0) col_count = max_fields
    if (col_count == 0) col_count = width_count
    if (col_count == 0) {
      col_count = 1
      width_vals[1] = 20
    }
    for (i = 1; i <= col_count; i++) {
      if (auto_width) {
        width_vals[i] = (max_len[i] > 0 ? max_len[i] : 6)
        if (width_vals[i] > 60) width_vals[i] = 60
      } else {
        width_vals[i] = trim(width_vals[i])
        if (width_vals[i] == "" || width_vals[i] < 3) {
          width_vals[i] = (max_len[i] > 0 ? max_len[i] : 6)
        }
      }
      if (width_vals[i] < 3) width_vals[i] = 3
      col_width[i] = int(width_vals[i])
      if (col_type[i] == "") col_type[i] = "text"
    }
    top = build_rule(TL, TM, TR)
    mid = build_rule(ML, MM, MR)
    bot = build_rule(BL, BM, BR)
    print border top reset
    for (r = 1; r <= rows; r++) {
      row_idx = (r == 1 ? 0 : r - 1)
      print_row(row_data[r], row_idx)
      if (r == 1) print border mid reset
    }
    print border bot reset
  }' || true
}

solid_progress_bar() {
  local pct="${1:-0}"
  local width="${2:-40}"
  local label="${3:-}"

  [[ "$pct" =~ ^-?[0-9]+([.][0-9]+)?$ ]] || pct=0
  [[ "$width" =~ ^[0-9]+$ ]] || width=40
  (( width < 1 )) && width=1

  local pct_val
  pct_val="$(awk -v p="$pct" 'BEGIN{
    if(p<0)p=0;
    if(p>100)p=100;
    printf "%.1f", p
  }')"

  local fill
  fill="$(awk -v p="$pct_val" -v w="$width" 'BEGIN{
    printf "%d", int((p/100.0)*w + 0.5)
  }')"
  [[ "$fill" =~ ^[0-9]+$ ]] || fill=0
  (( fill > width )) && fill=$width
  (( fill < 0 )) && fill=0
  local empty=$(( width - fill ))

  local reset="$(tput sgr0 2>/dev/null || printf '')"
  local color_count="$(tput colors 2>/dev/null || printf 8)"
  local bg_empty bg_fill
  if (( color_count >= 256 )); then
    bg_empty="$(tput setab 236 2>/dev/null || printf '')"
  else
    bg_empty="$(tput setab 7 2>/dev/null || printf '')"
  fi

  local band
  band="$(awk -v p="$pct_val" 'BEGIN{
    if (p >= 70)      print "high";
    else if (p >=30)  print "mid";
    else               print "low";
  }')"
  if (( color_count >= 256 )); then
    case "$band" in
      high) bg_fill="$(tput setab 2   2>/dev/null || printf '')" ;;
      mid)  bg_fill="$(tput setab 208 2>/dev/null || printf '')" ;;
      *)    bg_fill="$(tput setab 1   2>/dev/null || printf '')" ;;
    esac
  else
    case "$band" in
      high) bg_fill="$(tput setab 2 2>/dev/null || printf '')" ;;
      mid)  bg_fill="$(tput setab 3 2>/dev/null || printf '')" ;;
      *)    bg_fill="$(tput setab 1 2>/dev/null || printf '')" ;;
    esac
  fi

  local seg_fill seg_empty
  printf -v seg_fill "%*s" "$fill" ""
  printf -v seg_empty "%*s" "$empty" ""

  printf "%s[" "$(fg 244)"
  printf "%s%s" "$bg_fill" "$seg_fill"
  printf "%s%s" "$bg_empty" "$seg_empty"
  printf "%s%s" "$reset" "$(fg 244)"
  printf "]%s %5.1f%%" "$(reset)" "$pct_val"
  [[ -n "$label" ]] && printf " %s" "$label"
  printf "\n"
}

collect_epic_rows() {
  local rows="" payload
  payload="$(awk '
    BEGIN{flag=0}
    /^__GC_EPIC_TABLE__$/ {flag=1; next}
    /^__GC_EPIC_TABLE_END__$/ {flag=0; exit}
    flag {print}
  ' <<<"$INPUT")"
  if [[ -n "$payload" ]]; then
    rows="$(printf "%s\n" "$payload" | awk 'NR==1 {next} NF {print}')"
    printf "%s\n" "$rows"
    return 0
  fi

  local ascii_table
  ascii_table="$(awk '
    /^[[:space:]]*┌/ {capture=1}
    capture {
      print
      if ($0 ~ /┘[[:space:]]*$/) exit
    }
  ' <<<"$INPUT")"
  if [[ -n "$ascii_table" ]]; then
    rows="$(printf "%s\n" "$ascii_table" | awk -F"│" '
      function trim(s){ sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
      /^[[:space:]]*┌/ {next}
      /^[[:space:]]*├/ {next}
      /^[[:space:]]*└/ {exit}
      /^[[:space:]]*│/ {
        epic=trim($2); title=trim($3); stories=trim($4); tasks=trim($5); progress=trim($6);
        if (epic == "" || epic == "EPIC") next
        printf "%s\t%s\t%s\t%s\t%s\n", epic, title, stories, tasks, progress
      }
    ')"
    printf "%s\n" "$rows"
    return 0
  fi

  local table_block
  table_block="$(awk '
    BEGIN{flag=0}
    /^Epic ID[[:space:]]/ {flag=1; next}
    flag {
      if ($0 ~ /^$/) { exit }
      print
    }
  ' <<<"$INPUT")"
  rows="$(printf "%s" "$table_block" | awk -F'  +' '
    function trim(s){ sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
    NF >= 6 {
      epic=trim($1); title=trim($3); stories=trim($4); tasks=trim($5); prog=trim($6);
      if (epic ~ /^-+$/) next
      printf "%s\t%s\t%s\t%s\t%s\n", epic, title, stories, tasks, prog
    }
  ')"
  printf "%s\n" "$rows"
}

print_epic_table_from_rows() {
  local table_rows="$1"
  [[ -z "$table_rows" ]] && return 0
  local header_line=$'EPIC\tTITLE\tSTORIES\tTASKS\tPROGRESS'
  local payload="${header_line}"$'\n'"${table_rows}"
  [[ "$payload" != *$'\n' ]] && payload+=$'\n'
  printf "%s" "$payload" | draw_table "10,55,20,20,10" "text,text,text,text,percent"
}

print_story_breakdown_table() {
  local rows="$1"
  [[ -z "$rows" ]] && return 0
  local header_line=$'Story\tTitle\tStatus\tEpic\tTasks\tProgress'
  local payload="${header_line}"$'\n'"${rows}"
  [[ "$payload" != *$'\n' ]] && payload+=$'\n'
  printf "%s" "$payload" | draw_table "14,52,16,16,18,10" "text,text,status,text,text,percent"
}

print_story_tasks_table() {
  local table_rows="$1"
  [[ -z "$table_rows" ]] && return 0
  local header_line=$'#\tOrder\tTask ID\tTitle\tStatus\tSP'
  local payload="${header_line}"$'\n'"${table_rows}"
  [[ "$payload" != *$'\n' ]] && payload+=$'\n'
  printf "%s" "$payload" | draw_table "4,8,18,60,18,6" "text,text,text,text,status,text"
}

status_color() {
  case "$(tr '[:upper:]' '[:lower:]' <<<"${1:-}")" in
    pending)      fg 245 ;;
    in-progress)  fg 220 ;;
    complete|completed|done) fg 46 ;;
    *)            fg 251 ;;
  esac
}

badge() { # fancy rounded badge, with ASCII fallback
  local label="$1" col="$2"
  local accent="$(fg "$col")$(c 1)"
  if [[ "$BADGE_STYLE" == "unicode" ]]; then
    local left=$'\ue0b6' right=$'\ue0b4'
    printf "%s%s" "$(fg 240)" "$left"
    printf "%s %s %s" "$accent" "$label" "$(reset)"
    printf "%s%s" "$(fg 240)" "$right"
  else
    printf "%s[" "$(fg 240)"
    printf "%s %s %s" "$accent" "$label" "$(reset)"
    printf "%s]%s" "$(fg 240)" "$(reset)"
  fi
  printf "%s" "$(reset)"
}

lc(){ c "1;38;5;${1}"; }

numclean(){ tr -d ', ' <<<"$1"; }

badge_supports_unicode() {
  local charmap glyph_len
  charmap="$(LC_ALL=C locale charmap 2>/dev/null || echo UTF-8)"
  [[ "$charmap" == "UTF-8" ]] || return 1
  glyph_len="$(printf '%s' $'\ue0b6' | LC_ALL=C wc -m 2>/dev/null | tr -d '[:space:]')"
  [[ "$glyph_len" == "1" ]]
}

BADGE_STYLE="unicode"
if [[ "${GC_BADGE_STYLE:-}" =~ ^([Aa][Ss][Cc][Ii][Ii])$ || "${GC_BADGE_ASCII:-0}" == "1" ]]; then
  BADGE_STYLE="ascii"
elif ! badge_supports_unicode; then
  BADGE_STYLE="ascii"
fi

# ============================ Read stdin ============================
INPUT="$(cat)"

# ============================ Detectors ============================
is_estimate()         { grep -q '^Remaining Work Summary' <<<"$INPUT"; }
is_epic_children()    { grep -qE '^Stories for epic:' <<<"$INPUT"; }
is_story_tasks()      { grep -qE '^Tasks for story:' <<<"$INPUT"; }
is_overall_progress() { grep -qiE '^Overall backlog progress' <<<"$INPUT"; }
is_epic_overview()    { grep -qE '__GC_EPIC_TABLE__|^Epic ID[[:space:]]+Slug|^┌' <<<"$INPUT"; }
is_task_end()         { grep -qiE 'END TASK ID|^Task ID:' <<<"$INPUT"; }
is_task_start()       { grep -qiE 'START TASK ID|→ Working on task' <<<"$INPUT"; }

# ============================ Renderers ============================

render_estimate() {
  local comp_can comp_eff sp_done detect pend_can inprog_can rem_can rem_eff total rem_sp eta throughput obs_tokens avg_per_sp burn proj
  comp_can="$(sed -n 's/^Completed tasks (canonical)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  comp_eff="$(sed -n 's/^Completed tasks (effective)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  sp_done="$(sed -n 's/^Completed story points[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  detect="$(sed -n 's/^Detections pending apply[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  inprog_can="$(sed -n 's/^In-progress (canonical)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  pend_can="$(sed -n 's/^Pending (canonical)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  rem_can="$(sed -n 's/^Remaining (canonical)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  rem_eff="$(sed -n 's/^Remaining tasks (effective)[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  total="$(sed -n 's/^Total tasks[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  rem_sp="$(sed -n 's/^Remaining story points[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  eta="$(sed -n 's/^Estimated completion[[:space:]]\{1,\}\(.*\)$/\1/p' <<<"$INPUT")"

  throughput="$(sed -n 's/^Effective throughput[[:space:]]\{1,\}\([0-9.]\+\) SP\/hour.*/\1/p' <<<"$INPUT" | head -1)"
  obs_tokens="$(sed -n 's/^Observed tokens[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  avg_per_sp="$(sed -n 's/^Average tokens per story point[[:space:]]\{1,\}\([0-9.,]\+\).*/\1/p' <<<"$INPUT")"
  burn="$(sed -n 's/^Estimated token burn[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"
  proj="$(sed -n 's/^Projected remaining tokens[[:space:]]\{1,\}\([0-9,]\+\).*/\1/p' <<<"$INPUT")"

  local total_clean comp_eff_clean rem_clean
  total_clean="$(numclean "${total:-0}")"
  comp_eff_clean="$(numclean "${comp_eff:-0}")"
  rem_clean="$(numclean "${rem_can:-0}")"
  local progress_pct="0.0"
  if [[ "$total_clean" =~ ^[0-9]+$ ]] && (( total_clean > 0 )); then
    progress_pct="$(awk -v c="$comp_eff_clean" -v t="$total_clean" 'BEGIN{printf "%.1f",(c/t)*100}')"
  fi

  render_box_header "GPT-Creator :: Project Estimate Summary" 60

  printf "  "; badge "TOTAL ${total:-N/A}" 39; printf "  "
  badge "DONE ${comp_eff:-N/A}" 46; printf "  "
  badge "REMAIN ${rem_can:-N/A}" 208; printf "  "
  [[ -n "$eta" ]] && { badge "ETA ${eta}" 111; printf "  "; }
  [[ -n "$rem_sp" ]] && badge "SP ${rem_sp}" 201
  printf "\n\n"

  printf "  %sProgress%s\n" "$(lc 111)" "$(reset)"
  solid_progress_bar "$progress_pct" 40 "Complete"
  printf "\n"

  printf "%s🧾 Remaining Work Snapshot%s\n" "$(lc 111)" "$(reset)"
  printf "────────────────────────────────────────────\n"
  printf "  • %sCompleted (canonical):%s   %s\n" "$(c "1;32")" "$(reset)" "${comp_can:-—}"
  printf "  • %sCompleted (effective):%s   %s\n" "$(c "1;32")" "$(reset)" "${comp_eff:-—}"
  printf "  • %sCompleted SP:%s            %s\n" "$(c "1;32")" "$(reset)" "${sp_done:-—}"
  printf "  • %sDetections pending:%s      %s\n" "$(c "1;38;5;214")" "$(reset)" "${detect:-—}"
  printf "  • %sIn-progress:%s             %s\n" "$(c "1;38;5;220")" "$(reset)" "${inprog_can:-—}"
  printf "  • %sPending / Remaining:%s     %s / %s\n" "$(c "1;37")" "$(reset)" "${pend_can:-—}" "${rem_can:-—}"
  printf "  • %sRemaining (effective):%s   %s\n" "$(c "1;37")" "$(reset)" "${rem_eff:-—}"
  printf "  • %sRemaining story points:%s  %s\n" "$(c "1;31")" "$(reset)" "${rem_sp:-—}"
  printf "  • %sETA:%s                     %s\n\n" "$(c "1;35")" "$(reset)" "${eta:-—}"

  printf "%s⚙️ Throughput%s\n" "$(lc 111)" "$(reset)"
  printf "────────────────────────────────────────────\n"
  local throughput_section
  throughput_section="$(sed -n -e 's/^Throughput basis/• Basis/p' \
         -e 's/^Effective throughput/• Effective throughput/p' \
         -e 's/^Throughput window/• Window/p' \
         -e 's/^Run status/• Run status/p' <<<"$INPUT")"
  printf "%s\n\n" "${throughput_section:-  • (not reported)}"

  printf "%s🔢 Token Telemetry%s\n" "$(lc 111)" "$(reset)"
  printf "────────────────────────────────────────────\n"
  printf "  • Observed tokens:            %s%s%s\n" "$(c "1;36")" "${obs_tokens:-—}" "$(reset)"
  printf "  • Avg tokens / SP:            %s%s%s\n" "$(c "1;37")" "${avg_per_sp:-—}" "$(reset)"
  printf "  • Est. token burn:            %s%s%s @ %s%s SP/h%s\n" "$(c "1;31")" "${burn:-—}" "$(reset)" "$(c "1;32")" "${throughput:-—}" "$(reset)"
  printf "  • Projected remaining tokens: %s%s%s\n\n" "$(c "1;35")" "${proj:-—}" "$(reset)"
}

render_epic_children() {
  local header epic
  header="$(sed -n 's/^Stories for epic: \(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  epic="${header%% *}"

  render_backlog_header "Stories for Epic: ${header}" 66

  if grep -q 'Carried forward migration state' <<<"$INPUT"; then
    local mig
    mig="$(grep -m1 'Carried forward migration state' <<<"$INPUT")"
    printf "➜ %s\n\n" "$mig"
  fi

  printf "%s📘 Story Breakdown%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  local ascii_story_table
  ascii_story_table="$(awk '
    /^[[:space:]]*┌/ {capture=1}
    capture {
      print
      if ($0 ~ /┘[[:space:]]*$/) exit
    }
  ' <<<"$INPUT")"

  if [[ -n "$ascii_story_table" ]]; then
    printf "%s\n\n" "$ascii_story_table"
  else
  local ascii_story_table
  ascii_story_table="$(awk '
    /^[[:space:]]*┌/ {capture=1}
    capture {
      print
      if ($0 ~ /┘[[:space:]]*$/) exit
    }
  ' <<<"$INPUT")"

  local story_rows=""
  if [[ -n "$ascii_story_table" ]]; then
    story_rows="$(printf "%s\n" "$ascii_story_table" | awk -F'│' '
      function trim(s){ sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
      /^[[:space:]]*┌/ {next}
      /^[[:space:]]*├/ {next}
      /^[[:space:]]*└/ {exit}
      /^[[:space:]]*│/ {
        story=trim($2); title=trim($3); status=trim($4); epic=trim($5); tasks=trim($6); progress=trim($7);
        if (story == "" || story == "Story") next
        printf "%s\t%s\t%s\t%s\t%s\t%s\n", story,title,status,epic,tasks,progress
      }
    ')"
  fi

  if [[ -z "$story_rows" ]]; then
    story_rows="$(awk -F'  +' '
      BEGIN{ show=0 }
      /^Story Slug[[:space:]]/ { show=1; next }
      show && NF>=6 {
        slug=$1; title=$2; status=$3; epic=$4; tasks=$5; progress=$6;
        gsub(/^[ \t]+|[ \t]+$/,"",slug);
        gsub(/^[ \t]+|[ \t]+$/,"",title);
        gsub(/^[ \t]+|[ \t]+$/,"",status);
        gsub(/^[ \t]+|[ \t]+$/,"",epic);
        gsub(/^[ \t]+|[ \t]+$/,"",tasks);
        gsub(/^[ \t]+|[ \t]+$/,"",progress);
        printf "%s\t%s\t%s\t%s\t%s\t%s\n", slug,title,status,epic,tasks,progress;
      }' <<<"$INPUT")"
  fi

  print_story_breakdown_table "$story_rows"
  fi

  if grep -q '^Backlog totals (canonical)' <<<"$INPUT"; then
    printf "\n%s📊 Epic Totals%s\n" "$(lc 111)" "$(reset)"
    printf "──────────────────────────────────────────────\n"
    while IFS= read -r line; do
      case "$line" in
        "Completed:"*) comp="${line#Completed: }";;
        "In-progress:"*) inprog="${line#In-progress: }";;
        "Pending:"*) pend="${line#Pending: }";;
        "Remaining:"*) remain="${line#Remaining: }";;
        "Total tasks:"*) total="${line#Total tasks: }";;
      esac
    done < <(sed -n '/^Backlog totals (canonical)/,$p' <<<"$INPUT")
    printf "• Completed: %s%s%s | In-progress: %s%s%s | Pending: %s%s%s | Remaining: %s%s%s | Total: %s%s%s\n\n" \
      "$(c 1';32')" "${comp:-?}" "$(reset)" \
      "$(c 1';38;5;220')" "${inprog:-?}" "$(reset)" \
      "$(c 1';37')" "${pend:-?}" "$(reset)" \
      "$(c 1';37')" "${remain:-?}" "$(reset)" \
      "$(c 1';36')" "${total:-?}" "$(reset)"
  fi
}

render_story_tasks() {
  local header
  header="$(sed -n 's/^Tasks for story: \(.*\)$/\1/p' <<<"$INPUT" | head -1)"

  render_backlog_header "Tasks for Story: ${header}" 70

  if grep -q 'Carried forward migration state' <<<"$INPUT"; then
    local mig
    mig="$(grep -m1 'Carried forward migration state' <<<"$INPUT")"
    printf "➜ %s\n\n" "$mig"
  fi

  printf "%s🧩 Task Breakdown%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  local task_rows=""
  local ascii_task_table
  ascii_task_table="$(awk '
    /^[[:space:]]*┌/ {capture=1}
    capture {
      print
      if ($0 ~ /┘[[:space:]]*$/) exit
    }
  ' <<<"$INPUT")"

  if [[ -n "$ascii_task_table" ]]; then
    task_rows="$(printf "%s\n" "$ascii_task_table" | awk -F'│' '
      function trim(s){ sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
      /^[[:space:]]*┌/ {next}
      /^[[:space:]]*├/ {next}
      /^[[:space:]]*└/ {exit}
      /^[[:space:]]*│/ {
        idx=trim($2); order=trim($3); id=trim($4); title=trim($5); status=trim($6); sp=trim($7);
        if (idx == "" || idx == "#") next
        printf "%s\t%s\t%s\t%s\t%s\t%s\n", idx,order,id,title,status,sp
      }
    ')"
  fi

  if [[ -z "$task_rows" ]]; then
    task_rows="$(awk -F'  +' '
      BEGIN{ show=0 }
      /^#  Order[[:space:]]/ { show=1; next }
      show && $1 ~ /^[0-9-]+$/ && NF>=6 {
        idx=$1; order=$2; id=$3; status=$(NF-1); sp=$NF;
        title=$4; for(i=5;i<=NF-2;i++){ title=title " " $i }
        gsub(/^[ \t]+|[ \t]+$/,"",title);
        printf("%s\t%s\t%s\t%s\t%s\t%s\n", idx,order,id,title,status,sp);
      }' <<<"$INPUT")"
  fi

  print_story_tasks_table "$task_rows"
  printf "\n"

  if grep -q '^Backlog totals (canonical)' <<<"$INPUT"; then
    printf "\n%s📊 Backlog Totals%s\n" "$(lc 111)" "$(reset)"
    printf "──────────────────────────────────────────────\n"
    while IFS= read -r line; do
      case "$line" in
        "Completed:"*) comp="${line#Completed: }";;
        "In-progress:"*) inprog="${line#In-progress: }";;
        "Pending:"*) pend="${line#Pending: }";;
        "Remaining:"*) remain="${line#Remaining: }";;
        "Total tasks:"*) total="${line#Total tasks: }";;
      esac
    done < <(sed -n '/^Backlog totals (canonical)/,$p' <<<"$INPUT")
    printf "• Completed: %s%s%s | In-progress: %s%s%s | Pending: %s%s%s | Remaining: %s%s%s | Total: %s%s%s\n\n" \
      "$(c 1';32')" "${comp:-?}" "$(reset)" \
      "$(c 1';38;5;220')" "${inprog:-?}" "$(reset)" \
      "$(c 1';37')" "${pend:-?}" "$(reset)" \
      "$(c 1';37')" "${remain:-?}" "$(reset)" \
      "$(c 1';36')" "${total:-?}" "$(reset)"
  fi
}

render_overall() {
  local pct
  pct="$(sed -n 's/^Completed tasks (effective): .* (\(.*\)%).*/\1/p' <<<"$INPUT" | head -1)"
  pct="${pct:-0}"

  render_backlog_header "Overall Backlog Progress" 66

  if grep -q 'Carried forward migration state' <<<"$INPUT"; then
    local mig
    mig="$(grep -m1 'Carried forward migration state' <<<"$INPUT")"
    printf "➜ %s\n\n" "$mig"
  fi

  printf "%s📊 Backlog Summary%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  local comp_canon comp_eff comp_eff_pct inprog_eff pend_eff remain_can total_tasks
  comp_canon="$(sed -n 's/^Completed tasks (canonical):[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  comp_eff="$(sed -n 's/^Completed tasks (effective):[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  comp_eff_pct="$(sed -n 's/^Completed tasks (effective):.*(\(.*\)).*/\1/p' <<<"$INPUT" | head -1)"
  inprog_eff="$(sed -n 's/^In-progress (effective):[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  pend_eff="$(sed -n 's/^Pending (effective):[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  remain_can="$(sed -n 's/^Remaining (canonical):[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  total_tasks="$(sed -n 's/^Total tasks:[[:space:]]*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  printf "• Completed tasks (canonical):   %s\n" "${comp_canon:-—}"
  printf "• Completed tasks (effective):   %s (%s)\n" "${comp_eff:-—}" "$(colorize_pct_string "${comp_eff_pct:-0%}")"
  printf "• In-progress (effective):       %s\n" "${inprog_eff:-—}"
  printf "• Pending (effective):           %s\n" "${pend_eff:-—}"
  printf "• Remaining (canonical):         %s\n" "${remain_can:-—}"
  printf "• Total tasks:                   %s\n" "${total_tasks:-—}"
  printf "\n%s📈 Visual Progress%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  solid_progress_bar "$pct" 40 "Complete"
  printf "\n"

  if grep -q '^Backlog totals (canonical)' <<<"$INPUT"; then
    printf "%s📊 Backlog Totals (Canonical)%s\n" "$(lc 111)" "$(reset)"
    printf "──────────────────────────────────────────────────────────────\n"
    while IFS= read -r line; do
      case "$line" in
        "Completed:"*) comp="${line#Completed: }";;
        "In-progress:"*) inprog="${line#In-progress: }";;
        "Pending:"*) pend="${line#Pending: }";;
        "Remaining:"*) remain="${line#Remaining: }";;
        "Total tasks:"*) total="${line#Total tasks: }";;
      esac
    done < <(sed -n '/^Backlog totals (canonical)/,$p' <<<"$INPUT")
    printf "• Completed: %s%s%s | In-progress: %s%s%s | Pending: %s%s%s | Remaining: %s%s%s | Total: %s%s%s\n\n" \
      "$(c 1';32')" "${comp:-?}" "$(reset)" \
      "$(c 1';38;5;220')" "${inprog:-?}" "$(reset)" \
      "$(c 1';37')" "${pend:-?}" "$(reset)" \
      "$(c 1';37')" "${remain:-?}" "$(reset)" \
      "$(c 1';36')" "${total:-?}" "$(reset)"
  fi
}

render_task_start() {
  local id alias summary model provider workdir reasoning session step
  id="$(sed -n 's/^[^A-Z0-9-]*|\s*\(.*-T[0-9]\+\)\s*|\s*$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$id" ]] && id="$(sed -n 's/^.*(ADM-.*-T[0-9]\+).*/\1/p' <<<"$INPUT" | head -1)"
  alias="$(sed -n 's/^.*→ Working on task .* (\(ADM-.*-T[0-9]\+\)).*/\1/p' <<<"$INPUT" | head -1)"
  [[ -n "$alias" ]] && alias="Working on task ${alias##*-T}"
  summary="$(sed -n '/→ Working on task/,+2p' <<<"$INPUT" | sed -n '2{s/^[^A-Za-z0-9-]*//;p;q}')"
  step="$(sed -n 's/.*(step=\([^)]*\)).*/\1/p' <<<"$INPUT" | head -1)"
  model="$(sed -n 's/^model:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$model" ]] && model="$(sed -n 's/.*model=\(.*\) .*/\1/p' <<<"$INPUT" | head -1)"
  provider="$(sed -n 's/^provider:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$provider" ]] && provider="$(sed -n 's/^provider:\s*\(.*\)$/\1/p' <<<"$INPUT" | tail -1)"
  workdir="$(sed -n 's/^workdir:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  reasoning="$(sed -n 's/^reasoning effort:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$reasoning" ]] && reasoning="$(sed -n 's/.*reasoning=\(.*\)).*/\1/p' <<<"$INPUT" | head -1)"
  session="$(sed -n 's/^session id:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$session" ]] && session="$(sed -n 's/^Session:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"

  render_box_header "START OF TASK" 60

  printf "  %s[#]%s %sStart Task ID:%s  %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;45')" "${id:-N/A}" "$(reset)"
  [[ -n "$alias"   ]] && printf "  %s[↪]%s %sAlias:%s          %s%s%s\n"   "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;39')"  "$alias"      "$(reset)"
  [[ -n "$summary" ]] && printf "  %s[✍]%s %sSummary:%s        %s%s%s\n"   "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;51')"  "$summary"    "$(reset)"

  printf "  %s[■]%s %sModel:%s          %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;39')"  "${model:-N/A}"    "$(reset)"
  printf "  %s[⚙]%s %sProvider:%s       %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;38')"  "${provider:-N/A}" "$(reset)"
  [[ -n "$step"    ]] && printf "  %s[🧩]%s %sStep:%s           %s%s%s\n"   "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;208')" "${step}"      "$(reset)"
  printf "  %s[🧠]%s %sReasoning:%s      %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;221')" "${reasoning:-auto}" "$(reset)"
  printf "  %s[📁]%s %sWorkdir:%s        %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;247')" "${workdir:-N/A}"  "$(reset)"
  printf "  %s[🔑]%s %sSession:%s        %s%s%s\n"        "$(fg 244)" "$(reset)" "$(fg 111)" "$(reset)" "$(c 1';38;5;201')" "${session:-N/A}"  "$(reset)"

  printf "\n    %s%s%s\n\n" "$(fg 245)" "░░░░░ START OF A NEW TASK ░░░░░" "$(reset)"

  if [[ -n "${step}${model}" ]]; then
    printf "    %s[%sSTEP%s %s%s%s]%s  %s[%sMODEL%s %s%s%s]%s\n\n" \
      "$(fg 240)" "$(reset)" "$(fg 240)" "$(c 1';38;5;208')" "$step" "$(reset)" "$(fg 240)" \
      "$(fg 240)" "$(reset)" "$(fg 240)" "$(c 1';38;5;39')" "$model" "$(reset)" "$(fg 240)"
    reset
  fi
}

render_task_end() {
  local id tokens est sp time status term notes_block tb_exception tb_file tb_note needs_retry next_line
  id="$(sed -n 's/^[^A-Z0-9-]*|\s*\(.*-T[0-9]\+\)\s*|\s*$/\1/p' <<<"$INPUT" | head -1)"
  [[ -z "$id" ]] && id="$(sed -n 's/^Task ID:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  status="$(sed -n 's/^Status:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  term="$(sed -n 's/^Terminal:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  time="$(sed -n 's/^Time spent:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  sp="$(sed -n 's/^Story points:\s*\(.*\)$/\1/p' <<<"$INPUT" | head -1)"
  tokens="$(sed -n 's/.*TOKENS USED:\s*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  est="$(sed -n 's/.*EST\. TOKENS (PROMPT):\s*\([0-9,]\+\).*/\1/p' <<<"$INPUT" | head -1)"
  notes_block="$(sed -n '/^Notes/,/^$/p' <<<"$INPUT")"

  if grep -q '^Traceback (most recent call last):' <<<"$INPUT"; then
    tb_exception="$(grep -E '^[A-Za-z]*Error: ' -m1 <<<"$INPUT" || true)"
    tb_file="$(grep -E ' File ".*", line [0-9]+' <<<"$INPUT" | tail -1 || true)"
    tb_note="$(grep -m1 'gc-child-unhandled' <<<"$INPUT" || true)"
  fi
  needs_retry="$(grep -i 'STATUS: *needs-retry' <<<"$INPUT" || true)"
  next_line="$(grep -E '█▶|Working on task' <<<"$INPUT" | head -1)"

  local tokens_n est_n ratio_p ratio_x
  tokens_n="$(numclean "$tokens")"
  est_n="$(numclean "$est")"
  if [[ -n "$tokens_n" && -n "$est_n" && "$est_n" -gt 0 ]]; then
    ratio_p="$(awk -v a="$tokens_n" -v b="$est_n" 'BEGIN{printf "%.1f", (a/b)*100}')"
    ratio_x="$(awk -v a="$tokens_n" -v b="$est_n" 'BEGIN{printf "%.2f", (a/b)}')"
  fi

  render_box_header "END OF TASK" 60

  printf "  "
  badge "TASK ${id:-N/A}" 45
  printf "  "
  [[ -n "$status" ]] && badge "STATUS ${status}" "$([[ "$status" =~ ^(COMPLETE|COMPLETED)$ ]] && echo 46 || echo 208)"
  printf "  "
  [[ -n "$term"   ]] && badge "TERMINAL ${term}"  111
  printf "  "
  [[ -n "$sp"     ]] && badge "SP ${sp}"          39
  printf "  "
  [[ -n "$time"   ]] && badge "TIME ${time}"      221
  printf "\n\n"

  if [[ -n "$sp" ]]; then
    printf "  %sStory points:%s " "$(lc 111)" "$(reset)"
    bar "$(awk -v s="$sp" 'BEGIN{ if(s<0)s=0; if(s>13)s=13; printf "%.1f",(s/13)*100 }')" 28
    printf "\n"
  fi

  if [[ -n "$tokens_n" || -n "$est_n" ]]; then
    printf "  %sTokens used:%s  %'d\n" "$(lc 111)" "$(reset)" "${tokens_n:-0}"
    if [[ -n "$ratio_p" ]]; then
      printf "    "
      bar "$ratio_p" 30
      printf "  used vs prompt est (x%s)\n" "${ratio_x}"
    fi
    [[ -n "$est_n" ]] && printf "  %sEst. tokens:%s   %'d\n" "$(lc 111)" "$(reset)" "${est_n}"
  fi
  printf "\n"

  if [[ -n "$notes_block" ]]; then
    printf "%s📝 Notes%s\n" "$(lc 111)" "$(reset)"
    printf "────────────────────────────────────────────────────────────\n"
    sed -n '1d;p' <<<"$notes_block" | sed '/^$/d' | while IFS= read -r ln; do
      ln="${ln#- }"
      printf "  %s•%s %s\n" "$(fg 244)" "$(reset)" "$ln"
    done
    printf "\n"
  fi

  if [[ -n "$tb_exception" || -n "$tb_file" ]]; then
    printf "%s💥 Exception%s\n" "$(lc 203)" "$(reset)"
    printf "────────────────────────────────────────────────────────────\n"
    [[ -n "$tb_exception" ]] && printf "  %s%s%s\n" "$(c 1';38;5;203')" "$tb_exception" "$(reset)"
    [[ -n "$tb_file"      ]] && printf "  %s%s%s\n" "$(fg 245)" "$tb_file" "$(reset)"
    [[ -n "$tb_note"      ]] && printf "  %s%s%s\n" "$(fg 245)" "$tb_note" "$(reset)"
    printf "\n"
  fi

  if [[ -n "$needs_retry" ]]; then
    printf "  %s⚠ STATUS: NEEDS-RETRY%s\n\n" "$(c 1';38;5;208')" "$(reset)"
  fi

  if [[ -n "$next_line" ]]; then
    printf "%s➡ Next%s\n" "$(lc 111)" "$(reset)"
    printf "────────────────────────────────────────────────────────────\n"
    printf "  %s%s%s\n\n" "$(fg 110)" "$next_line" "$(reset)"
  fi

  mapfile -t ops_lines < <(grep -E '^(➜|(\[warn\]))' <<<"$INPUT" || true)
  if ((${#ops_lines[@]})); then
    printf "%s🧭 Follow-up Ops%s\n" "$(lc 111)" "$(reset)"
    printf "────────────────────────────────────────────────────────────\n"
    for op in "${ops_lines[@]}"; do
      if [[ "$op" =~ ^\[warn\] ]]; then
        printf "  %s⚠ %s%s\n" "$(c 1';38;5;214')" "${op}" "$(reset)"
      else
        printf "  %s➜%s %s\n" "$(fg 244)" "$(reset)" "${op#➜ }"
      fi
    done
    printf "\n"
  fi

  printf "    %s%s%s\n\n" "$(fg 245)" "░░░░░ END OF THE TASK WORK ░░░░░" "$(reset)"
}

render_epic_overview() {
  local project_display="${PROJECT_ROOT:-$PWD}"
  render_box_header "GPT-Creator :: Backlog Summary (${project_display})" 60

  local migration_line
  migration_line="$(grep -m1 'Carried forward migration state' <<<"$INPUT" || true)"
  [[ -n "$migration_line" ]] && printf "%s\n" "$migration_line"

  printf "\n%s📋 Epic Progress Overview%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"

  local data_rows
  data_rows="$(collect_epic_rows)"

  print_epic_table_from_rows "$data_rows"

  local total_epics=0 high=0 mid=0 low=0
  if [[ -n "$data_rows" ]]; then
    while IFS=$'\t' read -r epic title stories tasks progress; do
      [[ -z "$epic" ]] && continue
      ((++total_epics))
      local pct
      pct="$(printf '%s' "$progress" | tr -cd '0-9.')"
      [[ -z "$pct" ]] && pct="0"
      if (( $(awk "BEGIN {print ($pct >= 70)}") )); then
        ((++high))
      elif (( $(awk "BEGIN {print ($pct >= 30)}") )); then
        ((++mid))
      else
        ((++low))
      fi
    done <<<"$data_rows"
  fi

  printf "%s📈 Overall Trend%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────\n"
  printf "• %s%d%s epics at ≥70%% completion\n" "$(c "1;32")" "$high" "$(reset)"
  printf "• %s%d%s epics between 30-69%%\n" "$(c "1;38;5;214")" "$mid" "$(reset)"
  printf "• %s%d%s epics below 30%% or pending\n\n" "$(c "1;31")" "$low" "$(reset)"

  if grep -q '^Backlog totals (canonical)' <<<"$INPUT"; then
    printf "%s📊 Backlog totals (canonical)%s\n" "$(lc 111)" "$(reset)"
    printf "──────────────────────────────────────────────\n"
    while IFS= read -r line; do
      case "$line" in
        "Completed:"*) comp="${line#Completed: }";;
        "In-progress:"*) inprog="${line#In-progress: }";;
        "Pending:"*) pend="${line#Pending: }";;
        "Remaining:"*) remain="${line#Remaining: }";;
        "Total tasks:"*) total="${line#Total tasks: }";;
      esac
    done < <(sed -n '/^Backlog totals (canonical)/,$p' <<<"$INPUT")
    printf "• Completed: %s%s%s | In-progress: %s%s%s | Pending: %s%s%s | Remaining: %s%s%s | Total: %s%s%s\n\n" \
      "$(c "1;32")" "${comp:-?}" "$(reset)" \
      "$(c "1;38;5;220")" "${inprog:-?}" "$(reset)" \
      "$(c "1;37")" "${pend:-?}" "$(reset)" \
      "$(c "1;37")" "${remain:-?}" "$(reset)" \
      "$(c "1;36")" "${total:-?}" "$(reset)"
  fi
}

# ============================ Router ============================
if   is_task_end;         then render_task_end;         exit 0
elif is_task_start;       then render_task_start;       exit 0
elif is_estimate;         then render_estimate;         exit 0
elif is_epic_children;    then render_epic_children;    exit 0
elif is_story_tasks;      then render_story_tasks;      exit 0
elif is_overall_progress; then render_overall;          exit 0
elif is_epic_overview;    then render_epic_overview;    exit 0
else
  echo "Unrecognized gpt-creator output. Pipe one of:
  - estimate
  - backlog --progress
  - backlog --item-children <EPIC|story-slug>
  - START/END task blocks from logs" >&2
  exit 2
fi
