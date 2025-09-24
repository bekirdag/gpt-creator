#!/usr/bin/env bash
# pages.parse.sh — parse UI pages specifications and sample HTML files (extract metadata, routes, sections)

if [[ -n "${GC_LIB_PAGES_PARSE_SH:-}" ]]; then return 0; fi
GC_LIB_PAGES_PARSE_SH=1

# Parse pages.md to extract pages, routes, and relevant sections (used for documentation)
parse_pages_spec() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_pages_spec: file not found: $file" >&2; return 2; }
  awk '/^# / {print $0}' "$file" | sed 's/# //g'  # Simple page section extraction
}

# Parse HTML sample files (extract basic metadata like title, headings, links)
parse_html() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_html: file not found: $file" >&2; return 2; }
  grep -oP '<h[1-6][^>]*>(.*?)</h[1-6]>' "$file" | sed 's/<[^>]*>//g'
}

# Usage: parse_pages_spec "page_samples/website_pages.md"
# Usage: parse_html "page_samples/website_pages/HOM1.html"
