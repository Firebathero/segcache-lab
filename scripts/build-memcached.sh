#!/usr/bin/env bash
# Build memcached from the pinned checkout. libevent location is taken from
# pkg-config, falling back to Homebrew's prefix on macOS.
set -euo pipefail
cd "$(dirname "$0")/../repos/memcached"
[ -x memcached ] && ./memcached -V | grep -q '^memcached 1.6.45$' && exit 0
libevent=$(pkg-config --variable=prefix libevent 2>/dev/null || brew --prefix libevent)
./autogen.sh >/dev/null
./configure --with-libevent="$libevent" --disable-docs >/dev/null
make -j"$(getconf _NPROCESSORS_ONLN)" memcached >/dev/null
./memcached -V
