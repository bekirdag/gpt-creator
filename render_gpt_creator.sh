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
  rep "$fill" "█"
  reset
  rep "$empty" "─"
  printf "] %s%5.1f%%%s" "$(fg "$col")" "$pct" "$(reset)"
}

status_color() {
  case "$(tr '[:upper:]' '[:lower:]' <<<"${1:-}")" in
    pending)      fg 245 ;;
    in-progress)  fg 220 ;;
    complete|completed|done) fg 46 ;;
    *)            fg 251 ;;
  esac
}

badge() { # fancy rounded badge
  local label="$1" col="$2"
  printf "%s%s%s%s%s" "$(fg 240)" "$(fg "$col")" "$(c 1)" " $label " "$(reset)"
}

lc(){ c "1;38;5;${1}"; }

numclean(){ tr -d ', ' <<<"$1"; }

# ============================ Read stdin ============================
INPUT="$(cat)"

# ============================ Detectors ============================
is_estimate()         { grep -q '^Remaining Work Summary' <<<"$INPUT"; }
is_epic_children()    { grep -qE '^Stories for epic:' <<<"$INPUT"; }
is_story_tasks()      { grep -qE '^Tasks for story:' <<<"$INPUT"; }
is_overall_progress() { grep -qiE '^Overall backlog progress' <<<"$INPUT"; }
is_epic_overview()    { grep -qE '^Epic ID[[:space:]]+Slug|^┌' <<<"$INPUT"; }
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

  printf "\n%s╭────────────────────────────────────────────────────────────╮%s\n" "$(c "1;38;5;214")" "$(reset)"
  printf "│  %sGPT-Creator :: Project Estimate Summary%s                │\n" "$(c "1;38;5;39")" "$(reset)"
  printf "%s╰────────────────────────────────────────────────────────────╯%s\n" "$(c "1;38;5;214")" "$(reset)"

  printf "  "; badge "TOTAL ${total:-N/A}" 39; printf "  "
  badge "DONE ${comp_eff:-N/A}" 46; printf "  "
  badge "REMAIN ${rem_can:-N/A}" 208; printf "  "
  [[ -n "$eta" ]] && { badge "ETA ${eta}" 111; printf "  "; }
  [[ -n "$rem_sp" ]] && badge "SP ${rem_sp}" 201
  printf "\n\n"

  printf "  %sProgress%s\n" "$(lc 111)" "$(reset)"
  printf "  "
  bar "$progress_pct" 40
  printf "  %s%s%% complete%s\n\n" "$(c "1;38;5;82")" "$progress_pct" "$(reset)"

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

  printf "\n%s╭──────────────────────────────────────────────────────────────╮%s\n" "$(c 1';38;5;214')" "$(reset)"
  printf "│  %sStories for Epic: %s%s │\n" "$(c 1';38;5;39')" "$header" "$(reset)"
  printf "%s╰──────────────────────────────────────────────────────────────╯%s\n" "$(c 1';38;5;214')" "$(reset)"

  local migration_line
  migration_line="$(grep -m1 'Carried forward migration state' <<<"$INPUT" || true)"
  [[ -n "$migration_line" ]] && printf "%s\n" "$migration_line"
  printf "\n%s📘 Story Breakdown%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  printf "%s%-14s %-58s %-13s %-8s %-30s %-s%s\n" "$(c 1';90')" "Story Slug" "Title" "Status" "Epic" "Tasks" "Progress" "$(reset)"
  printf "%s%-14s %-58s %-13s %-8s %-30s %-s%s\n" "$(c 1';90')" "────────────" "────────────────────────────────────────────" "───────────" "──────" "──────────────────────────────" "────────" "$(reset)"

  awk -F'  +' '
    BEGIN{ show=0 }
    /^Story Slug[[:space:]]/ { show=1; next }
    show && NF>=6 {
      slug=$1; title=$2; status=$3; epic=$4; tasks=$5; progress=$6;
      gsub(/^[ \t]+|[ \t]+$/,"",slug); gsub(/^[ \t]+|[ \t]+$/,"",title);
      gsub(/^[ \t]+|[ \t]+$/,"",status); gsub(/^[ \t]+|[ \t]+$/,"",epic);
      gsub(/^[ \t]+|[ \t]+$/,"",tasks); gsub(/^[ \t]+|[ \t]+$/,"",progress);
      printf("%s\t%s\t%s\t%s\t%s\n", slug,title,status,epic,progress"|"tasks);
    }' <<<"$INPUT" | while IFS=$'\t' read -r slug title status epic progress_tasks; do
      tasks="${progress_tasks#*|}"
      progress="${progress_tasks%%|*}"
      pct="${progress%%%}"
      printf "%s%-14s%s %-58s " "$(c 1';37')" "$slug" "$(reset)" "$title"
      sc=$(status_color "$status")
      printf "%s%-13s%s " "$sc" "$status" "$(reset)"
      printf "%-8s %-30s " "$epic" "$tasks"
      bar "${pct:-0}" 22
      printf "\n"
    done

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

  printf "\n%s╭──────────────────────────────────────────────────────────────╮%s\n" "$(c 1';38;5;214')" "$(reset)"
  printf "│  %sTasks for Story: %s%s │\n" "$(c 1';38;5;39')" "$header" "$(reset)"
  printf "%s╰──────────────────────────────────────────────────────────────╯%s\n" "$(c 1';38;5;214')" "$(reset)"

  local migration_line
  migration_line="$(grep -m1 'Carried forward migration state' <<<"$INPUT" || true)"
  [[ -n "$migration_line" ]] && printf "%s\n" "$migration_line"
  printf "\n%s🧩 Task Breakdown%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  printf "%s%-4s %-6s %-12s %-66s %-10s %-4s %-s%s\n" "$(c 1';90')" "#" "Order" "Task ID" "Title" "Status" "SP" "Weight" "$(reset)"
  printf "%s%-4s %-6s %-12s %-66s %-10s %-4s %-s%s\n" "$(c 1';90')" "─" "─────" "────────────" "───────────────────────────────────────────────" "───────" "──" "────────────" "$(reset)"

  awk -F'  +' '
    BEGIN{ show=0 }
    /^#  Order[[:space:]]/ { show=1; next }
    show && $1 ~ /^[0-9-]+$/ && NF>=6 {
      idx=$1; order=$2; id=$3; status=$(NF-1); sp=$NF;
      title=$4; for(i=5;i<=NF-2;i++){ title=title " " $i }
      gsub(/^[ \t]+|[ \t]+$/,"",title);
      printf("%s\t%s\t%s\t%s\t%s\t%s\n", idx,order,id,title,status,sp);
    }' <<<"$INPUT" | while IFS=$'\t' read -r idx order id title status sp; do
      sc=$(status_color "$status")
      pct=$(awk -v s="${sp:-0}" 'BEGIN{ if(s<0)s=0; if(s>13)s=13; printf "%.1f", (s/13.0)*100 }')
      printf "%s%-4s%s %-6s %-12s %-66s %s%-10s%s %-4s " \
        "$(c 1';36')" "$idx" "$(reset)" "$order" "$id" "$title" "$sc" "$status" "$(reset)" "$sp"
      bar "$pct" 18
      printf "\n"
    done

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

  printf "\n%s╭──────────────────────────────────────────────────────────────╮%s\n" "$(c 1';38;5;214')" "$(reset)"
  printf "│  %sOverall Backlog Progress%s                                 │\n" "$(c 1';38;5;39')" "$(reset)"
  printf "%s╰──────────────────────────────────────────────────────────────╯%s\n" "$(c 1';38;5;214')" "$(reset)"

  local migration_line
  migration_line="$(grep -m1 'Carried forward migration state' <<<"$INPUT" || true)"
  [[ -n "$migration_line" ]] && printf "%s\n" "$migration_line"
  printf "\n%s📊 Backlog Summary%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  sed -n \
    -e 's/^Completed tasks (canonical): /• Completed tasks (canonical):   /p' \
    -e 's/^Completed tasks (effective): /• Completed tasks (effective):   /p' \
    -e 's/^In-progress (effective): /• In-progress (effective):       /p' \
    -e 's/^Pending (effective): /• Pending (effective):           /p' \
    -e 's/^Remaining (canonical): /• Remaining (canonical):         /p' \
    -e 's/^Total tasks: /• Total tasks:                   /p' \
    <<<"$INPUT"
  printf "\n%s📈 Visual Progress%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"
  bar "$pct" 30
  printf "  %sComplete%s\n\n" "$(c 1';32')" "$(reset)"

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

  printf "\n%s╭────────────────────────────────────────────────────────────╮%s\n" "$(c 1';38;5;214')" "$(reset)"
  printf "│  %sSTART OF TASK%s                                             │\n" "$(c 1';38;5;39')" "$(reset)"
  printf "%s╰────────────────────────────────────────────────────────────╯%s\n" "$(c 1';38;5;214')" "$(reset)"

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

  printf "\n%s╭────────────────────────────────────────────────────────────╮%s\n" "$(c 1';38;5;214')" "$(reset)"
  printf "│  %sEND OF TASK%s                                               │\n" "$(c 1';38;5;39')" "$(reset)"
  printf "%s╰────────────────────────────────────────────────────────────╯%s\n" "$(c 1';38;5;214')" "$(reset)"

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
  printf "\n%s╭────────────────────────────────────────────────────────────╮%s\n" "$(c "1;38;5;214")" "$(reset)"
  printf "│  %sGPT-Creator :: Backlog Summary (%s)%s     │\n" "$(c "1;38;5;39")" "$project_display" "$(reset)"
  printf "%s╰────────────────────────────────────────────────────────────╯%s\n" "$(c "1;38;5;214")" "$(reset)"

  local migration_line
  migration_line="$(grep -m1 'Carried forward migration state' <<<"$INPUT" || true)"
  [[ -n "$migration_line" ]] && printf "%s\n" "$migration_line"

  printf "\n%s📋 Epic Progress Overview%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────────────────────\n"

  local ascii_table data_rows
  ascii_table="$(awk '
    /^[[:space:]]*┌/ {capture=1}
    capture {
      print
      if ($0 ~ /┘[[:space:]]*$/) exit
    }
  ' <<<"$INPUT")"

  if [[ -n "$ascii_table" ]]; then
    printf "%s\n\n" "$ascii_table"
    data_rows="$(printf "%s\n" "$ascii_table" | awk -F'│' '
      function trim(s){ sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
      /^[[:space:]]*┌/ {next}
      /^[[:space:]]*├/ {next}
      /^[[:space:]]*└/ {exit}
      /^[[:space:]]*│/ {
        epic=trim($2); title=trim($3); stories=trim($4); tasks=trim($5); progress=trim($6);
        if (epic == "" || epic == "EPIC") next
        printf "%s\t%s\t%s\t%s\t%s\n", epic, title, stories, tasks, progress
      }
    ')"
  else
    local table_block
    table_block="$(awk '
      BEGIN{flag=0}
      /^Epic ID[[:space:]]/ {flag=1; next}
      flag {
        if ($0 ~ /^$/) { exit }
        print
      }
    ' <<<"$INPUT")"
    printf "%s\n\n" "$table_block"
    data_rows="$(printf "%s" "$table_block" | awk -F'  +' '
      function trim(s){ sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
      NF >= 6 {
        epic=trim($1); title=trim($3); stories=trim($4); tasks=trim($5); prog=trim($6);
        if (epic ~ /^-+$/) next
        printf "%s\t%s\t%s\t%s\t%s\n", epic, title, stories, tasks, prog
      }
    ')"
  fi

  local total_epics=0 high=0 mid=0 low=0
  if [[ -n "$data_rows" ]]; then
    while IFS=$'\t' read -r epic title stories tasks progress; do
      [[ -z "$epic" ]] && continue
      ((total_epics++))
      local pct
      pct="$(printf '%s' "$progress" | tr -cd '0-9.')"
      [[ -z "$pct" ]] && pct="0"
      if (( $(awk "BEGIN {print ($pct >= 70)}") )); then
        ((high++))
      elif (( $(awk "BEGIN {print ($pct >= 30)}") )); then
        ((mid++))
      else
        ((low++))
      fi
    done <<<"$data_rows"
  fi

  printf "%s📈 Overall Trend%s\n" "$(lc 111)" "$(reset)"
  printf "──────────────────────────────────────────────\n"
  printf "• %d epics at ≥70%% completion\n" "$high"
  printf "• %d epics between 30-69%%\n" "$mid"
  printf "• %d epics below 30%% or pending\n\n" "$low"

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
