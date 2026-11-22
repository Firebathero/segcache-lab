#!/usr/bin/env python3
"""Stop 3 measurements (notes/stop-3-amdahl.md). Native, on the host in
env/host.md. Writes latency.csv, scaling.csv and rtt.csv next to this file.

Builds two variants of the harness: the engine's default features (metrics on)
into harness/target, and --no-default-features into harness/target/nometrics.
"""

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILDS = {"metrics": ROOT / "harness/target/release", "nometrics": ROOT / "harness/target/nometrics/release"}
HEADER = "build,op,threads,rep,prefill,hash_power,ops,elapsed_ns,ns_per_op,mops"


def build():
    subprocess.run(["cargo", "build", "-q", "--release"], cwd=ROOT / "harness", check=True)
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / "harness/target/nometrics"))
    subprocess.run(["cargo", "build", "-q", "--release", "--no-default-features"],
                   cwd=ROOT / "harness", check=True, env=env)


def scale(build, **kw):
    args = [str(BUILDS[build] / "scale")]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    return [f"{build},{line}" for line in out.strip().splitlines()]


def write(name, rows):
    (HERE / name).write_text("\n".join(rows) + "\n")
    print(f"wrote {name}: {len(rows) - 1} rows", file=sys.stderr)


def latency():
    # Single thread. "cached": 1,024 objects and a 2^13-slot index, resident in
    # the core's caches. "dram": 4M objects and a 2^24-slot index, ~480 MB.
    rows = ["workset," + HEADER]
    for build in BUILDS:
        for ws, prefill, power in (("cached", 1024, 13), ("dram", 4_000_000, 24)):
            for op in ("get", "peek", "miss", "replace"):
                n = 500_000 if op == "replace" else 2_000_000
                rows += [f"{ws},{r}" for r in scale(build, op=op, threads=1, n=n, prefill=prefill,
                                                     hash_power=power, heap_mib=2048, reps=5)]
    write("latency.csv", rows)


def scaling():
    rows = [HEADER]
    for build in BUILDS:
        for op in ("get", "peek", "miss", "replace"):
            for threads in (1, 2, 4, 8):
                n = 150_000 if op == "replace" else 1_000_000
                rows += scale(build, op=op, threads=threads, n=n, prefill=1_000_000,
                              hash_power=23, heap_mib=2048, reps=5)
            print(f"scaling: {build} {op} done", file=sys.stderr)
    write("scaling.csv", rows)


def rtt():
    rows = ["rep,batch,clients,gets,elapsed_s,server_cpu_s,server_ns_per_get,client_gets_per_s"]
    for batch, clients in ((1, 1), (1, 4), (1, 8), (32, 8)):
        for rep in range(3):
            out = subprocess.run([str(BUILDS["metrics"] / "rtt"), "--batch", str(batch), "--clients", str(clients),
                                  "--secs", "5"], check=True, capture_output=True, text=True).stdout
            rows.append(f"{rep},{out.strip()}")
    write("rtt.csv", rows)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["latency", "scaling", "rtt"]
    build()
    for s in steps:
        globals()[s]()
