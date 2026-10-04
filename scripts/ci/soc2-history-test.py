#!/usr/bin/env python3
"""Reject semantically incomplete history even after regeneration and commit."""
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = 'docs/compliance/soc2/evidence/HOME-30-v6/'
BASE = '2be233ffce44495ab63e5c1b3d349eeb795c28b6'


def command(args, cwd, env=None, expected=0):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if (result.returncode == 0) != (expected == 0):
        raise RuntimeError('Unexpected result for ' + repr(args) + ': ' + result.stdout + result.stderr)
    return result.stdout.strip(), result.stderr


def main():
    env = dict(os.environ, GIT_AUTHOR_NAME='Evidence fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
               GIT_COMMITTER_NAME='Evidence fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
    tree, _ = command(['git', 'write-tree'], ROOT)
    squash, _ = command(['git', 'commit-tree', tree, '-p', BASE, '-m', 'Synthetic history fixture'], ROOT, env)
    with tempfile.TemporaryDirectory(prefix='soc2-history-') as temporary:
        clone = Path(temporary)
        command(['git', 'init', '-q'], clone)
        command(['git', 'fetch', '--quiet', '--no-tags', 'file://' + str(ROOT), squash], clone)
        command(['git', 'checkout', '--quiet', '--detach', 'FETCH_HEAD'], clone)
        original = json.loads((clone / PACKET / 'history.json').read_text())
        cases = {}
        for version in (1, 2, 3):
            case = copy.deepcopy(original)
            case['packets'] = [p for p in case['packets'] if p['version'] != version]
            cases[f'missing-v{version}'] = case
        cases['empty'] = {'schema_version': 1, 'packets': [], 'objects': {}}
        case = copy.deepcopy(original)
        case['packets'][1] = copy.deepcopy(case['packets'][0])
        cases['duplicate'] = case
        for field in ('version', 'revision', 'tree', 'manifest', 'manifest_sha256'):
            case = copy.deepcopy(original)
            case['packets'][0][field] = 4 if field == 'version' else case['packets'][1][field]
            cases['substituted-' + field] = case
        case = copy.deepcopy(original)
        case['packets'][0] = dict(case['packets'][1], version=1)
        cases['substituted-coherent-packet'] = case
        case = copy.deepcopy(original)
        del case['packets']
        cases['missing-packets-key'] = case
        case = copy.deepcopy(original)
        case['objects'] = {}
        cases['empty-objects'] = case
        # QA's exact nonsecret payload: correct digest, but outside every proof.
        payload = b'SYNTHETIC NONSECRET UNRELATED QA OBJECT\n'
        extra_oid = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        extra = {'type': 'blob', 'base64': base64.b64encode(payload).decode()}
        case = copy.deepcopy(original)
        case['objects'][extra_oid] = extra
        cases['qa-extra-object'] = case
        case = copy.deepcopy(original)
        empty_tree = hashlib.sha1(b'tree 0\0').hexdigest()
        case['objects'][empty_tree] = {'type': 'tree', 'base64': ''}
        cases['extra-tree'] = case
        root_oid = original['packets'][0]['tree']
        blob_oid = next(oid for oid, record in original['objects'].items() if record['type'] == 'blob')
        for name, oid in [('root', root_oid), ('blob', blob_oid)]:
            case = copy.deepcopy(original)
            del case['objects'][oid]
            cases['missing-' + name + '-object'] = case
        case = copy.deepcopy(original)
        del case['objects'][blob_oid]
        case['objects'][extra_oid] = extra
        cases['same-count-substitution'] = case
        modes = [([], {}), (['-O'], {}), ([], {'PYTHONOPTIMIZE': '1'})]
        checks = 0
        # A valid reordered packet set must remain acceptable after regeneration.
        valid = copy.deepcopy(original)
        valid['packets'].reverse()
        cases = {'valid-clean': original, 'valid-reordered': valid, **cases}
        for name, history in cases.items():
            (clone / PACKET / 'history.json').write_text(json.dumps(history, indent=2) + '\n')
            command([sys.executable, 'scripts/soc2-evidence-index.py'], clone)
            command(['git', 'add', PACKET], clone)
            command(['git', 'commit', '--allow-empty', '-qm', 'Synthetic ' + name], clone, env)
            for flags, extra in modes:
                mode_env = dict(os.environ)
                mode_env.pop('PYTHONOPTIMIZE', None)
                mode_env.update(extra)
                for script in ['scripts/soc2-evidence-verify.py',
                               'docs/compliance/soc2/evidence/HOME-30-v2/verify.py',
                               'docs/compliance/soc2/evidence/HOME-30-v3/verify.py']:
                    _, error = command([sys.executable, *flags, script], clone,
                                       mode_env, expected=0 if name.startswith('valid-') else 1)
                    if not name.startswith('valid-') and not any(message in error for message in (
                            'historical packet', 'historical binding', 'historical objects',
                            'historical proof object', 'historical archive contains objects')):
                        raise RuntimeError('Fixture rejected for unrelated reason: ' + error)
                    checks += 1
        print(f'PASS: {checks} checks, {len(cases) - 2} regenerated/committed negative histories; normal/-O/PYTHONOPTIMIZE=1')


if __name__ == '__main__':
    main()
