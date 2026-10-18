#!/usr/bin/env python3
"""Inventory and independently restore-verify retained legacy OpenClaw state."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath


STORAGE = Path(__file__).with_name('runtime-storage.py')
if not STORAGE.exists():
    STORAGE = Path(__file__).parent.parent / 'assistant/runtime-storage.py'
spec = importlib.util.spec_from_file_location('openclaw_runtime_storage', STORAGE)
runtime_storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_storage)

KEEPALIVE_SECONDS = 30


def keepalive(stop):
    while not stop.wait(KEEPALIVE_SECONDS):
        print('Legacy retention operation active', file=sys.stderr, flush=True)


def private_dir(path, owner=None):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('private destination must be an absolute, non-symlink directory')
    path = path.resolve(strict=True)
    info = path.stat()
    if not path.is_dir() or info.st_uid != (os.getuid() if owner is None else owner) \
            or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private destination must be owned by this user with mode 0700')
    if any((part / '.git').exists() for part in (path, *path.parents)):
        raise ValueError('private destination must be outside Git')
    return path


def private_file(path, owner=None):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('private file cannot be a symlink')
    info = path.stat()
    if not path.is_file() or info.st_uid != (os.getuid() if owner is None else owner) \
            or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('private file must be owned by this user with mode 0600')
    private_dir(path.parent, owner)
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree(root):
    """Bind every retained byte and permission, including historical archives."""
    record = hashlib.sha256()
    count = total = 0
    for path in (root, *sorted(root.rglob('*'))):
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)):
            raise ValueError('unsupported special file in legacy state')
        value = {
            'path': str(path.relative_to(root)), 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid, 'size': info.st_size,
            'mtimeNs': info.st_mtime_ns,
            'type': 'file' if stat.S_ISREG(info.st_mode) else
                    'link' if stat.S_ISLNK(info.st_mode) else 'directory',
        }
        if stat.S_ISREG(info.st_mode):
            value['sha256'] = digest(path)
            total += info.st_size
        elif stat.S_ISLNK(info.st_mode):
            value['target'] = os.readlink(path)
        record.update(json.dumps(value, sort_keys=True).encode() + b'\n')
        count += 1
    return {'entries': count, 'bytes': total, 'sha256': record.hexdigest()}


def write_private(path, value, owner=None):
    private_dir(path.parent, owner)
    with path.open('x', encoding='utf-8') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(value, output, sort_keys=True, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())


def config_at(path):
    config = json.loads(Path(path).read_text())['legacyRetention']
    for key in ('requiredLocal', 'requiredNas'):
        for name in config[key]:
            item = PurePosixPath(name)
            if item.is_absolute() or '..' in item.parts or str(item) in ('', '.'):
                raise ValueError('unsafe committed required path')
    return config


def roots(config):
    local, nas = Path(config['localRoot']), Path(config['nasRoot'])
    for root, uid in ((local, config['localUid']), (nas, config['nasUid'])):
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid != uid:
            raise ValueError('legacy root missing or ownership changed')
    if local.resolve() == nas.resolve() or local.resolve().is_relative_to(nas.resolve()):
        raise ValueError('local and NAS roots overlap')
    for relative in config['requiredLocal']:
        file = local / relative
        if not file.is_file() or file.is_symlink() or file.stat().st_uid != config['localUid']:
            raise ValueError('required local database missing or ownership changed')
        runtime_storage.verify_database(file)
    for relative in config['requiredNas']:
        item = nas / relative
        if not item.is_dir() or item.is_symlink() or not any(item.iterdir()):
            raise ValueError('required NAS state or historical checkpoint missing')
    for relative, mount in (
        (config['requiredLocal'][0], config['stateMount']),
        (config['requiredLocal'][1], config['agentMount']),
    ):
        target = Path(mount) / Path(relative).name
        if not target.is_file() or not (local / relative).samefile(target):
            raise ValueError('overlapping local PV mount identity changed')
    return local, nas


def volume_identity(status, config):
    checked = status.get('checkedAt')
    if (type(checked) is not int or not 0 <= time.time() - checked <= 120
            or status.get('namespace') != config['namespace']
            or status.get('deployment') != config['deployment']
            or status.get('nodeReady') is not True):
        raise ValueError('legacy Kubernetes inventory is stale or uncertain')
    claims = {name: config[name] for name in ('localClaim', 'stateClaim', 'agentClaim', 'nasClaim')}
    volumes = status.get('volumes')
    if not isinstance(volumes, dict) or set(volumes) != set(claims.values()):
        raise ValueError('legacy volume identity is incomplete')
    for claim, item in volumes.items():
        if (not isinstance(item, dict) or set(item) != {'pvcUid', 'pvName', 'pvUid'}
                or any(not isinstance(value, str) or len(value) < 8 for value in item.values())
                or claim != config['nasClaim'] and item['pvName'] != claim):
            raise ValueError('legacy PVC/PV identity is incomplete or unexpected')
    if (status.get('image') != config['image']
            or status.get('assistantSha256') != config['assistantSha256']
            or status.get('claims') != claims or status.get('node') != config['node']):
        raise ValueError('legacy deployment or claim identity changed')
    return {'image': status['image'], 'assistantSha256': status['assistantSha256'],
            'volumes': volumes}


def inventory(config, status=None):
    identity = volume_identity(status, config) if status is not None else None
    local, nas = roots(config)
    result = {
        'format': 1,
        'node': config['node'],
        'claims': {name: config[name] for name in ('localClaim', 'stateClaim', 'agentClaim', 'nasClaim')},
        'roots': {
            'local': {'device': local.stat().st_dev, 'inode': local.stat().st_ino,
                      'uid': local.stat().st_uid, 'tree': tree(local)},
            'nas': {'device': nas.stat().st_dev, 'inode': nas.stat().st_ino,
                    'uid': nas.stat().st_uid, 'tree': tree(nas)},
        },
        'databases': {name: {'bytes': (local / name).stat().st_size,
                             'sha256': digest(local / name)} for name in config['requiredLocal']},
        'requiredNas': config['requiredNas'],
    }
    if status is not None:
        result['kubernetes'] = identity
        if not all(status.get('roots', {}).get(name) == {
            key: result['roots'][name][key] for key in ('device', 'inode', 'uid')
        } for name in ('local', 'nas')):
            raise ValueError('legacy mounted root identity changed')
    return result


def stopped(status, config, observed, baseline):
    checked = status.get('checkedAt')
    roots_match = all(status.get('roots', {}).get(name) == {
        key: observed['roots'][name][key] for key in ('device', 'inode', 'uid')
    } for name in ('local', 'nas'))
    if (type(checked) is not int or not 0 <= time.time() - checked <= 120
            or status.get('namespace') != config['namespace']
            or status.get('node') != config['node']
            or status.get('nodeReady') is not True
            or status.get('deployment') != config['deployment']
            or status.get('image') != config['image']
            or status.get('assistantSha256') != config['assistantSha256']
            or status.get('replicas') != 0 or status.get('readyReplicas') != 0
            or status.get('pods') != 0 or status.get('cronJob') != config['cronJob']
            or not (status.get('cronJobSuspended') is True
                    or status.get('cronJobAbsent') is True)
            or status.get('activeJobs') != 0
            or status.get('claims') != observed['claims']
            or volume_identity(status, config) != observed.get('kubernetes')
            or observed.get('kubernetes') != baseline.get('kubernetes')
            or {name: {key: item[key] for key in ('device', 'inode', 'uid')}
                for name, item in observed['roots'].items()} != baseline.get('rootIdentity')
            or not roots_match):
        raise ValueError('legacy writer or source identity is active, missing, or uncertain')


def add_tree(tar, root, label):
    def check(member):
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError('unsupported special file in legacy state')
        if member.issym() and (PurePosixPath(member.linkname).is_absolute()
                              or '..' in PurePosixPath(member.linkname).parts):
            raise ValueError('unsafe source symlink in legacy state')
        return member

    tar.add(root, arcname=label, recursive=True, filter=check)


def verify_bundle(bundle, expected, config):
    private_file(bundle, config['nasUid'])
    if digest(bundle) != expected:
        raise ValueError('archive checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='oce-legacy-restore-',
                                     dir=private_dir(bundle.parent, config['nasUid'])) as scratch:
        with tarfile.open(bundle, 'r:gz') as tar:
            members = tar.getmembers()
            if not members or any(PurePosixPath(m.name).parts[0] not in ('local', 'nas') for m in members):
                raise ValueError('archive contains unexpected root')
            tar.extractall(scratch, filter='data')
        local, nas = Path(scratch) / 'local', Path(scratch) / 'nas'
        for relative in config['requiredLocal']:
            runtime_storage.verify_database(local / relative)
        for relative in config['requiredNas']:
            item = nas / relative
            if not item.is_dir() or not any(item.iterdir()):
                raise ValueError('archive restore omitted required NAS state')
        return {name: digest(local / name) for name in config['requiredLocal']}


def archive(config, status_path, baseline_path, observed_path, destination):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('archive runs only in the protected workflow')
    status = json.loads(private_file(status_path).read_text())
    baseline = json.loads(private_file(baseline_path, config['nasUid']).read_text())
    observed = json.loads(private_file(observed_path).read_text())
    if observed.get('format') != 1 or observed.get('requiredNas') != config['requiredNas']:
        raise ValueError('legacy inventory is incomplete or mismatched')
    stopped(status, config, observed, baseline)
    destination = private_dir(destination, config['nasUid'])
    if any(destination.is_relative_to(root.resolve()) for root in roots(config)):
        raise ValueError('archive destination cannot share a source root')
    scratch = Path(tempfile.mkdtemp(prefix='.partial-oce-legacy-', dir=destination))
    bundle = scratch / 'legacy.tar.gz'
    with bundle.open('xb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', mtime=0, filename='') as compressed:
            with tarfile.open(fileobj=compressed, mode='w', dereference=False) as tar:
                local, nas = roots(config)
                add_tree(tar, local, 'local')
                add_tree(tar, nas, 'nas')
    bundle.chmod(0o600)
    restored = verify_bundle(bundle, digest(bundle), config)
    if restored != {name: item['sha256'] for name, item in observed['databases'].items()}:
        raise ValueError('restored database differs from stopped source')
    if inventory(config) != {key: value for key, value in observed.items()
                             if key not in ('kubernetes', 'rootIdentity')}:
        raise ValueError('legacy source changed during archive')
    receipt = {'format': 1, 'inventory': observed, 'sha256': digest(bundle),
               'restoredDatabases': restored}
    completed = destination / ('legacy-' + receipt['sha256'])
    if completed.exists():
        existing = completed / 'receipt.json'
        if verify_archive(config, existing) != receipt:
            raise ValueError('existing archive with this identity differs')
        shutil.rmtree(scratch)
        return existing
    write_private(scratch / 'receipt.json', receipt, config['nasUid'])
    os.rename(scratch, completed)
    return completed / 'receipt.json'


def verify_archive(config, receipt_path):
    receipt_path = private_file(receipt_path, config['nasUid'])
    record = json.loads(receipt_path.read_text())
    identity = record.get('inventory', {})
    if (record.get('format') != 1
            or identity.get('node') != config['node']
            or identity.get('requiredNas') != config['requiredNas']
            or set(identity.get('databases', {})) != set(config['requiredLocal'])
            or identity.get('claims') != {name: config[name] for name in (
                'localClaim', 'stateClaim', 'agentClaim', 'nasClaim')}):
        raise ValueError('archive receipt does not match the committed recovery contract')
    restored = verify_bundle(receipt_path.parent / 'legacy.tar.gz', record['sha256'], config)
    if restored != record['restoredDatabases'] or restored != {
        name: item['sha256'] for name, item in record['inventory']['databases'].items()
    }:
        raise ValueError('archive restore differs from receipt')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('inventory', 'archive', 'verify-archive'))
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--status', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--observed', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    stop = threading.Event()
    heartbeat = threading.Thread(target=keepalive, args=(stop,), daemon=True)
    heartbeat.start()
    try:
        config = config_at(args.config)
        if args.operation == 'inventory' and args.output and args.status:
            status = json.loads(private_file(args.status).read_text())
            observed = inventory(config, status)
            observed['rootIdentity'] = {name: {key: item[key] for key in ('device', 'inode', 'uid')}
                                        for name, item in observed['roots'].items()}
            write_private(args.output, observed)
        elif args.operation == 'archive' and args.status and args.baseline and args.observed and args.destination:
            receipt = archive(config, args.status, args.baseline, args.observed, args.destination)
            if args.output:
                write_private(args.output, {'receipt': str(receipt)})
            print('Verified private legacy archive')
        elif args.operation == 'verify-archive' and args.receipt:
            verify_archive(config, args.receipt)
            print('Verified independent legacy restore')
        else:
            parser.error('operation-specific private output, status, destination, or receipt required')
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, tarfile.TarError) as error:
        print(f'Legacy retirement refused: {type(error).__name__}', file=sys.stderr)
        return 1
    finally:
        stop.set()
        heartbeat.join()


if __name__ == '__main__':
    sys.exit(main())
