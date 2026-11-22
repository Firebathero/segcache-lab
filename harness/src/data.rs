//! Keys and values derived from an index, so a reader can regenerate the
//! expected bytes instead of storing them.

pub const KEY_LEN: usize = 16;

/// `k` followed by the index as 15 zero-padded decimal digits.
pub fn key(i: u64) -> [u8; KEY_LEN] {
    assert!(i < 1_000_000_000_000_000, "index does not fit in 15 digits");
    let mut k = [b'0'; KEY_LEN];
    k[0] = b'k';
    let mut n = i;
    for b in k[1..].iter_mut().rev() {
        *b = b'0' + (n % 10) as u8;
        n /= 10;
    }
    k
}

/// Fill `buf` with bytes determined by `seed` (splitmix64, little-endian).
pub fn value(seed: u64, buf: &mut [u8]) {
    let mut s = seed;
    for chunk in buf.chunks_mut(8) {
        let x = splitmix64(&mut s).to_le_bytes();
        chunk.copy_from_slice(&x[..chunk.len()]);
    }
}

pub fn splitmix64(s: &mut u64) -> u64 {
    *s = s.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *s;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}
