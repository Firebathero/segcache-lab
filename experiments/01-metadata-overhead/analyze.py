#!/usr/bin/env python3
"""Summarise experiment 01 from its CSVs. Prints the markdown tables used in
RESULTS.md and writes summary.csv. Standard library only."""

import collections
import csv
import pathlib
import statistics

HERE = pathlib.Path(__file__).resolve().parent
KEY = 16
BUDGET = 64 << 20


def rows(name):
    with open(HERE / name) as f:
        return list(csv.DictReader(f))


def spread(xs):
    lo, hi = min(xs), max(xs)
    return f"{lo:,}" if lo == hi else f"{lo:,}–{hi:,}"


def main():
    results = rows("results.csv")
    pred = {(r["config"], int(r["value_size"])): r for r in rows("prediction.csv")}
    for r in results:
        for k in ("value_size", "rep", "stored", "resident", "lost", "value_mismatches",
                  "hash_refusals", "space_refusals", "other_errors", "evictions",
                  "index_bytes", "hash_power", "index_settle_ms", "attempted"):
            r[k] = int(r[k])

    total = collections.Counter()
    for r in results:
        total["runs"] += 1
        total["lost"] += r["lost"]
        total["mismatches"] += r["value_mismatches"]
        total["evictions"] += r["evictions"]
        total["other"] += r["other_errors"]
        total["resident_ne_stored"] += r["resident"] != r["stored"]
    print("## Integrity\n")
    print(f"{total['runs']} runs: {total['lost']} lost, {total['mismatches']} mismatched, "
          f"{total['evictions']} evictions, {total['other']} other errors, "
          f"{total['resident_ne_stored']} runs where resident != stored.\n")

    sizes = sorted({r["value_size"] for r in results})
    summary = []

    # Segcache fit power per (size, key set).
    seg = collections.defaultdict(list)
    for r in results:
        if r["backend"] == "segcache":
            seg[(r["value_size"], r["rep"])].append(r)
    fit = {}
    for key, rs in seg.items():
        clean = [r for r in rs if r["hash_refusals"] == 0]
        fit[key] = min(clean, key=lambda r: r["hash_power"])

    print("## Capacity against prediction\n")
    print("| config | value B | predicted | measured (5 key sets) | match | index power |")
    print("|---|---:|---:|---:|:---:|---:|")
    for v in sizes:
        for config in ("segcache", "mc-default", "mc-noCAS", "mc-C-f1.08"):
            if config == "segcache":
                rs = [fit[(v, rep)] for rep in range(5)]
            else:
                rs = [r for r in results if r["config"] == config and r["value_size"] == v]
            p = pred[(config, v)]
            stored = [r["stored"] for r in rs]
            powers = [r["hash_power"] for r in rs]
            match = all(s == int(p["capacity"]) for s in stored)
            label = "segcache (fit)" if config == "segcache" else config
            pp = f"{spread(powers)} (pred {p['hash_power']})"
            print(f"| {label} | {v} | {int(p['capacity']):,} | {spread(stored)} | {'yes' if match else 'NO'} | {pp} |")
            for r in rs:
                heap = BUDGET / r["stored"] - KEY - v
                idx = r["index_bytes"] / r["stored"]
                summary.append({
                    "config": label, "value_size": v, "rep": r["rep"], "stored": r["stored"],
                    "hash_power": r["hash_power"], "index_bytes": r["index_bytes"],
                    "heap_overhead": round(heap, 3), "index_per_object": round(idx, 3),
                    "total_overhead": round(heap + idx, 3),
                })
    print()

    print("## Overhead per object, bytes (mean over 5 key sets)\n")
    print("| value B | segcache heap only | segcache heap + fit index | mc-default | mc-noCAS | mc-C-f1.08 |")
    print("|---:|---:|---:|---:|---:|---:|")
    by = collections.defaultdict(list)
    for s in summary:
        by[(s["config"], s["value_size"])].append(s)
    for v in sizes:
        cells = [f"{statistics.mean(x['heap_overhead'] for x in by[('segcache (fit)', v)]):.1f}"]
        for c in ("segcache (fit)", "mc-default", "mc-noCAS", "mc-C-f1.08"):
            xs = [x["total_overhead"] for x in by[(c, v)]]
            lo, hi = min(xs), max(xs)
            cell = f"{statistics.mean(xs):.1f}"
            if hi - lo >= 0.05:
                cell += f" ({lo:.1f}–{hi:.1f})"
            cells.append(cell)
        print(f"| {v} | " + " | ".join(cells) + " |")
    print()

    print("## Default index (hash_power 16, 65,536 slots)\n")
    print("| value B | data-bound capacity | stored | refused inserts | first refusal at load |")
    print("|---:|---:|---:|---:|---:|")
    for v in sizes:
        rs = [r for r in results if r["config"] == "segcache-p16" and r["value_size"] == v]
        cap = fit[(v, 0)]["stored"]
        loads = [r["stored_at_first_hash_refusal"] for r in rs if r["stored_at_first_hash_refusal"]]
        load = f"{min(int(x) for x in loads) / 65536:.3f}–{max(int(x) for x in loads) / 65536:.3f}" if loads else "none"
        print(f"| {v} | {cap:,} | {spread([r['stored'] for r in rs])} | "
              f"{spread([r['hash_refusals'] for r in rs])} | {load} |")
    print()

    # The first refusal depends only on the key set and the table, not the
    # value size, so each (power, key set) is one outcome however many value
    # sizes reached it.
    print("## First-refusal load by table size\n")
    print("| hash_power | key sets | measured mean | min | max | first-fit model mean | min | max |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    outcomes = {}
    for r in results:
        if r["backend"] == "segcache" and r["stored_at_first_hash_refusal"]:
            load = int(r["stored_at_first_hash_refusal"]) / (1 << r["hash_power"])
            prev = outcomes.setdefault((r["hash_power"], r["rep"]), load)
            assert prev == load, "first refusal differs across value sizes for one key set"
    model = {int(r["hash_power"]): r for r in rows("model-loads.csv")}
    for p in sorted({p for p, _ in outcomes}):
        xs = [v for (q, _), v in outcomes.items() if q == p]
        m = model.get(p)
        mcells = f"{float(m['mean']):.3f} | {float(m['min']):.3f} | {float(m['max']):.3f}" if m else "| |"
        print(f"| {p} | {len(xs)} | {statistics.mean(xs):.3f} | {min(xs):.3f} | {max(xs):.3f} | {mcells} |")
    print()

    print("## Fine sweep: segcache heap overhead by value size mod 8 (values 32..1024)\n")
    sweep = [r for r in rows("sweep.csv") if r["config"] == "segcache-p24" and int(r["value_size"]) <= 1024]
    by_mod = collections.defaultdict(list)
    for r in sweep:
        v = int(r["value_size"])
        by_mod[v % 8].append(BUDGET / int(r["stored"]) - KEY - v)
    print("| value mod 8 | min B | max B |")
    print("|---:|---:|---:|")
    for k in range(8):
        print(f"| {k} | {min(by_mod[k]):.2f} | {max(by_mod[k]):.2f} |")
    print()

    print("## Refused share of inserts by slot load (5 key sets or seeds pooled)\n")
    print("| curve | hash_power | load at first refused bin | load where refused share >= 1% | >= 10% |")
    print("|---|---:|---:|---:|---:|")
    def thresholds(rs):
        agg = collections.defaultdict(lambda: [0, 0])
        for r in rs:
            agg[float(r["load_lo"])][0] += int(r["attempts"])
            agg[float(r["load_lo"])][1] += int(r["refusals"])
        bins = sorted(agg.items())
        first = next((b for b, (n, rf) in bins if rf > 0), None)
        def at(share):
            return next((b for b, (n, rf) in bins if n and rf / n >= share), None)
        return first, at(0.01), at(0.10)
    measured = rows("refusals.csv")
    mod = rows("model-refusals.csv")
    for p in sorted({int(r["hash_power"]) for r in measured}):
        for name, rs in [("segcache measured", [r for r in measured if int(r["hash_power"]) == p]),
                         ("first-fit model", [r for r in mod if int(r["hash_power"]) == p and r["policy"] == "first-fit"]),
                         ("least-loaded model", [r for r in mod if int(r["hash_power"]) == p and r["policy"] == "least-loaded"])]:
            f, a, b = thresholds(rs)
            print(f"| {name} | {p} | {f:.3f} | {a:.3f} | {b:.3f} |")
    print()

    print("## memcached index\n")
    print("| config | value B | settled hash_power | index B | settle ms |")
    print("|---|---:|---:|---:|---:|")
    for v in sizes:
        for config in ("mc-default", "mc-C-f1.08"):
            rs = [r for r in results if r["config"] == config and r["value_size"] == v]
            print(f"| {config} | {v} | {spread([r['hash_power'] for r in rs])} | "
                  f"{spread([r['index_bytes'] for r in rs])} | {spread([r['index_settle_ms'] for r in rs])} |")

    with open(HERE / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(summary)


if __name__ == "__main__":
    main()
