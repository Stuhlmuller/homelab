#!/usr/bin/env python3
"""Run affected probe blocks offline; only an explicit zero may skip AFFiNE."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'octelium-e2e-check.sh').read_text()
assignment = source[source.index('AFFINE_SUSPENDED="$(', source.index('note "Checking local tools"')):source.index('note "Checking Kubernetes control-plane and connector state"')]
probes = source[source.index('note "Checking public app and Enterprise console hostnames"'):source.index('note "Checking public callback hostnames"')]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'scripts').mkdir()
    deployment = root / 'clusters/homelab/apps/affine/deployment.yaml'
    deployment.parent.mkdir(parents=True)
    check = root / 'scripts/check.sh'
    for value, expected in [('0', 0), ('1', 4), ('', 4), ('"0"', 4)]:
        deployment.write_text(f'spec:\n  replicas: {value}\n' if value else 'spec: {}\n')
        calls = root / 'calls'
        calls.write_text('')
        check.write_text('''#!/usr/bin/env bash
set -euo pipefail
AFFINE_HOST=affine.stinkyboi.com
NOFX_HOST=nofx.stinkyboi.com
APP_HOSTS=$'affine.stinkyboi.com\\ndispatcharr.stinkyboi.com\\ngrafana.stinkyboi.com'
TEST_PATH=/
FAILURES=0
note() { :; }
pass() { :; }
fail() { FAILURES=$((FAILURES + 1)); }
dig() { if [ "${4}" = A ]; then echo 203.0.113.5; fi; }
curl() {
  printf '%s\\n' "$*" >> 'CALL_FILE'
  local header='' body='' format='' payload='' url=''
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -D) header="$2"; shift 2 ;;
      -o) body="$2"; shift 2 ;;
      -w) format="$2"; shift 2 ;;
      --data-binary) payload="$2"; shift 2 ;;
      https:*) url="$1"; shift ;;
      *) shift ;;
    esac
  done
  printf 'access-control-allow-origin: assets://.\\naccess-control-allow-methods: POST\\naccess-control-allow-headers: content-type,x-affine-version,x-operation-name\\nx-octelium-unauthorized: true\\n' > "$header"
  if [[ "$payload" == *getWorkspaces* ]]; then
    printf '{"data":null,"errors":[{"extensions":{"status":401,"type":"AUTHENTICATION_REQUIRED"}}]}' > "$body"
  else
    printf '{"data":{"serverConfig":{"baseUrl":"https://affine.stinkyboi.com"}}}' > "$body"
  fi
  if [[ "$url" == https://affine.* ]]; then printf 200; else printf 401; fi
  if [[ "$format" == *remote_ip* ]]; then printf ' 203.0.113.5'; fi
}
'''.replace('CALL_FILE', str(calls)) + assignment + probes + '\n[ "$FAILURES" -eq 0 ]\n')
        result = subprocess.run(['bash', str(check)], capture_output=True, text=True)
        assert result.returncode == 0, (value, result.stdout, result.stderr)
        observed = calls.read_text().splitlines()
        assert sum('https://affine.' in call for call in observed) == expected, (value, observed)
        assert sum('https://dispatcharr.' in call for call in observed) == 1, observed
        assert sum('https://grafana.' in call for call in observed) == 1, observed
        assert sum('https://nofx.' in call for call in observed) == 2, observed
    deployment.unlink()
    result = subprocess.run(['bash', str(check)], capture_output=True, text=True)
    assert result.returncode != 0, 'missing desired state must fail closed'
print('AFFiNE suspension probes: zero skips only AFFiNE runtime; one/missing/string replicas probe; other apps and NOFX auth preserved; missing file fails')
