//! Experiment 01 predictions, from the source-derived model only. Prints CSV
//! to stdout; `--markdown` prints the table used in PREDICTION.md.

use lab::data::KEY_LEN;
use lab::model::{self, MIB};
use lab::Args;

const SIZES: [usize; 8] = [32, 64, 128, 256, 512, 1024, 2048, 4096];
const BUDGET: usize = 64 * MIB;
const SEEDS: u64 = 5;

struct Pred {
    config: &'static str,
    value_size: usize,
    item_bytes: usize,
    unit_bytes: usize,
    capacity: usize,
    index_bytes: usize,
    hash_power: u32,
}

/// Mean first-refusal load of the first-fit model at the real bucket count.
fn first_fit_load(power: u32) -> f64 {
    let buckets = 1usize << (power - 3);
    (0..SEEDS)
        .map(|s| model::first_refusal_load(buckets, 8, false, s))
        .sum::<f64>()
        / SEEDS as f64
}

fn main() {
    let a = Args::parse();
    if let Some(power) = a.get("curve") {
        let power: u32 = power.parse().expect("--curve <hash_power>");
        println!("policy,seed,load_lo,attempts,refusals");
        for (policy, least) in [("first-fit", false), ("least-loaded", true)] {
            for seed in 0..SEEDS {
                for (b, (n, r)) in model::refusal_curve(1 << (power - 3), 8, least, seed)
                    .iter()
                    .enumerate()
                {
                    if *n > 0 {
                        println!("{policy},{seed},{:.3},{n},{r}", b as f64 / 200.0);
                    }
                }
            }
        }
        return;
    }
    if a.get("loads").is_some() {
        println!("| hash_power | buckets | first-fit mean | first-fit min | first-fit max | least-loaded mean |");
        println!("|---:|---:|---:|---:|---:|---:|");
        for power in 13..=23u32 {
            let buckets = 1usize << (power - 3);
            let ff: Vec<f64> = (0..SEEDS)
                .map(|s| model::first_refusal_load(buckets, 8, false, s))
                .collect();
            let ll = (0..SEEDS)
                .map(|s| model::first_refusal_load(buckets, 8, true, s))
                .sum::<f64>()
                / SEEDS as f64;
            let mean = ff.iter().sum::<f64>() / SEEDS as f64;
            let min = ff.iter().cloned().fold(f64::MAX, f64::min);
            let max = ff.iter().cloned().fold(0.0, f64::max);
            println!("| {power} | {buckets} | {mean:.3} | {min:.3} | {max:.3} | {ll:.3} |");
        }
        return;
    }
    let mut rows = Vec::new();
    let mut load_cache = std::collections::HashMap::new();
    for v in SIZES {
        for (config, exact) in [("segcache", false), ("segcache-exact-round", true)] {
            let item = if exact {
                model::segcache_item_exact(KEY_LEN, v)
            } else {
                model::segcache_item(KEY_LEN, v)
            };
            let capacity = model::segcache_capacity(BUDGET, MIB, item);
            // Smallest power whose first-fit table is predicted to take the
            // whole data-bound capacity without a refusal.
            let mut power = 7;
            loop {
                let load = *load_cache
                    .entry(power)
                    .or_insert_with(|| first_fit_load(power));
                if capacity as f64 <= load * (1u64 << power) as f64 {
                    break;
                }
                power += 1;
            }
            rows.push(Pred {
                config,
                value_size: v,
                item_bytes: item,
                unit_bytes: MIB,
                capacity,
                index_bytes: 8 << power,
                hash_power: power,
            });
        }
        for (config, cas, factor) in [
            ("mc-default", true, 1.25),
            ("mc-noCAS", false, 1.25),
            ("mc-C-f1.08", false, 1.08),
        ] {
            let item = model::memcached_item(KEY_LEN, v, cas);
            let class = model::memcached_class(&model::memcached_classes(factor), item);
            let capacity = model::memcached_capacity(BUDGET, class);
            // Settled table: smallest power with items <= 1.5 x buckets,
            // starting from the default of 16 (`assoc.c:145`).
            let mut power = 16;
            while capacity * 2 > 3 << power {
                power += 1;
            }
            rows.push(Pred {
                config,
                value_size: v,
                item_bytes: item,
                unit_bytes: class.size as usize,
                capacity,
                index_bytes: 8 << power,
                hash_power: power,
            });
        }
    }

    if a.get("markdown").is_some() {
        println!("| config | value B | item B | chunk B | capacity | heap B/object | index B/object | overhead B/object |");
        println!("|---|---:|---:|---:|---:|---:|---:|---:|");
        for p in &rows {
            let heap = BUDGET as f64 / p.capacity as f64;
            let index = p.index_bytes as f64 / p.capacity as f64;
            let chunk = if p.config.starts_with("mc") {
                p.unit_bytes.to_string()
            } else {
                "".into()
            };
            println!(
                "| {} | {} | {} | {} | {} | {:.1} | {:.1} | {:.1} |",
                p.config,
                p.value_size,
                p.item_bytes,
                chunk,
                p.capacity,
                heap,
                index,
                heap + index - (KEY_LEN + p.value_size) as f64
            );
        }
    } else {
        println!("config,value_size,item_bytes,unit_bytes,capacity,index_bytes,hash_power");
        for p in &rows {
            println!(
                "{},{},{},{},{},{},{}",
                p.config,
                p.value_size,
                p.item_bytes,
                p.unit_bytes,
                p.capacity,
                p.index_bytes,
                p.hash_power
            );
        }
    }
}
