#!/usr/bin/env bash
# sds.detector.sh — detect SDS-related files (System Design Specifications)
# Search for SDS in filenames/content to identify System Design Specifications.
if [[ -n "${GC_LIB_SDS_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_SDS_DETECTOR_SH=1

detect_sds() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (sds|system.*design.*specification) && "$file" =~ .*\.(md|docx?|pdf)$ ]]; then
    echo "SDS detected: $file"
  fi
}

# Usage: detect_sds "/path/to/file.md"
