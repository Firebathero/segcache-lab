#!/usr/bin/env bash
# Exact per-operation costs of the engine, by function and by source line.
# Run inside a Linux guest provisioned by scripts/vm-provision.sh.
#
# Each operation type is profiled twice with cachegrind: once in full and
# once with --skip-phase, which does everything except the measured phase.
# The difference is the phase alone. Cachegrind attributes cost by
# instruction address, so the result does not depend on call tracking, which
# tail calls on arm64 defeat (callgrind's --toggle-collect miscounted by
# ~50x here).
#
#   LABEL=lse RUSTFLAGS="-C target-feature=+lse" scripts/cachegrind.sh
#   LABEL=linux-default scripts/cachegrind.sh
#   LABEL=lse-no-metrics RUSTFLAGS="-C target-feature=+lse" FEATURES=--no-default-features scripts/cachegrind.sh
#
# Writes profiles/<label>/: ops.csv (events per operation), <op>.txt
# (functions and annotated source of the phase), raw/ (cachegrind files,
# gitignored; kcachegrind and qcachegrind open them).
set -euo pipefail
cd "$(dirname "$0")/.."
. "$HOME/.cargo/env"
LABEL=${LABEL:?set LABEL}
FEATURES=${FEATURES:-}
N=${N:-100000}
OPS=${OPS:-"get-hit get-miss insert-fresh insert-replace delete"}
ROOT=$(pwd)
HARNESS=${HARNESS:-harness}   # or harness/variants/<name> (scripts/variant.sh)
export CARGO_TARGET_DIR="$HOME/target-prof/$LABEL"
(cd "$HARNESS" && cargo build -q --release --bin profile $FEATURES)
BIN="$CARGO_TARGET_DIR/release/profile"
OUT="profiles/$LABEL"
mkdir -p "$OUT/raw"
ARGS=(--n "$N" --prefill "${PREFILL:-200000}" --heap-mib "${HEAP:-256}" --hash-power "${POWER:-22}")
# Simulated caches use the M4 Pro performance core's geometry (192 KiB L1I,
# 128 KiB L1D, 16 MiB shared L2, 128 B lines) rather than valgrind's
# defaults. Associativities are approximations; the miss counts are a model,
# not a hardware measurement.
VG=(valgrind --tool=cachegrind --cache-sim=yes --branch-sim=yes
    --I1=196608,6,128 --D1=131072,8,128 --LL=16777216,16,128)

# Committed output carries no host paths.
MOD='s/^(\/Users\/[^\/]+\/code\/segcache-lab\/|\/home\/[^\/]+\/\.cargo\/registry\/src\/[^\/]+\/|\/rustc\/[0-9a-f]+\/)//'
scrub() { sed -e "s#$ROOT/##g" -e "s#$HOME#~#g"; }

{
  echo "# label=$LABEL rustflags='${RUSTFLAGS:-}' features='$FEATURES' n=$N args=${ARGS[*]}"
  echo "# $(rustc --version); $(valgrind --version); $(uname -srm)"
  echo "op,n,ir,ir_per_op,dr_per_op,dw_per_op,d1_miss_per_op,ll_miss_per_op,cond_branch_per_op,mispredict_per_op"
} > "$OUT/ops.csv"

for op in $OPS; do
  run="$OUT/raw/cachegrind.$op.run.out"
  base="$OUT/raw/cachegrind.$op.base.out"
  "${VG[@]}" --cachegrind-out-file="$run" "$BIN" --op "$op" "${ARGS[@]}" > /dev/null 2> "$OUT/raw/$op.run.log"
  "${VG[@]}" --cachegrind-out-file="$base" "$BIN" --op "$op" "${ARGS[@]}" --skip-phase 1 > /dev/null 2> "$OUT/raw/$op.base.log"
  cg_annotate --diff --mod-filename="$MOD" --show-percs --threshold=0.5 --context=1 \
    --show=Ir,Dr,Dw,D1mr,D1mw,DLmr,DLmw,Bcm \
    "$base" "$run" | scrub > "$OUT/$op.txt"
  python3 - "$base" "$run" "$op" "$N" >> "$OUT/ops.csv" <<'PY'
import sys
def summary(path):
    ev = tot = None
    for line in open(path):
        if line.startswith("events:"):
            ev = line.split()[1:]
        elif line.startswith("summary:"):
            tot = [int(x) for x in line.split()[1:]]
    return dict(zip(ev, tot))
base, run, op, n = summary(sys.argv[1]), summary(sys.argv[2]), sys.argv[3], int(sys.argv[4])
d = {k: run[k] - base[k] for k in run}
per = lambda v: f"{v / n:.2f}"
print(",".join([op, str(n), str(d["Ir"]), per(d["Ir"]), per(d["Dr"]), per(d["Dw"]),
                per(d["D1mr"] + d["D1mw"]), per(d["DLmr"] + d["DLmw"]), per(d["Bc"]),
                per(d["Bcm"] + d["Bim"])]))
PY
  echo "$LABEL $op done" >&2
done
cat "$OUT/ops.csv"
