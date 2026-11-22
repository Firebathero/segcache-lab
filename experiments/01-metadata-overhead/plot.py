#!/usr/bin/env python3
"""Render experiment 01's figures as static SVG, one light and one dark file
each, from the committed CSVs. Standard library only.

Marks: 2 px lines, r = 4 markers with a 2 px surface ring, 1 px solid grid.
Categorical slots in fixed order: blue, orange, aqua, yellow. The light and
dark steps were validated with the dataviz palette checker. Aqua and yellow
are below 3:1 on the light surface, so every series is direct-labelled or in
the legend, and RESULTS.md carries the numbers as tables.
"""

import collections
import csv
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "figures"
KEY = 16
BUDGET = 64 << 20

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7",
                  series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835",
                 series=["#3987e5", "#d95926", "#199e70", "#c98500"]),
}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Axis:
    def __init__(self, lo, hi, log=False, ticks=(), fmt=str):
        self.lo, self.hi, self.log, self.ticks, self.fmt = lo, hi, log, ticks, fmt

    def frac(self, v):
        if self.log:
            return (math.log(v) - math.log(self.lo)) / (math.log(self.hi) - math.log(self.lo))
        return (v - self.lo) / (self.hi - self.lo)


class Chart:
    W, H = 760, 440
    L, R, T, B = 64, 168, 116, 52

    def __init__(self, title, subtitle, x, y, xlabel, ylabel):
        self.title, self.subtitle, self.x, self.y = title, subtitle, x, y
        self.xlabel, self.ylabel = xlabel, ylabel
        self.series = []  # (name, slot, points, markers, step)
        self.notes = []   # (x, y, text, dx, dy)

    def add(self, name, slot, points, markers=False, step=False, gap=None):
        """`gap`: break the line where consecutive x values differ by more."""
        self.series.append((name, slot, points, markers, step, gap))

    def note(self, x, y, text, dx=40, dy=-28):
        self.notes.append((x, y, text, dx, dy))

    def px(self, v):
        return self.L + self.x.frac(v) * (self.W - self.L - self.R)

    def py(self, v):
        return self.H - self.B - self.y.frac(v) * (self.H - self.T - self.B)

    def render(self, theme):
        t = THEMES[theme]
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W} {self.H}" '
             f'width="{self.W}" height="{self.H}" font-family=\'{FONT}\' role="img" '
             f'aria-label="{esc(self.title)}">',
             f'<rect width="{self.W}" height="{self.H}" fill="{t["surface"]}"/>',
             f'<text x="{self.L}" y="28" font-size="16" font-weight="600" fill="{t["ink"]}">{esc(self.title)}</text>',
             f'<text x="{self.L}" y="48" font-size="12" fill="{t["ink2"]}">{esc(self.subtitle)}</text>']
        # Legend: one row under the subtitle.
        lx = self.L
        for name, slot, *_ in self.series:
            c = t["series"][slot]
            o.append(f'<line x1="{lx}" y1="70" x2="{lx + 16}" y2="70" stroke="{c}" stroke-width="2" stroke-linecap="round"/>')
            o.append(f'<text x="{lx + 22}" y="74" font-size="12" fill="{t["ink2"]}">{esc(name)}</text>')
            lx += 22 + 7.0 * len(name) + 22
        x0, x1 = self.L, self.W - self.R
        y0, y1 = self.H - self.B, self.T
        for v in self.y.ticks:
            yy = self.py(v)
            o.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{t["grid"]}" stroke-width="1"/>')
            o.append(f'<text x="{x0 - 8}" y="{yy + 4:.1f}" font-size="11" text-anchor="end" fill="{t["muted"]}" '
                     f'style="font-variant-numeric: tabular-nums">{esc(self.y.fmt(v))}</text>')
        for v in self.x.ticks:
            xx = self.px(v)
            o.append(f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y0 + 4}" stroke="{t["axis"]}" stroke-width="1"/>')
            o.append(f'<text x="{xx:.1f}" y="{y0 + 18}" font-size="11" text-anchor="middle" fill="{t["muted"]}" '
                     f'style="font-variant-numeric: tabular-nums">{esc(self.x.fmt(v))}</text>')
        o.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="{t["axis"]}" stroke-width="1"/>')
        o.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{self.H - 12}" font-size="12" text-anchor="middle" fill="{t["ink2"]}">{esc(self.xlabel)}</text>')
        o.append(f'<text x="{x0}" y="{y1 - 10}" font-size="12" fill="{t["ink2"]}">{esc(self.ylabel)}</text>')

        ends = []
        # The first series added is the subject: draw it last, on top.
        for name, slot, pts, markers, step, gap in reversed(self.series):
            c = t["series"][slot]
            pts = [(a, b) for a, b in pts if self.x.lo <= a <= self.x.hi and self.y.lo <= b <= self.y.hi]
            if not pts:
                continue
            path = []
            prev = None
            last_x = None
            for a, b in pts:
                X, Y = self.px(a), self.py(b)
                if prev is None or (gap is not None and a - last_x > gap):
                    path.append(f"M{X:.1f},{Y:.1f}")
                elif step:
                    path.append(f"H{X:.1f}V{Y:.1f}")
                else:
                    path.append(f"L{X:.1f},{Y:.1f}")
                prev = (X, Y)
                last_x = a
            o.append(f'<path d="{"".join(path)}" fill="none" stroke="{c}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
            if markers:
                for a, b in pts:
                    o.append(f'<circle cx="{self.px(a):.1f}" cy="{self.py(b):.1f}" r="4" fill="{c}" '
                             f'stroke="{t["surface"]}" stroke-width="2"/>')
            ends.append([self.py(pts[-1][1]), name, self.px(pts[-1][0])])
        # Direct end labels only where they do not collide; the legend
        # carries identity for the rest.
        ends.sort()
        placed = []
        for i, (yy, name, xx) in enumerate(ends):
            near = [e for j, e in enumerate(ends) if j != i and abs(e[0] - yy) < 14]
            if not near:
                placed.append((yy, name, xx))
        for yy, name, xx in placed:
            o.append(f'<text x="{xx + 10:.1f}" y="{yy + 4:.1f}" font-size="12" fill="{t["ink"]}">{esc(name)}</text>')
        for a, b, text, dx, dy in self.notes:
            X, Y = self.px(a), self.py(b)
            o.append(f'<line x1="{X:.1f}" y1="{Y:.1f}" x2="{X + dx:.1f}" y2="{Y + dy:.1f}" stroke="{t["muted"]}" stroke-width="1"/>')
            o.append(f'<text x="{X + dx + 4:.1f}" y="{Y + dy + 4:.1f}" font-size="11" fill="{t["ink2"]}">{esc(text)}</text>')
        o.append("</svg>")
        return "\n".join(o) + "\n"

    def save(self, stem):
        OUT.mkdir(exist_ok=True)
        for theme in THEMES:
            suffix = "" if theme == "light" else "-dark"
            (OUT / f"{stem}{suffix}.svg").write_text(self.render(theme))


def rows(name):
    with open(HERE / name) as f:
        return list(csv.DictReader(f))


def heap_overhead(r):
    return BUDGET / int(r["stored"]) - KEY - int(r["value_size"])


def pow2(v):
    return f"{v:,}"


def fig_heap(sweep):
    c = Chart("Heap bytes per object beyond key and value",
              "64 MiB budget, 16 B keys, filled until the cache refuses writes. Index excluded. Measured.",
              Axis(32, 4096, log=True, ticks=[32, 64, 128, 256, 512, 1024, 2048, 4096], fmt=pow2),
              Axis(4, 2000, log=True, ticks=[5, 10, 20, 50, 100, 200, 500, 1000], fmt=pow2),
              "value size, bytes (log)", "bytes per object (log)")
    for name, config, slot in [("segcache", "segcache-p24", 0),
                               ("memcached defaults", "mc-default", 1),
                               ("memcached -C -f 1.08", "mc-C-f1.08", 2)]:
        pts = sorted((int(r["value_size"]), heap_overhead(r)) for r in sweep if r["config"] == config)
        c.add(name, slot, pts)
    c.save("01-heap-overhead")


def fig_roundup(sweep):
    c = Chart("Segcache item padding: the round-up adds a word when none is needed",
              "Heap bytes per object beyond key and value, 16 B keys, every value size 32 to 96 B.",
              Axis(32, 96, ticks=list(range(32, 97, 8))),
              Axis(0, 16, ticks=[0, 4, 8, 12, 16]),
              "value size, bytes", "bytes per object")
    measured = sorted((int(r["value_size"]), heap_overhead(r)) for r in sweep
                      if r["config"] == "segcache-p24" and 32 <= int(r["value_size"]) <= 96)
    exact = []
    for v in range(32, 97):
        item = -(-(6 + KEY + v) // 8) * 8
        per_seg = (1 << 20) // item
        exact.append((v, (1 << 20) / per_seg - KEY - v))
    c.add("measured, ((raw >> 3) + 1) << 3", 0, measured, step=True)
    c.add("model, exact round-up as in the C artifact", 1, exact, step=True)
    spike = next(p for p in measured if p[0] % 8 == 2 and p[0] > 60)
    c.note(spike[0], spike[1], f"value {spike[0]} B: raw item is 8-aligned, +8 B", dx=24, dy=-10)
    c.save("01-roundup")


def fig_total(results, analysis_fit):
    c = Chart("Total overhead per object, heap and index",
              "64 MiB budget, 16 B keys. Segcache index sized to take the whole fill without a refused insert. Mean of 5 key sets.",
              Axis(32, 4096, log=True, ticks=[32, 64, 128, 256, 512, 1024, 2048, 4096], fmt=pow2),
              Axis(4, 1000, log=True, ticks=[5, 10, 20, 50, 100, 200, 500, 1000], fmt=pow2),
              "value size, bytes (log)", "bytes per object (log)")
    series = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in results:
        if r["backend"] == "memcached":
            v = int(r["value_size"])
            total = heap_overhead(r) + int(r["index_bytes"]) / int(r["stored"])
            series[r["config"]][v].append(total)
    for (v, rep), r in analysis_fit.items():
        series["seg-total"][v].append(heap_overhead(r) + int(r["index_bytes"]) / int(r["stored"]))
        series["seg-heap"][v].append(heap_overhead(r))
    for name, key, slot in [("segcache, heap + index", "seg-total", 0),
                            ("memcached defaults", "mc-default", 1),
                            ("memcached -C -f 1.08", "mc-C-f1.08", 2),
                            ("segcache, heap only", "seg-heap", 3)]:
        pts = sorted((v, sum(xs) / len(xs)) for v, xs in series[key].items())
        c.add(name, slot, pts, markers=True)
    c.save("01-total-overhead")


def fig_refusals(measured, model, power):
    c = Chart(f"Refused inserts by index load, 2^{power} slots",
              "Share of inserts refused because both candidate buckets were full, in 0.5% load bins. 5 key sets or seeds per curve.",
              Axis(0, 1, ticks=[0, 0.2, 0.4, 0.6, 0.8, 1.0], fmt=lambda v: f"{v:.0%}" if v else "0"),
              Axis(1e-4, 1, log=True, ticks=[1e-4, 1e-3, 1e-2, 1e-1, 1], fmt=lambda v: f"{v * 100:g}%"),
              "slots occupied", "share of inserts refused (log)")

    def curve(rs):
        agg = collections.defaultdict(lambda: [0, 0])
        for r in rs:
            b = float(r["load_lo"])
            agg[b][0] += int(r["attempts"])
            agg[b][1] += int(r["refusals"])
        return [(b + 0.0025, rf / n) for b, (n, rf) in sorted(agg.items()) if rf > 0 and b < 1.0]

    # Bins with no refusal cannot sit on a log axis; the line breaks there.
    c.add("segcache, measured", 0,
          curve([r for r in measured if int(r["hash_power"]) == power]), gap=0.006)
    c.add("first-fit model", 1,
          curve([r for r in model if int(r["hash_power"]) == power and r["policy"] == "first-fit"]), gap=0.006)
    c.add("least-loaded model", 2,
          curve([r for r in model if int(r["hash_power"]) == power and r["policy"] == "least-loaded"]), gap=0.006)
    c.save(f"01-refusals-p{power}")


def main():
    sweep = rows("sweep.csv")
    results = rows("results.csv")
    fit = {}
    for r in results:
        if r["backend"] != "segcache" or int(r["hash_refusals"]) != 0:
            continue
        key = (int(r["value_size"]), int(r["rep"]))
        if key not in fit or int(r["hash_power"]) < int(fit[key]["hash_power"]):
            fit[key] = r
    fig_heap(sweep)
    fig_roundup(sweep)
    fig_total(results, fit)
    measured, model = rows("refusals.csv"), rows("model-refusals.csv")
    for power in (16, 20):
        fig_refusals(measured, model, power)


if __name__ == "__main__":
    main()
