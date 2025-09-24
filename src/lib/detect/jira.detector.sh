#!/usr/bin/env bash
# jira.detector.sh — detect Jira-related files (task trackers)
# Searches for files related to Jira tasks or tickets.
if [[ -n "${GC_LIB_JIRA_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_JIRA_DETECTOR_SH=1

detect_jira() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (jira|tasks?) && "$file" =~ .*\.(md|csv|xlsx?)$ ]]; then
    echo "Jira detected: $file"
  fi
}

# Usage: detect_jira "/path/to/file.md"
