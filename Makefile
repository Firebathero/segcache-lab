.PHONY: fetch host

fetch:
	./scripts/fetch.sh
	./scripts/build-memcached.sh

host:
	./scripts/host.sh
