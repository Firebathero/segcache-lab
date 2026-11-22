# 01 metadata overhead: prediction

Committed before the measurement run. Every number below comes from
`harness/target/release/predict`, i.e. from the source-derived model in
`harness/src/model.rs`. `make verify` checks that model against the engines
themselves: the segcache item size against `keyvalue::item_size`, and
memcached's slab classes against the table the server prints.

## Question

At a fixed 64 MiB data budget, how many fixed-size objects does each engine
store, and what does one object cost in total once the index is included?

## Method

- Keys are 16 B. Values are 32 to 4096 B, powers of two. No expiry, client
  flags 0, no optional data.
- Each run fills one engine until it refuses writes (segcache
  `Policy::None`, memcached `-M`), then reads back every key it wrote.
- Five disjoint key sets per point. Both engines hash with fixed seeds, so a
  key set fully determines one outcome. The spread across key sets is the
  spread of hash placements.
- Segcache: 1 MiB segments, 64 MiB heap. Each point runs every `hash_power`
  from 12 up to the first that takes the whole fill without one refused insert.
  That smallest power is the point's **fit** configuration.
- memcached 1.6.45 configs: `mc-default` (`-m 64 -M`), `mc-noCAS` (`-C`) and
  `mc-C-f1.08` (`-C -f 1.08`). Index size is read after the hash table has
  stopped growing.
- Overhead per object = (heap budget + index bytes) / objects − 16 − value
  size. Segment headers (64 B per 1 MiB segment) are below 0.01 B per object
  at every size and are left out of the table.

## Runs made before this file

These runs informed what is measured, so the prediction gets no credit for
them:

- Segcache at value 32 B, `hash_power` 16, 17 and 18, key sets 0 to 2. This
  exposed the `hash_power` misreading corrected in `notes/stop-1-layout.md`.
  The first refusal came at 24,198, 23,862 and 25,694 stored objects of
  65,536 slots.
- memcached `mc-default` at value 32 B (559,232 stored) and 64 B (441,472).
- The refusal histogram at 32 B, `hash_power` 16.
- `make verify` capacity-determinism runs at value 100 B on an 8 MiB budget.

The index predictions below come from the placement model, not from these
runs.

## Predictions

**P1.** memcached stores exactly the modelled capacity in every config, size
and key set: 64 pages × the per-page count of the item's slab class. This
assumes all 64 pages go to that one class. Any difference falsifies P1.

**P2.** At its fit power, segcache stores exactly 64 × floor(1 MiB / item)
objects. Any difference falsifies P2.

**P3.** No run loses an object it acknowledged or returns a byte that differs
from what was written.

**P4.** The fit `hash_power` per value size is the one in the table. It is the
smallest power whose first-fit model, at that table's bucket count, has a mean
first-refusal load above the data-bound capacity. The model's first-refusal
load falls as the table grows (second table), so larger caches need
proportionally more index. A measured fit more than one power away from the
prediction at any size falsifies the placement model.

**P5.** At the default `hash_power` 16 (65,536 slots), segcache refuses
inserts at every value size up to 2048 B and none at 4096 B, where the
data-bound capacity (16,256) is a quarter of the slots.

**P6.** Total overhead per object follows the table. At 32 B, fit-provisioned
segcache (64.0 B) is within 25% of memcached (79.5 B default, 62.5 B
`-C -f 1.08`), and its index is 87% of its overhead. At 4096 B, segcache is
48.5 B against memcached's 482.6 B, because slab rounding dominates
memcached's cost at that size.

**P7.** Segcache's in-heap overhead (item − key − value) is exactly 8 B at
every power-of-two size: a 6 B header plus 2 B of padding.

**P8.** Over a fine value-size sweep, segcache's in-heap overhead repeats with
period 8 B between 7 and 14 B. It peaks at 14 B where `vlen ≡ 2 (mod 8)`,
the off-by-one round-up from Stop 1. With the C artifact's exact round-up
(not measured, model only) it would be 6 to 13 B. memcached's in-heap
overhead is a sawtooth with a tooth per slab class, reaching about 20% of the
chunk size at factor 1.25.

**P9.** The measured refusal rate by slot load follows the first-fit model's
curve. The least-loaded model takes about 0.7 of the slots before its first
refusal at every table size here.

### Capacity and overhead

`segcache` rows are at the predicted fit power. `segcache-exact-round` is
model only. `chunk B` is memcached's slab class.

| config | value B | item B | chunk B | capacity | heap B/object | index B/object | overhead B/object |
|---|---:|---:|---:|---:|---:|---:|---:|
| segcache | 32 | 56 |  | 1198336 | 56.0 | 56.0 | 64.0 |
| segcache-exact-round | 32 | 56 |  | 1198336 | 56.0 | 56.0 | 64.0 |
| mc-default | 32 | 107 | 120 | 559232 | 120.0 | 7.5 | 79.5 |
| mc-noCAS | 32 | 99 | 120 | 559232 | 120.0 | 7.5 | 79.5 |
| mc-C-f1.08 | 32 | 99 | 104 | 645248 | 104.0 | 6.5 | 62.5 |
| segcache | 64 | 88 |  | 762560 | 88.0 | 44.0 | 52.0 |
| segcache-exact-round | 64 | 88 |  | 762560 | 88.0 | 44.0 | 52.0 |
| mc-default | 64 | 139 | 152 | 441472 | 152.0 | 9.5 | 81.5 |
| mc-noCAS | 64 | 131 | 152 | 441472 | 152.0 | 9.5 | 81.5 |
| mc-C-f1.08 | 64 | 131 | 136 | 493440 | 136.0 | 8.5 | 64.5 |
| segcache | 128 | 152 |  | 441472 | 152.0 | 38.0 | 46.0 |
| segcache-exact-round | 128 | 152 |  | 441472 | 152.0 | 38.0 | 46.0 |
| mc-default | 128 | 203 | 240 | 279616 | 240.0 | 7.5 | 103.5 |
| mc-noCAS | 128 | 195 | 240 | 279616 | 240.0 | 7.5 | 103.5 |
| mc-C-f1.08 | 128 | 195 | 200 | 335488 | 200.0 | 6.3 | 62.3 |
| segcache | 256 | 280 |  | 239616 | 280.1 | 35.0 | 43.1 |
| segcache-exact-round | 256 | 280 |  | 239616 | 280.1 | 35.0 | 43.1 |
| mc-default | 256 | 331 | 384 | 174720 | 384.1 | 6.0 | 118.1 |
| mc-noCAS | 256 | 323 | 384 | 174720 | 384.1 | 6.0 | 118.1 |
| mc-C-f1.08 | 256 | 323 | 336 | 199680 | 336.1 | 10.5 | 74.6 |
| segcache | 512 | 536 |  | 125184 | 536.1 | 33.5 | 41.6 |
| segcache-exact-round | 512 | 536 |  | 125184 | 536.1 | 33.5 | 41.6 |
| mc-default | 512 | 587 | 600 | 111808 | 600.2 | 9.4 | 81.6 |
| mc-noCAS | 512 | 579 | 600 | 111808 | 600.2 | 9.4 | 81.6 |
| mc-C-f1.08 | 512 | 579 | 600 | 111808 | 600.2 | 9.4 | 81.6 |
| segcache | 1024 | 1048 |  | 64000 | 1048.6 | 32.8 | 41.3 |
| segcache-exact-round | 1024 | 1048 |  | 64000 | 1048.6 | 32.8 | 41.3 |
| mc-default | 1024 | 1099 | 1184 | 56640 | 1184.8 | 9.3 | 154.1 |
| mc-noCAS | 1024 | 1091 | 1184 | 56640 | 1184.8 | 9.3 | 154.1 |
| mc-C-f1.08 | 1024 | 1091 | 1136 | 59072 | 1136.1 | 8.9 | 104.9 |
| segcache | 2048 | 2072 |  | 32384 | 2072.3 | 32.4 | 40.7 |
| segcache-exact-round | 2048 | 2072 |  | 32384 | 2072.3 | 32.4 | 40.7 |
| mc-default | 2048 | 2123 | 2320 | 28864 | 2325.0 | 18.2 | 279.2 |
| mc-noCAS | 2048 | 2115 | 2320 | 28864 | 2325.0 | 18.2 | 279.2 |
| mc-C-f1.08 | 2048 | 2115 | 2144 | 31296 | 2144.3 | 16.8 | 97.1 |
| segcache | 4096 | 4120 |  | 16256 | 4128.3 | 32.3 | 48.5 |
| segcache-exact-round | 4096 | 4120 |  | 16256 | 4128.3 | 32.3 | 48.5 |
| mc-default | 4096 | 4171 | 4544 | 14720 | 4559.0 | 35.6 | 482.6 |
| mc-noCAS | 4096 | 4163 | 4544 | 14720 | 4559.0 | 35.6 | 482.6 |
| mc-C-f1.08 | 4096 | 4163 | 4320 | 15488 | 4333.0 | 33.9 | 254.8 |

### First-refusal load of the placement models

Load = stored / slots at the first refused insert. Five seeds per row, with
8 slots per bucket and two independent uniform choices per key. The first-fit
model is the policy at `hashtable/table.rs:1304-1310`.

| hash_power | buckets | first-fit mean | first-fit min | first-fit max | least-loaded mean |
|---:|---:|---:|---:|---:|---:|
| 13 | 1024 | 0.466 | 0.409 | 0.571 | 0.763 |
| 14 | 2048 | 0.469 | 0.425 | 0.522 | 0.758 |
| 15 | 4096 | 0.429 | 0.350 | 0.480 | 0.757 |
| 16 | 8192 | 0.403 | 0.347 | 0.449 | 0.763 |
| 17 | 16384 | 0.382 | 0.346 | 0.408 | 0.733 |
| 18 | 32768 | 0.377 | 0.339 | 0.408 | 0.742 |
| 19 | 65536 | 0.346 | 0.313 | 0.368 | 0.722 |
| 20 | 131072 | 0.314 | 0.261 | 0.348 | 0.722 |
| 21 | 262144 | 0.308 | 0.292 | 0.320 | 0.711 |
| 22 | 524288 | 0.280 | 0.248 | 0.305 | 0.698 |
| 23 | 1048576 | 0.265 | 0.232 | 0.300 | 0.683 |

## What would change the conclusion

- If memcached or segcache capacities miss the model (P1, P2), the per-object
  costs in the table are wrong and Stop 1's layout reading has an error.
- If the measured fit power is lower than predicted (P4), the engine places
  better than the idealised first-fit model, and segcache's index share is
  smaller than predicted.
