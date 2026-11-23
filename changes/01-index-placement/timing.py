#!/usr/bin/env python3
"""Change 01, time per operation. Single thread, native, on the host in
env/host.md. Each engine gets the index it needs for a refusal-free fill:
first-fit at 2^p, least-loaded at 2^(p-2).

  small  the cachegrind workload: 180,000 objects of 64 B
         (first-fit 2^20, least-loaded 2^18)
  large  the same loads x8: 1,440,000 objects (2^23, 2^21)

get and miss run over the end state. insert prefills 7/9 of it and times the
remaining 2/9 as fresh keys, one repetition per process. The two builds
alternate process by process so drift lands on both.

  build     harness/target/release (pinned) and
            harness/target/variants/least-loaded-2 (0001 + 0002)
  run       writes timing.csv
  summary   writes timing-summary.csv: median and range per cell
"""

import csv
import io
import pathlib
import statistics
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILDS = {
    "first-fit": (ROOT / "harness/target/release/scale", 0),
    "least-loaded": (ROOT / "harness/target/variants/least-loaded-2/release/scale", -2),
}
REGIMES = {"small": (180_000, 20), "large": (1_440_000, 23)}
HEADER = "regime,build,op,proc,op_,threads,rep,prefill,hash_power,ops,elapsed_ns,ns_per_op,mops"


def build():
    subprocess.run(["cargo", "build", "-q", "--release", "--bin", "scale"], cwd=ROOT / "harness", check=True)
    subprocess.run([str(ROOT / "scripts/variant.sh"), "least-loaded-2",
                    str(HERE / "0001-least-loaded-claim.patch"), str(HERE / "0002-single-pass-claim.patch")],
                   cwd=ROOT, check=True)


def scale(path, **kw):
    args = [str(path)]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip().splitlines()


def run():
    rows = [HEADER]
    for regime, (objects, power) in REGIMES.items():
        for op, procs in (("get", 3), ("miss", 3), ("insert", 10)):
            for proc in range(procs):
                for build, (path, dp) in BUILDS.items():
                    if op == "insert":
                        kw = dict(prefill=objects * 7 // 9, n=objects * 2 // 9, reps=1)
                    else:
                        kw = dict(prefill=objects, n=2_000_000, reps=5)
                    out = scale(path, op=op, threads=1, hash_power=power + dp, heap_mib=256,
                                value_size=64, **kw)
                    rows += [f"{regime},{build},{op},{proc},{line}" for line in out]
            print(f"timing: {regime} {op} done", file=sys.stderr)
    (HERE / "timing.csv").write_text("\n".join(rows) + "\n")


def summary():
    data = {}
    for r in csv.DictReader((HERE / "timing.csv").open()):
        data.setdefault((r["regime"], r["op"], r["build"]), []).append(float(r["ns_per_op"]))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["regime", "op", "build", "samples", "median_ns", "min_ns", "max_ns", "vs_first_fit"])
    for (regime, op, build), xs in sorted(data.items()):
        base = statistics.median(data[(regime, op, "first-fit")])
        w.writerow([regime, op, build, len(xs), f"{statistics.median(xs):.1f}", f"{min(xs):.1f}",
                    f"{max(xs):.1f}", f"{statistics.median(xs) / base:.3f}"])
    (HERE / "timing-summary.csv").write_text(out.getvalue())
    print(out.getvalue(), end="")


if __name__ == "__main__":
    for step in sys.argv[1:] or ["build", "run", "summary"]:
        globals()[step]()
