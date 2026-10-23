#!/usr/bin/env bash
# Read-only compute host CPU counters for an S1 baseline interval.
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${PROJECT_ROOT}/scripts/lib/common.sh"

host="${1:?compute host is required}"
[[ "${host}" =~ ^osk8s-compute[0-9]+$ ]] || die "invalid compute host name"
run_on "${host}" bash -s <<'REMOTE'
set -Eeuo pipefail
python3 - <<'PY'
import datetime, json, pathlib
cpu_line = next(line for line in pathlib.Path('/proc/stat').read_text().splitlines()
                if line.startswith('cpu '))
fields = [int(value) for value in cpu_line.split()[1:9]]
load = pathlib.Path('/proc/loadavg').read_text().split()
pressure = pathlib.Path('/proc/pressure/cpu').read_text().splitlines()
memory = {line.split(':')[0]: int(line.split()[1]) * 1024
          for line in pathlib.Path('/proc/meminfo').read_text().splitlines()
          if line.startswith(('MemAvailable:', 'MemTotal:'))}
print(json.dumps({'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'cpu_ticks': fields, 'load_average': [float(value) for value in load[:3]],
                  'cpu_pressure': pressure, 'memory': memory,
                  'memory_pressure': pathlib.Path('/proc/pressure/memory').read_text().splitlines(),
                  'io_pressure': pathlib.Path('/proc/pressure/io').read_text().splitlines()}))
PY
REMOTE
