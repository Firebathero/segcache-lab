# segcache-lab

Segcache (Yang, Yue, Rashmi, NSDI '21) studied by reading its current
implementation, measuring each mechanism against the paper's claims and
memcached 1.6, and changing it.

The engine under test is the `segcache` crate in
[pelikan-io/cache-rs](https://github.com/pelikan-io/cache-rs), driven
in-process. memcached runs as a native process. Every measurement drives
upstream code compiled from the commits in `notes/repos.md`.

Status: phase 0, sources pinned and host recorded. No measurements yet.
