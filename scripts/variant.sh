#!/usr/bin/env bash
# Build the harness against cache-rs at the pinned commit plus patches.
#   scripts/variant.sh <name> [patch ...]
# The checkout is a git worktree at repos/cache-rs-<name>, reset to the pin
# and patched afresh on every call. Binaries land in
# harness/target/variants/<name>/release/. Extra cargo flags can be passed in
# CARGO_FLAGS (for example --features vclock).
set -euo pipefail
cd "$(dirname "$0")/.."
name=$1; shift
pin=$(awk -F'\t' '$1 == "cache-rs" {print $3}' scripts/pins.tsv)
wt="repos/cache-rs-$name"
[ -d "$wt" ] || git -C repos/cache-rs worktree add -q --detach "../cache-rs-$name" "$pin"
git -C "$wt" reset -q --hard "$pin"
for patch in "$@"; do git -C "$wt" apply "$PWD/$patch"; done
dir="harness/variants/$name"
mkdir -p "$dir"
sed "s#\.\./repos/cache-rs/#../../../repos/cache-rs-$name/#" harness/Cargo.toml > "$dir/Cargo.toml"
cp harness/Cargo.lock "$dir/Cargo.lock"
ln -sfn ../../src "$dir/src"
(cd "$dir" && CARGO_TARGET_DIR="$PWD/../../target/variants/$name" cargo build -q --release ${CARGO_FLAGS:-})
echo "harness/target/variants/$name/release"
