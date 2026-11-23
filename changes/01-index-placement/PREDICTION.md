# Change 01: least-loaded placement in the hash index, prediction

Committed before any measurement of the patched engine.

## The change

`0001-least-loaded-claim.patch` applies to cache-rs at `4620d7e`. It
touches `crates/segcache/src/hashtable/table.rs`: +41/−3 lines.

- `try_claim_new_slot` splits into `try_take_matching_ghost` and
  `try_claim_free_slot`. It keeps its behaviour for its other caller, the
  retry after all candidates were found full.
- A fresh key first takes a ghost with a matching tag in any candidate, in
  choice order, as before. A key re-inserted after eviction keeps its
  frequency.
- Otherwise the key goes to the candidate with fewer live entries, with ties
  keeping choice order. Before, it went to the first candidate with any free
  slot.
- The stripe lock, the slot CASes and the all-full retry are unchanged.
  Occupancy is read with relaxed loads and only orders the attempts. A
  concurrent insert can make the read stale, which affects balance, not
  correctness.

Stop 1 gives the motivation: cache-rs's `docs/segcache.md:85` says inserts
prefer the least-full bucket, and the code did not. Experiment 01 gives the
cost.

## Method

- **Correctness:** cache-rs's own suites on the pinned commit and on the
  patched commit (`scripts/cache-rs-tests.sh`). These are the default
  tests, the `debug` feature, and the shuttle concurrency models. They were
  started before this file was written. Their output had not been read.
- **Capacity:** experiment 01's segcache fit search, run against the patched
  engine (`scripts/variant.sh`). The setup is the same: 64 MiB heap, 16 B
  keys, values 32 to 4096 B, five key sets, `hash_power` from 12 up to the
  first with no refused insert.
- **Refusal curves:** the experiment 01 histogram at 2^16, 2^18 and 2^20
  slots, five key sets.
- **Cost per operation:** the Stop 2 cachegrind workload (`+lse`, 100,000
  operations, about 7% slot load).
- **Invariants:** `make verify`'s checks, built against the patched engine.

## Predictions

**P1.** Every suite that passes on the pinned commit passes with the patch,
except tests that assert first-fit placement order. Any such test is listed
with the assertion it makes.

**P2.** At every table size from 2^13 to 2^22 slots, the mean first-refusal
load over five key sets is within 0.05 of the least-loaded model mean in
`experiments/01-metadata-overhead/model-loads.csv`, for example 0.76 at
2^16 and 0.72 at 2^20. That is up from 0.375 and 0.304.

**P3.** Fit `hash_power` by value size is 32 B → 21, 64 B → 20 or 21
(762,560 objects in 2^20 slots is 0.727 load, against a model mean of
0.722), 128 B → 20, 256 B → 19, 512 B → 18, 1024 B → 17, 2048 B → 16 and
4096 B → 15. That is one or two powers below today at every size.

**P4.** Objects stored at the fit power equal experiment 01's data-bound
capacity at every size. Placement does not touch the heap.

**P5.** Total overhead per object falls from today's 52.8 B to 22.0 B at
32 B values, and from 46.0 B to 27.0 B at 128 B. At 64 B it falls from
52.0 B to 19.0 B if the fit is 2^20, or 30.0 B if it is 2^21. Objects per
byte rise 1.44× at 32 B, 1.20× or 1.29× at 64 B, and 1.11× at 128 B, and
by 1.06× or less from 256 B up. This is the "least-loaded, 2^p" column of
Stop 3.

**P6.** In the patched engine, the refused share of inserts reaches 1% at
0.80 ± 0.03 load and 10% at 0.87 ± 0.03 at all three table sizes. Today
those loads are 0.565 to 0.57 and 0.745 to 0.755.

**P7.** Instructions per operation, +lse build:

- get-hit rises by at most 30. At 7% load, about a third of keys land in
  their second candidate, and a hit there scans both buckets.
- get-miss is unchanged within ±5.
- insert-fresh rises by 20 to 60 for two occupancy counts.
- insert-replace and delete change by at most 30.

**P8.** All `make verify` checks pass against the patched engine.

## What would change the conclusion

- P2 or P6 missing the model by more than its tolerance would mean the
  engine's placement deviates from the idealised model. In that case the
  Stop 3 capacity gains would need re-deriving from measured loads.
- A P7 hit cost above 30 instructions would mean the capacity gain carries a
  lookup cost that Stop 3 did not price. It would need weighing against the
  1.1× to 1.4× capacity gain.

## Follow-up 0002: single-pass claim

Added after measuring 0001, before measuring 0002. In 0001, P7 failed on
new-key inserts: +215 instructions where +20 to 60 was predicted. 0001 scans
each candidate twice before claiming: once for a matching-tag ghost, once to
count live entries. `0002-single-pass-claim.patch`, applied on top of 0001,
reads both facts in one relaxed pass per candidate (`scan_for_claim`). It
then takes the ghost or claims a free slot in the same order as 0001.

**Q1.** Placement is unchanged from 0001. The fit-search and refusal-curve
CSVs from the 0001+0002 build are identical to 0001's, row for row.

**Q2.** A new-key insert costs 40 to 90 instructions more than the unpatched
engine, 1,116 to 1,166 against 1,076.

**Q3.** Every other operation is within ±5 instructions of 0001.

**Q4.** cache-rs's default, debug and shuttle suites pass with the same
counts as on the pinned commit. All 13 `make verify` checks pass.

## Follow-up: cost per operation at equal memory

Added after measuring 0001 and 0002, before this run. Those cost numbers come
from the Stop 2 workload at about 7% slot load. There most placements are
ties and stay in the first bucket, which understates the cost of hits that
land in the second. Here both engines hold the same objects, each with the
index it needs for a refusal-free fill: 140,000 objects prefilled, then
40,000 operations, ending at 180,000 objects. The baseline (first-fit)
needs 2^20 slots, 17% full at the end. Least-loaded needs 2^18 slots, 69%
full, a quarter of the index memory.

**R1.** A least-loaded get-hit costs at most 40 instructions more than a
baseline get-hit, because about half its keys sit in their second
candidate.

**R2.** Its last-level misses per get-hit are no higher than the baseline's.
The index is 2 MiB instead of 8 MiB.

**R3.** get-miss cost is within ±5 instructions of the baseline. Both scan
both buckets.

## Follow-up: time per operation

Added after the instruction counts above, before any timed run of either
build at these parameters. `timing.py` runs `scale` single-threaded on the
host in `env/host.md`, on AC power at powermode 0. Each engine gets the index
it needs for a refusal-free fill:

- **small:** the cachegrind workload, 180,000 objects of 64 B. First-fit
  uses 2^20 slots (8 MiB), least-loaded 2^18 (2 MiB). Index plus heap is
  about 24 and 18 MB, against a 16 MiB L2 per P-core cluster.
- **large:** the same loads ×8, 1,440,000 objects. First-fit uses 2^23
  (64 MiB), least-loaded 2^21 (16 MiB). The heap is about 127 MB, so the item
  read is a DRAM miss for both.

`get` and `miss` run 2,000,000 operations over the end state (3 processes ×
5 repetitions). `insert` prefills 7/9 of the end state and times the
remaining 2/9 as fresh keys (10 processes, 1 repetition each). The ratios
below are least-loaded median over first-fit median. A ratio inside the
run-to-run range of either build counts as no difference.

**S1.** small, get-hit: 0.90 to 1.05. The +22 instructions and the smaller
index roughly cancel in a working set near the L2 size.

**S2.** small, get-miss: at most 1.02.

**S3.** small, insert: 1.05 to 1.30, the +27% instructions partly hidden
behind the item write.

**S4.** large, get-hit: at most 0.95. First-fit's index read misses to DRAM
before the item read can start. A 16 MiB index is partly resident in L2 and
the system cache, so least-loaded pays that serial miss less often.

**S5.** large, get-miss: at most 0.95, for the same reason with no item
read.

**S6.** large, insert: 0.80 to 1.20.

**S7.** The 80/10/10 mix is 0.95 to 1.05 small and at most 0.97 large.
