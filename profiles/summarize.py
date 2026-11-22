#!/usr/bin/env python3
"""Per-component and per-line instruction costs of each operation, computed
from the raw cachegrind files written by scripts/cachegrind.sh.

Cachegrind attributes each instruction to the source file and line it came
from, inlined code included. A phase's cost is the full run minus the run
with --skip-phase. Writes, per label:

  components.csv   op, component, Ir per operation
  lines.csv        op, file, line, Ir per operation (lines >= 1 Ir/op)

Usage: python3 profiles/summarize.py lse [linux-default ...]
"""

import collections
import csv
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
OPS = ["get-hit", "get-miss", "insert-fresh", "insert-replace", "delete"]

# First match wins. Paths are as cachegrind records them.
COMPONENTS = [
    ("hash table", r"segcache/src/hashtable/|stdarch/.*/neon/"),
    ("key hashing", r"/ahash-"),
    ("segments and pins", r"segcache/src/segments/"),
    ("TTL buckets", r"segcache/src/ttl_buckets/"),
    ("item layout", r"crates/keyvalue/"),
    ("clock", r"segcache/src/clock\.rs|/clocksource-"),
    ("metrics", r"segcache/src/metrics\.rs|/metriken"),
    ("frequency RNG", r"segcache/src/rand\.rs"),
    ("free queue", r"/crossbeam-"),
    ("API and retry logic", r"segcache/src/segcache\.rs|segcache/src/(item|cas|error|sync)"),
    ("atomics, inlined", r"core/src/sync/atomic\.rs"),
    ("atomics, outline helpers", r"compiler-builtins|lse\.S|outline_atomic|^\?\?\?$"),
    ("memcpy and memcmp", r"memcpy|memcmp|memmove|string/"),
    ("harness loop", r"harness/src/"),
]


def component(path):
    for name, pattern in COMPONENTS:
        if re.search(pattern, path):
            return name
    return "other std inlines"


def parse(path):
    """Ir per (file, line) from a cachegrind output file."""
    ir = collections.Counter()
    events, fl = None, "???"
    for line in open(path):
        if line.startswith("events:"):
            events = line.split()[1:]
        elif line.startswith("fl="):
            fl = line[3:].strip()
        elif line[:1].isdigit():
            parts = line.split()
            ir[(fl, int(parts[0]))] += int(parts[1 + events.index("Ir")])
    return ir


def main(labels):
    for label in labels:
        root = HERE / label
        comp_rows, line_rows = [], []
        for op in OPS:
            run = parse(root / "raw" / f"cachegrind.{op}.run.out")
            base = parse(root / "raw" / f"cachegrind.{op}.base.out")
            n = int(next(r for r in csv.reader(
                l for l in open(root / "ops.csv") if not l.startswith("#")) if r[0] == op)[1])
            diff = collections.Counter(run)
            diff.subtract(base)
            comps = collections.Counter()
            for (fl, ln), v in diff.items():
                comps[component(fl)] += v
                if v / n >= 1:
                    short = re.sub(r"^.*?(segcache-lab/|registry/src/[^/]+/|/rustc/[0-9a-f]+/)", "", fl)
                    line_rows.append((op, short, ln, round(v / n, 2)))
            for name, v in comps.most_common():
                if abs(v / n) >= 0.05:
                    comp_rows.append((op, name, round(v / n, 2)))
        with open(root / "components.csv", "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["op", "component", "ir_per_op"])
            w.writerows(comp_rows)
        with open(root / "lines.csv", "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["op", "file", "line", "ir_per_op"])
            w.writerows(sorted(line_rows, key=lambda r: (OPS.index(r[0]), -r[3])))
        print(f"{label}: wrote components.csv, lines.csv")


if __name__ == "__main__":
    main(sys.argv[1:] or ["lse"])
