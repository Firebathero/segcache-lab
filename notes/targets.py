#!/usr/bin/env python3
"""Draw the Segcache target map: the engine's four structures with each
optimisation target pinned to the part it concerns.

  python3 notes/targets.py            writes notes/target-map.svg (standalone,
                                      light and dark via prefers-color-scheme)
  python3 notes/targets.py --inline   prints the <svg> for embedding in a page
                                      whose CSS defines the same classes

Marker encoding: filled = measured; ring = confirmed in source or machine
code, cost not yet measured; dashed ring = hypothesis.
"""

import sys

W, H = 1180, 600
MEASURED, CODE, HYPOTHESIS = "m", "c", "h"

STANDALONE_CSS = """
.panel{fill:#fbfaf8;stroke:#d9d6cf}.box{fill:#ffffff;stroke:#b9b5ab}.slot{fill:#e3e0d8;stroke:#b9b5ab}
.slot.full{fill:#c9c4b8}.free{fill:none;stroke:#b9b5ab;stroke-dasharray:3 3}
.ink{fill:#1d1c1a}.ink2{fill:#55524b}.mute{fill:#8a867c}.line{stroke:#8a867c;fill:none}
.acc{fill:#b4410e}.accs{stroke:#b4410e}.accbg{fill:#fbfaf8}
.mk-m{fill:#b4410e;stroke:#b4410e}.mk-c{fill:#fbfaf8;stroke:#b4410e}.mk-h{fill:#fbfaf8;stroke:#8a867c;stroke-dasharray:3 2}
.mt-m{fill:#ffffff}.mt-c{fill:#b4410e}.mt-h{fill:#55524b}
@media (prefers-color-scheme: dark){
.panel{fill:#1f1e1c;stroke:#3a3834}.box{fill:#262522;stroke:#55524b}.slot{fill:#33312d;stroke:#55524b}
.slot.full{fill:#4a4741}.free{stroke:#55524b}.ink{fill:#ecebe6}.ink2{fill:#bdb9ae}.mute{fill:#8f8b80}
.line{stroke:#8f8b80}.acc{fill:#f08a4b}.accs{stroke:#f08a4b}.accbg{fill:#1f1e1c}
.mk-m{fill:#f08a4b;stroke:#f08a4b}.mk-c{fill:#1f1e1c;stroke:#f08a4b}.mk-h{fill:#1f1e1c;stroke:#8f8b80}
.mt-m{fill:#1f1e1c}.mt-c{fill:#f08a4b}.mt-h{fill:#bdb9ae}}
text{font-family:"Schibsted Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace}
"""

out = []


def t(x, y, s, cls="ink", size=12, anchor="start", weight=None, mono=False):
    w = f' font-weight="{weight}"' if weight else ""
    c = cls + (" mono" if mono else "")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out.append(f'<text x="{x}" y="{y}" class="{c}" font-size="{size}" text-anchor="{anchor}"{w}>{s}</text>')


def rect(x, y, w, h, cls="box", r=4):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" class="{cls}" stroke-width="1"/>')


def line(x1, y1, x2, y2, arrow=True, cls="line"):
    m = ' marker-end="url(#arr)"' if arrow else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}" stroke-width="1.2"{m}/>')


def marker(x, y, n, kind):
    out.append(f'<circle cx="{x}" cy="{y}" r="10" class="mk-{kind}" stroke-width="1.6"/>')
    out.append(f'<text x="{x}" y="{y + 4}" class="mt-{kind}" font-size="11" text-anchor="middle" font-weight="700">{n}</text>')


def panel(x, y, w, h, title, cost):
    rect(x, y, w, h, "panel", 10)
    t(x + 16, y + 26, title, "ink", 15, weight=600)
    if cost:
        t(x + w - 16, y + 26, cost, "mute", 11, anchor="end", mono=True)


def draw():
    out.append('<defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" '
               'orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" class="mute"/></marker></defs>')

    # ---- Hash table -------------------------------------------------------
    panel(12, 12, 572, 330, "Hash table", "Ir/op  hit 159 · miss 282 · fresh insert 522")
    t(28, 62, "key ─ ahash ─▶ 64-bit hash ─▶ tag 12 bits, two candidate buckets", "ink2", 11.5)
    slot_w, gap, x0 = 52, 3, 128
    for row, (label, used) in enumerate([("bucket 1", 8), ("bucket 2", 5)]):
        y = 84 + row * 40
        t(28, y + 20, label, "ink2", 12)
        for i in range(8):
            rect(x0 + i * (slot_w + gap), y, slot_w, 28, "slot full" if i < used else "slot", 3)
    bx1 = x0 + 8 * (slot_w + gap) - gap
    # 64 B bucket vs 128 B line
    t(x0, 78, "one bucket = 8 slots × 8 B = 64 B", "mute", 10.5)
    marker(bx1 - 4, 74, 7, HYPOTHESIS)
    # first-fit
    t(28, 176, "Placement: first candidate with a free slot (first-fit).", "ink2", 11.5)
    t(28, 192, "No overflow chain: both candidates full ─▶ insert refused.", "ink2", 11.5)
    marker(560, 182, 1, MEASURED)
    # slot bits
    rect(28, 206, 516, 26, "box", 3)
    t(40, 223, "slot: tag 12 │ freq 8 │ seg 18 · gen 6 · offset÷8 20", "ink2", 11, mono=True)
    marker(560, 219, 6, CODE)
    # operations on the table
    rows = [
        (2, MEASURED, "Miss: second scalar pass over both buckets, looking for ghosts"),
        (3, MEASURED, "Tag match: NEON compare, match mask built one lane at a time"),
        (4, MEASURED, "New-key insert: replace check before and after the stripe lock, two claim passes"),
        (5, CODE, "Frequency draw: one table-wide AtomicU64, one ldadd per hit below freq 127"),
    ]
    for i, (n, kind, label) in enumerate(rows):
        y = 256 + i * 21
        marker(40, y - 4, n, kind)
        t(60, y, label, "ink", 11.5)

    # ---- Segments ---------------------------------------------------------
    panel(596, 12, 572, 330, "Segments", "Ir/op  hit 79 · replace 184 · delete 177")
    t(612, 62, "headers (separate array, 64 B each)", "ink2", 11.5)
    hx, hw = 612, 64
    for i in range(6):
        rect(hx + i * (hw + 4), 72, hw, 26, "box", 3)
        t(hx + i * (hw + 4) + hw / 2, 89, f"hdr {i}", "mute", 10.5, anchor="middle")
    # 128 B line brackets over pairs
    for p in range(3):
        x = hx + p * 2 * (hw + 4)
        out.append(f'<path d="M{x},104 v6 h{2 * hw + 4} v-6" class="line" stroke-width="1" fill="none"/>')
        t(x + hw + 2, 122, "one 128 B line", "mute", 9.5, anchor="middle")
    marker(1032, 85, 12, HYPOTHESIS)
    t(1052, 82, "write offset, live bytes,", "ink2", 10.5)
    t(1052, 96, "ref count, generation", "ink2", 10.5)
    # reader pin
    t(612, 148, "Read pin: ref count +1 on get, −1 on drop (acq_rel)", "ink2", 11.5)
    line(780, 140, 744, 101)
    marker(880, 144, 10, CODE)
    t(1132, 148, "Replace: two pins (#99)", "ink2", 11, anchor="end")
    marker(1150, 144, 13, CODE)
    # segment data
    t(612, 176, "segment data (1 MiB, append-only)", "ink2", 11.5)
    sx, sy, sh = 612, 184, 34
    widths = [96, 64, 120, 80]
    x = sx
    for w in widths:
        rect(x, sy, w, sh, "slot full", 2)
        x += w + 2
    rect(x, sy, 1152 - x, sh, "free", 2)
    t(x + 10, sy + 21, "free", "mute", 10.5)
    line(x - 1, sy + 50, x - 1, sy + sh + 2)
    t(x - 4, sy + 62, "Append: one CAS'd tail offset per TTL bucket", "ink2", 11, anchor="end")
    marker(x + 16, sy + 58, 11, MEASURED)
    # item zoom
    fields = [("header 6 B", 96), ("key", 120), ("value", 210), ("pad 1–8 B", 94)]
    fx = 612
    centres = []
    for name, fw in fields:
        rect(fx, 274, fw, 26, "box", 3)
        t(fx + fw / 2, 291, name, "ink2", 11, anchor="middle", mono=True)
        centres.append(fx + fw / 2)
        fx += fw
    out.append(f'<path d="M{sx},{sy + sh} L612,274 M{sx + 96},{sy + sh} L{fx},274" class="line" '
               f'stroke-width="0.8" stroke-dasharray="2 3" fill="none"/>')
    t(596 + 16, 320, "item", "mute", 10.5)
    marker(centres[0], 318, 9, CODE)
    marker(centres[3], 318, 8, MEASURED)

    # ---- TTL buckets ------------------------------------------------------
    panel(12, 354, 572, 170, "TTL buckets", "1,024 buckets in 4 tiers")
    t(28, 398, "Tier 1: TTLs of 1–2,047 s in 8 s buckets. Effective lifetime is the bucket floor.", "ink2", 11.5)
    rx, ry, rw = 40, 440, 480
    out.append(f'<line x1="{rx}" y1="{ry}" x2="{rx + rw}" y2="{ry}" class="line" stroke-width="1"/>')
    for s in range(0, 33, 8):
        x = rx + rw * s / 32
        out.append(f'<line x1="{x}" y1="{ry - 5}" x2="{x}" y2="{ry + 5}" class="line" stroke-width="1"/>')
        t(x, ry + 20, f"{s} s", "mute", 10.5, anchor="middle")
    # TTL 10 s lives 8 s
    x10, x8 = rx + rw * 10 / 32, rx + rw * 8 / 32
    out.append(f'<circle cx="{x10}" cy="{ry}" r="4" class="acc"/>')
    line(x10, ry - 12, x8 + 3, ry - 12)
    t(x10 + 6, ry - 16, "TTL 10 s ─▶ 8 s", "ink", 11)
    x5, x1 = rx + rw * 5 / 32, rx + rw * 1 / 32
    out.append(f'<circle cx="{x5}" cy="{ry}" r="4" class="acc"/>')
    line(x5, ry + 34, x1 + 3, ry + 34)
    t(x5 + 6, ry + 38, "TTL 1–7 s ─▶ 1 s", "ink", 11)
    t(rx, ry + 62, "Expiry runs from segment creation; items written later in a segment lose more.", "ink2", 11)
    marker(560, 480, 14, MEASURED)

    # ---- Every operation --------------------------------------------------
    panel(596, 354, 572, 170, "Cross-cutting", "")
    marker(624, 400, 15, MEASURED)
    t(644, 404, "Outline atomics (aarch64 Linux default build):", "ink", 11.5)
    t(644, 420, "+6.4% Ir on get-hit, +17.1% on replace, against +lse", "ink2", 11)
    marker(624, 452, 16, MEASURED)
    t(644, 456, "Global metrics counters, one atomic add per event:", "ink", 11.5)
    t(644, 472, "1.3% of get-hit Ir, 6.2% of replace; contention not measured", "ink2", 11)

    # ---- Legend -------------------------------------------------------------
    ly = 560
    marker(24, ly, "", MEASURED)
    t(42, ly + 4, "measured", "ink2", 11.5)
    marker(148, ly, "", CODE)
    t(166, ly + 4, "confirmed in source or machine code, cost not yet measured", "ink2", 11.5)
    marker(626, ly, "", HYPOTHESIS)
    t(644, ly + 4, "hypothesis", "ink2", 11.5)
    t(1168, ly + 4, "cache-rs 4620d7e · Ir from cachegrind, +lse build", "mute", 10.5, anchor="end", mono=True)


def main():
    draw()
    body = "\n".join(out)
    label = ("Segcache target map: sixteen optimisation targets pinned to the hash table, "
             "segments, TTL buckets and per-operation costs")
    if "--inline" in sys.argv:
        print(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{label}" class="map">\n{body}\n</svg>')
    else:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
               f'role="img" aria-label="{label}">\n<style>{STANDALONE_CSS}</style>\n'
               f'<rect width="{W}" height="{H}" class="accbg"/>\n{body}\n</svg>\n')
        import pathlib
        p = pathlib.Path(__file__).resolve().parent / "target-map.svg"
        p.write_text(svg)
        print(f"wrote {p.name}")


if __name__ == "__main__":
    main()
