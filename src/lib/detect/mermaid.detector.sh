#!/usr/bin/env bash
# mermaid.detector.sh — detect Mermaid diagrams (workflow, ERD)
# Detects `.mmd` files commonly used for Mermaid diagrams for visual flow representations.
if [[ -n "${GC_LIB_MERMAID_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_MERMAID_DETECTOR_SH=1

detect_mermaid() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ \.mmd$ ]]; then
    echo "Mermaid diagram detected: $file"
  fi
}

# Usage: detect_mermaid "/path/to/file.mmd"
