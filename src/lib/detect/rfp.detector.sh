#!/usr/bin/env bash
# rfp.detector.sh — detect RFP-related files (Request for Proposal)
# Looks for RFP terms in filenames/content to identify RFP documents.
if [[ -n "${GC_LIB_RFP_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_RFP_DETECTOR_SH=1

detect_rfp() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (rfp|request.*for.*proposal) && "$file" =~ .*\.(md|docx?|pdf)$ ]]; then
    echo "RFP detected: $file"
  fi
}

# Usage: detect_rfp "/path/to/file.md"
