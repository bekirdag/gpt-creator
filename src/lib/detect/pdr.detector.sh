#!/usr/bin/env bash
# pdr.detector.sh — detect PDR-related files (Product Design Requirements)
# Look for keywords in filenames/content to identify PDR documents.
if [[ -n "${GC_LIB_PDR_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_PDR_DETECTOR_SH=1

detect_pdr() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (pdr|product.*design.*requirement) && "$file" =~ .*\.(md|docx?|pdf)$ ]]; then
    echo "PDR detected: $file"
  fi
}

# Usage: detect_pdr "/path/to/file.md"
