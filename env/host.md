# Host

Every result in this repository was produced on the machine below unless its
RESULTS.md says otherwise. Regenerate the table with `scripts/host.sh`.

| property | value |
|---|---|
| collected | 2026-11-22T15:35:58Z |
| cpu | Apple M4 Pro |
| logical cpus | 12 |
| perflevel0 (Performance) | 8 cores, L1d 128 KiB, L2 16384 KiB shared per 4 cpus |
| perflevel1 (Efficiency) | 4 cores, L1d 64 KiB, L2 4096 KiB shared per 4 cpus |
| cache line | 128 B |
| page size | 16384 B |
| memory | 24 GiB |
| os | macOS 15.7.9 (24G830), Darwin 24.6.0 arm64 |
| power | AC Power, powermode 0 (0 automatic, 1 low, 2 high) |
| rustc | rustc 1.100.0 (0ef1bc386 2026-11-09) |
| cc | Apple clang version 17.0.0 (clang-1700.0.13.5) |
| libevent | 2.1.13-stable |
| memcached | memcached 1.6.45 |

## What this host can and cannot support

**Supported: counts.** Capacity, resident objects, hit and miss ratios, expiry
counts and bytes held by expired objects do not depend on timing. They are
measured here at full validity. Segcache runs in-process; memcached runs as a
native process on loopback. No container or VM sits under either.

**Bounded: single-thread timing.** Native arm64, no virtualisation layer.
macOS exposes no thread-to-core affinity, so the scheduler may place a thread on
an efficiency core. Timing claims made on this host are limited to effects
larger than their measured run-to-run spread, and state the spread.

**Not supported: thread scaling beyond 8.** There are 8 performance and 4
efficiency cores with different microarchitectures. A scaling curve past 8
threads mixes core types. A load generator and server cannot be given disjoint
cores. Thread-scaling results (experiment 06) need a Linux host with affinity
control and are not produced here.

**Not available: Linux tooling.** No perf, eBPF or perf_event_open. Sampling
profiles use samply; hardware counters, where used, come from Instruments and
are labelled as such.

## Layout facts that matter for the engine under test

- `hw.cachelinesize` reports 128 B. Segcache's hash bucket and segment header
  are both declared `#[repr(C, align(64))]` with size 64 B, sized for a 64 B
  line (see notes/stop-1-layout.md). On this host two buckets or two segment
  headers share one reported line. Whether that matters for false sharing or
  prefetch is an open question for the hot-path work, not a result.
- Page size is 16 KiB. memcached's slab page (1 MiB) and Segcache's default
  segment (1 MiB) are both multiples of it.
