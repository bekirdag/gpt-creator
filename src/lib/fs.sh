#!/usr/bin/env bash
# shellcheck shell=bash
# gpt-creator lib/fs.sh — filesystem utilities (POSIX-friendly, macOS-aware)
# Safe to source multiple times.
if [[ -n "${GC_LIB_FS_SH:-}" ]]; then return 0; fi
GC_LIB_FS_SH=1

# ---- Guards & defaults -------------------------------------------------------
: "${GC_TRACE:=0}"

_fs_trace() { [[ "${GC_TRACE}" == "1" ]] && printf '[fs] %s\n' "$*" >&2 || true; }

# ---- Predicates --------------------------------------------------------------
fs_is_file()    { [[ -f "$1" ]]; }
fs_is_dir()     { [[ -d "$1" ]]; }
fs_is_link()    { [[ -L "$1" ]]; }
fs_exists()     { [[ -e "$1" ]]; }

# ---- Ensure / mkdir -p with sane perms --------------------------------------
fs_ensure_dir() {
  # Usage: fs_ensure_dir <dir> [mode]
  local dir="$1" mode="${2:-}"
  [[ -z "${dir}" ]] && { echo "fs_ensure_dir: dir required" >&2; return 2; }
  if [[ -n "${mode}" ]]; then
    mkdir -p -m "${mode}" -- "${dir}"
  else
    mkdir -p -- "${dir}"
  fi
  [[ -d "${dir}" ]]
}

# ---- Temp helpers ------------------------------------------------------------
fs_tmpdir()  { mktemp -d 2>/dev/null || mktemp -dt gpt-creator; }
fs_tmpfile() { mktemp 2>/dev/null || mktemp -t gpt-creator; }

# ---- Atomic write (reads from STDIN) ----------------------------------------
fs_atomic_write() {
  # Usage: cmd | fs_atomic_write <dest> [mode]
  local dest="$1" mode="${2:-}"
  [[ -z "${dest}" ]] && { echo "fs_atomic_write: dest required" >&2; return 2; }
  local dir; dir="$(dirname -- "${dest}")"
  fs_ensure_dir "${dir}" || return 1
  local tmp; tmp="$(fs_tmpfile)" || return 1
  # Write stdin to tmp
  cat > "${tmp}" || { rm -f -- "${tmp}"; return 1; }
  # Set permissions if asked
  if [[ -n "${mode}" ]]; then chmod "${mode}" -- "${tmp}"; fi
  # Move over (same FS) to be atomic
  mv -f -- "${tmp}" "${dest}"
  _fs_trace "atomic write → ${dest}"
}

# ---- Write/append text -------------------------------------------------------
fs_write_text() {
  # Usage: fs_write_text <dest> "<text>" [mode]
  local dest="$1" text="${2-}" mode="${3:-}"
  [[ -z "${dest}" ]] && { echo "fs_write_text: dest required" >&2; return 2; }
  printf '%s' "${text}" | fs_atomic_write "${dest}" "${mode}"
}

fs_append_text() {
  # Usage: fs_append_text <dest> "<text>"
  local dest="$1" text="${2-}"
  [[ -z "${dest}" ]] && { echo "fs_append_text: dest required" >&2; return 2; }
  fs_ensure_dir "$(dirname -- "${dest}")" || return 1
  printf '%s' "${text}" >> "${dest}"
}

# ---- Read file to stdout -----------------------------------------------------
fs_read_file() {
  # Usage: fs_read_file <path>
  [[ -f "$1" ]] || { echo "fs_read_file: not a file: $1" >&2; return 2; }
  cat -- "$1"
}

# ---- Copy / Move -------------------------------------------------------------
fs_copy() {
  # Usage: fs_copy <src> <dest>
  local src="$1" dest="$2"
  [[ -z "${src}" || -z "${dest}" ]] && { echo "fs_copy: src and dest required" >&2; return 2; }
  fs_ensure_dir "$(dirname -- "${dest}")" || return 1
  # Preserve attrs where possible; fall back to cp -R
  if command -v rsync >/dev/null 2>&1; then
    rsync -a -- "${src}" "${dest}"
  else
    cp -R -- "${src}" "${dest}"
  fi
}

fs_move() {
  # Usage: fs_move <src> <dest>
  local src="$1" dest="$2"
  [[ -z "${src}" || -z "${dest}" ]] && { echo "fs_move: src and dest required" >&2; return 2; }
  fs_ensure_dir "$(dirname -- "${dest}")" || return 1
  mv -f -- "${src}" "${dest}"
}

# ---- Safe remove -------------------------------------------------------------
fs_rm() {
  # Usage: fs_rm <path...>
  # Protect against catastrophic deletes (/, ~, empty).
  for p in "$@"; do
    [[ -z "${p}" ]] && { echo "fs_rm: empty path blocked" >&2; return 2; }
    case "${p}" in
      "/"|"/root"|"/home"|"/Users"|~) echo "fs_rm: dangerous path blocked: ${p}" >&2; return 2;;
    esac
  done
  rm -rf -- "$@"
}

# ---- Replace in file (portable sed -i) --------------------------------------
fs_replace_in_file() {
  # Usage: fs_replace_in_file <file> <sed-expr>
  # Example: fs_replace_in_file file 's/foo/bar/g'
  local file="$1" expr="$2"
  [[ -f "${file}" ]] || { echo "fs_replace_in_file: not found: ${file}" >&2; return 2; }
  [[ -z "${expr}" ]] && { echo "fs_replace_in_file: sed expr required" >&2; return 2; }
  # macOS/BSD sed needs a suffix; GNU sed accepts both. Use .bak then rm.
  sed -i.bak -e "${expr}" -- "${file}" && rm -f -- "${file}.bak"
}

# ---- Checksums ---------------------------------------------------------------
fs_sha256() {
  # Usage: fs_sha256 <file>
  local f="$1"
  [[ -f "${f}" ]] || { echo "fs_sha256: not a file: ${f}" >&2; return 2; }
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "${f}" | awk '{print $1}'
  else
    # macOS
    shasum -a 256 -- "${f}" | awk '{print $1}'
  fi
}

# ---- Permissions -------------------------------------------------------------
fs_executable() {
  # Usage: fs_executable <path>
  chmod +x -- "$1"
}

# ---- Normalize line endings & strip BOM -------------------------------------
fs_strip_bom() {
  # Usage: fs_strip_bom <file>
  local f="$1"
  [[ -f "${f}" ]] || { echo "fs_strip_bom: not a file: ${f}" >&2; return 2; }
  # Remove UTF-8 BOM if present
  if head -c 3 -- "${f}" | od -An -t x1 | grep -qi 'ef bb bf'; then
    tail -c +4 -- "${f}" > "${f}.nobom" && mv -f -- "${f}.nobom" "${f}"
  fi
}

fs_unixify() {
  # Usage: fs_unixify <file>  (CRLF→LF)
  local f="$1"
  [[ -f "${f}" ]] || { echo "fs_unixify: not a file: ${f}" >&2; return 2; }
  # sed solution avoids depending on dos2unix
  sed -i.bak -e 's/\r$//' -- "${f}" && rm -f -- "${f}.bak"
}

# ---- Simple lock (flock if available; else directory lock) ------------------
fs_with_lock() {
  # Usage: fs_with_lock <lockfile> <command...>
  local lock="$1"; shift || true
  [[ -z "${lock}" ]] && { echo "fs_with_lock: lockfile required" >&2; return 2; }
  fs_ensure_dir "$(dirname -- "${lock}")" || return 1

  if command -v flock >/dev/null 2>&1; then
    flock --timeout 30 "${lock}" "$@"
    return $?
  fi

  # Poor-man's lock: mkdir succeeds atomically
  local dir="${lock}.d"
  local acquired=0
  for _ in {1..30}; do
    if mkdir "${dir}" 2>/dev/null; then acquired=1; break; fi
    sleep 1
  done
  if [[ "${acquired}" -ne 1 ]]; then
    echo "fs_with_lock: failed to acquire lock ${lock}" >&2
    return 1
  fi
  trap 'rmdir "${dir}" >/dev/null 2>&1 || true' EXIT
  "$@"
  local rc=$?
  rmdir "${dir}" >/dev/null 2>&1 || true
  trap - EXIT
  return "${rc}"
}

# ---- Directory emptiness -----------------------------------------------------
fs_is_empty_dir() {
  # Usage: fs_is_empty_dir <dir>
  local d="$1"
  [[ -d "${d}" ]] || return 1
  [[ -z "$(ls -A "${d}")" ]]
}

return 0
