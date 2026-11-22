//! Deterministic single-thread workloads for profilers.
//!
//! Setup (building the cache, prefilling it) runs outside the measured
//! phase. Each operation type is one `#[no_mangle]`, `#[inline(never)]`
//! function, so callgrind can restrict collection to it with
//! `--toggle-collect=phase_<op>` and samply's call tree has one root per
//! phase. Every operation's outcome is checked, so a profile of a workload
//! that silently failed is impossible.
//!
//! `--skip-phase 1` does everything except call the phase. Subtracting a
//! skipped run's profile from a full run's isolates the phase exactly,
//! without relying on a profiler's call tracking (scripts/cachegrind.sh).
//!
//! Prints `op,n,repeat,ns_per_op`. The timing is informational only; the
//! numbers that matter come from the profiler.

use lab::data::{self, KEY_LEN};
use lab::model::MIB;
use lab::Args;
use segcache::{Policy, Segcache, Value};
use std::hint::black_box;
use std::time::{Duration, Instant};

/// Keys at or above this index are never inserted: get-miss draws from here.
/// The default index (2^23 slots) keeps every phase far below the load at
/// which first-fit placement starts refusing inserts (experiment 01).
const MISS_BASE: u64 = 500_000_000_000_000;

pub struct Load {
    keys: Vec<[u8; KEY_LEN]>,
    value: Vec<u8>,
}

impl Load {
    /// `n` keys drawn from `0..space` (or `MISS_BASE + i`) in a fixed
    /// pseudo-random order, so successive operations touch unrelated buckets.
    fn new(n: usize, space: u64, miss: bool, value_size: usize, seed: u64) -> Self {
        let mut s = seed;
        let keys = (0..n as u64)
            .map(|i| {
                let k = if miss {
                    MISS_BASE + i
                } else {
                    data::splitmix64(&mut s) % space
                };
                data::key(k)
            })
            .collect();
        let mut value = vec![0u8; value_size];
        data::value(seed, &mut value);
        Load { keys, value }
    }
}

#[no_mangle]
#[inline(never)]
pub fn phase_get_hit(cache: &Segcache, load: &Load) -> u64 {
    let mut hits = 0;
    for k in &load.keys {
        let item = cache.get(k).expect("get-hit missed");
        hits += matches!(item.value(), Value::Bytes(b) if b.len() == load.value.len()) as u64;
    }
    black_box(hits)
}

#[no_mangle]
#[inline(never)]
pub fn phase_get_miss(cache: &Segcache, load: &Load) -> u64 {
    let mut misses = 0;
    for k in &load.keys {
        misses += cache.get(k).is_none() as u64;
    }
    black_box(misses)
}

#[no_mangle]
#[inline(never)]
pub fn phase_insert_fresh(cache: &Segcache, load: &Load) -> u64 {
    for k in &load.keys {
        cache
            .insert(k, &load.value[..], None, Duration::ZERO)
            .expect("insert-fresh refused");
    }
    black_box(load.keys.len() as u64)
}

#[no_mangle]
#[inline(never)]
pub fn phase_insert_replace(cache: &Segcache, load: &Load) -> u64 {
    for k in &load.keys {
        cache
            .insert(k, &load.value[..], None, Duration::ZERO)
            .expect("insert-replace refused");
    }
    black_box(load.keys.len() as u64)
}

#[no_mangle]
#[inline(never)]
pub fn phase_delete(cache: &Segcache, load: &Load) -> u64 {
    let mut deleted = 0;
    for k in &load.keys {
        deleted += cache.delete(k) as u64;
    }
    black_box(deleted)
}

fn main() {
    let a = Args::parse();
    let op = a
        .get("op")
        .expect("--op get-hit|get-miss|insert-fresh|insert-replace|delete");
    let n: usize = a.num("n", 100_000);
    let prefill: u64 = a.num("prefill", 200_000);
    let value_size: usize = a.num("value-size", 64);
    let repeat: u32 = a.num("repeat", 1);
    let skip = a.get("skip-phase").is_some();
    let cache = Segcache::builder()
        .heap_size(a.num::<usize>("heap-mib", 1024) * MIB)
        .segment_size(MIB as i32)
        .hash_power(a.num("hash-power", 23))
        .eviction(Policy::None)
        .build()
        .expect("build");

    let mut value = vec![0u8; value_size];
    for i in 0..prefill {
        data::value(i, &mut value);
        cache
            .insert(&data::key(i), &value[..], None, Duration::ZERO)
            .expect("prefill refused");
    }

    let start = Instant::now();
    let mut done = 0u64;
    let phase = |f: &dyn Fn() -> u64, expected: u64| if skip { expected } else { f() };
    for r in 0..repeat {
        let seed = 0xC0FFEE + r as u64;
        // Unique keys per repeat where the op needs them.
        done += match op {
            "get-hit" => {
                let load = Load::new(n, prefill, false, value_size, seed);
                phase(&|| phase_get_hit(&cache, &load), n as u64)
            }
            "get-miss" => {
                let load = Load::new(n, 0, true, value_size, seed);
                phase(&|| phase_get_miss(&cache, &load), n as u64)
            }
            "insert-fresh" => {
                let base = prefill + r as u64 * n as u64;
                let load = Load {
                    keys: (base..base + n as u64).map(data::key).collect(),
                    value: vec![0xA5; value_size],
                };
                phase(&|| phase_insert_fresh(&cache, &load), n as u64)
            }
            "insert-replace" => {
                let load = Load::new(n, prefill, false, value_size, seed);
                phase(&|| phase_insert_replace(&cache, &load), n as u64)
            }
            "delete" => {
                let base = r as u64 * n as u64;
                assert!(
                    base + n as u64 <= prefill,
                    "delete needs prefill >= n * repeat"
                );
                let load = Load {
                    keys: (base..base + n as u64).map(data::key).collect(),
                    value: vec![],
                };
                phase(&|| phase_delete(&cache, &load), n as u64)
            }
            other => panic!("unknown op {other}"),
        };
    }
    let elapsed = start.elapsed();
    let ops = n as u64 * repeat as u64;
    if matches!(op, "get-hit" | "get-miss" | "delete") {
        assert_eq!(
            done, ops,
            "{op}: {done} of {ops} operations had the expected outcome"
        );
    }
    println!(
        "{op},{n},{repeat},{:.1}",
        elapsed.as_nanos() as f64 / ops as f64
    );
}
