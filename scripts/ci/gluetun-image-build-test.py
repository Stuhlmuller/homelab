#!/usr/bin/env python3
"""Offline runner boundary regressions; no Docker, registry or scanner execution."""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'gluetun_build', Path(__file__).with_name('gluetun-image-build.py'))
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
SOURCE = 'a' * 40
CANDIDATE = 'sha256:' + 'b' * 64
DOCKER = ['docker', '--config', '/unused-fixture-config', '--host', BUILD.SOCKET]


def result(stdout='', stderr='', code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class BeforeDocker(RuntimeError):
    """Stop the main path before any external build or Docker operation."""


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gluetun-runner-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def git_directory(self, name):
        directory = self.directory / name
        directory.mkdir()
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('GIT_')}
        subprocess.run(['git', 'init', '-q', str(directory)], check=True, env=environment)
        return directory

    def test_subprocess_uses_repo_cwd_and_removes_ambient_tool_overrides(self):
        repository = self.git_directory('repository')
        alternate = self.git_directory('alternate')
        overrides = {
            'GIT_DIR': str(alternate / '.git'), 'GIT_WORK_TREE': str(alternate),
            'GIT_INDEX_FILE': str(self.directory / 'alternate-index'),
            'DOCKER_HOST': 'tcp://invalid.example:2375',
            'DOCKER_CONTEXT': 'alternate', 'DOCKER_CONFIG': '/unused',
            'DOCKER_AUTH_CONFIG': '{"auths":{}}', 'BUILDX_CONFIG': '/unused-buildx',
            'BUILDX_BUILDER': 'alternate', 'BUILDKIT_HOST': 'tcp://invalid.example:1234',
            'GLUETUN_RUNNER_TEST_MARKER': 'preserved',
        }
        script = ('import json,os; print(json.dumps({"cwd":os.getcwd(),'
                  '"overrides":[k for k in os.environ if k.startswith('
                  '("GIT_","DOCKER_","BUILDX_","BUILDKIT_"))],'
                  '"marker":os.environ.get("GLUETUN_RUNNER_TEST_MARKER")}))')
        with patch.object(BUILD, 'ROOT', repository), patch.dict(os.environ, overrides):
            observed = json.loads(BUILD.run([sys.executable, '-c', script], capture=True).stdout)
            top = BUILD.run(['git', 'rev-parse', '--show-toplevel'], capture=True).stdout.strip()
        self.assertEqual(Path(observed['cwd']).resolve(), repository.resolve())
        self.assertEqual(Path(top).resolve(), repository.resolve())
        self.assertEqual(observed['overrides'], [])
        self.assertEqual(observed['marker'], 'preserved')

    def source_gate(self, repository):
        original_run = BUILD.run

        def bounded_run(args, **kwargs):
            # Actual Git status in an empty fixture; no unsigned fixture commit.
            if args == ['git', 'rev-parse', 'HEAD']:
                return result(SOURCE)
            if args == ['git', 'show', '-s', '--format=%ct', 'HEAD']:
                return result('1788739200')
            if args[:2] == ['git', 'status']:
                return original_run(args, **kwargs)
            raise BeforeDocker('Reached the first external operation')

        with patch.object(BUILD, 'ROOT', repository), patch.object(BUILD, 'run', bounded_run), \
                patch.object(BUILD.platform, 'system', return_value='Linux'), \
                patch.object(BUILD.platform, 'machine', return_value='x86_64'):
            BUILD.main()

    def test_clean_git_fixture_reaches_external_boundary(self):
        with self.assertRaises(BeforeDocker):
            self.source_gate(self.git_directory('clean'))

    def test_untracked_build_input_fails_before_docker(self):
        repository = self.git_directory('dirty')
        path = repository / 'images/gluetun/native-build.sh'
        path.parent.mkdir(parents=True)
        path.write_text('synthetic untracked build input\n')
        with self.assertRaisesRegex(RuntimeError, 'committed, clean checkout'):
            self.source_gate(repository)

    def test_candidate_timeout_still_removes_owned_builder(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args[len(DOCKER):])
            if 'image' in args:
                raise subprocess.TimeoutExpired(args, 20)
            if 'inspect' in args:
                return result('Name: owned\nDriver: docker-container\nNodes:\n')
            return result()

        with patch.object(BUILD, 'run', fake_run), \
                self.assertRaisesRegex(RuntimeError, 'candidate tag cleanup could not finish'):
            BUILD.cleanup(DOCKER, 'owned', True, 'owned:tag', CANDIDATE)
        self.assertIn(['buildx', 'rm', '--force', 'owned'], calls)

    def test_cleanup_retains_foreign_objects_and_reports_both_failures(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args[len(DOCKER):])
            if 'image' in args:
                return result('sha256:' + 'c' * 64)
            return result('Name: foreign\nDriver: docker-container\nNodes:\n')

        with patch.object(BUILD, 'run', fake_run), \
                self.assertRaisesRegex(RuntimeError, 'tag changed identity; Owned builder changed identity'):
            BUILD.cleanup(DOCKER, 'owned', True, 'owned:tag', CANDIDATE)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any('rm' in call for call in calls))

    def test_cleanup_transport_errors_do_not_skip_second_attempt(self):
        with patch.object(BUILD, 'run', side_effect=OSError('synthetic transport failure')) as command, \
                self.assertRaisesRegex(RuntimeError, 'candidate tag.*; Owned builder'):
            BUILD.cleanup(DOCKER, 'owned', True, 'owned:tag', CANDIDATE)
        self.assertEqual(command.call_count, 2)

    def test_cleanup_accepts_verified_absence_but_rejects_unknown_failure(self):
        with patch.object(BUILD, 'run', side_effect=[
                result(stderr='No such image: owned:tag', code=1),
                result(stderr='no builder "owned" found', code=1)]) as command:
            BUILD.cleanup(DOCKER, 'owned', True, 'owned:tag', CANDIDATE)
        self.assertEqual(command.call_count, 2)
        with patch.object(BUILD, 'run', return_value=result(stderr='daemon unavailable', code=1)), \
                self.assertRaisesRegex(RuntimeError, 'absence could not be verified'):
            BUILD.cleanup(DOCKER, 'owned', True, 'owned:tag', CANDIDATE)

    def artifacts(self, name):
        root = self.directory / name
        binaries = root / 'usr/sbin'
        binaries.mkdir(parents=True)
        for family in ('2.5', '2.6'):
            path = binaries / ('openvpn' + family)
            path.write_bytes(b'synthetic-native-' + family.encode())
            path.chmod(0o555)
        return root

    def test_native_inventory_detects_bytes_and_modes(self):
        first, second = self.artifacts('first'), self.artifacts('second')
        expected = BUILD.artifact_inventory(first)
        self.assertEqual(expected, BUILD.artifact_inventory(second))
        binary = second / 'usr/sbin/openvpn2.5'
        binary.chmod(0o755)
        self.assertNotEqual(expected, BUILD.artifact_inventory(second))
        binary.write_bytes(b'different synthetic executable')
        binary.chmod(0o555)
        self.assertNotEqual(expected, BUILD.artifact_inventory(second))

    def test_native_inventory_rejects_missing_sdk_symlink_and_nonregular(self):
        for case in ('missing', 'sdk', 'symlink', 'directory-symlink', 'fifo'):
            with self.subTest(case=case):
                root = self.artifacts(case)
                if case == 'missing':
                    (root / 'usr/sbin/openvpn2.5').unlink()
                elif case == 'sdk':
                    (root / 'usr/sbin/compiler').write_text('synthetic SDK leak')
                elif case == 'symlink':
                    (root / 'usr/sbin/link').symlink_to('openvpn2.5')
                elif case == 'directory-symlink':
                    (root / 'alias').symlink_to(root / 'usr', target_is_directory=True)
                else:
                    os.mkfifo(root / 'usr/sbin/pipe')
                with self.assertRaises(RuntimeError):
                    BUILD.artifact_inventory(root)

    def scan_report(self):
        packages = BUILD.manifest()['expected_runtime_packages']
        go = {'stdlib': 'v1.26.7', 'golang.org/x/crypto': 'v0.56.0',
              'golang.org/x/net': 'v0.57.0', 'golang.org/x/text': 'v0.41.0',
              'github.com/cloudflare/circl': 'v1.6.3'}
        go.update({f'synthetic.example/module-{i}': 'v1.0.0' for i in range(45)})
        return {'SchemaVersion': 2, 'ArtifactType': 'container_image',
                'Metadata': {'ImageID': CANDIDATE, 'ImageConfig': {
                    'architecture': 'amd64', 'os': 'linux', 'config': {'Labels': {
                        'org.opencontainers.image.revision': SOURCE}}}},
                'Results': [
                    {'Class': 'os-pkgs', 'Type': 'alpine', 'Packages': [
                        {'Name': name, 'Version': version} for name, version in packages.items()]},
                    {'Type': 'gobinary', 'Target': '/gluetun-entrypoint', 'Packages': [
                        {'Name': name, 'Version': version} for name, version in go.items()]}]}

    def scan(self, report):
        with tempfile.TemporaryDirectory(dir=self.directory) as name:
            scratch = Path(name)

            def fake_scan(args, **kwargs):
                self.assertEqual(args[args.index('--input') + 1], '/synthetic-candidate.tar')
                self.assertEqual(args[args.index('--config') + 1], '/dev/null')
                environment = kwargs['env']
                self.assertFalse(any(key.startswith('TRIVY_') for key in environment))
                self.assertNotIn('DOCKER_AUTH_CONFIG', environment)
                config = Path(environment['DOCKER_CONFIG']) / 'config.json'
                self.assertEqual(json.loads(config.read_text()), {'auths': {}})
                Path(args[args.index('--output') + 1]).write_text(json.dumps(report))
                return result()

            with patch.object(BUILD, 'run', fake_scan), redirect_stdout(io.StringIO()), \
                    patch.dict(os.environ, {'TRIVY_SEVERITY': 'LOW', 'TRIVY_IGNORE_UNFIXED': 'true',
                                            'DOCKER_AUTH_CONFIG': 'synthetic', 'DOCKER_CONFIG': '/unused'}):
                BUILD.scan_image(Path('/synthetic-trivy'), Path('/synthetic-candidate.tar'),
                                 scratch, CANDIDATE, SOURCE)
            self.assertEqual((scratch / 'candidate-trivy.json').stat().st_mode & 0o777, 0o600)

    def test_complete_synthetic_report_passes_with_isolated_scanner_settings(self):
        self.scan(self.scan_report())

    def test_os_inventory_denies_missing_extra_wrong_and_stale_packages(self):
        for case in ('missing', 'extra', 'wrong-version', 'stale-openvpn'):
            with self.subTest(case=case):
                report = self.scan_report()
                packages = report['Results'][0]['Packages']
                if case == 'missing':
                    packages.pop()
                elif case == 'wrong-version':
                    packages[0]['Version'] = '0.0.0-r0'
                else:
                    packages.append({'Name': 'openvpn' if case == 'stale-openvpn' else 'synthetic-sdk',
                                     'Version': '2.6.20-r0'})
                with self.assertRaisesRegex(RuntimeError, 'OS inventory differs'):
                    self.scan(report)

    def test_scan_denies_identity_coverage_and_locked_go_drift(self):
        for case in ('identity', 'platform', 'source', 'os-duplicate', 'go-missing', 'go-version'):
            with self.subTest(case=case):
                report = self.scan_report()
                if case == 'identity':
                    report['Metadata']['ImageID'] = 'sha256:' + 'c' * 64
                elif case == 'platform':
                    report['Metadata']['ImageConfig']['architecture'] = 'arm64'
                elif case == 'source':
                    report['Metadata']['ImageConfig']['config']['Labels'].clear()
                elif case == 'os-duplicate':
                    report['Results'].append(copy.deepcopy(report['Results'][0]))
                elif case == 'go-missing':
                    report['Results'][1]['Target'] = '/some-other-executable'
                else:
                    report['Results'][1]['Packages'][0]['Version'] = 'v0.0.0'
                with self.assertRaises(RuntimeError):
                    self.scan(report)

    def test_scan_denies_high_and_critical_outside_main_binary(self):
        for severity in ('HIGH', 'CRITICAL'):
            with self.subTest(severity=severity):
                report = self.scan_report()
                report['Results'].append({'Target': '/synthetic-other-binary', 'Vulnerabilities': [
                    {'VulnerabilityID': 'SYNTHETIC-ONLY', 'Severity': severity}]})
                with self.assertRaisesRegex(RuntimeError, 'HIGH/CRITICAL gate failed'):
                    self.scan(report)


if __name__ == '__main__':
    unittest.main()
