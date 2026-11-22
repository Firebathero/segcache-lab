//! One capacity measurement. Fill an engine with fixed-size objects that
//! never expire until it refuses writes, then read back every key ever
//! written. Prints one CSV row; `--header` prints the column names.
//!
//! Segcache runs in-process with `Policy::None`, so a full cache refuses
//! instead of evicting. memcached runs with `-M` for the same reason.

use lab::data::{self, KEY_LEN};
use lab::mc::{self, Client, Server, SetReply};
use lab::model::MIB;
use lab::Args;
use segcache::{Policy, Segcache, SegcacheError, Value};
use std::path::PathBuf;
use std::time::Duration;

/// Stop after this many consecutive refused writes.
const CONFIRM: u64 = 4096;
/// Each repetition writes a disjoint key set. Both engines hash with fixed
/// seeds, so repeating one key set reproduces one outcome exactly; distinct
/// key sets sample the distribution of hash placements.
const REP_KEY_STRIDE: u64 = 10_000_000_000_000;
const MC_BATCH: usize = 256;
const MC_GET_BATCH: usize = 100;

const HEADER: &str = "backend,config,value_size,key_size,rep,budget_bytes,allocated_bytes,\
attempted,stored,resident,lost,value_mismatches,hash_refusals,space_refusals,other_errors,\
evictions,first_refusal,stored_at_first_hash_refusal,index_bytes,hash_power,index_settle_ms,\
shared_bytes,rss_bytes";

#[derive(Default)]
struct Row {
    backend: &'static str,
    config: String,
    value_size: usize,
    rep: u32,
    budget: usize,
    allocated: usize,
    attempted: u64,
    stored: u64,
    resident: u64,
    lost: u64,
    mismatches: u64,
    hash_refusals: u64,
    space_refusals: u64,
    other_errors: u64,
    evictions: u64,
    first_refusal: String,
    stored_at_first_hash_refusal: Option<u64>,
    index_bytes: u64,
    hash_power: u32,
    index_settle_ms: u64,
    shared_bytes: u64,
    rss: u64,
}

impl Row {
    fn print(&self) {
        println!(
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            self.backend,
            self.config,
            self.value_size,
            KEY_LEN,
            self.rep,
            self.budget,
            self.allocated,
            self.attempted,
            self.stored,
            self.resident,
            self.lost,
            self.mismatches,
            self.hash_refusals,
            self.space_refusals,
            self.other_errors,
            self.evictions,
            self.first_refusal,
            self.stored_at_first_hash_refusal
                .map(|n| n.to_string())
                .unwrap_or_default(),
            self.index_bytes,
            self.hash_power,
            self.index_settle_ms,
            self.shared_bytes,
            self.rss,
        );
    }
}

fn main() {
    let a = Args::parse();
    if a.get("header").is_some() {
        println!("{HEADER}");
        return;
    }
    let backend = a.get("backend").expect("--backend segcache|memcached");
    let mut row = Row {
        value_size: a.num("value-size", 0),
        rep: a.num("rep", 0),
        budget: a.num::<usize>("budget-mib", 64) * MIB,
        config: a.get("config").unwrap_or(backend).to_string(),
        ..Row::default()
    };
    match backend {
        "segcache" => segcache_run(&a, &mut row),
        "memcached" => memcached_run(&a, &mut row).expect("memcached run"),
        other => panic!("unknown backend {other}"),
    }
    row.print();
}

fn segcache_run(a: &Args, row: &mut Row) {
    row.backend = "segcache";
    let power: u8 = a.num("hash-power", 16);
    let cache = Segcache::builder()
        .heap_size(row.budget)
        .segment_size(MIB as i32)
        .hash_power(power)
        .eviction(Policy::None)
        .build()
        .expect("build segcache");

    let base = row.rep as u64 * REP_KEY_STRIDE;
    let mut buf = vec![0u8; row.value_size];
    let mut stored = Vec::new();
    let mut consecutive = 0u64;
    let mut i = 0u64;
    // Optional histogram of insert outcomes by slot load, in 0.5% bins.
    let curve_path = a.get("refusal-curve").map(PathBuf::from);
    let slots = 1u64 << power;
    let mut curve = vec![(0u64, 0u64); 201];
    while consecutive <= CONFIRM {
        let bin = (row.stored * 200 / slots).min(200) as usize;
        data::value(base + i, &mut buf);
        let ok = match cache.insert(&data::key(base + i), &buf[..], None, Duration::ZERO) {
            Ok(()) => true,
            Err(e) => {
                if row.first_refusal.is_empty() {
                    row.first_refusal = format!("{e:?}");
                }
                match e {
                    SegcacheError::HashTableInsertEx => {
                        row.hash_refusals += 1;
                        row.stored_at_first_hash_refusal.get_or_insert(row.stored);
                    }
                    SegcacheError::NoFreeSegments | SegcacheError::EvictionEx => {
                        row.space_refusals += 1
                    }
                    _ => row.other_errors += 1,
                }
                false
            }
        };
        curve[bin].0 += 1;
        curve[bin].1 += !ok as u64;
        row.stored += ok as u64;
        consecutive = if ok { 0 } else { consecutive + 1 };
        stored.push(ok);
        i += 1;
    }
    row.attempted = i;
    if let Some(path) = curve_path {
        let mut out = String::from("load_lo,attempts,refusals\n");
        for (b, (n, r)) in curve.iter().enumerate().filter(|(_, (n, _))| *n > 0) {
            out.push_str(&format!("{:.3},{n},{r}\n", b as f64 / 200.0));
        }
        std::fs::write(path, out).expect("write refusal curve");
    }

    for (j, &was_stored) in stored.iter().enumerate() {
        match cache.get_no_freq_incr(&data::key(base + j as u64)) {
            Some(item) => {
                row.resident += 1;
                data::value(base + j as u64, &mut buf);
                let exact = matches!(item.value(), Value::Bytes(b) if b == &buf[..]);
                if !(was_stored && exact) {
                    row.mismatches += 1;
                }
            }
            None if was_stored => row.lost += 1,
            None => {}
        }
    }

    row.allocated = row.budget;
    row.hash_power = power as u32;
    // 2^(power - 3) buckets of 64 B: `hashtable/table.rs:182-189`.
    row.index_bytes = (1u64 << power) * 8;
    row.shared_bytes = (row.budget / MIB) as u64 * 64;
    row.rss = lab::rss_bytes(std::process::id()).expect("rss");
}

fn memcached_run(a: &Args, row: &mut Row) -> std::io::Result<()> {
    row.backend = "memcached";
    let binary = a
        .get("memcached")
        .map(PathBuf::from)
        .unwrap_or_else(mc::default_binary);
    let budget_mib = (row.budget / MIB).to_string();
    let mut args = vec!["-m", budget_mib.as_str(), "-M"];
    for extra in a.all("mc-arg") {
        args.extend(extra.split_whitespace());
    }
    let server = Server::spawn(&binary, &args)?;
    let mut c = Client::connect(server.port)?;

    let base = row.rep as u64 * REP_KEY_STRIDE;
    let mut keys = vec![[0u8; KEY_LEN]; MC_BATCH];
    let mut vals = vec![vec![0u8; row.value_size]; MC_BATCH];
    let mut replies = Vec::with_capacity(MC_BATCH);
    let mut stored = Vec::new();
    let mut consecutive = 0u64;
    let mut i = 0u64;
    while consecutive <= CONFIRM {
        for b in 0..MC_BATCH {
            keys[b] = data::key(base + i + b as u64);
            data::value(base + i + b as u64, &mut vals[b]);
        }
        let items: Vec<(&[u8], &[u8])> = keys
            .iter()
            .zip(&vals)
            .map(|(k, v)| (&k[..], &v[..]))
            .collect();
        c.set_many(&items, 0, &mut replies)?;
        for r in &replies {
            let ok = *r == SetReply::Stored;
            if !ok && row.first_refusal.is_empty() {
                row.first_refusal = format!("{r:?}");
            }
            match r {
                SetReply::Stored => {}
                SetReply::OutOfMemory => row.space_refusals += 1,
                SetReply::Other => row.other_errors += 1,
            }
            row.stored += ok as u64;
            consecutive = if ok { 0 } else { consecutive + 1 };
            stored.push(ok);
        }
        i += MC_BATCH as u64;
    }
    row.attempted = i;

    // memcached checks for hash-table growth once per clock tick
    // (`memcached.c:3938`) and grows one power at a time on a background
    // thread, so the table lags the item count by seconds. Read its size
    // once no further growth is due: not expanding, and items no more than
    // 1.5 x buckets (`assoc.c:145`).
    let num = |m: &std::collections::HashMap<String, String>, k: &str| -> u64 {
        m.get(k)
            .and_then(|v| v.parse().ok())
            .unwrap_or_else(|| panic!("stat {k} missing"))
    };
    let filled = std::time::Instant::now();
    let mut stats = c.stats("")?;
    let settle = a.get("no-index-settle").is_none();
    loop {
        let buckets = 1u64 << num(&stats, "hash_power_level");
        let settled =
            num(&stats, "hash_is_expanding") == 0 && num(&stats, "curr_items") * 2 <= buckets * 3;
        if settled || !settle {
            break;
        }
        assert!(
            filled.elapsed() < Duration::from_secs(60),
            "hash table did not settle"
        );
        std::thread::sleep(Duration::from_millis(50));
        stats = c.stats("")?;
    }
    row.index_settle_ms = filled.elapsed().as_millis() as u64;
    row.index_bytes = num(&stats, "hash_bytes");
    row.hash_power = num(&stats, "hash_power_level") as u32;
    row.evictions = num(&stats, "evictions");
    row.allocated = num(&c.stats("slabs")?, "total_malloced") as usize;

    let mut expect = vec![0u8; row.value_size];
    for start in (0..stored.len()).step_by(MC_GET_BATCH) {
        let end = (start + MC_GET_BATCH).min(stored.len());
        let batch: Vec<[u8; KEY_LEN]> = (start..end).map(|j| data::key(base + j as u64)).collect();
        let refs: Vec<&[u8]> = batch.iter().map(|k| &k[..]).collect();
        let mut hit = vec![false; refs.len()];
        c.get_many(&refs, |idx, v| {
            hit[idx] = true;
            row.resident += 1;
            let j = start + idx;
            data::value(base + j as u64, &mut expect);
            if !(stored[j] && v == &expect[..]) {
                row.mismatches += 1;
            }
        })?;
        for (idx, h) in hit.iter().enumerate() {
            if !h && stored[start + idx] {
                row.lost += 1;
            }
        }
    }

    row.rss = lab::rss_bytes(server.pid())?;
    server.stop()?;
    Ok(())
}
