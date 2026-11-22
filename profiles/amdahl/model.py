#!/usr/bin/env python3
"""Stop 3, count-based half: memory footprint by component, the TTL floor's
effect on hit ratio, capacity converted to miss ratio, and instruction shares
for an operation mix. Inputs are committed data from experiment 01, Stop 2 and
the placement model. Prints markdown tables. Standard library only.
"""

import csv
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
E01 = ROOT / "experiments/01-metadata-overhead"
KEY = 16
SIZES = [32, 64, 128, 256, 512, 1024, 2048, 4096]


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


# ---- 1. memory -----------------------------------------------------------------
summary = rows(E01 / "summary.csv")
loads = {int(r["hash_power"]): r for r in rows(E01 / "model-loads.csv")}


def mean(xs):
    return sum(xs) / len(xs)


def ll_power(capacity):
    """Smallest power whose least-loaded model holds `capacity` refusal-free."""
    p = 13
    while capacity > float(loads[min(p, 23)]["least_loaded_mean"]) * (1 << p):
        p += 1
    return p


print("## Memory: bytes per object at a fixed memory budget\n")
print("Footprint = key + value + heap overhead + index share. Gain = current footprint / new footprint, "
      "i.e. objects per byte.\n")
print("| value B | key+value | heap overhead | index now (first-fit, 2^p) | footprint now | "
      "least-loaded, 2^p | least-loaded, exact size | gain, 2^p | gain, exact |")
print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
mem_rows = []
for v in SIZES:
    rs = [r for r in summary if r["config"] == "segcache (fit)" and int(r["value_size"]) == v]
    cap = int(rs[0]["stored"])
    heap = mean([float(r["heap_overhead"]) for r in rs])
    idx_now = mean([float(r["index_per_object"]) for r in rs])
    p = ll_power(cap)
    idx_ll_pow2 = 8 * (1 << p) / cap
    l_exact = float(loads[min(p, 23)]["least_loaded_mean"])
    idx_ll_exact = 8 / l_exact
    base = KEY + v + heap
    now, pow2, exact = base + idx_now, base + idx_ll_pow2, base + idx_ll_exact
    mem_rows.append((v, now, pow2, exact))
    print(f"| {v} | {KEY + v} | {heap:.1f} | {idx_now:.1f} | {now:.1f} | {idx_ll_pow2:.1f} | "
          f"{idx_ll_exact:.1f} | {now / pow2:.2f}× | {now / exact:.2f}× |")
print()

# ---- 2. TTL floor ----------------------------------------------------------------
# A TTL cache filled on miss, with requests to one object arriving as a Poisson
# process at rate lam: each miss starts a lifetime T, and the hit ratio is
# lam*T / (1 + lam*T). Segment age (items written later in an open segment
# expire earlier) is ignored, so the effective lifetimes are upper bounds.


def floor_ttl(t):
    return max(1, (t >> 3) << 3) if t < 2048 else t


print("## TTL floor: miss ratio for one object under Poisson requests\n")
print("| max-age s | lifetime s | 0.1 req/s: exact → floored | 1 req/s | 10 req/s |")
print("|---:|---:|---:|---:|---:|")
for t in (1, 2, 5, 7, 10, 15, 30, 60, 300):
    te = floor_ttl(t)
    cells = []
    for lam in (0.1, 1, 10):
        m = lambda T: 1 / (1 + lam * T)
        cells.append(f"{m(t):.1%} → {m(te):.1%}")
    print(f"| {t} | {te} | " + " | ".join(cells) + " |")
print()

# ---- 3. capacity to miss ratio ----------------------------------------------------
# LRU under independent Zipf requests, Che's approximation, ranks binned
# geometrically. An illustration of how a capacity gain converts to misses,
# not a measurement: experiment 04 replaces it with traces.


def zipf_bins(n, alpha, nbins=4000):
    edges = sorted({int(round(math.exp(i * math.log(n) / nbins))) for i in range(nbins + 1)} | {1, n + 1})
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        count = hi - lo
        mid = (lo + hi - 1) / 2
        bins.append((count, mid ** -alpha))
    z = sum(c * w for c, w in bins)
    return [(c, w / z) for c, w in bins]


def lru_miss(bins, cap):
    lo, hi = 0.0, 1e18
    for _ in range(200):
        t = math.sqrt(lo * hi) if lo > 0 else hi / 1e6
        occ = sum(c * (1 - math.exp(-p * t)) for c, p in bins)
        lo, hi = (t, hi) if occ < cap else (lo, t)
        if hi / max(lo, 1e-300) < 1 + 1e-9:
            break
    t = (lo + hi) / 2
    return 1 - sum(c * p * (1 - math.exp(-p * t)) for c, p in bins)


print("## Capacity to miss ratio (model: LRU, independent Zipf requests, 10M objects)\n")
print("| alpha | cache holds | miss ratio | ×1.20 capacity | ×1.33 capacity | ×1.44 capacity |")
print("|---:|---:|---:|---:|---:|---:|")
N = 10_000_000
for alpha in (0.8, 1.0):
    bins = zipf_bins(N, alpha)
    for frac in (0.02, 0.10):
        base = lru_miss(bins, frac * N)
        cells = [f"{lru_miss(bins, g * frac * N):.1%} ({lru_miss(bins, g * frac * N) / base - 1:+.0%})"
                 for g in (1.20, 1.33, 1.44)]
        print(f"| {alpha} | {frac:.0%} | {base:.1%} | " + " | ".join(cells) + " |")
print()

# ---- 4. instructions for an operation mix -------------------------------------------
ops = {b: {r["op"]: float(r["ir_per_op"]) for r in rows(ROOT / f"profiles/{b}/ops.csv")}
       for b in ("lse", "linux-default", "lse-no-metrics")}
lines = rows(ROOT / "profiles/lse/lines.csv")


def line_ir(op, lo, hi):
    return sum(float(r["ir_per_op"]) for r in lines
               if r["op"] == op and r["file"].endswith("hashtable/table.rs") and lo <= int(r["line"]) <= hi)


def neon(op):
    return line_ir(op, 369, 463) + sum(float(r["ir_per_op"]) for r in lines
                                       if r["op"] == op and "neon/generated" in r["file"])


MIX = {"get-hit": 0.80, "get-miss": 0.10, "insert-fresh": 0.10}
total = sum(w * ops["lse"][op] for op, w in MIX.items())
targets = {
    "2 ghost pass (all of it)": {"get-miss": line_ir("get-miss", 604, 630)},
    "3 NEON tag scan (all of it)": {op: neon(op) for op in MIX},
    "4 insert rescans (replace check + claim passes)": {"insert-fresh": line_ir("insert-fresh", 724, 860)},
    "15 outline atomics (default vs +lse)": {op: ops["linux-default"][op] - ops["lse"][op] for op in MIX},
    "16 metrics (with vs without)": {op: ops["lse"][op] - ops["lse-no-metrics"][op] for op in MIX},
}
print("## Instructions: upper bound per target, mix of 80% hits, 10% misses, 10% new-key inserts\n")
print(f"Weighted cost of the mix: {total:.0f} instructions per operation (+lse build).\n")
print("| target | instructions per op in the mix | share of the mix |")
print("|---|---:|---:|")
for name, per in targets.items():
    w = sum(MIX[op] * v for op, v in per.items())
    print(f"| {name} | {w:.1f} | {w / total:.1%} |")
