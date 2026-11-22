# Upstream repositories

Cloned into `repos/` (gitignored) by `scripts/fetch.sh`, which checks out and
verifies each commit below. Every `file:line` citation in this repository is
made against these commits.

| name | commit | date | describe | role |
|---|---|---|---|---|
| [pelikan-io/cache-rs](https://github.com/pelikan-io/cache-rs) | `4620d7e87cdc21c2356f6292121636f1537d30f3` | 2026-10-05 | `4620d7e` (crate `segcache` 0.4.5) | engine under test, `crates/segcache` and `crates/keyvalue` |
| [memcached/memcached](https://github.com/memcached/memcached) | `2d51e364799bc9698bd4b11728ea978cea12da6e` | 2026-07-09 | `1.6.45` | baseline |
| [Thesys-lab/Segcache](https://github.com/Thesys-lab/Segcache) | `0abdfeed3031b5cf441f07d35ad2aeb3d870789d` | 2023-05-14 | `osdi22-11-g0abdfee` | the paper's C artifact; read for reference, not built |
| [pelikan-io/pelikan](https://github.com/pelikan-io/pelikan) | `cb2b7c0c4c5dc76f349736f1dfb20a8e5119dee8` | 2026-09-01 | `v0.3.2-28-gcb2b7c0` | server that embeds the engine (PR #189); read for reference |

## Why the engine is tested in-process

pelikan's server moved to the concurrent engine in cache-rs in pelikan PR #189
(merged 2026-08-20). The engine is a library with a `&self` API, so experiments
drive it directly. That removes protocol parsing and the network from storage
measurements. memcached has no library form and is driven over loopback TCP. No
experiment in this repository compares timing across that boundary.

## Build

- cache-rs: built as a path dependency of `harness/` with the toolchain pinned
  in `rust-toolchain.toml`. Release profile: `opt-level = 3`, `lto = true`,
  `codegen-units = 1`, matching cache-rs's own release profile.
- memcached: `scripts/build-memcached.sh` (autogen, configure against
  libevent, `make memcached`).

## Licences

cache-rs is MIT OR Apache-2.0, memcached is BSD-3-Clause, and Segcache (C) and
pelikan are Apache-2.0. None of their source is copied into this repository.
Patches to upstream code, when there are any, live under `patches/` with the
upstream licence header kept intact.
