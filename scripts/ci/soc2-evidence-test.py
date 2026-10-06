#!/usr/bin/env python3
"""Exercise a fresh squash clone and evidence corruption with optimization on/off."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '2be233ffce44495ab63e5c1b3d349eeb795c28b6'
PACKET = 'docs/compliance/soc2/evidence/HOME-30-v6/'


def run(args, cwd=ROOT, **kwargs):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kwargs)


def checked(args, cwd=ROOT, **kwargs):
    result = run(args, cwd, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def main():
    tree = checked(['git', 'write-tree'])
    env = dict(os.environ, GIT_AUTHOR_NAME='Evidence fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
               GIT_COMMITTER_NAME='Evidence fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
    squash = checked(['git', 'commit-tree', tree, '-p', BASE, '-m', 'Synthetic squash fixture'], env=env)
    count = 0
    with tempfile.TemporaryDirectory(prefix='soc2-fixture-') as temporary:
        clone = Path(temporary)
        checked(['git', 'init', '-q'], clone)
        checked(['git', 'fetch', '--quiet', '--no-tags', 'file://' + str(ROOT), squash], clone)
        checked(['git', 'checkout', '--quiet', '--detach', 'FETCH_HEAD'], clone)
        historical = json.loads((clone / PACKET / 'history.json').read_text())
        for packet in historical['packets']:
            if run(['git', 'cat-file', '-e', packet['revision']], clone).returncode == 0:
                raise RuntimeError('Historical PR commit unexpectedly present')
        if run(['git', 'cat-file', '-e', 'e2aa3e6b7d41bc93df65b6c5f459cc5f81596058'], clone).returncode == 0:
            raise RuntimeError('Historical integration commit unexpectedly present')
        for document in ['docs/compliance/soc2/scope.md', PACKET + 'packet.md']:
            source = clone / document
            for link in re.findall(r'\]\(([^)]+)\)', source.read_text()):
                if '://' not in link and not (source.parent / link.split('#')[0]).exists():
                    raise RuntimeError('Missing linked artifact: ' + link)
        modes = [([], {}), (['-O'], {}), ([], {'PYTHONOPTIMIZE': '1'})]
        for flags, extra in modes:
            for script in ['scripts/soc2-evidence-verify.py'] + [
                    f'docs/compliance/soc2/evidence/HOME-30-v{v}/verify.py' for v in (2, 3)]:
                checked([sys.executable, *flags, script], clone, env=dict(os.environ, **extra))
                count += 1
            for path in ['.policy.yml', 'scripts/ci/static-checks.sh', 'scripts/ci/terragrunt-apply.sh',
                         'docs/compliance/soc2/evidence/HOME-30-v2/excluded-sources.json',
                         'docs/compliance/soc2/evidence/HOME-30-v3/HOME-45-original.txt'] + [
                             PACKET + name for name in ('history.json', 'population.json', 'SHA256SUMS')]:
                target = clone / path
                original = target.read_bytes()
                target.write_bytes(original + b'\nCORRUPTION\n')
                result = run([sys.executable, *flags, 'scripts/soc2-evidence-verify.py'], clone,
                             env=dict(os.environ, **extra))
                target.write_bytes(original)
                if result.returncode == 0:
                    raise RuntimeError('Corruption accepted: ' + path)
                count += 1
            # Exercise inner archive checks independently of the envelope digest.
            code = "import runpy,json; m=runpy.run_path('scripts/soc2-evidence-verify.py'); h=json.load(open('" + PACKET + "history.json')); next(iter(h['objects'].values()))['base64']='Y29ycnVwdA=='; m['history_check'](h)"
            if run([sys.executable, *flags, '-c', code], clone, env=dict(os.environ, **extra)).returncode == 0:
                raise RuntimeError('Corrupt archived object accepted')
            count += 1
        # A committed source change must also be rejected, with an unchanged packet.
        target = clone / '.policy.yml'
        target.write_bytes(target.read_bytes() + b'\n# synthetic drift\n')
        checked(['git', 'add', '.policy.yml'], clone)
        checked(['git', 'commit', '-qm', 'Synthetic committed drift'], clone, env=env)
        for flags, extra in modes:
            if run([sys.executable, *flags, 'scripts/soc2-evidence-verify.py'], clone,
                   env=dict(os.environ, **extra)).returncode == 0:
                raise RuntimeError('Committed drift accepted')
            count += 1
    print(f'PASS: {count} checks; fresh squash clone lacks historical PR commits; normal/-O/PYTHONOPTIMIZE=1')


if __name__ == '__main__':
    main()
