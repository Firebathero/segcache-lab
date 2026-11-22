#!/usr/bin/env python3
"""Stop 3 figures, light and dark, drawn with experiment 01's chart code."""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p01", ROOT / "experiments/01-metadata-overhead/plot.py")
p01 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p01)
p01.OUT = pathlib.Path(__file__).resolve().parent / "figures"
Chart, Axis = p01.Chart, p01.Axis


def floor_ttl(t):
    return max(1, (t >> 3) << 3)


def ttl_figure(lam):
    c = Chart(f"Miss ratio by max-age, one object at {lam:g} request/s",
              "Poisson requests, cached on miss. Segcache's lifetime is the floor of the TTL's 8 s bucket. Model.",
              Axis(1, 32, ticks=[1, 4, 8, 12, 16, 20, 24, 28, 32]),
              Axis(0, 0.6, ticks=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], fmt=lambda v: f"{v:.0%}"),
              "max-age, seconds", "miss ratio")
    exact = [(t, 1 / (1 + lam * t)) for t in range(1, 33)]
    floored = [(t, 1 / (1 + lam * floor_ttl(t))) for t in range(1, 33)]
    c.add("segcache, bucket floor", 1, floored, step=True)
    c.add("TTL honoured exactly", 0, exact)
    c.note(5, 1 / (1 + lam * 1), "max-age 5 s lives 1 s", dx=30, dy=-14)
    c.save(f"03-ttl-floor-{lam:g}rps")


def capacity_figure():
    rows = [(32, 1.44, 1.50), (64, 1.20, 1.33), (128, 1.11, 1.17), (256, 1.06, 1.08),
            (512, 1.03, 1.04), (1024, 1.02, 1.02), (2048, 1.01, 1.01), (4096, 1.00, 1.01)]
    c = Chart("Objects per byte with a different index, relative to today",
              "Least-loaded two-choice placement, index sized for a refusal-free fill. 16 B keys. Model on 01 data.",
              Axis(32, 4096, log=True, ticks=[32, 64, 128, 256, 512, 1024, 2048, 4096], fmt=lambda v: f"{v:,}"),
              Axis(1.0, 1.6, ticks=[1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6], fmt=lambda v: f"{v:.1f}×"),
              "value size, bytes (log)", "objects per byte, today = 1.0")
    c.add("exact-size index", 0, [(v, e) for v, _, e in rows], markers=True)
    c.add("power-of-two index", 1, [(v, p) for v, p, _ in rows], markers=True)
    c.save("03-capacity-gain")


if __name__ == "__main__":
    ttl_figure(1)
    capacity_figure()
