#!/usr/bin/env bash
# Clone every upstream into repos/ at the commit pinned in scripts/pins.tsv.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p repos
grep -v '^#' scripts/pins.tsv | while IFS=$'\t' read -r name url commit _; do
  if [ ! -d "repos/$name/.git" ]; then
    git clone -q "$url" "repos/$name"
  fi
  git -C "repos/$name" fetch -q origin "$commit" 2>/dev/null || true
  git -C "repos/$name" checkout -q --detach "$commit"
  actual=$(git -C "repos/$name" rev-parse HEAD)
  [ "$actual" = "$commit" ] || { echo "pin mismatch: $name $actual != $commit" >&2; exit 1; }
  echo "$name $commit"
done
