#!/usr/bin/env python3
"""Change 01 figures, light and dark, drawn with experiment 01's chart code."""

import collections
import csv
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
E01 = ROOT / "experiments/01-metadata-overhead"
spec = importlib.util.spec_from_file_location("p01", E01 / "plot.py")
p01 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p01)
p01.OUT = HERE / "figures"
Chart, Axis = p01.Chart, p01.Axis
BUDGET, KEY = 64 << 20, 16


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def curve(rs, power):
    agg = collections.defaultdict(lambda: [0, 0])
    for r in rs:
        if int(r["hash_power"]) == power and r.get("policy", "least-loaded") == "least-loaded":
            agg[float(r["load_lo"])][0] += int(r["attempts"])
            agg[float(r["load_lo"])][1] += int(r["refusals"])
    return [(b + 0.0025, rf / n) for b, (n, rf) in sorted(agg.items()) if rf > 0 and b < 1.0]


def refusal_figure(power=20):
    c = Chart(f"Refused inserts by index load, 2^{power} slots, before and after",
              "Share of inserts refused because both candidate buckets were full, 0.5% load bins, 5 key sets each.",
              Axis(0, 1, ticks=[0, 0.2, 0.4, 0.6, 0.8, 1.0], fmt=lambda v: f"{v:.0%}" if v else "0"),
              Axis(1e-4, 1, log=True, ticks=[1e-4, 1e-3, 1e-2, 1e-1, 1], fmt=lambda v: f"{v * 100:g}%"),
              "slots occupied", "share of inserts refused (log)")
    first = [r for r in rows(E01 / "refusals.csv")]
    after = [r for r in rows(HERE / "refusals.csv")]
    model = [r for r in rows(E01 / "model-refusals.csv")]
    c.add("least-loaded, measured", 0, curve(after, power), gap=0.006)
    c.add("first-fit, measured (today)", 1, curve(first, power), gap=0.006)
    c.add("least-loaded model", 2, curve(model, power), gap=0.006)
    c.save("c01-refusals")


def fits(path):
    out = {}
    for r in rows(path):
        if r["backend"] == "segcache" and int(r["hash_refusals"]) == 0:
            k = (int(r["value_size"]), int(r["rep"]))
            if k not in out or int(r["hash_power"]) < int(out[k]["hash_power"]):
                out[k] = r
    return out


def overhead_figure():
    def series(fs):
        by = collections.defaultdict(list)
        for (v, _), r in fs.items():
            by[v].append((BUDGET + int(r["index_bytes"])) / int(r["stored"]) - KEY - v)
        return sorted((v, sum(xs) / len(xs)) for v, xs in by.items())
    mc = collections.defaultdict(list)
    for r in rows(E01 / "results.csv"):
        if r["config"] == "mc-C-f1.08":
            v = int(r["value_size"])
            mc[v].append((BUDGET + int(r["index_bytes"])) / int(r["stored"]) - KEY - v)
    c = Chart("Overhead per object, heap and index, before and after",
              "64 MiB heap, 16 B keys, index sized for a refusal-free fill. Mean of 5 key sets. Measured.",
              Axis(32, 4096, log=True, ticks=[32, 64, 128, 256, 512, 1024, 2048, 4096], fmt=lambda v: f"{v:,}"),
              Axis(10, 1000, log=True, ticks=[10, 20, 50, 100, 200, 500, 1000], fmt=lambda v: f"{v:,}"),
              "value size, bytes (log)", "bytes per object (log)")
    c.add("segcache, least-loaded", 0, series(fits(HERE / "results.csv")), markers=True)
    c.add("segcache today", 1, series(fits(E01 / "results.csv")), markers=True)
    c.add("memcached -C -f 1.08", 2, sorted((v, sum(x) / len(x)) for v, x in mc.items()), markers=True)
    c.save("c01-overhead")


if __name__ == "__main__":
    refusal_figure()
    overhead_figure()
