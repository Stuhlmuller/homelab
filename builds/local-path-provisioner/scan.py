#!/usr/bin/env python3
"""Scan both local OCI children and retain private reports plus a bound receipt."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tarfile
import tempfile

RECIPE = Path(__file__).resolve().parent
BUILD = runpy.run_path(str(RECIPE / 'build.py'))
SOURCE = BUILD['SOURCE']
OCI = 'application/vnd.oci.image.'
BINARY = 'usr/bin/local-path-provisioner'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def manifest(ref, env):
    return subprocess.check_output(['regctl', 'manifest', 'get', ref, '--format', 'raw-body'], env=env)


def verify_config(raw, arch, diff_id):
    expected = BUILD['image_config'](arch, diff_id)
    require(raw == json.dumps(expected, sort_keys=True, separators=(',', ':')).encode(),
            'unexpected OCI runtime configuration')


def run_trivy(scanner, args, work, env, **options):
    # An ambient trivy.yaml can suppress findings via ignore-policy even with --ignorefile /dev/null.
    config = work / 'scanner-config.yaml'
    config.write_text('{}\n')
    return subprocess.run([scanner, '--config', config, *args], cwd=work, env=env, check=True, **options)


def verified_binary(archive, child, arch, work, env):
    # The archive passed to Trivy must describe the exact bytes in the OCI child.
    with tarfile.open(archive, 'r:') as tar:
        entries = json.load(tar.extractfile('manifest.json'))
        require(len(entries) == 1 and len(entries[0]['Layers']) == 1, 'unexpected exported image shape')
        config_raw = tar.extractfile(entries[0]['Config']).read()
        require(digest(config_raw) == child['config']['digest'] and len(config_raw) == child['config']['size'],
                'exported image config differs from OCI manifest')
        config = json.loads(config_raw)
        layers = child['layers']
        require(len(layers) == 1 and layers[0]['mediaType'] == OCI + 'layer.v1.tar', 'unexpected OCI layer')
        layer = tar.extractfile(entries[0]['Layers'][0]).read()
        require(len(layer) == layers[0]['size'] and digest(layer) == layers[0]['digest']
                and config['rootfs']['diff_ids'] == [digest(layer)], 'layer bytes differ from the OCI child')
        verify_config(config_raw, arch, layers[0]['digest'])
    with tarfile.open(fileobj=io.BytesIO(layer), mode='r:') as tar:
        expected = {BINARY, 'etc/ssl/certs/ca-certificates.crt', 'usr/share/licenses/go/LICENSE',
                    'usr/share/licenses/local-path-provisioner/LICENSE',
                    'usr/share/licenses/local-path-provisioner/THIRD_PARTY'}
        members = tar.getmembers()
        require(len(members) == len(expected) and {m.name for m in members} == expected
                and all(m.isfile() and m.uid == 0 and m.gid == 0 and m.mtime == 0
                        and m.mode == (0o755 if m.name == BINARY else 0o644) for m in members),
                'unexpected runtime payload')
        require(digest(tar.extractfile('etc/ssl/certs/ca-certificates.crt').read()) == 'sha256:' + SOURCE['ca_sha256'],
                'CA bundle changed')
        raw = tar.extractfile(BINARY).read()
    binary = work / ('controller-' + arch)
    binary.write_bytes(raw)
    info = json.loads(subprocess.check_output(['go', 'version', '-m', '-json', binary], cwd=work, env=env))
    require(info['Path'] == 'github.com/rancher/local-path-provisioner'
            and info['GoVersion'] == 'go' + SOURCE['go_version'], 'unexpected module or compiler')
    require(all(not dep.get('Replace') for dep in info['Deps']), 'unexpected replaced Go module')
    modules = {dep['Path']: {'version': dep['Version'], 'sum': dep['Sum']} for dep in info['Deps']}
    require(len(modules) == len(info['Deps']) and all(v['version'] and re.fullmatch(r'h1:[A-Za-z0-9+/]{43}=', v['sum'])
                                                     for v in modules.values()), 'invalid linked module graph')
    require(all(modules.get(name) == expected for name, expected in SOURCE['modules'].items()),
            'fixed dependencies or their module sums differ')
    settings = {s['Key']: s['Value'] for s in info['Settings']}
    require(settings.get('GOOS') == 'linux' and settings.get('GOARCH') == arch
            and settings.get('CGO_ENABLED') == '0', 'unexpected Go target')
    return config, digest(raw), modules


def covered_packages(report, config_id, diff_ids, modules):
    require(report['SchemaVersion'] == 2 and report['ArtifactType'] == 'container_image'
            and report['Metadata']['ImageID'] == config_id and report['Metadata']['DiffIDs'] == diff_ids,
            'scan identity mismatch')
    targets = report['Results']
    require(len(targets) == 1 and targets[0]['Type'] == 'gobinary'
            and targets[0]['Target'].lstrip('/') == BINARY and not targets[0].get('Vulnerabilities'),
            'expected a covered controller with zero fixable HIGH/CRITICAL findings')
    # Trivy also reports the source-built main module without a version.
    records = targets[0]['Packages']
    unversioned = [p['Name'] for p in records if not p.get('Version')]
    require(unversioned == ['github.com/rancher/local-path-provisioner'], 'unexpected unversioned packages')
    versioned = [(p['Name'], p['Version']) for p in records if p.get('Version')]
    expected = {name: dep['version'] for name, dep in modules.items()}
    expected['stdlib'] = 'v' + SOURCE['go_version']
    require(len(versioned) == len(expected) and dict(versioned) == expected,
            'scan does not cover the complete linked Go package inventory')
    return len(versioned)


def scan(layout, output, scanner):
    output.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='local-path-scan-') as directory:
        work = Path(directory)
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE') if k in os.environ}
        env.update(REGCTL_CONFIG=str(work / 'regctl.json'), DOCKER_CONFIG=str(work / 'docker'), GOTOOLCHAIN='local',
                   GOENV='off', GOWORK='off', GOAUTH='off')
        (work / 'docker').mkdir()
        (work / 'docker/config.json').write_text('{"auths":{}}')
        subprocess.run(['regctl', 'config', 'set', '--docker-cred=false', '--docker-cert=false'], env=env, check=True)
        scanner_path = shutil.which(scanner)
        require(scanner_path is not None, 'pinned Trivy executable is unavailable')
        with Path(scanner_path).open('rb') as stream:
            scanner_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(any(scanner_hash == r['executable_sha256'] for r in SOURCE['trivy_releases'].values()),
                'Trivy executable differs from the pinned release')
        scanner = scanner_path
        version = run_trivy(scanner, ['--version'], work, env, capture_output=True, text=True).stdout
        require('Version: ' + SOURCE['trivy_version'] in version.splitlines(), 'unexpected Trivy version')
        database = 'ghcr.io/aquasecurity/trivy-db'
        db_digest = subprocess.check_output(['regctl', 'image', 'digest', database + ':2'], env=env, text=True).strip()
        require(re.fullmatch('sha256:[0-9a-f]{64}', db_digest), 'invalid public DB digest')
        base = ['image', '--cache-dir', work / 'cache', '--skip-version-check']
        run_trivy(scanner, [*base, '--download-db-only', '--db-repository', database + '@' + db_digest], work, env)
        metadata = json.loads((work / 'cache/db/metadata.json').read_text())
        now = datetime.now(timezone.utc)
        updated = datetime.fromisoformat(metadata['UpdatedAt'])
        require(metadata['Version'] == 2 and timedelta(0) <= now - updated <= timedelta(days=1)
                and now < datetime.fromisoformat(metadata['NextUpdate']), 'stale vulnerability database')
        ref = 'ocidir://' + str(layout)
        raw = manifest(ref + ':' + SOURCE['image_tag'], env)
        index = json.loads(raw)
        require(set(index) == {'schemaVersion', 'mediaType', 'manifests'} and index['schemaVersion'] == 2
                and index['mediaType'] == OCI + 'index.v1+json' and sorted(
            (d['platform']['os'], d['platform']['architecture']) for d in index['manifests']
        ) == [('linux', 'amd64'), ('linux', 'arm64')], 'expected one image for each supported architecture')
        receipt = {'index': digest(raw), 'source_revision': SOURCE['revision'], 'compiler': SOURCE['go_version'],
                   'dependency_patch': digest((RECIPE / 'dependencies.patch').read_bytes()),
                   'scanner': SOURCE['trivy_version'], 'scanner_binary': 'sha256:' + scanner_hash, 'checked_at': now.isoformat(),
                   'db': database + '@' + db_digest, 'db_updated_at': metadata['UpdatedAt'], 'platforms': {}}
        for desc in index['manifests']:
            arch = desc['platform']['architecture']
            require(set(desc) == {'mediaType', 'digest', 'size', 'platform'}
                    and desc['mediaType'] == OCI + 'manifest.v1+json'
                    and desc['platform'] == {'os': 'linux', 'architecture': arch}
                    and re.fullmatch(r'sha256:[0-9a-f]{64}', desc['digest']), 'unexpected index descriptor')
            child_ref = ref + '@' + desc['digest']
            raw = manifest(child_ref, env)
            require(digest(raw) == desc['digest'] and len(raw) == desc['size'], 'child descriptor mismatch')
            child = json.loads(raw)
            require(set(child) == {'schemaVersion', 'mediaType', 'config', 'layers'} and child['schemaVersion'] == 2
                    and child['mediaType'] == OCI + 'manifest.v1+json'
                    and child['config']['mediaType'] == OCI + 'config.v1+json',
                    'unexpected image media type')
            archive = work / f'{arch}.tar'
            subprocess.run(['regctl', 'image', 'export', child_ref, archive], env=env, check=True)
            config, binary_digest, modules = verified_binary(archive, child, arch, work, env)
            report = output / f'{arch}.json'
            run_trivy(scanner, [*base, '--input', archive, '--scanners', 'vuln', '--list-all-pkgs', '--severity',
                            'HIGH,CRITICAL', '--ignore-unfixed', '--ignorefile', os.devnull, '--exit-code', '1',
                            '--offline-scan', '--skip-db-update', '--skip-java-db-update', '--cache-backend', 'memory',
                            '--format', 'json', '--output', report], work, env)
            raw = report.read_bytes()
            result = json.loads(raw)
            count = covered_packages(result, child['config']['digest'], config['rootfs']['diff_ids'], modules)
            modules_digest = digest(json.dumps(modules, sort_keys=True, separators=(',', ':')).encode())
            receipt['platforms']['linux/' + arch] = {'manifest': desc['digest'], 'config': child['config']['digest'],
                'binary': binary_digest, 'module_graph': modules_digest, 'versioned_packages': count,
                'report': digest(raw), 'fixable_high': 0, 'fixable_critical': 0}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('output', type=Path, help='new private report directory')
    parser.add_argument('--trivy', default='trivy', help='Trivy 0.72.0 executable')
    args = parser.parse_args()
    os.umask(0o077)
    scan(args.layout.resolve(), args.output.resolve(), args.trivy)
