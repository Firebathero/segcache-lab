# Requires cargo (toolchain pinned in rust-toolchain.toml), a C toolchain,
# autotools and libevent for memcached, and python3 for experiment drivers.

BIN  := harness/target/release
VBIN := harness/target/vclock/release

.PHONY: fetch host build verify predict01 exp01

fetch:
	./scripts/fetch.sh
	./scripts/build-memcached.sh

host:
	./scripts/host.sh

build:
	cd harness && cargo build --release

# verify needs the engine's virtual clock, which adds a lookup to its read
# path, so it is built into a separate target directory from the measured
# binaries.
verify:
	cd harness && CARGO_TARGET_DIR=target/vclock cargo build --release --features vclock
	$(VBIN)/verify

predict01: build
	$(BIN)/predict --markdown

exp01: build verify
	python3 experiments/01-metadata-overhead/run.py
