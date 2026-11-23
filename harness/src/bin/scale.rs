//! In-process throughput of one operation type across threads.
//!
//! All threads share one cache and run the same operation on their own
//! pseudo-random key sequence. Timing starts at a barrier after every
//! thread's keys are prepared. Prints one CSV row per repetition:
//! `op,threads,rep,prefill,hash_power,ops,elapsed_ns,ns_per_op,mops`.
//!
//! Operations:
//!   get       `Segcache::get`: frequency update (shared RNG word, slot CAS)
//!   peek      `Segcache::get_no_freq_incr`: the same lookup without it
//!   miss      `get` of keys never inserted
//!   replace   `insert` over existing keys
//!   insert    `insert` of keys not yet present. Each repetition adds
//!             `n` objects per thread, so `--reps 1` keeps the end state fixed

use lab::data::{self, KEY_LEN};
use lab::model::MIB;
use lab::Args;
use segcache::{Policy, Segcache, Value};
use std::hint::black_box;
use std::sync::Barrier;
use std::time::{Duration, Instant};

const MISS_BASE: u64 = 500_000_000_000_000;

fn keys(n: usize, space: u64, miss: bool, seed: u64) -> Vec<[u8; KEY_LEN]> {
    let mut s = seed;
    (0..n as u64)
        .map(|i| {
            data::key(if miss {
                MISS_BASE + i + seed * n as u64
            } else {
                data::splitmix64(&mut s) % space
            })
        })
        .collect()
}

fn run(cache: &Segcache, op: &str, keys: &[[u8; KEY_LEN]], value: &[u8]) -> u64 {
    let mut ok = 0u64;
    match op {
        "get" => {
            for k in keys {
                ok += cache.get(k).is_some_and(
                    |it| matches!(it.value(), Value::Bytes(b) if b.len() == value.len()),
                ) as u64;
            }
        }
        "peek" => {
            for k in keys {
                ok += cache.get_no_freq_incr(k).is_some_and(
                    |it| matches!(it.value(), Value::Bytes(b) if b.len() == value.len()),
                ) as u64;
            }
        }
        "miss" => {
            for k in keys {
                ok += cache.get(k).is_none() as u64;
            }
        }
        "replace" | "insert" => {
            for k in keys {
                ok += cache.insert(k, value, None, Duration::ZERO).is_ok() as u64;
            }
        }
        other => panic!("unknown op {other}"),
    }
    black_box(ok)
}

fn main() {
    let a = Args::parse();
    let op = a
        .get("op")
        .expect("--op get|peek|miss|replace|insert")
        .to_string();
    let threads: usize = a.num("threads", 1);
    let n: usize = a.num("n", 1_000_000);
    let prefill: u64 = a.num("prefill", 1_000_000);
    let reps: u32 = a.num("reps", 5);
    let power: u8 = a.num("hash-power", 23);
    let value_size: usize = a.num("value-size", 64);
    let cache = Segcache::builder()
        .heap_size(a.num::<usize>("heap-mib", 1024) * MIB)
        .segment_size(MIB as i32)
        .hash_power(power)
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

    for rep in 0..reps {
        let loads: Vec<_> = (0..threads)
            .map(|t| {
                if op == "insert" {
                    // The keys after the prefill, as profile.rs's insert-fresh uses.
                    let base = prefill + (rep as u64 * threads as u64 + t as u64) * n as u64;
                    (base..base + n as u64).map(data::key).collect()
                } else {
                    keys(n, prefill, op == "miss", 1 + rep as u64 * 1000 + t as u64)
                }
            })
            .collect();
        let barrier = Barrier::new(threads + 1);
        let (elapsed, ok) = std::thread::scope(|s| {
            let handles: Vec<_> = loads
                .iter()
                .map(|load| {
                    let (cache, barrier, op, value) = (&cache, &barrier, op.as_str(), &value);
                    s.spawn(move || {
                        barrier.wait();
                        run(cache, op, load, value)
                    })
                })
                .collect();
            barrier.wait();
            let start = Instant::now();
            let ok: u64 = handles.into_iter().map(|h| h.join().unwrap()).sum();
            (start.elapsed(), ok)
        });
        let ops = (n * threads) as u64;
        assert_eq!(
            ok, ops,
            "{op}: {ok} of {ops} operations had the expected outcome"
        );
        let ns = elapsed.as_nanos() as f64;
        println!(
            "{op},{threads},{rep},{prefill},{power},{ops},{},{:.1},{:.2}",
            elapsed.as_nanos(),
            ns * threads as f64 / ops as f64,
            ops as f64 / ns * 1e3
        );
    }
}
