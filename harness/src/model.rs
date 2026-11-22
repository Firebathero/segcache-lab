//! Capacity model derived from source; see notes/stop-1-layout.md. `verify`
//! checks it against `keyvalue::item_size` and against the slab table
//! memcached prints, so predictions are made with checked code.

pub const MIB: usize = 1 << 20;

/// Segcache item footprint: `crates/keyvalue/src/item/mod.rs:42-45`.
pub fn segcache_item(klen: usize, vlen: usize) -> usize {
    let raw = keyvalue::ITEM_HDR_SIZE + klen + vlen;
    ((raw >> 3) + 1) << 3
}

/// The same header with the C artifact's exact round-up
/// (`src/storage/seg/item.h:151`).
pub fn segcache_item_exact(klen: usize, vlen: usize) -> usize {
    let raw = keyvalue::ITEM_HDR_SIZE + klen + vlen;
    raw.div_ceil(8) * 8
}

/// Objects stored before the first refusal under `Policy::None`, assuming
/// every segment holds `floor(segment / item)` objects and the index never
/// refuses an insert.
pub fn segcache_capacity(heap: usize, segment: usize, item: usize) -> usize {
    (heap / segment) * (segment / item)
}

/// Bytes memcached allocates for one item: `items.c:152-160`, `:259-261`.
/// Client flags are 0, so no flags suffix. `vlen + 2` is `nbytes` with CRLF.
pub fn memcached_item(klen: usize, vlen: usize, cas: bool) -> usize {
    48 + (klen + 1) + (vlen + 2) + if cas { 8 } else { 0 }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SlabClass {
    pub id: u32,
    pub size: u32,
    pub perslab: u32,
}

/// memcached's slab classes, transcribed from `slabs_init` (`slabs.c:202-268`)
/// with sizeof(item) = 48, chunk_size = 48, 1 MiB pages and
/// slab_chunk_size_max = page / 2.
pub fn memcached_classes(factor: f64) -> Vec<SlabClass> {
    const PAGE: u32 = 1 << 20;
    const CHUNK_MAX: u32 = PAGE / 2;
    const MAX_CLASSES: i32 = 63 + 1;
    let mut out = Vec::new();
    let mut size: u32 = 48 + 48;
    let mut i: i32 = 0;
    loop {
        i += 1;
        if i >= MAX_CLASSES - 1 || f64::from(size) >= f64::from(CHUNK_MAX) / factor {
            break;
        }
        if !size.is_multiple_of(8) {
            size += 8 - size % 8;
        }
        out.push(SlabClass {
            id: i as u32,
            size,
            perslab: PAGE / size,
        });
        size = (f64::from(size) * factor) as u32;
    }
    out.push(SlabClass {
        id: i as u32,
        size: CHUNK_MAX,
        perslab: PAGE / CHUNK_MAX,
    });
    out
}

/// The class an item of `ntotal` bytes is stored in.
pub fn memcached_class(classes: &[SlabClass], ntotal: usize) -> SlabClass {
    *classes
        .iter()
        .find(|c| c.size as usize >= ntotal)
        .expect("item larger than the largest slab class")
}

/// Objects stored before the first refusal under `-M`, assuming every 1 MiB
/// page of the budget goes to the item's class.
pub fn memcached_capacity(budget: usize, class: SlabClass) -> usize {
    (budget / MIB) * class.perslab as usize
}

/// Load (stored / slots) at the first refused insert, for a table of
/// `buckets` buckets of `slots` slots with two independent uniform choices
/// per key. `least_loaded` false is first-fit in choice order, the policy at
/// `hashtable/table.rs:1304-1310`; true places in the emptier bucket.
/// An idealised model: real placement uses one 64-bit hash, not two
/// independent draws.
pub fn first_refusal_load(buckets: usize, slots: u8, least_loaded: bool, seed: u64) -> f64 {
    let mut load = vec![0u8; buckets];
    let mut s = seed;
    let mut n = 0usize;
    loop {
        let a = (crate::data::splitmix64(&mut s) % buckets as u64) as usize;
        let b = (crate::data::splitmix64(&mut s) % buckets as u64) as usize;
        let t = if least_loaded {
            if load[a] <= load[b] {
                a
            } else {
                b
            }
        } else if load[a] < slots {
            a
        } else {
            b
        };
        if load[t] >= slots {
            return n as f64 / (buckets * slots as usize) as f64;
        }
        load[t] += 1;
        n += 1;
    }
}

/// The lifetime segcache gives a TTL of `secs`: the floor of its TTL bucket,
/// `ttl_buckets/ttl_buckets.rs:27-35` (tiers) and `:61` (`width * j`, at
/// least 1). Zero means no expiry and maps to the last bucket.
pub fn segcache_effective_ttl(secs: u32) -> u32 {
    const SHIFTS: [u32; 4] = [3, 7, 11, 15];
    if secs == 0 {
        return (1 << SHIFTS[3]) * 255;
    }
    for shift in &SHIFTS[..3] {
        if secs < 1 << (shift + 8) {
            return ((secs >> shift) << shift).max(1);
        }
    }
    (secs >> SHIFTS[3]).min(255) << SHIFTS[3]
}

/// Insert outcomes by slot load for the placement model, in 0.5% bins:
/// `(attempts, refusals)` per bin, filling until every slot is taken or
/// 4096 consecutive inserts are refused.
pub fn refusal_curve(buckets: usize, slots: u8, least_loaded: bool, seed: u64) -> Vec<(u64, u64)> {
    let mut load = vec![0u8; buckets];
    let total = (buckets * slots as usize) as u64;
    let mut curve = vec![(0u64, 0u64); 201];
    let mut s = seed;
    let (mut stored, mut consecutive) = (0u64, 0u64);
    while stored < total && consecutive <= 4096 {
        let bin = (stored * 200 / total).min(200) as usize;
        let a = (crate::data::splitmix64(&mut s) % buckets as u64) as usize;
        let b = (crate::data::splitmix64(&mut s) % buckets as u64) as usize;
        let t = if least_loaded {
            if load[a] <= load[b] {
                a
            } else {
                b
            }
        } else if load[a] < slots {
            a
        } else {
            b
        };
        curve[bin].0 += 1;
        if load[t] >= slots {
            curve[bin].1 += 1;
            consecutive += 1;
        } else {
            load[t] += 1;
            stored += 1;
            consecutive = 0;
        }
    }
    curve
}
