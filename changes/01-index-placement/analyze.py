#!/usr/bin/env python3
"""Compare change 01 (least-loaded placement) with experiment 01's baseline."""

import collections
import csv
import pathlib
import statistics

HERE = pathlib.Path(__file__).resolve().parent
E01 = HERE.parents[1] / "experiments/01-metadata-overhead"
BUDGET, KEY = 64 << 20, 16


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def ints(rs):
    for r in rs:
        for k in ("value_size", "rep", "stored", "lost", "value_mismatches", "hash_refusals",
                  "hash_power", "index_bytes", "other_errors"):
            r[k] = int(r[k])
    return rs


def fits(rs):
    out = {}
    for r in rs:
        if r["backend"] == "segcache" and r["hash_refusals"] == 0:
            key = (r["value_size"], r["rep"])
            if key not in out or r["hash_power"] < out[key]["hash_power"]:
                out[key] = r
    return out


base, new = ints(rows(E01 / "results.csv")), ints(rows(HERE / "results.csv"))
bf, nf = fits(base), fits(new)
print(f"## Integrity\n\n{len(new)} runs: {sum(r['lost'] for r in new)} lost, "
      f"{sum(r['value_mismatches'] for r in new)} mismatched, {sum(r['other_errors'] for r in new)} other errors.\n")

print("## Fit power, capacity and overhead\n")
print("| value B | fit power before | after | capacity before = after | overhead before | after | objects per byte |")
print("|---:|---:|---:|:---:|---:|---:|---:|")
for v in sorted({k[0] for k in nf}):
    b = [bf[(v, r)] for r in range(5)]
    n = [nf[(v, r)] for r in range(5)]
    same = all(x["stored"] == y["stored"] for x, y in zip(b, n))
    ov = lambda r: (BUDGET + r["index_bytes"]) / r["stored"] - KEY - v
    ob, on = statistics.mean(map(ov, b)), statistics.mean(map(ov, n))
    fp = lambda rs: "–".join(sorted({str(r["hash_power"]) for r in rs}))
    gain = statistics.mean((KEY + v + ov(x)) / (KEY + v + ov(y)) for x, y in zip(b, n))
    print(f"| {v} | {fp(b)} | {fp(n)} | {'yes' if same else 'NO'} | {ob:.1f} | {on:.1f} | {gain:.2f}× |")
print()

model = {int(r["hash_power"]): float(r["least_loaded_mean"]) for r in rows(E01 / "model-loads.csv")}
print("## First-refusal load by table size\n")
print("| hash_power | before (first-fit) | after (least-loaded) | min | max | least-loaded model |")
print("|---:|---:|---:|---:|---:|---:|")


def outcomes(rs):
    o = {}
    for r in rs:
        if r["backend"] == "segcache" and r["stored_at_first_hash_refusal"]:
            o.setdefault((r["hash_power"], r["rep"]), int(r["stored_at_first_hash_refusal"]) / (1 << r["hash_power"]))
    return o


ob_, on_ = outcomes(base), outcomes(new)
for p in sorted({p for p, _ in on_}):
    xs = [v for (q, _), v in on_.items() if q == p]
    bs = [v for (q, _), v in ob_.items() if q == p]
    m = model.get(p)
    print(f"| {p} | {statistics.mean(bs):.3f} | {statistics.mean(xs):.3f} | {min(xs):.3f} | {max(xs):.3f} | "
          f"{f'{m:.3f}' if m else ''} |")
print()


def thresholds(path):
    agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in rows(path):
        a = agg[int(r["hash_power"])][float(r["load_lo"])]
        a[0] += int(r["attempts"]); a[1] += int(r["refusals"])
    out = {}
    for p, bins in agg.items():
        b = sorted(bins.items())
        at = lambda share: next((x for x, (n, rf) in b if n and rf / n >= share), None)
        out[p] = (at(0.01), at(0.10))
    return out


tb, tn = thresholds(E01 / "refusals.csv"), thresholds(HERE / "refusals.csv")
print("## Load at which the refused share of inserts reaches 1% and 10%\n")
print("| hash_power | before 1% | after 1% | before 10% | after 10% |")
print("|---:|---:|---:|---:|---:|")
for p in sorted(tn):
    print(f"| {p} | {tb[p][0]:.3f} | {tn[p][0]:.3f} | {tb[p][1]:.3f} | {tn[p][1]:.3f} |")
