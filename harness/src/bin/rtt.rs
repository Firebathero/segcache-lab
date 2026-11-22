//! Server CPU per request for memcached over loopback: the denominator for
//! a networked deployment, against which an engine's lookup cost is a share.
//!
//! Starts memcached with one worker thread, prefills it, then runs `clients`
//! connections for `secs` seconds, each sending gets for random present keys
//! in batches of `batch` keys per request line (batch 1 is one round trip per
//! get). Server CPU time comes from `ps -o time` before and after. Prints
//! `batch,clients,gets,elapsed_s,server_cpu_s,server_ns_per_get,client_gets_per_s`.

use lab::data::{self, KEY_LEN};
use lab::mc::{self, Client, Server};
use lab::Args;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant};

fn cpu_seconds(pid: u32) -> f64 {
    let out = std::process::Command::new("ps")
        .args(["-o", "time=", "-p", &pid.to_string()])
        .output()
        .expect("ps");
    // [[dd-]hh:]mm:ss.ss
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    s.split(':').fold(0.0, |acc, part| {
        acc * 60.0 + part.parse::<f64>().unwrap_or(0.0)
    })
}

fn main() {
    let a = Args::parse();
    let batch: usize = a.num("batch", 1);
    let clients: usize = a.num("clients", 8);
    let secs: f64 = a.num("secs", 5.0);
    let prefill: u64 = a.num("prefill", 100_000);
    let value_size: usize = a.num("value-size", 64);
    let server = Server::spawn(&mc::default_binary(), &["-m", "1024", "-t", "1"]).expect("spawn");
    let mut c = Client::connect(server.port).expect("connect");
    let mut replies = Vec::new();
    for start in (0..prefill).step_by(256) {
        let keys: Vec<[u8; KEY_LEN]> = (start..(start + 256).min(prefill)).map(data::key).collect();
        let vals: Vec<Vec<u8>> = keys.iter().map(|_| vec![0x5a; value_size]).collect();
        let items: Vec<(&[u8], &[u8])> = keys
            .iter()
            .zip(&vals)
            .map(|(k, v)| (&k[..], &v[..]))
            .collect();
        c.set_many(&items, 0, &mut replies).expect("prefill");
    }
    drop(c);

    let stop = AtomicBool::new(false);
    let gets = AtomicU64::new(0);
    let cpu0 = cpu_seconds(server.pid());
    let start = Instant::now();
    std::thread::scope(|s| {
        for t in 0..clients {
            let (stop, gets, port) = (&stop, &gets, server.port);
            s.spawn(move || {
                let mut c = Client::connect(port).expect("connect");
                let mut seed = 77 + t as u64;
                let mut done = 0u64;
                while !stop.load(Ordering::Relaxed) {
                    let keys: Vec<[u8; KEY_LEN]> = (0..batch)
                        .map(|_| data::key(data::splitmix64(&mut seed) % prefill))
                        .collect();
                    let refs: Vec<&[u8]> = keys.iter().map(|k| &k[..]).collect();
                    let mut hits = 0;
                    c.get_many(&refs, |_, _| hits += 1).expect("get");
                    assert_eq!(hits, batch, "every key is present");
                    done += batch as u64;
                }
                gets.fetch_add(done, Ordering::Relaxed);
            });
        }
        std::thread::sleep(Duration::from_secs_f64(secs));
        stop.store(true, Ordering::Relaxed);
    });
    let elapsed = start.elapsed().as_secs_f64();
    let cpu = cpu_seconds(server.pid()) - cpu0;
    let n = gets.load(Ordering::Relaxed);
    println!(
        "{batch},{clients},{n},{elapsed:.3},{cpu:.2},{:.0},{:.0}",
        cpu * 1e9 / n as f64,
        n as f64 / elapsed
    );
    server.stop().expect("stop");
}
