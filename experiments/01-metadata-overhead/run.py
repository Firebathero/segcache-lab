#!/usr/bin/env python3
"""Experiment 01 driver.

Every row comes from one run of harness/target/release/capacity or predict.
Writes, next to this file:

  results.csv         primary sweep: 8 value sizes x 5 key sets x every config
  sweep.csv           fine value-size sweep, one key set, heap capacity only
  refusals.csv        segcache insert outcomes by index slot load
  model-refusals.csv  the same for the first-fit and least-loaded models
  prediction.csv      the source-derived predictions (also in PREDICTION.md)
  model-loads.csv     the placement models' first-refusal loads by table size

Run from the repository root with `make exp01`.
"""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BIN = HERE.parents[1] / "harness" / "target" / "release"
SIZES = [32, 64, 128, 256, 512, 1024, 2048, 4096]
REPS = 5
MEMCACHED = {
    "mc-default": [],
    "mc-noCAS": ["--mc-arg", "-C"],
    "mc-C-f1.08": ["--mc-arg", "-C -f 1.08"],
}
# Large enough that the index never binds at any size in the sweep.
SWEEP_POWER = 24
CURVE_POWERS = [16, 18, 20]


def run(binary, *args):
    cmd = [str(BIN / binary), *map(str, args)]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def capacity(*args):
    return run("capacity", *args)


def write(name, lines):
    (HERE / name).write_text("\n".join(lines) + "\n")
    print(f"wrote {name}: {len(lines) - 1} rows", file=sys.stderr)


def primary():
    rows = [capacity("--header")]
    for v in SIZES:
        for rep in range(REPS):
            for name, extra in MEMCACHED.items():
                rows.append(capacity("--backend", "memcached", "--config", name,
                                     "--value-size", v, "--rep", rep, *extra))
            # Every hash power from 12 up to the first that takes the whole
            # fill without refusing an insert.
            power = 12
            while True:
                row = capacity("--backend", "segcache", "--config", f"segcache-p{power}",
                               "--value-size", v, "--rep", rep, "--hash-power", power)
                rows.append(row)
                if int(row.split(",")[12]) == 0:
                    break
                power += 1
            print(f"primary: value {v} rep {rep} done", file=sys.stderr)
    write("results.csv", rows)


def sweep():
    rows = [capacity("--header")]
    sizes = list(range(32, 1025)) + list(range(1032, 4097, 8))
    for v in sizes:
        rows.append(capacity("--backend", "segcache", "--config", f"segcache-p{SWEEP_POWER}",
                             "--value-size", v, "--hash-power", SWEEP_POWER))
    for v in range(32, 4097, 8):
        for name in ("mc-default", "mc-C-f1.08"):
            rows.append(capacity("--backend", "memcached", "--config", name, "--value-size", v,
                                 "--no-index-settle", "1", *MEMCACHED[name]))
    write("sweep.csv", rows)


def refusals():
    rows = ["hash_power,rep,load_lo,attempts,refusals"]
    path = HERE / ".curve.tmp"
    for power in CURVE_POWERS:
        for rep in range(REPS):
            capacity("--backend", "segcache", "--value-size", 32, "--rep", rep,
                     "--hash-power", power, "--refusal-curve", path)
            for line in path.read_text().splitlines()[1:]:
                rows.append(f"{power},{rep},{line}")
    path.unlink()
    write("refusals.csv", rows)

    rows = ["hash_power,policy,seed,load_lo,attempts,refusals"]
    for power in CURVE_POWERS:
        for line in run("predict", "--curve", power).splitlines()[1:]:
            rows.append(f"{power},{line}")
    write("model-refusals.csv", rows)


def main():
    steps = {"predict": None, "loads": None, "primary": primary, "sweep": sweep,
             "refusals": refusals}
    chosen = sys.argv[1:] or list(steps)
    if "predict" in chosen:
        write("prediction.csv", run("predict").splitlines())
    if "loads" in chosen:
        lines = ["hash_power,buckets,mean,min,max,least_loaded_mean"]
        for line in run("predict", "--loads").splitlines()[2:]:
            lines.append(",".join(c.strip() for c in line.strip("|").split("|")))
        write("model-loads.csv", lines)
    for step in chosen:
        if steps.get(step):
            steps[step]()


if __name__ == "__main__":
    main()
