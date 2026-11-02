#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location("promote", Path(__file__).with_name("image-automation-promote.py"))
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)

state = {"applications": {"app": {"failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "safe", "recovery_attempt": None, "failed_digest": "sha256:" + "a" * 64}}}
candidate = {"base_sha": "b" * 40, "candidate_sha": "c" * 40, "parents": ["b" * 40], "application": "app", "operation": "rollback", "changes": {"rejected_digests": ["sha256:" + "a" * 64]}}
assert promote.promotion_plan(state, candidate, "b" * 40)[0] is True
assert promote.promotion_plan(state, candidate, "d" * 40)[0] is False
assert promote.promotion_plan(state, candidate, "c" * 40)[0] is True
malformed = dict(candidate, changes={"workflow": "forged"})
assert promote.promotion_plan(state, malformed, "c" * 40)[0] is False
config = {"schema_version": 1, "imports_paused": False, "import_schedule": "0 * * * *",
          "verification_interval_minutes": 5,
          "images": [{"image_id": "pilot", "source": "cgr.dev/chainguard/python:latest",
                      "destination": "harbor.stinkyboi.com/homelab/python:latest", "access_class": "public",
                      "required_platforms": ["linux/amd64"], "release_recipe": "python-release-v1"}],
          "consumers": [{"consumer_id": "pilot", "application_id": "app", "image_id": "pilot",
                         "target": "/clusters/homelab/apps/pilot.yaml", "migration_status": "candidate",
                         "automation_status": "enrolled", "owner": "argocd"}],
          "applications": [{"application_id": "app", "consumer_ids": ["pilot"],
                             "preflight_recipe": "python-workload-v1", "health_recipe": "python-workload-v1",
                             "recovery_recipe": "stateless-recovery-v1", "deadline_minutes": 30}]}
assert promote.validate_candidate_paths(config, candidate,
    ["scripts/config/image-automation-candidate.json", "clusters/homelab/apps/pilot.yaml"])[0] is True
assert promote.validate_candidate_paths(config, candidate, [".github/workflows/evil.yml"])[0] is False
assert promote.validate_candidate_paths(config, candidate, ["clusters/homelab/apps/pilot.yaml"], ["x"])[0] is False
assert promote.fast_forward_ref("b" * 40, "b" * 40, "c" * 40)[0] is True
assert promote.fast_forward_ref("d" * 40, "b" * 40, "c" * 40)[0] is False

# Exercise the actual trusted workflow against a proposal containing committed metadata.
root = Path(__file__).resolve().parents[2]
workflow = json.loads(subprocess.check_output([
    'yq', '-o=json', '.', str(root / '.github/workflows/image-automation.yml')], text=True))
validation_steps = [next(step['run'] for step in workflow['jobs'][job]['steps']
                         if step.get('name') == name)
                    for job, name in (
                        ('image-update-gate', 'Validate exact proposal scope'),
                        ('promote', 'Validate trusted candidate'),
                        ('fallback-pr', 'Revalidate candidate before PR fallback'))]
with tempfile.TemporaryDirectory() as directory:
    scratch = Path(directory)
    repo = scratch / 'repo'
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()

    git('init', '-q', '-b', 'main')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    scripts = repo / 'scripts/ci'
    scripts.mkdir(parents=True)
    for name in ('image-automation.py', 'image-automation-promote.py'):
        shutil.copyfile(root / 'scripts/ci' / name, scripts / name)
    settings = repo / 'scripts/config'
    settings.mkdir()
    (settings / 'image-automation-state.json').write_text(json.dumps(state))
    catalog = repo / 'clusters/homelab/apps/harbor/image-automation.json'
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps(config))
    git('add', '.')
    git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture base')
    base_sha = git('rev-parse', 'HEAD')
    git('switch', '-qc', 'codex/image-updater-proposals')
    metadata = {key: value for key, value in candidate.items() if key != 'candidate_sha'}
    metadata.update(base_sha=base_sha, parents=[base_sha])
    metadata_path = settings / 'image-automation-candidate.json'
    metadata_path.write_text(json.dumps(metadata))
    git('add', '.')
    git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture proposal')
    candidate_sha = git('rev-parse', 'HEAD')
    git('switch', '-q', 'main')
    git('remote', 'add', 'origin', str(repo))
    environment = dict(os.environ, MAIN_SHA=base_sha, RUNNER_TEMP=str(scratch),
                       GITHUB_STEP_SUMMARY=str(scratch / 'summary'))
    for script in validation_steps:
        result = subprocess.run(['bash', '-c', script], cwd=repo, env=environment,
                                text=True, capture_output=True, timeout=30, check=False)
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)['promotable'] is True
    assert 'candidate_sha' not in json.loads(git('show', f'{candidate_sha}:scripts/config/image-automation-candidate.json'))

    git('switch', '-q', 'codex/image-updater-proposals')
    metadata['candidate_sha'] = candidate_sha
    metadata_path.write_text(json.dumps(metadata))
    git('add', '.')
    git('-c', 'commit.gpgsign=false', 'commit', '--amend', '--no-edit', '-q')
    assert git('rev-parse', 'HEAD') != candidate_sha
    git('switch', '-q', 'main')
    git('update-ref', '-d', 'refs/remotes/origin/codex/image-updater-proposals')
    for script in validation_steps:
        result = subprocess.run(['bash', '-c', script], cwd=repo, env=environment,
                                text=True, capture_output=True, timeout=30, check=False)
        assert result.returncode != 0, 'Committed candidate SHA was trusted'
        assert 'candidate_sha must come from the fetched Git ref' in result.stderr, result.stderr
print('Image promotion: all three workflow validators accept real commits and reject embedded SHAs')
