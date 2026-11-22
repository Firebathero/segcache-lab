#!/usr/bin/env python3
"""Change 01 measurements against the patched engine. The baseline is
experiment 01's committed results (deterministic per key set).

  VARIANT=<name> selects harness/target/variants/<name>; files other than
  the default variant's get a -<name> suffix.

  results.csv   fit search: 8 value sizes x 5 key sets, hash_power from 12 up
                to the first with no refused insert
  refusals.csv  insert outcomes by slot load at 2^16, 2^18, 2^20 slots
"""

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VARIANT = os.environ.get("VARIANT", "least-loaded")
BIN = ROOT / f"harness/target/variants/{VARIANT}/release"
SUFFIX = "" if VARIANT == "least-loaded" else f"-{VARIANT}"
SIZES = [32, 64, 128, 256, 512, 1024, 2048, 4096]


def capacity(*args):
    return subprocess.run([str(BIN / "capacity"), *map(str, args)], check=True,
                          capture_output=True, text=True).stdout.strip()


def fit():
    rows = [capacity("--header")]
    for v in SIZES:
        for rep in range(5):
            power = 12
            while True:
                row = capacity("--backend", "segcache", "--config", f"least-loaded-p{power}",
                               "--value-size", v, "--rep", rep, "--hash-power", power)
                rows.append(row)
                if int(row.split(",")[12]) == 0:
                    break
                power += 1
        print(f"fit: value {v} done", file=sys.stderr)
    (HERE / f"results{SUFFIX}.csv").write_text("\n".join(rows) + "\n")


def refusals():
    rows = ["hash_power,rep,load_lo,attempts,refusals"]
    tmp = HERE / ".curve.tmp"
    for power in (16, 18, 20):
        for rep in range(5):
            capacity("--backend", "segcache", "--value-size", 32, "--rep", rep,
                     "--hash-power", power, "--refusal-curve", tmp)
            rows += [f"{power},{rep},{line}" for line in tmp.read_text().splitlines()[1:]]
    tmp.unlink()
    (HERE / f"refusals{SUFFIX}.csv").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    for step in sys.argv[1:] or ["fit", "refusals"]:
        globals()[step]()
