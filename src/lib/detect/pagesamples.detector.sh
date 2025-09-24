#!/usr/bin/env bash
# pagesamples.detector.sh — detect page sample files (HTML, CSS)
# Looks for page sample files (HTML, CSS) in specific folders or filenames.
if [[ -n "${GC_LIB_PAGESAMPLES_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_PAGESAMPLES_DETECTOR_SH=1

detect_pagesamples() {
  local file="$1"
  if [[ -f "$file" && ( "$file" =~ .*\.(html|css)$ ) && "$file" =~ page_samples/ ]]; then
    echo "Page sample detected: $file"
  fi
}

# Usage: detect_pagesamples "/path/to/file.html"
