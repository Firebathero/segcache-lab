#!/usr/bin/env bash
# The three builds profiled in notes/stop-2-hot-paths.md. Run inside the guest.
set -euo pipefail
cd "$(dirname "$0")"
LABEL=lse RUSTFLAGS="-C target-feature=+lse" ./cachegrind.sh
LABEL=linux-default ./cachegrind.sh
LABEL=lse-no-metrics RUSTFLAGS="-C target-feature=+lse" FEATURES=--no-default-features ./cachegrind.sh
