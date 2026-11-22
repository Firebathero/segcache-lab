//! Shared pieces of the harness: deterministic keys and values, the
//! source-derived capacity model, and a minimal memcached client.

pub mod data;
pub mod mc;
pub mod model;

use std::io;

/// Resident set size of a process in bytes, read with `ps`. Both engines are
/// measured with the same tool so their numbers are comparable.
pub fn rss_bytes(pid: u32) -> io::Result<u64> {
    let out = std::process::Command::new("ps")
        .args(["-o", "rss=", "-p", &pid.to_string()])
        .output()?;
    let kib: u64 = String::from_utf8_lossy(&out.stdout)
        .trim()
        .parse()
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    Ok(kib * 1024)
}

/// Minimal `--name value` argument parsing: the harness binaries take a
/// handful of flags and no positional arguments.
pub struct Args(Vec<(String, String)>);

impl Args {
    pub fn parse() -> Self {
        let mut out = Vec::new();
        let mut it = std::env::args().skip(1);
        while let Some(flag) = it.next() {
            let name = flag
                .strip_prefix("--")
                .unwrap_or_else(|| panic!("unexpected argument {flag}"))
                .to_string();
            let value = it.next().unwrap_or_default();
            out.push((name, value));
        }
        Args(out)
    }

    pub fn get(&self, name: &str) -> Option<&str> {
        self.0
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, v)| v.as_str())
    }

    pub fn all(&self, name: &str) -> Vec<&str> {
        self.0
            .iter()
            .filter(|(n, _)| n == name)
            .map(|(_, v)| v.as_str())
            .collect()
    }

    pub fn num<T: std::str::FromStr>(&self, name: &str, default: T) -> T {
        match self.get(name) {
            Some(v) => v
                .parse()
                .unwrap_or_else(|_| panic!("--{name}: cannot parse {v}")),
            None => default,
        }
    }
}
