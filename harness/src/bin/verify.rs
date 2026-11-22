//! Invariant checks the experiments depend on. Exits non-zero if any fails.
//! Build with `--features vclock`; the segcache expiry check needs it.

use lab::data::{self, KEY_LEN};
use lab::mc::{self, Client, Server, SetReply};
use lab::model::{self, MIB};
use segcache::{Policy, Segcache, Value};
use std::process::Command;
use std::time::Duration;

struct Report {
    failures: u32,
}

impl Report {
    fn check(&mut self, name: &str, ok: bool, detail: String) {
        println!(
            "{} {name}{}",
            if ok { "PASS" } else { "FAIL" },
            if detail.is_empty() {
                detail
            } else {
                format!(": {detail}")
            }
        );
        if !ok {
            self.failures += 1;
        }
    }
}

/// Mixed value sizes 1..=8192 B.
fn mixed_size(i: u64) -> usize {
    (i * 7919 % 8192) as usize + 1
}

fn main() {
    let mut r = Report { failures: 0 };
    model_checks(&mut r);
    segcache_checks(&mut r);
    memcached_checks(&mut r).expect("memcached checks");
    capacity_determinism(&mut r);
    println!("{} failure(s)", r.failures);
    std::process::exit(if r.failures == 0 { 0 } else { 1 });
}

fn model_checks(r: &mut Report) {
    let mut bad = Vec::new();
    for klen in [1usize, 16, 100, 250] {
        for vlen in 0..=8192usize {
            let engine = keyvalue::item_size(klen, &keyvalue::Value::Bytes(&vec![0; vlen]), 0);
            if engine != model::segcache_item(klen, vlen) {
                bad.push((klen, vlen, engine));
            }
        }
    }
    r.check(
        "model: segcache_item equals keyvalue::item_size for klen {1,16,100,250}, vlen 0..=8192",
        bad.is_empty(),
        bad.first()
            .map(|b| format!("first mismatch {b:?}"))
            .unwrap_or_default(),
    );

    for factor in ["1.25", "1.08"] {
        let server = Server::spawn(&mc::default_binary(), &["-vv", "-f", factor]).expect("spawn");
        // The table is printed during startup; wait until the port answers.
        drop(Client::connect(server.port).expect("connect"));
        let printed = mc::parse_slab_table(&server.stop().expect("stop"));
        let modelled = model::memcached_classes(factor.parse().unwrap());
        r.check(
            &format!(
                "model: memcached_classes({factor}) equals the table memcached prints with -vv"
            ),
            !printed.is_empty() && printed == modelled,
            format!("{} printed, {} modelled", printed.len(), modelled.len()),
        );
    }
}

fn segcache_checks(r: &mut Report) {
    let cache = Segcache::builder()
        .heap_size(256 * MIB)
        .segment_size(MIB as i32)
        .hash_power(20)
        .eviction(Policy::None)
        .build()
        .expect("build");
    const N: u64 = 50_000;
    let mut refused = 0;
    let mut buf = Vec::new();
    for i in 0..N {
        buf.resize(mixed_size(i), 0);
        data::value(i, &mut buf);
        refused += cache
            .insert(&data::key(i), &buf[..], None, Duration::ZERO)
            .is_err() as u32;
    }
    let mut wrong = 0;
    for i in 0..N {
        buf.resize(mixed_size(i), 0);
        data::value(i, &mut buf);
        let exact = cache
            .get(&data::key(i))
            .is_some_and(|it| matches!(it.value(), Value::Bytes(b) if b == &buf[..]));
        wrong += !exact as u32;
    }
    r.check(
        "segcache: 50,000 inserts of 1..=8192 B all accepted and read back byte-exact",
        refused == 0 && wrong == 0,
        format!("{refused} refused, {wrong} not byte-exact"),
    );

    let mut wrong = 0;
    for i in 0..1000 {
        buf.resize(mixed_size(i), 0);
        data::value(i ^ 0xFFFF_FFFF, &mut buf);
        cache
            .insert(&data::key(i), &buf[..], None, Duration::ZERO)
            .expect("overwrite");
        let exact = cache
            .get(&data::key(i))
            .is_some_and(|it| matches!(it.value(), Value::Bytes(b) if b == &buf[..]));
        wrong += !exact as u32;
    }
    r.check(
        "segcache: overwrite returns the new value",
        wrong == 0,
        format!("{wrong} wrong"),
    );

    let deleted = (1000..2000)
        .filter(|&i| cache.delete(&data::key(i)))
        .count();
    let resurrected = (1000..2000)
        .filter(|&i| cache.get(&data::key(i)).is_some())
        .count();
    let untouched = (2000..3000)
        .filter(|&i| cache.get(&data::key(i)).is_some())
        .count();
    r.check(
        "segcache: delete removes exactly the deleted keys",
        deleted == 1000 && resurrected == 0 && untouched == 1000,
        format!("{deleted} deleted, {resurrected} still readable, {untouched}/1000 neighbours"),
    );

    segcache_expiry(r);
}

#[cfg(feature = "vclock")]
fn segcache_expiry(r: &mut Report) {
    use segcache::clock;
    // Each TTL in a fresh cache, so its segment is created at the insert.
    let ttls: Vec<u32> = (1..=300)
        .chain([2047, 2048, 2049, 2175, 2176, 32767, 32768])
        .collect();
    let mut bad = Vec::new();
    for (n, &ttl) in ttls.iter().enumerate() {
        let cache = Segcache::builder()
            .heap_size(4 * MIB)
            .build()
            .expect("build");
        let base = 1_000 + n as u32 * 40_000;
        clock::set_virtual_now(base);
        cache
            .insert(b"k", b"v", None, Duration::from_secs(ttl as u64))
            .expect("insert");
        let effective = model::segcache_effective_ttl(ttl);
        clock::set_virtual_now(base + effective - 1);
        let before = cache.get(b"k").is_some();
        clock::set_virtual_now(base + effective);
        let at = cache.get(b"k").is_some();
        if !(before && !at && effective <= ttl) {
            bad.push((ttl, effective, before, at));
        }
    }
    clock::clear_virtual_now();
    r.check(
        "segcache: for each TTL in 1..=300 s and 7 tier-boundary values, the first miss is at the modelled bucket floor, never after the TTL",
        bad.is_empty(),
        bad.first().map(|b| format!("first mismatch (ttl, modelled, hit before, hit at) {b:?}")).unwrap_or_default(),
    );
}

#[cfg(not(feature = "vclock"))]
fn segcache_expiry(r: &mut Report) {
    r.check(
        "segcache: expiry check",
        false,
        "built without --features vclock".into(),
    );
}

fn memcached_checks(r: &mut Report) -> std::io::Result<()> {
    let server = Server::spawn(&mc::default_binary(), &["-m", "1024"])?;
    let mut c = Client::connect(server.port)?;
    const N: u64 = 50_000;
    let mut replies = Vec::new();
    let mut refused = 0;
    for start in (0..N).step_by(100) {
        let keys: Vec<[u8; KEY_LEN]> = (start..start + 100).map(data::key).collect();
        let vals: Vec<Vec<u8>> = (start..start + 100)
            .map(|i| {
                let mut v = vec![0; mixed_size(i)];
                data::value(i, &mut v);
                v
            })
            .collect();
        let items: Vec<(&[u8], &[u8])> = keys
            .iter()
            .zip(&vals)
            .map(|(k, v)| (&k[..], &v[..]))
            .collect();
        c.set_many(&items, 0, &mut replies)?;
        refused += replies.iter().filter(|x| **x != SetReply::Stored).count();
    }
    let mut wrong = 0u64;
    let mut hits = 0u64;
    for start in (0..N).step_by(100) {
        let keys: Vec<[u8; KEY_LEN]> = (start..start + 100).map(data::key).collect();
        let refs: Vec<&[u8]> = keys.iter().map(|k| &k[..]).collect();
        c.get_many(&refs, |idx, v| {
            let i = start + idx as u64;
            let mut expect = vec![0; mixed_size(i)];
            data::value(i, &mut expect);
            hits += 1;
            wrong += (v != &expect[..]) as u64;
        })?;
    }
    let curr: u64 = c.stats("")?["curr_items"].parse().unwrap();
    r.check(
        "memcached: 50,000 sets of 1..=8192 B all stored, read back byte-exact, curr_items reconciles",
        refused == 0 && hits == N && wrong == 0 && curr == N,
        format!("{refused} refused, {hits} hits, {wrong} not byte-exact, curr_items {curr}"),
    );

    let deleted = (1000..2000)
        .filter(|&i| c.delete(&data::key(i)).unwrap())
        .count();
    let keys: Vec<[u8; KEY_LEN]> = (1000..3000).map(data::key).collect();
    let mut still = 0;
    let mut neighbours = 0;
    for chunk in keys.chunks(100) {
        let refs: Vec<&[u8]> = chunk.iter().map(|k| &k[..]).collect();
        c.get_many(&refs, |idx, _| {
            if chunk[idx] < data::key(2000) {
                still += 1
            } else {
                neighbours += 1
            }
        })?;
    }
    r.check(
        "memcached: delete removes exactly the deleted keys",
        deleted == 1000 && still == 0 && neighbours == 1000,
        format!("{deleted} deleted, {still} still readable, {neighbours}/1000 neighbours"),
    );

    c.set_many(&[(&b"ttl-key"[..], &b"v"[..])], 2, &mut replies)?;
    let mut before = false;
    c.get_many(&[&b"ttl-key"[..]], |_, _| before = true)?;
    std::thread::sleep(Duration::from_millis(3200));
    let mut after = false;
    c.get_many(&[&b"ttl-key"[..]], |_, _| after = true)?;
    r.check(
        "memcached: a 2 s TTL is readable at once and not after 3.2 s (wall clock)",
        before && !after,
        format!("at once {before}, +3.2 s {after}"),
    );
    server.stop()?;
    Ok(())
}

/// Two capacity runs with the same arguments must agree in every count.
fn capacity_determinism(r: &mut Report) {
    let bin = std::env::current_exe().unwrap().with_file_name("capacity");
    for args in [
        vec![
            "--backend",
            "segcache",
            "--value-size",
            "100",
            "--budget-mib",
            "8",
            "--hash-power",
            "20",
        ],
        vec![
            "--backend",
            "segcache",
            "--value-size",
            "100",
            "--budget-mib",
            "8",
            "--hash-power",
            "14",
        ],
        vec![
            "--backend",
            "memcached",
            "--value-size",
            "100",
            "--budget-mib",
            "8",
        ],
    ] {
        let run = || {
            let out = Command::new(&bin)
                .args(&args)
                .output()
                .expect("run capacity");
            assert!(
                out.status.success(),
                "capacity failed: {}",
                String::from_utf8_lossy(&out.stderr)
            );
            // Columns 7..=17: attempted through stored_at_first_hash_refusal.
            String::from_utf8(out.stdout)
                .unwrap()
                .trim()
                .split(',')
                .skip(7)
                .take(11)
                .collect::<Vec<_>>()
                .join(",")
        };
        let (a, b) = (run(), run());
        r.check(
            &format!("capacity is deterministic: {}", args.join(" ")),
            a == b,
            format!("{a} / {b}"),
        );
    }
}
