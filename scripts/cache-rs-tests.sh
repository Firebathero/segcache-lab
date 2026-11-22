#!/usr/bin/env bash
# Run cache-rs's own segcache suites in a checkout: unit and integration
# tests, the same with the debug feature, and the shuttle concurrency models.
#   scripts/cache-rs-tests.sh repos/cache-rs-<name> <out-dir>
# Writes <out-dir>/<suite>.log and prints each suite's result lines.
set -uo pipefail
cd "$(dirname "$0")/.."
src=$1; out=$2
mkdir -p "$out"
# One shared target directory without debug info keeps disk use down.
export CARGO_TARGET_DIR="$PWD/repos/target-tests" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
run() {
  local name=$1; shift
  (cd "$src" && cargo test -q -p segcache "$@") > "$out/$name.log" 2>&1
  echo "$name exit=$? $(grep -E '^test result:' "$out/$name.log" | awk '{p+=$4; f+=$6; i+=$8} END {print "passed=" p, "failed=" f, "ignored=" i}')"
}
run default
run debug --features debug
run shuttle --features shuttle -- shuttle_
