#!/usr/bin/env python3
"""Refresh v5 population from staged source and hash the fixed evidence envelope."""
import hashlib
import json
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'scripts/soc2-evidence-verify.py'))
PACKET = MODULE['PACKET']
ENVELOPE = MODULE['ENVELOPE']
entries = []
for row in subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0'):
    if not row:
        continue
    meta, path = row.split(b'\t', 1)
    mode, oid, stage = meta.decode().split()
    if stage != '0':
        raise ValueError('Unmerged index')
    path = path.decode()
    if path not in ENVELOPE:
        data = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT)
        entries.append([path, mode, 'blob', oid, hashlib.sha256(data).hexdigest()])
(ROOT / PACKET / 'population.json').write_text(json.dumps({'schema_version': 1, 'entries': entries}, indent=2) + '\n')
lines = [hashlib.sha256((ROOT / path).read_bytes()).hexdigest() + '  ' + path
         for path in sorted(ENVELOPE - {PACKET + 'SHA256SUMS'})]
(ROOT / PACKET / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
print(f'Prepared {len(entries)} source paths plus {len(ENVELOPE)} envelope paths; stage envelope before testing')
