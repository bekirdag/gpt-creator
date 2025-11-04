#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
HELP_DIR="${ROOT_DIR}/assets/templates/help"
PLACEHOLDER_TEMPLATE_DIR="${ROOT_DIR}/assets/templates/doc_placeholders"
GC_WORK_DIR_NAME="${GC_WORK_DIR_NAME:-.gpt-creator}"

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root="${2:-${ROOT_DIR}}"
  local source_path="${ROOT_DIR}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    echo "Python helper missing at ${source_path}" >&2
    return 1
  fi
  local target_dir="${root%/}/${GC_WORK_DIR_NAME:-.gpt-creator}/shims/python"
  local target_path="${target_dir}/${script_name}"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || { echo "Failed to create ${target_dir}" >&2; return 1; }
  fi
  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || { echo "Failed to copy ${script_name}" >&2; return 1; }
  fi
  printf '%s\n' "$target_path"
}

usage() {
  local usage_file="${HELP_DIR}/create_doc_placeholder_usage.txt"
  if [[ -f "$usage_file" ]]; then
    cat "$usage_file" >&2
  else
    printf '%s\n' \
      "Usage: create-doc-placeholder.sh <path> --owner \"Owner\" [--summary \"Summary\"] [--date YYYY-MM-DD]" \
      "" \
      "Creates a minimal placeholder file for the referenced documentation path." >&2
  fi
  exit 2
}

if [[ $# -lt 1 ]]; then
  usage
fi

owner=""
summary=""
override_date=""
path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner)
      owner="${2:-}"
      shift 2
      ;;
    --summary)
      summary="${2:-}"
      shift 2
      ;;
    --date)
      override_date="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      ;;
    *)
      if [[ -z "$path" ]]; then
        path="$1"
      else
        echo "Only one path may be specified." >&2
        usage
      fi
      shift
      ;;
  esac
done

if [[ -z "$path" ]]; then
  echo "Placeholder path is required." >&2
  usage
fi

if [[ -z "$owner" ]]; then
  echo "--owner is required." >&2
  usage
fi

if [[ -z "$override_date" ]]; then
  timestamp=$(date -u +%Y-%m-%d)
else
  timestamp="$override_date"
fi

abs_path="$path"
mkdir -p "$(dirname "$abs_path")"

if [[ -f "$abs_path" ]]; then
  echo "[info] File already exists: $abs_path" >&2
  exit 0
fi

base_name=$(basename "$abs_path")
summary_text="$summary"
if [[ -z "$summary_text" ]]; then
  summary_text="Populate ${base_name} with project-specific details."
fi

extension="${abs_path##*.}"
if [[ "$abs_path" == "$extension" ]]; then
  extension=""
fi
extension="${extension,,}"

template_file=""
template_format="text"
case "$extension" in
  md|mdx)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/markdown.md.tmpl"
    template_format="markdown"
    ;;
  txt|log|mdown|markdown|"")
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/text.txt.tmpl"
    ;;
  csv)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/data.csv.tmpl"
    template_format="csv"
    ;;
  json|ndjson|jsonl)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/data.json.tmpl"
    template_format="json"
    ;;
  sql)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/data.sql.tmpl"
    template_format="sql"
    ;;
  ics)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/event.ics.tmpl"
    template_format="ics"
    ;;
  *)
    template_file="${PLACEHOLDER_TEMPLATE_DIR}/default.txt.tmpl"
    ;;
esac

if [[ ! -f "$template_file" ]]; then
  echo "Template missing for extension '${extension}' (expected at ${template_file})" >&2
  exit 1
fi

helper_path="$(gc_clone_python_tool "render_doc_placeholder.py" "$ROOT_DIR")"
if [[ -z "$helper_path" ]]; then
  echo "Failed to prepare render_doc_placeholder helper." >&2
  exit 1
fi

python3 "$helper_path" \
  --template "$template_file" \
  --format "$template_format" \
  --owner "$owner" \
  --timestamp "$timestamp" \
  --summary "$summary_text" \
  --path "$abs_path" \
  --base-name "$base_name" \
  --output "$abs_path"

printf '[ok] Created placeholder %s\n' "$abs_path" >&2
