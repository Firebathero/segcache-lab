# Requires cargo (toolchain pinned in rust-toolchain.toml), a C toolchain,
# autotools and libevent for memcached, and python3 for experiment drivers.

BIN  := harness/target/release
VBIN := harness/target/vclock/release

.PHONY: fetch host build verify predict01 exp01 vm cachegrind samply

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

# Profiling. Exact counts come from cachegrind in an arm64 Linux guest (valgrind
# does not run on macOS arm64); call stacks and wall time from samply, natively.
VM := segprof
LAB := $(CURDIR)

vm:
	limactl create --name=$(VM) --cpus=4 --memory=4 --disk=12 --vm-type=vz \
	  --mount-only $(LAB):w --containerd=none --tty=false template:ubuntu-24.04
	limactl start $(VM) --tty=false
	limactl shell $(VM) -- bash $(LAB)/scripts/vm-provision.sh

cachegrind:
	limactl shell $(VM) -- bash -lc 'cd $(LAB) && scripts/profile-all.sh'

# make samply OP=get-hit   (records, then opens the Firefox Profiler locally)
OP ?= get-hit
samply: build
	mkdir -p profiles/samply
	samply record --save-only --rate 4000 -o profiles/samply/$(OP).json.gz -- \
	  $(BIN)/profile --op $(OP) --n 2000000 --repeat 5
	samply load profiles/samply/$(OP).json.gz
