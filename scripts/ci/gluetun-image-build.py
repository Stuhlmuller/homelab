#!/usr/bin/env python3
"""Build, compare, exercise and scan the complete image locally; never publish."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / 'images/gluetun'
SOCKET = 'unix:///var/run/docker.sock'
BUILDKIT = 'moby/buildkit:v0.33.0@sha256:6c2fa84a6b61ccd72899dde4239f8d5717f05f9a8ca6f3cad185fb1a95a94de3'
SOURCE = '3d1e20c5551e9cae1f9d938dc7b7214a6987f27e'
BASE = 'ghcr.io/qdm12/gluetun:v3.41.3@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027'
HOSTS = {'dl-cdn.alpinelinux.org', 'codeload.github.com', 'build.openvpn.net'}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(args, timeout=600, capture=False, env=None, check=True, diagnostics=False):
    if env is None:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('DOCKER_', 'BUILDX_', 'BUILDKIT_', 'GIT_'))}
    return subprocess.run(args, check=check, text=True, timeout=timeout, env=env, cwd=ROOT,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture and not diagnostics else None)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest():
    data = json.loads((IMAGE / 'native-inputs.json').read_text())
    require(data['schema'] == 1 and data['platform'] == 'linux/amd64' and data['base_image'] == BASE,
            'Native build manifest does not match the reviewed image target')
    rows = data['inputs']
    require(0 < len(rows) <= 128, 'Invalid input inventory size')
    names = set()
    for row in rows:
        name = row['filename']
        url = urlsplit(row['url'])
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,180}', name) and name not in names,
                'Input names must be unique plain filenames')
        require(re.fullmatch(r'[0-9a-f]{64}', row['sha256']), 'Input lacks an exact SHA256')
        require(url.scheme == 'https' and url.hostname in HOSTS and not url.username
                and not url.password and url.port in (None, 443) and not url.fragment,
                'Input URL is outside the fixed public source hosts')
        require(row['kind'] in ('runtime-apk', 'build-apk', 'source-archive'), 'Unknown input kind')
        names.add(name)
    runtime = {row['filename'] for row in rows if row['kind'] == 'runtime-apk'}
    require(runtime == {'libcrypto3-3.5.8-r0.apk', 'libssl3-3.5.8-r0.apk'},
            'Runtime package set changed without a corresponding composition review')
    expected = data['expected_runtime_packages']
    require(isinstance(expected, dict) and len(expected) == 36 and 'openvpn' not in expected
            and all(re.fullmatch(r'[a-z0-9][a-z0-9+_.-]*', name)
                    and isinstance(version, str) and re.fullmatch(r'[a-zA-Z0-9+_.-]+', version)
                    for name, version in expected.items()), 'Invalid complete runtime package contract')
    return data


def fetch_inputs(data, context):
    directory = context / 'inputs'
    directory.mkdir()
    checksums = []
    for row in data['inputs']:
        path = directory / row['filename']
        # No curl configuration, proxies, redirects, credentials or optional mirrors.
        status = run(['curl', '-q', '--fail', '--silent', '--show-error', '--proto', '=https',
                      '--proxy', '', '--connect-timeout', '10', '--max-time', '120',
                      '--max-filesize', str(256 * 1024 * 1024), '--output', str(path),
                      '--write-out', '%{http_code}', row['url']], timeout=130, capture=True).stdout
        require(status == '200' and path.is_file() and not path.is_symlink(), 'Input download failed')
        require(digest(path) == row['sha256'], 'Input download SHA256 mismatch')
        checksums.append(row['sha256'] + '  inputs/' + row['filename'])
    (context / 'inputs.sha256').write_text('\n'.join(checksums) + '\n')
    print(f'Verified {len(checksums)} exact public build inputs', flush=True)



def artifact_inventory(directory):
    inventory = {}
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'Native artifact export contains a symbolic link')
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        require(path.is_file() and (relative in ('usr/sbin/openvpn2.5', 'usr/sbin/openvpn2.6')
                or relative.startswith('usr/share/homelab-gluetun/native/')),
                'Unexpected SDK content in native runtime artifacts')
        inventory[relative] = [digest(path), path.stat().st_mode & 0o777]
    require(all(name in inventory for name in ('usr/sbin/openvpn2.5', 'usr/sbin/openvpn2.6')),
            'Native export is missing an OpenVPN executable')
    return inventory


def cleanup(docker, builder, requested, tag, candidate):
    errors = []
    def remove_candidate():
        inspected = run([*docker, 'image', 'inspect', '--format', '{{.Id}}', tag],
                        capture=True, timeout=20, check=False)
        if inspected.returncode == 0:
            if inspected.stdout.strip() != candidate:
                errors.append('Owned candidate tag changed identity')
            else:
                removed = run([*docker, 'image', 'rm', tag], capture=True, timeout=30, check=False)
                if removed.returncode:
                    errors.append('Owned candidate tag cleanup failed')
        elif 'No such image' not in inspected.stderr:
            errors.append('Owned candidate tag absence could not be verified')
    def remove_builder():
        inspected = run([*docker, 'buildx', 'inspect', builder], capture=True, timeout=30, check=False)
        if inspected.returncode == 0:
            fields = dict(re.findall(r'^(Name|Driver):[ \t]+([^\n]+)',
                                     inspected.stdout.split('Nodes:', 1)[0], re.MULTILINE))
            if fields.get('Name') != builder or fields.get('Driver') != 'docker-container':
                errors.append('Owned builder changed identity')
            else:
                removed = run([*docker, 'buildx', 'rm', '--force', builder],
                              capture=True, timeout=60, check=False)
                if removed.returncode:
                    errors.append('Owned builder cleanup failed')
        elif not re.search(r'no builder|not found|does not exist', inspected.stderr, re.IGNORECASE):
            errors.append('Owned builder absence could not be verified')
    for needed, operation, name in ((candidate, remove_candidate, 'candidate tag'),
                                    (requested, remove_builder, 'builder')):
        if needed:
            try:
                operation()
            except (OSError, subprocess.SubprocessError):
                errors.append('Owned ' + name + ' cleanup could not finish')
    require(not errors, '; '.join(errors))


def scan_image(scanner, archive, scratch, candidate, source):
    print('::group::Native Trivy complete-image scan and coverage gate', flush=True)
    config = scratch / 'registry-empty'
    config.mkdir()
    (config / 'config.json').write_text('{"auths":{}}\n')
    cache = scratch / 'trivy-cache'
    report = scratch / 'candidate-trivy.json'
    # These only remove ambient scanner/registry credentials and overrides.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('TRIVY_') and key not in ('DOCKER_AUTH_CONFIG', 'DOCKER_CONFIG')}
    environment['DOCKER_CONFIG'] = str(config)
    command = [str(scanner), '--config', '/dev/null', '--cache-dir', str(cache), 'image',
               '--input', str(archive), '--scanners', 'vuln', '--list-all-pkgs',
               '--ignorefile', '/dev/null', '--format', 'json', '--output', str(report),
               '--timeout', '10m', '--exit-code', '0']
    run(command, timeout=660, env=environment)
    report.chmod(0o600)
    data = json.loads(report.read_text())
    require(data.get('SchemaVersion') == 2 and data.get('ArtifactType') == 'container_image',
            'Scanner did not analyze a complete container image')
    metadata = data.get('Metadata', {})
    require(metadata.get('ImageID') == candidate, 'Scan does not match the tested image config ID')
    image_config = metadata.get('ImageConfig', {})
    require(image_config.get('architecture') == 'amd64' and image_config.get('os') == 'linux',
            'Scan platform does not match the tested platform')
    require(image_config.get('config', {}).get('Labels', {}).get('org.opencontainers.image.revision') == source,
            'Scan source revision does not match the tested source')
    results = data.get('Results', [])
    os_results = [r for r in results if r.get('Class') == 'os-pkgs' and r.get('Type') == 'alpine']
    go_results = [r for r in results if r.get('Type') == 'gobinary'
                  and Path(r.get('Target', '')).name == 'gluetun-entrypoint']
    require(len(os_results) == 1 and len(go_results) == 1, 'OS or main Go executable scan coverage is missing')
    os_packages = {p['Name']: p.get('Version') for p in os_results[0].get('Packages', [])}
    go_packages = {p['Name']: p.get('Version') for p in go_results[0].get('Packages', [])}
    require(os_packages == manifest()['expected_runtime_packages'],
            'OS inventory differs from the reviewed complete runtime package set')
    require(len(go_packages) >= 50, 'Incomplete Go package inventory')
    require(os_packages.get('libcrypto3') == '3.5.8-r0' and os_packages.get('libssl3') == '3.5.8-r0',
            'Runtime libraries do not match the signed input versions')
    for package, version in {'stdlib': 'v1.26.7', 'golang.org/x/crypto': 'v0.56.0',
                             'golang.org/x/net': 'v0.57.0', 'golang.org/x/text': 'v0.41.0',
                             'github.com/cloudflare/circl': 'v1.6.3'}.items():
        require(go_packages.get(package) == version, 'Go inventory does not match the locked dependency graph')
    high = [v for result in results for v in result.get('Vulnerabilities', [])
            if v.get('Severity') in ('HIGH', 'CRITICAL')]
    require(not high, 'Complete-image HIGH/CRITICAL gate failed; private report discarded with temporary build files')
    print('Complete-image OS/main-Go coverage and HIGH/CRITICAL gate passed.', flush=True)
    print('Native OpenVPN provenance and compatibility are separate evidence; APK silence is not native-code clearance.', flush=True)
    print('::endgroup::', flush=True)


def compare_runtime(baseline, candidate):
    before, after = baseline['Config'], candidate['Config']
    for key in ('Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'ExposedPorts', 'Volumes', 'StopSignal', 'Healthcheck'):
        require(before.get(key) == after.get(key), 'Inherited runtime contract changed: ' + key)
    require(before.get('User', '') in ('', '0', 'root') and after.get('User') == 'root',
            'Image initialization identity changed')


def main():
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64',
            'Complete image validation requires native Linux/amd64 and local Docker')
    data = manifest()
    source = run(['git', 'rev-parse', 'HEAD'], capture=True, timeout=10).stdout.strip()
    require(re.fullmatch(r'[0-9a-f]{40}', source), 'Invalid repository source identity')
    require(not run(['git', 'status', '--porcelain', '--untracked-files=all'], capture=True, timeout=10).stdout,
            'Image validation requires a committed, clean checkout')
    source_epoch = int(run(['git', 'show', '-s', '--format=%ct', 'HEAD'], capture=True, timeout=10).stdout.strip())
    source_created = datetime.fromtimestamp(source_epoch, timezone.utc).isoformat().replace('+00:00', 'Z')
    with tempfile.TemporaryDirectory(prefix='homelab-gluetun-build-') as directory:
        scratch = Path(directory)
        scratch.chmod(0o700)
        context = scratch / 'context'
        context.mkdir()
        config = scratch / 'docker-config'
        config.mkdir()
        (config / 'config.json').write_text('{"auths":{}}\n')
        docker = ['docker', '--config', str(config), '--host', SOCKET]
        info = json.loads(run([*docker, 'info', '--format', '{{json .}}'], capture=True).stdout)
        require(info['OSType'] == 'linux' and info['Architecture'] in ('x86_64', 'amd64'),
                'Local Docker daemon is not Linux/amd64')
        print('::group::Locked Go artifact and native upstream unit tests', flush=True)
        binary = Path(run(['nix', 'build', '.#gluetun-candidate', '--no-link', '--print-out-paths'],
                          timeout=2700, capture=True, diagnostics=True).stdout.strip()) / 'bin/gluetun-entrypoint'
        require(binary.is_file(), 'Nix did not produce the expected executable')
        with binary.open('rb') as stream:
            header = stream.read(20)
        require(header[:6] == b'\x7fELF\x02\x01' and header[18:20] == b'\x3e\x00',
                'Go artifact is not Linux/amd64 ELF')
        shutil.copyfile(binary, context / 'gluetun-entrypoint')
        print('Locked Linux Go build and selected upstream unit tests passed.', flush=True)
        print('::endgroup::', flush=True)
        for name in ('Dockerfile', 'native.Dockerfile', 'native-build.sh', 'native-inputs.json'):
            shutil.copyfile(IMAGE / name, context / name)
        fetch_inputs(data, context)
        run([*docker, 'pull', '--platform', 'linux/amd64', data['base_image']], timeout=300)
        baseline = json.loads(run([*docker, 'image', 'inspect', data['base_image']], capture=True).stdout)[0]
        require(baseline['Os'] == 'linux' and baseline['Architecture'] == 'amd64', 'Baseline platform mismatch')
        require('ghcr.io/qdm12/gluetun@' + BASE.split('@')[1] in baseline['RepoDigests'], 'Baseline digest mismatch')
        builder = 'gluetun-build-' + uuid.uuid4().hex
        tag = 'homelab-gluetun-test:' + uuid.uuid4().hex
        builder_requested = False
        candidate = None
        try:
            builder_requested = True
            run([*docker, 'buildx', 'create', '--name', builder, '--driver', 'docker-container',
                 '--driver-opt', 'image=' + BUILDKIT])
            print('::group::Pinned OpenVPN sources and offline signed Alpine SDK', flush=True)
            native_inventories = []
            for number in (1, 2):
                destination = scratch / f'native-{number}'
                run([*docker, 'buildx', 'build', '--builder', builder, '--platform', 'linux/amd64',
                     '--no-cache', '--file', str(context / 'native.Dockerfile'), '--target', 'artifacts',
                     '--build-arg', 'SOURCE_DATE_EPOCH=' + str(source_epoch), '--provenance=false',
                     '--output', 'type=local,dest=' + str(destination), str(context)], timeout=1200)
                native_inventories.append(artifact_inventory(destination))
            require(native_inventories[0] == native_inventories[1],
                    'Repeated native builds differ in bytes or file modes')
            shutil.copytree(scratch / 'native-1', context / 'native')
            print('Both native binaries and their provenance reproduce exactly.', flush=True)
            print('::endgroup::', flush=True)
            print('::group::Repeat complete image build and compare immutable output', flush=True)
            outputs = []
            for number in (1, 2):
                archive = scratch / f'candidate-{number}.tar'
                metadata = scratch / f'candidate-{number}.json'
                run([*docker, 'buildx', 'build', '--builder', builder, '--platform', 'linux/amd64',
                     '--no-cache', '--build-arg', 'SOURCE_DATE_EPOCH=' + str(source_epoch), '--provenance=false',
                     '--label', 'org.opencontainers.image.revision=' + source,
                     '--label', 'org.opencontainers.image.created=' + source_created,
                     '--metadata-file', str(metadata), '--tag', tag,
                     '--output', f'type=docker,dest={archive},rewrite-timestamp=true,oci-mediatypes=false',
                     str(context)], timeout=600)
                result = json.loads(metadata.read_text())
                outputs.append((archive, result['containerimage.config.digest'], result['containerimage.digest']))
            require(outputs[0][1:] == outputs[1][1:], 'Repeated complete image builds are not identical')
            archive, candidate, image_digest = outputs[0]
            require(re.fullmatch(r'sha256:[0-9a-f]{64}', candidate), 'Invalid built image identity')
            run([*docker, 'load', '--input', str(archive)])
            candidate_info = json.loads(run([*docker, 'image', 'inspect', tag], capture=True).stdout)[0]
            require(candidate_info['Id'] == candidate and candidate_info['Os'] == 'linux'
                    and candidate_info['Architecture'] == 'amd64', 'Loaded image does not match built output')
            labels = candidate_info['Config'].get('Labels', {})
            require(labels.get('org.opencontainers.image.revision') == source
                    and labels.get('org.opencontainers.image.created') == source_created
                    and labels.get('io.homelab.gluetun.upstream-revision') == SOURCE,
                    'Built image provenance differs from reviewed sources')
            compare_runtime(baseline, candidate_info)
            print('Repeat config/manifest digests and inherited runtime contract match.', flush=True)
            print('::endgroup::', flush=True)
            print('::group::Native file settings, profiling, firewall and encrypted VPN traffic', flush=True)
            # Buildx writes its own metadata beside config.json. Fixtures get a
            # separate empty directory so their credential-isolation check holds.
            fixture_config = scratch / 'fixture-docker-config'
            fixture_config.mkdir(mode=0o700)
            (fixture_config / 'config.json').write_text('{"auths":{}}\n')
            run([sys.executable, str(ROOT / 'scripts/ci/gluetun-image-native.py'),
                 '--baseline', baseline['Id'], '--candidate', candidate,
                 '--docker-config', str(fixture_config)], timeout=1200)
            print('::endgroup::', flush=True)
            scanner = Path(run(['nix', 'build', '.#gluetun-scanner', '--no-link', '--print-out-paths'],
                               timeout=2700, capture=True, diagnostics=True).stdout.strip()) / 'bin/trivy'
            scan_image(scanner, archive, scratch, candidate, source)
            print(json.dumps({'source': source, 'upstream_source': SOURCE, 'image_config': candidate,
                              'image_manifest': image_digest, 'platform': 'linux/amd64',
                              'native_compatibility': 'passed', 'published': False}), flush=True)
        finally:
            cleanup(docker, builder, builder_requested, tag, candidate)


if __name__ == '__main__':
    if sys.argv[1:] == ['--check-inputs']:
        manifest()
        print('Pinned image input schema passed.')
    else:
        require(not sys.argv[1:], 'Unexpected build arguments')
        main()
