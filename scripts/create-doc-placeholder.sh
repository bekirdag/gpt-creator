#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE' >&2
Usage: create-doc-placeholder.sh <path> --owner "Owner" [--summary "Summary"] [--date YYYY-MM-DD]

Creates a minimal placeholder file for the referenced documentation path.
USAGE
  exit 2
}

if [[ $# -lt 1 ]]; then
  usage
fi

owner=""
summary=""
override_date=""

path=""

escape_json() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  printf '%s' "$value"
}

escape_csv() {
  local value="$1"
  value="${value//\"/\"\"}"
  printf '%s' "$value"
}

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

summary_text="$summary"
if [[ -z "$summary_text" ]]; then
  base_name=$(basename "$path")
  summary_text="Populate ${base_name} with project-specific details."
fi

abs_path="$path"
mkdir -p "$(dirname "$abs_path")"

if [[ -f "$abs_path" ]]; then
  echo "[info] File already exists: $abs_path" >&2
  exit 0
fi

extension="${abs_path##*.}"
base_name=$(basename "$abs_path")

case "$extension" in
  md|mdx)
    cat <<EOF >"$abs_path"
# Placeholder: ${summary_text}

- Owner: ${owner}
- Last Updated: ${timestamp}
- TODO: ${summary_text}
EOF
    ;;
  txt|log|mdown|markdown)
    cat <<EOF >"$abs_path"
Owner: ${owner}
Date: ${timestamp}
TODO: ${summary_text}
EOF
    ;;
  csv)
    owner_csv=$(escape_csv "$owner")
    summary_csv=$(escape_csv "$summary_text")
    cat <<EOF >"$abs_path"
owner,date,summary,todo
"${owner_csv}","${timestamp}","${summary_csv}","Replace this placeholder with final content"
EOF
    ;;
  json|ndjson|jsonl)
    owner_json=$(escape_json "$owner")
    summary_json=$(escape_json "$summary_text")
    path_json=$(escape_json "$path")
    cat <<EOF >"$abs_path"
{
  "owner": "${owner_json}",
  "last_updated": "${timestamp}",
  "summary": "${summary_json}",
  "todo": "Replace this placeholder with final content",
  "path": "${path_json}"
}
EOF
    ;;
  sql)
    cat <<EOF >"$abs_path"
-- Owner: ${owner}
-- Last Updated: ${timestamp}
-- TODO: ${summary_text}
EOF
    ;;
  ics)
    summary_line=${summary_text//$'\n'/ }
    cat <<EOF >"$abs_path"
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//gpt-creator//Doc Placeholder//EN
BEGIN:VEVENT
UID:${base_name}-placeholder
DTSTAMP:${timestamp//-/}T000000Z
SUMMARY:${summary_line}
DESCRIPTION:Owner ${owner}; replace placeholder with real event details.
END:VEVENT
END:VCALENDAR
EOF
    ;;
  *)
    cat <<EOF >"$abs_path"
Owner: ${owner}
Date: ${timestamp}
TODO: ${summary_text}
EOF
    ;;
esac

printf '[ok] Created placeholder %s\n' "$abs_path" >&2
