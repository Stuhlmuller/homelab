#!/usr/bin/env python3
"""Build both local-path controller platforms into a local OCI layout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import urllib.request


RECIPE = Path(__file__).resolve().parent
SOURCE = json.loads((RECIPE / 'source.json').read_text())
TAG = SOURCE['image_tag']
EPOCH = '1970-01-01T00:00:00Z'


def verified_download(url, destination, expected):
    if destination.exists():
        with destination.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError(f'Cached archive SHA-256 mismatch: {destination.name}')
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        path = Path(temporary.name)
    try:
        total = 0
        checksum = hashlib.sha256()
        with opener.open(url, timeout=120) as response, path.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 128 * 1024 * 1024:
                    raise ValueError('Downloaded archive exceeds its size limit')
                checksum.update(chunk)
                output.write(chunk)
        if checksum.hexdigest() != expected:
            raise ValueError('Downloaded archive SHA-256 mismatch')
        path.replace(destination)
    finally:
        path.unlink(missing_ok=True)


def tool_env():
    return {key: os.environ[key] for key in ('PATH', 'TMPDIR', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE')
            if key in os.environ}


def extract(archive, destination, root, skip_vendor=False):
    with tarfile.open(archive) as tar:
        for member in tar:
            parts = Path(member.name).parts
            if not parts or parts[0] != root or '..' in parts:
                raise ValueError('Unexpected archive path')
            if skip_vendor and parts[1:2] == ('vendor',):
                continue
            tar.extract(member, destination, filter='data')
    return destination / root


def prepare(scratch, cache):
    revision = SOURCE['revision']
    archive = cache / f'local-path-provisioner-{revision}.tar.gz'
    verified_download(f'https://codeload.github.com/rancher/local-path-provisioner/tar.gz/{revision}',
                      archive, SOURCE['archive_sha256'])
    source = extract(archive, scratch, f'local-path-provisioner-{revision}', skip_vendor=True)
    subprocess.run(['git', 'apply', '--check', str(RECIPE / 'dependencies.patch')], cwd=source, env=tool_env(), check=True)
    subprocess.run(['git', 'apply', str(RECIPE / 'dependencies.patch')], cwd=source, env=tool_env(), check=True)

    machine = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64'}[platform.machine()]
    name = f"go{SOURCE['go_version']}.{platform.system().lower()}-{machine}.tar.gz"
    verified_download('https://go.dev/dl/' + name, cache / name, SOURCE['go_archives'][name])
    go = extract(cache / name, scratch, 'go') / 'bin/go'
    env = {**tool_env(), 'GOROOT': str(go.parents[1]), 'GOENV': 'off', 'GOTOOLCHAIN': 'local',
           'GOAUTH': 'off', 'GOCACHEPROG': '',
           'GOWORK': 'off', 'GOOS': platform.system().lower(), 'GOARCH': machine, 'CGO_ENABLED': '0',
           'GOPATH': str(cache / 'go-path'), 'GOMODCACHE': str(cache / 'modcache'),
           'GOCACHE': str(cache / 'go-build-cache'), 'GOPROXY': 'https://proxy.golang.org',
           'GOSUMDB': 'sum.golang.org', 'GOPRIVATE': '', 'GONOSUMDB': '', 'GONOPROXY': ''}
    locks = {name: (source / name).read_bytes() for name in ('go.mod', 'go.sum')}
    for args in (['mod', 'download'], ['mod', 'verify'], ['test', '-mod=readonly', '-p', '4', '.']):
        subprocess.run([go, *args], cwd=source, env=env, check=True)
    if any((source / name).read_bytes() != raw for name, raw in locks.items()):
        raise ValueError('Go modified the reviewed module locks')
    return source, go, env


def add_file(tar, source, name, mode):
    header = tarfile.TarInfo(name)
    header.mode = mode
    header.size = source.stat().st_size
    with source.open('rb') as stream:
        tar.addfile(header, stream)


def dependency_notices(go, source, env, destination):
    listing = subprocess.check_output([go, 'list', '-mod=readonly', '-deps', '-f',
                                       '{{with .Module}}{{.Path}}|{{.Dir}}{{end}}', '.'],
                                      cwd=source, env=env, text=True)
    with destination.open('wb') as out:
        for entry in sorted(set(listing.splitlines()) - {''}):
            module, directory = entry.split('|', 1)
            if Path(directory) == source:
                continue
            for file in sorted(Path(directory).iterdir()):
                if file.is_file() and file.name.lower().startswith(('license', 'copying', 'notice')):
                    out.write(f'\n{module}/{file.name}\n\n'.encode() + file.read_bytes() + b'\n')


def image_config(arch, diff_id):
    return {'architecture': arch, 'os': 'linux', 'created': EPOCH,
              'rootfs': {'type': 'layers', 'diff_ids': [diff_id]},
              'history': [{'created': EPOCH, 'created_by': 'local-path-provisioner rebuild'}],
              'config': {'WorkingDir': '/', 'Cmd': ['/usr/bin/local-path-provisioner'],
                         'Env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'],
                         'Labels': {'org.opencontainers.image.licenses': 'Apache-2.0',
                                    'org.opencontainers.image.source': 'https://github.com/Stuhlmuller/homelab',
                                    'org.opencontainers.image.version': TAG,
                                    'dev.stuhlmuller.upstream.revision': SOURCE['revision']}}}


def build(output, cache):
    if output.exists():
        raise ValueError('Output path already exists')
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.local-path-') as directory:
        scratch = Path(directory)
        source, go, env = prepare(scratch, cache)
        # regctl uses only anonymous public reads and local ocidir writes.
        registry_env = {**tool_env(), 'REGCTL_CONFIG': str(scratch / 'regctl.json'),
                        'DOCKER_CONFIG': str(scratch / 'empty-docker')}
        def regctl(*args):
            subprocess.run(['regctl', *args], env=registry_env, check=True)
        regctl('config', 'set', '--docker-cred=false', '--docker-cert=false')
        ca = scratch / 'ca.crt'
        regctl('image', 'get-file', SOURCE['ca_image'], '/etc/ssl/certs/ca-certificates.crt', ca)
        if hashlib.sha256(ca.read_bytes()).hexdigest() != SOURCE['ca_sha256']:
            raise ValueError('Upstream CA bundle does not match its recorded digest')
        layout = 'ocidir://' + str(scratch / 'image')
        for arch in ('amd64', 'arm64'):
            target_env = {**env, 'GOOS': 'linux', 'GOARCH': arch, 'GOAMD64': 'v1', 'GOARM64': 'v8.0'}
            binary = scratch / f'local-path-provisioner-{arch}'
            subprocess.run([go, 'build', '-mod=readonly', '-p', '4', '-buildvcs=false', '-trimpath',
                            '-ldflags', '-s -w -buildid= -X main.VERSION=' + SOURCE['upstream_version'],
                            '-o', binary, '.'], cwd=source, env=target_env, check=True)
            notices = scratch / f'{arch}-notices.txt'
            dependency_notices(go, source, target_env, notices)
            layer = scratch / f'{arch}.tar'
            with tarfile.open(layer, 'w', format=tarfile.USTAR_FORMAT) as tar:
                add_file(tar, ca, 'etc/ssl/certs/ca-certificates.crt', 0o644)
                add_file(tar, binary, 'usr/bin/local-path-provisioner', 0o755)
                add_file(tar, source / 'LICENSE', 'usr/share/licenses/local-path-provisioner/LICENSE', 0o644)
                add_file(tar, go.parents[1] / 'LICENSE', 'usr/share/licenses/go/LICENSE', 0o644)
                add_file(tar, notices, 'usr/share/licenses/local-path-provisioner/THIRD_PARTY', 0o644)
            with layer.open('rb') as stream:
                diff_id = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
            config = image_config(arch, diff_id)
            config_file = scratch / f'{arch}-config.json'
            config_file.write_text(json.dumps(config, sort_keys=True, separators=(',', ':')))
            regctl('artifact', 'put', layout + ':' + arch,
                   '--config-file', config_file, '--config-type', 'application/vnd.oci.image.config.v1+json',
                   '--file', layer, '--file-media-type', 'application/vnd.oci.image.layer.v1.tar')
        regctl('index', 'create', layout + ':' + TAG, '--ref', layout + ':amd64', '--ref', layout + ':arm64')
        (scratch / 'image').rename(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new local OCI layout in an existing directory')
    parser.add_argument('cache', type=Path, help='private cache for verified public archives and Go modules')
    args = parser.parse_args()
    build(args.output.resolve(), args.cache.resolve())
