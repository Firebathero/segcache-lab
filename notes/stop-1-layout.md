# Stop 1: what one object costs

What each engine spends on one stored object, derived from source before any
measurement. Citations are `file:line` at the commits in `notes/repos.md`.
Paths under `crates/` are in cache-rs.

## Segcache (cache-rs `4620d7e`)

An object costs three things: its bytes inside a segment, one slot in the hash
table, and a share of a segment header.

### In the segment

- `ItemHeader` (`crates/keyvalue/src/item/header.rs:75`) is `klen: u8`,
  `flags: AtomicU8`, `vlen: [u8; 4]`. A compile-time assert fixes it at 6 B
  (`header.rs:87`). With the `integrity` feature it is 12 B (magic and CRC32).
- `flags` packs `is_numeric:1`, `is_deleted:1` and a 6-bit optional-data length.
  It is the only header byte written after publication, which is why it is
  atomic (`header.rs:56-73`).
- Footprint is `item_size_for` (`crates/keyvalue/src/item/mod.rs:42-45`), with
  `raw = 6 + olen + klen + vlen` and footprint `((raw >> 3) + 1) << 3`.
  `RawItem::size` (`crates/keyvalue/src/item/raw.rs:523-533`) uses the same
  formula on the scan path, so reservation and scanning agree.
- Byte-valued items carry nothing else. Numeric items add an alignment pad and
  an 8 B seqlock word.

### In the hash table

- `Hashbucket` (`crates/segcache/src/hashtable/bucket.rs:15-19`) is
  `#[repr(C, align(64))]`, eight `AtomicU64` slots, no metadata slot. Asserted
  64 B (`bucket.rs:24`).
- A slot is a 12-bit tag, an 8-bit frequency counter and a 44-bit location
  (`bucket.rs:12`). The location splits into an 18-bit segment id, a 6-bit
  incarnation tag and a 20-bit offset in 8 B units
  (`crates/segcache/src/hashtable/location.rs:20-28`, constants `:46-56`).
  That caps a segment at 2^23 B = 8 MiB (`location.rs:109`) and a heap at
  about 2^18 segments.
- Lookups probe two candidate buckets by default (`hashtable/table.rs:148`).
  There are no overflow chains. If every candidate bucket holds eight live
  entries, the insert fails (`table.rs:1326`), surfacing as
  `SegcacheError::HashTableInsertEx` (`crates/segcache/src/segcache.rs:847`,
  `:856`).
- The table is sized once, at construction: 2^`hash_power` buckets of 64 B.
  The default `hash_power` is 16 (`crates/segcache/src/builder.rs:20`), which
  gives 65,536 buckets, 524,288 slots and 4 MiB. It does not grow.

### Shared

- One 64 B `SegmentHeader` per segment, in a separate array
  (`crates/segcache/src/segments/header.rs:162`, assert `:191`;
  `segments/segments.rs:31`). The segment chain's prev and next ids are packed
  with the segment state into one `AtomicU64` (`header.rs:152`).
- Segment data is one anonymous mmap (`segments/segments.rs:186`). Defaults are
  1 MiB segments and a 64 MiB heap (`segments/builder.rs:19-26`).
- At 1 MiB segments the header share is 64 B divided by the objects in the
  segment, for example 0.003 B at 18,724 objects.

### Paper, C artifact and Rust side by side

| field | paper §3.4 (PDF p. 7) | C artifact `src/storage/seg/` | Rust `crates/keyvalue/` |
|---|---|---|---|
| key length | 8 bit | 8 bit (`item.h:70`) | 8 bit |
| value length | 24 bit | 24 bit (`item.h:71`) | 32 bit (`header.rs:80`) |
| flags | 8 bit | 8 bit (`item.h:76-78`) | 8 bit |
| header | 5 B | 5 B (`constant.h:41`, `offsetof(struct item, end)`) | 6 B (`header.rs:87`) |
| frequency counter | hash table (footnote 4) | hash table (`constant.h:48`) | hash slot, 8 bit |
| round-up to 8 | not stated | `(((sz - 1) >> 3) + 1) << 3` (`item.h:151`) | `((raw >> 3) + 1) << 3` (`mod.rs:44`) |

### The round-up differs from the C original

The two formulas agree unless `raw` is already a multiple of 8. Then C stores
`raw` bytes and Rust stores `raw + 8`. The Rust padding is 1 to 8 bytes
(mean 4.5 over uniformly distributed `raw mod 8`); the C padding is 0 to 7
(mean 3.5).

The Kani proof over this function asserts `size > raw_bytes` strictly
(`mod.rs:98`), so the proof checks the formula as written; an exact round-up
would fail it. Nothing read so far depends on a strictly positive gap after an
item. Whether anything does is an open question, to be answered by changing the
formula and running cache-rs's own test, fuzz and shuttle suites.

With 16 B keys and no optional data, `raw = 22 + vlen`, so the extra 8 B occur
when `vlen ≡ 2 (mod 8)`. Power-of-two value sizes never hit it.

### What "5 bytes" means for a stored object

The paper's 5 B excludes the hash-table slot and frequency counter (§3.4
footnote 4, PDF p. 7). For the Rust engine at the same scope, the figure is 6 B
plus 1 to 8 B of alignment. Each object also occupies one 8 B slot in a table
whose size is fixed in advance. The index share is `64 · 2^p / N` bytes per
object for N objects, and `p` has to be large enough that two-choice placement
never finds both buckets full at N. That makes the index share at least 8 B,
and higher in practice. Experiment 01 measures it.

## memcached (1.6.45)

- `struct _stritem` (`memcached.h:613-636`): `next`, `prev`, `h_next`
  (3 × 8 B), `time`, `exptime` (2 × 4 B), `nbytes` (4 B), `refcount` (2 B),
  `it_flags` (2 B), `slabs_clsid` (1 B) and `nkey` (1 B). 42 B of fields, and
  `sizeof(item)` is 48 on arm64, checked by compiling against the pinned header.
- `item_make_header` (`items.c:152-160`) returns
  `sizeof(item) + (nkey + 1) + nsuffix + nbytes`. `nsuffix` is 0 when the client
  flags are 0 and 4 otherwise (`items.c:154-158`). `nbytes` includes the
  trailing `\r\n`. CAS adds 8 B when enabled (`items.c:259-261`), which is the
  default (`memcached.c:217`).
- With flags 0 and CAS on, the item is `vlen + klen + 59` B: a 48 B struct, 8 B
  CAS, a 1 B key terminator and 2 B of CRLF. With `-C` it is `vlen + klen + 51`.
- Slab classes (`slabs.c:202-262`) start at `sizeof(item) + chunk_size`
  = 48 + 48 = 96 B (`memcached.c:232`). Each class is the previous one × the
  factor (default 1.25, `memcached.c:231`), aligned up to 8 (`slabs.c:252-253`),
  until `slab_chunk_size_max / factor` (`slabs.c:248`). A class holds
  `page_size / size` chunks (`slabs.c:256`), and an item takes a chunk in the
  smallest class that fits. At factor 1.25, up to about 20% of a chunk is
  unused.
- The hash table is a separate `calloc` of `2^hashpower` pointers
  (`assoc.c:59`). It starts at 2^16 buckets and doubles when the item count
  exceeds 1.5 × buckets (`assoc.c:145`). It is not counted against `-m`. Per
  object it costs `8 / load` B with load in (0.75, 1.5], which is 5.3 to
  10.7 B.

### The paper's 56 B

§2.2 (PDF p. 4) gives 56 B per object. Footnote 3 lists 2 × 8 B LRU pointers,
8 B hash pointer, 4 B access time, 4 B expire time, 8 B object size and 8 B CAS.
Those fields sum to 48 B. The 1.6.45 struct plus CAS is 48 + 8 = 56 B, so the
total matches the code even though the itemisation does not: `nbytes` is 4 B,
and `refcount`, `it_flags`, `slabs_clsid` and `nkey` are not listed.

## Drift between cache-rs's documentation and its code

`docs/segcache.md` at `4620d7e` disagrees with the code in four places:

- It describes a 5 B item header with a 24-bit value length (`:17`). The code
  has 6 B and a 32-bit length (`header.rs:75-87`).
- Its "Threading Model" section (`:153`) says the engine is single-threaded with
  `&mut self` on every operation. The engine is concurrent with a `&self` API
  (`segcache.rs:270`, `:610`).
- It draws the segment header with separate 32-bit prev and next fields (`:46`).
  They are packed with state into one word (`header.rs:152`).
- It states an 88% metadata reduction compared to Memcached (`:5`). The paper
  states 91% (§3.4, PDF p. 7).

## Carried forward

- Prediction for experiment 01: `experiments/01-metadata-overhead/PREDICTION.md`.
- Open: does anything depend on the strictly positive post-item gap? This is
  the first candidate change.
- Open: how does a 64 B bucket and segment-header layout behave against a 128 B
  reported cache line (`env/host.md`)? Deferred to the hot-path work.
