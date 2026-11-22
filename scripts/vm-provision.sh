#!/usr/bin/env bash
# Provision a Linux guest for callgrind: valgrind, graphviz, gprof2dot and
# the Rust toolchain pinned in rust-toolchain.toml. Run inside the guest.
set -euo pipefail
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential pkg-config curl valgrind graphviz python3-venv >/dev/null
[ -x "$HOME/.venv-prof/bin/gprof2dot" ] || {
  python3 -m venv "$HOME/.venv-prof"
  "$HOME/.venv-prof/bin/pip" install -q "gprof2dot==${GPROF2DOT_VERSION:-2025.4.14}"
}
if ! command -v rustup >/dev/null; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain none >/dev/null
fi
. "$HOME/.cargo/env"
cd "$(dirname "$0")/.."
rustup install >/dev/null 2>&1   # the toolchain pinned in rust-toolchain.toml
valgrind --version
rustc --version
"$HOME/.venv-prof/bin/pip" show gprof2dot | grep -E '^(Name|Version)'
dot -V
