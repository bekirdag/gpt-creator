#!/usr/bin/env bash
# csshtml.detector.sh — detect general CSS/HTML files
# Detects generic HTML/CSS files that are part of UI or content.
if [[ -n "${GC_LIB_CSSHTML_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_CSSHTML_DETECTOR_SH=1

detect_csshtml() {
  local file="$1"
  if [[ -f "$file" && ( "$file" =~ .*\.(html|css)$ ) ]]; then
    echo "CSS/HTML detected: $file"
  fi
}

# Usage: detect_csshtml "/path/to/file.html"
