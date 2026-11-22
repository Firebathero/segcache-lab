#!/usr/bin/env bash
# Print the host description recorded in env/host.md. Read-only.
set -euo pipefail
s() { sysctl -n "$1" 2>/dev/null || echo n/a; }
mib() { awk -v b="$1" 'BEGIN { printf "%d KiB", b / 1024 }'; }
echo "| property | value |"
echo "|---|---|"
echo "| collected | $(date -u +%Y-%m-%dT%H:%M:%SZ) |"
echo "| cpu | $(s machdep.cpu.brand_string) |"
echo "| logical cpus | $(s hw.ncpu) |"
for l in 0 1; do
  name=$(s hw.perflevel$l.name)
  echo "| perflevel$l ($name) | $(s hw.perflevel$l.physicalcpu) cores, L1d $(mib "$(s hw.perflevel$l.l1dcachesize)"), L2 $(mib "$(s hw.perflevel$l.l2cachesize)") shared per $(s hw.perflevel$l.cpusperl2) cpus |"
done
echo "| cache line | $(s hw.cachelinesize) B |"
echo "| page size | $(s hw.pagesize) B |"
echo "| memory | $(( $(s hw.memsize) / 1073741824 )) GiB |"
echo "| os | macOS $(sw_vers -productVersion) ($(sw_vers -buildVersion)), $(uname -srm) |"
echo "| power | $(pmset -g batt | head -1 | sed "s/Now drawing from //; s/'//g"), powermode $(pmset -g | awk '/powermode/ {print $2}') (0 automatic, 1 low, 2 high) |"
echo "| rustc | $(rustc -V) |"
echo "| cc | $(cc --version | head -1) |"
echo "| libevent | $(pkg-config --modversion libevent 2>/dev/null || echo n/a) |"
echo "| memcached | $(repos/memcached/memcached -V) |"
