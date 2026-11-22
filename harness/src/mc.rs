//! A memcached process on loopback and a minimal text-protocol client.

use std::collections::HashMap;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Path of the memcached binary built by scripts/build-memcached.sh,
/// relative to the repository root.
pub fn default_binary() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../repos/memcached/memcached")
}

pub struct Server {
    child: Child,
    pub port: u16,
}

impl Server {
    /// Start memcached on 127.0.0.1 with a free TCP port and UDP disabled.
    /// `args` are appended after the address flags.
    pub fn spawn(binary: &Path, args: &[&str]) -> io::Result<Server> {
        let port = TcpListener::bind("127.0.0.1:0")?.local_addr()?.port();
        let child = Command::new(binary)
            .args(["-l", "127.0.0.1", "-p", &port.to_string(), "-U", "0"])
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()?;
        Ok(Server { child, port })
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    /// Stop the server and return what it wrote to stderr.
    pub fn stop(mut self) -> io::Result<String> {
        self.child.kill()?;
        let mut err = String::new();
        if let Some(mut s) = self.child.stderr.take() {
            s.read_to_string(&mut err)?;
        }
        self.child.wait()?;
        Ok(err)
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SetReply {
    Stored,
    OutOfMemory,
    Other,
}

pub struct Client {
    reader: BufReader<TcpStream>,
    writer: TcpStream,
    wbuf: Vec<u8>,
    line: Vec<u8>,
}

impl Client {
    /// Connect, retrying while the server starts.
    pub fn connect(port: u16) -> io::Result<Client> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let stream = loop {
            match TcpStream::connect(("127.0.0.1", port)) {
                Ok(s) => break s,
                Err(e) if Instant::now() > deadline => return Err(e),
                Err(_) => std::thread::sleep(Duration::from_millis(10)),
            }
        };
        stream.set_nodelay(true)?;
        Ok(Client {
            reader: BufReader::with_capacity(1 << 20, stream.try_clone()?),
            writer: stream,
            wbuf: Vec::with_capacity(1 << 20),
            line: Vec::with_capacity(256),
        })
    }

    fn read_line(&mut self) -> io::Result<&[u8]> {
        self.line.clear();
        self.reader.read_until(b'\n', &mut self.line)?;
        if !self.line.ends_with(b"\r\n") {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "short line"));
        }
        let n = self.line.len() - 2;
        Ok(&self.line[..n])
    }

    /// Pipeline one `set` per item, then read every reply in order.
    pub fn set_many(
        &mut self,
        items: &[(&[u8], &[u8])],
        exptime: u32,
        replies: &mut Vec<SetReply>,
    ) -> io::Result<()> {
        self.wbuf.clear();
        for (k, v) in items {
            self.wbuf.extend_from_slice(b"set ");
            self.wbuf.extend_from_slice(k);
            write!(self.wbuf, " 0 {} {}\r\n", exptime, v.len())?;
            self.wbuf.extend_from_slice(v);
            self.wbuf.extend_from_slice(b"\r\n");
        }
        self.writer.write_all(&self.wbuf)?;
        replies.clear();
        for _ in items {
            let line = self.read_line()?;
            replies.push(match line {
                b"STORED" => SetReply::Stored,
                l if l.starts_with(b"SERVER_ERROR out of memory") => SetReply::OutOfMemory,
                _ => SetReply::Other,
            });
        }
        Ok(())
    }

    /// One multi-key `get`. Calls `hit(index_in_keys, value)` for each key
    /// returned; keys come back in request order with misses omitted.
    pub fn get_many(
        &mut self,
        keys: &[&[u8]],
        mut hit: impl FnMut(usize, &[u8]),
    ) -> io::Result<()> {
        self.wbuf.clear();
        self.wbuf.extend_from_slice(b"get");
        for k in keys {
            self.wbuf.push(b' ');
            self.wbuf.extend_from_slice(k);
        }
        self.wbuf.extend_from_slice(b"\r\n");
        self.writer.write_all(&self.wbuf)?;
        let mut next = 0usize;
        let mut value = Vec::new();
        loop {
            let line = self.read_line()?.to_vec();
            if line == b"END" {
                return Ok(());
            }
            let text = std::str::from_utf8(&line)
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
            let mut f = text.split(' ');
            let (Some("VALUE"), Some(k), Some(_flags), Some(len)) =
                (f.next(), f.next(), f.next(), f.next())
            else {
                return Err(io::Error::new(io::ErrorKind::InvalidData, text.to_string()));
            };
            let len: usize = len
                .parse()
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
            value.resize(len + 2, 0);
            self.reader.read_exact(&mut value)?;
            while next < keys.len() && keys[next] != k.as_bytes() {
                next += 1;
            }
            if next == keys.len() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "unrequested key",
                ));
            }
            hit(next, &value[..len]);
            next += 1;
        }
    }

    /// `delete`; true when the server replied `DELETED`.
    pub fn delete(&mut self, key: &[u8]) -> io::Result<bool> {
        self.wbuf.clear();
        self.wbuf.extend_from_slice(b"delete ");
        self.wbuf.extend_from_slice(key);
        self.wbuf.extend_from_slice(b"\r\n");
        self.writer.write_all(&self.wbuf)?;
        Ok(self.read_line()? == b"DELETED")
    }

    /// `stats` or `stats <sub>` as a name-to-value map.
    pub fn stats(&mut self, sub: &str) -> io::Result<HashMap<String, String>> {
        let cmd = if sub.is_empty() {
            "stats\r\n".to_string()
        } else {
            format!("stats {sub}\r\n")
        };
        self.writer.write_all(cmd.as_bytes())?;
        let mut out = HashMap::new();
        loop {
            let line = String::from_utf8_lossy(self.read_line()?).into_owned();
            if line == "END" {
                return Ok(out);
            }
            let mut f = line.splitn(3, ' ');
            if let (Some("STAT"), Some(k), Some(v)) = (f.next(), f.next(), f.next()) {
                out.insert(k.to_string(), v.to_string());
            }
        }
    }
}

/// Parse the `slab class N: chunk size X perslab Y` lines memcached prints
/// at startup with `-vv`.
pub fn parse_slab_table(stderr: &str) -> Vec<crate::model::SlabClass> {
    stderr
        .lines()
        .filter_map(|l| {
            let rest = l.strip_prefix("slab class")?;
            let mut nums = rest
                .split(|c: char| !c.is_ascii_digit())
                .filter(|s| !s.is_empty())
                .map(|s| s.parse::<u32>().ok());
            Some(crate::model::SlabClass {
                id: nums.next()??,
                size: nums.next()??,
                perslab: nums.next()??,
            })
        })
        .collect()
}
