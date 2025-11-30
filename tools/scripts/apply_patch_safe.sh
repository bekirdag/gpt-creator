#!/usr/bin/env bash
# Robust unified-diff applier that tolerates markdown wrapping, wrong -p levels, and small context drift.
# Usage: scripts/apply_patch_safe.sh /path/to/file.patch [repo_root]

set -Eeuo pipefail
PATCH_FILE="${1:?patch file required}"
REPO_ROOT="${2:-"$(git rev-parse --show-toplevel 2>/dev/null || pwd)"}"

cd "$REPO_ROOT"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "apply_patch_safe: patch not found: $PATCH_FILE" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
cleanup() { rm -rf "$tmp_dir"; }
trap cleanup EXIT INT TERM

# Normalize line endings, drop code fences/markdown noise.
sed -e 's/\r$//' -e '/^```/d' -e '/^---$/d' "$PATCH_FILE" >"$tmp_dir/patch0"

# Extract diff payload (prefer diff --git blocks).
awk 'BEGIN{on=0}
     /^diff --git /{on=1}
     on{print}' "$tmp_dir/patch0" >"$tmp_dir/patch.diff"

if ! grep -q '^diff --git ' "$tmp_dir/patch.diff"; then
  awk 'BEGIN{on=0}
       /^--- [ab]\//{on=1}
       on{print}' "$tmp_dir/patch0" >"$tmp_dir/patch.diff"
fi

if ! grep -Eq '^(diff --git |--- [ab]/|\+\+\+ [ab]/|@@ )' "$tmp_dir/patch.diff"; then
  echo "apply_patch_safe: no unified diff content found in $PATCH_FILE" >&2
  exit 2
fi

# Relax whitespace enforcement to keep diffs smooth.
git config --local -f .git/config apply.whitespace fix >/dev/null 2>&1 || true

try_apply() {
  local strip="$1" mode="$2"
  if [[ "$mode" == "merge" ]]; then
    git apply --index --3way --whitespace=fix -p"$strip" "$tmp_dir/patch.diff"
  else
    git apply --reject --whitespace=fix -p"$strip" "$tmp_dir/patch.diff"
  fi
}

# Attempt matrix: 3-way first, then rejects; strip components 1,0,2.
for s in 1 0 2; do
  if try_apply "$s" merge; then
    exit 0
  fi
done

for s in 1 0 2; do
  if try_apply "$s" reject; then
    echo "apply_patch_safe: applied with rejects (check *.rej)" >&2
    exit 0
  fi
done

echo "apply_patch_safe: failed to apply $PATCH_FILE" >&2
exit 1
