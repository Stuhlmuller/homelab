#!/usr/bin/env python3
"""Versioned application backup publication; never execute or delete archive data."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

SPEC = importlib.util.spec_from_file_location('etcd_offsite', Path(__file__).with_name('etcd-offsite-backup.py'))
OFFSITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OFFSITE)
CONFIG = Path(__file__).resolve().parents[1] / 'IaC/config/application-backup-storage.json'
CONTRACTS = {
    'octelium': ('globals.sql', 'octelium.dump'),
    'multica': ('globals.sql', 'multica.dump', 'uploads.tar', 'capture.json'),
    'affine': ('globals.sql', 'affine.dump', 'blobs.tar', 'config.tar', 'capture.json'),
    'media-postgres': ('globals.sql', 'sonarr-main.dump', 'sonarr-log.dump',
                       'radarr-main.dump', 'radarr-log.dump', 'prowlarr-main.dump', 'prowlarr-log.dump'),
}
MAX_AGE = 30 * 3600
ID = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}')


def target():
    value = json.loads(CONFIG.read_text())
    if (set(value) != {'account_id', 'region', 'bucket'}
            or not re.fullmatch(r'[0-9]{12}', value['account_id'])
            or value['region'] != 'us-east-1'
            or value['bucket'] != f"homelab-application-backups-{value['account_id']}-{value['region']}"):
        raise ValueError('invalid committed destination')
    return value


def now():
    return datetime.now(timezone.utc).timestamp()


def captured(stamp):
    return datetime.strptime(stamp, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()


def fresh(stamp):
    age = now() - captured(stamp)
    if not -300 <= age <= MAX_AGE:
        raise ValueError('source recovery point is stale or in the future')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def write(path, data):
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def safe_source(path):
    # No symlinks, special files, or multiply linked files, including ancestors.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink in source path')
    info = path.lstat()
    if not path.is_file() or info.st_nlink != 1:
        raise ValueError('source must be an ordinary single-link file')


def prepare(source, workspace, app):
    """Copy only the existing CronJob's completed, checksummed file allowlist."""
    if app not in CONTRACTS:
        raise ValueError('unsupported application')
    fresh(source.name)
    names = CONTRACTS[app]
    safe_source(source / 'SHA256SUMS')
    if (source / 'SHA256SUMS').stat().st_size > 16384:
        raise ValueError('oversized checksum manifest')
    lines = (source / 'SHA256SUMS').read_text().splitlines()
    hashes = {}
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64})  (?:\./)?([a-z0-9.-]+)', line)
        if not match or match[2] not in names or match[2] in hashes:
            raise ValueError('invalid source checksum manifest')
        hashes[match[2]] = match[1]
    if set(hashes) != set(names):
        raise ValueError('incomplete application recovery set')
    workspace = OFFSITE.backup.private_directory(workspace)
    pending = Path(tempfile.mkdtemp(prefix='.partial-source-', dir=workspace))
    objects = {}
    for name in names:
        safe_source(source / name)
        descriptor = os.open(source / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as original:
            info = os.fstat(original.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 5 * 1024**3:
                raise ValueError('invalid source file')
            with (pending / name).open('xb') as output:
                os.chmod(pending / name, 0o600)
                remaining = info.st_size
                if sum(item['bytes'] for item in objects.values()) + remaining > 5 * 1024**3:
                    raise ValueError('recovery set exceeds publication budget')
                while remaining:
                    chunk = original.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError('source truncated during copy')
                    output.write(chunk)
                    remaining -= len(chunk)
                if original.read(1):
                    raise ValueError('source grew during copy')
        (pending / name).chmod(0o600)
        OFFSITE.sync_file(pending / name)
        objects[name] = OFFSITE.digest(pending / name)
        if objects[name]['sha256'] != hashes[name]:
            raise ValueError('source checksum failure')
    if sum(item['bytes'] for item in objects.values()) > 5 * 1024**3:
        raise ValueError('recovery set exceeds 5 GiB publication budget')
    if app in ('multica', 'affine'):
        if (pending / 'capture.json').stat().st_size > 16384:
            raise ValueError('oversized capture record')
        capture = json.loads((pending / 'capture.json').read_text())
        if (capture.get('captured_at') != source.name or capture.get('writers_fenced') is not True
                or not isinstance(capture.get('approved_fence_reference'), str)
                or not capture['approved_fence_reference'].strip()):
            raise ValueError('paired database/blob sets require a reviewed writer fence')
    record = {'format': 1, 'app': app, 'captured_at': source.name, 'objects': objects}
    identifier = source.name + '-' + hashlib.sha256(canonical(record)).hexdigest()
    write(pending / 'source.json', canonical(record))
    complete = workspace / identifier
    if complete.exists():
        if load(complete) != record:
            raise ValueError('existing preparation differs')
        # Keep the duplicate working copy; no automated archive deletion.
        return complete
    pending.rename(complete)
    OFFSITE.backup.sync_directory(workspace)
    return complete


def validate_record(record, identifier, versions=False):
    if (not ID.fullmatch(identifier) or record.get('format') != 1
            or record.get('app') not in CONTRACTS
            or record.get('captured_at') != identifier[:16]
            or set(record.get('objects', {})) != set(CONTRACTS[record['app']])):
        raise ValueError('invalid application manifest')
    captured(record['captured_at'])
    unversioned = {}
    for name, item in record['objects'].items():
        digest = item.get('digest', {}) if versions else item
        if (set(digest) != {'bytes', 'sha256'} or type(digest['bytes']) is not int
                or not 0 < digest['bytes'] <= 5 * 1024**3
                or not re.fullmatch(r'[0-9a-f]{64}', digest['sha256'])):
            raise ValueError('invalid object digest')
        if versions and (not isinstance(item.get('version_id'), str)
                         or item['version_id'] in ('', 'null')):
            raise ValueError('missing immutable object version')
        unversioned[name] = digest
    if sum(item['bytes'] for item in unversioned.values()) > 5 * 1024**3:
        raise ValueError('recovery set exceeds 5 GiB publication budget')
    original = {'format': 1, 'app': record['app'], 'captured_at': record['captured_at'], 'objects': unversioned}
    if hashlib.sha256(canonical(original)).hexdigest() != identifier[17:]:
        raise ValueError('manifest identity mismatch')
    return original


def load(directory):
    directory = OFFSITE.backup.private_directory(directory)
    OFFSITE.private_file(directory / 'source.json')
    record = json.loads((directory / 'source.json').read_text())
    validate_record(record, directory.name)
    for name, digest in record['objects'].items():
        if OFFSITE.digest(directory / name) != digest:
            raise ValueError('prepared source changed')
    return record


def upload(aws, key, path, digest):
    args = ['--key', key, '--checksum-mode', 'ENABLED']
    metadata = aws.call('s3api', 'head-object', args, missing=True)
    if metadata is None:
        response = aws.call('s3api', 'put-object', [
            '--key', key, '--body', str(path), '--if-none-match', '*',
            '--checksum-algorithm', 'SHA256', '--checksum-sha256', OFFSITE.checksum(digest),
            '--server-side-encryption', 'aws:kms', '--ssekms-key-id',
            f"arn:aws:kms:{aws.target['region']}:{aws.target['account_id']}:alias/aws/s3",
            '--bucket-key-enabled'])
        version = response.get('VersionId')
        if not version or version == 'null':
            raise ValueError('unversioned upload')
        metadata = aws.call('s3api', 'head-object', [*args, '--version-id', version])
        return OFFSITE.object_metadata(metadata, digest, version)
    return OFFSITE.object_metadata(metadata, digest)


def download(aws, key, item, path):
    metadata = aws.call('s3api', 'get-object', [
        '--key', key, '--version-id', item['version_id'], '--checksum-mode', 'ENABLED', str(path)])
    path.chmod(0o600)
    OFFSITE.sync_file(path)
    OFFSITE.object_metadata(metadata, item['digest'], item['version_id'])
    if OFFSITE.digest(path) != item['digest']:
        raise ValueError('downloaded bytes failed checksum')


def publish(directory, workspace, aws):
    record = load(directory)
    fresh(record['captured_at'])
    aws.check()
    prefix = f"applications/{record['app']}/{directory.name}"
    manifest = {'format': 1, 'app': record['app'], 'captured_at': record['captured_at'], 'objects': {}}
    scratch = Path(tempfile.mkdtemp(prefix='.partial-verification-', dir=workspace))
    for name, digest in record['objects'].items():
        if load(directory) != record:
            raise ValueError('source changed during publication')
        version = upload(aws, f'{prefix}/{name}', directory / name, digest)
        item = {'digest': digest, 'version_id': version}
        download(aws, f'{prefix}/{name}', item, scratch / name)
        manifest['objects'][name] = item
    fresh(record['captured_at'])
    if load(directory) != record:
        raise ValueError('source changed before completion')
    # A remote completion marker exists only after every version was downloaded
    # and its actual bytes checked. Content is deterministic for resumable PUTs.
    write(scratch / 'complete.json', canonical(manifest))
    digest = OFFSITE.digest(scratch / 'complete.json')
    version = upload(aws, f'{prefix}/complete.json', scratch / 'complete.json', digest)
    download(aws, f'{prefix}/complete.json', {'digest': digest, 'version_id': version}, scratch / 'marker-check.json')
    OFFSITE.save(directory / 'publication.json', {'destination': aws.target, 'id': directory.name,
                 'marker_version': version, 'verified_at': now(), 'application_restore_tested': False})
    return directory.name


def retrieve(app, identifier, workspace, aws):
    if app not in CONTRACTS or not ID.fullmatch(identifier):
        raise ValueError('invalid application or recovery ID')
    workspace = OFFSITE.backup.private_directory(workspace)
    aws.check()
    prefix = f'applications/{app}/{identifier}'
    scratch = Path(tempfile.mkdtemp(prefix='.partial-retrieval-', dir=workspace))
    meta = aws.call('s3api', 'head-object', ['--key', f'{prefix}/complete.json', '--checksum-mode', 'ENABLED'])
    if not 0 < meta.get('ContentLength', 0) <= 16384:
        raise ValueError('invalid completion marker size')
    # Resolve the immutable marker version before reading any content.
    version = meta.get('VersionId')
    if not version or version == 'null':
        raise ValueError('unversioned completion marker')
    response = aws.call('s3api', 'get-object', ['--key', f'{prefix}/complete.json', '--version-id', version,
                        '--checksum-mode', 'ENABLED', str(scratch / 'complete.json')])
    (scratch / 'complete.json').chmod(0o600)
    OFFSITE.sync_file(scratch / 'complete.json')
    digest = OFFSITE.digest(scratch / 'complete.json')
    OFFSITE.object_metadata(meta, digest, version)
    OFFSITE.object_metadata(response, digest, version)
    record = json.loads((scratch / 'complete.json').read_text())
    validate_record(record, identifier, versions=True)
    if record['app'] != app:
        raise ValueError('wrong application')
    for name, item in record['objects'].items():
        download(aws, f'{prefix}/{name}', item, scratch / name)
    OFFSITE.save(scratch / 'retrieval.json', {'id': identifier, 'marker_version': version,
                 'destination': aws.target, 'verified_at': now(), 'application_restore_tested': False})
    complete = scratch.with_name(scratch.name.replace('.partial-', '', 1))
    scratch.rename(complete)
    OFFSITE.backup.sync_directory(workspace)
    return complete


def completed(aws, app):
    if app not in CONTRACTS:
        raise ValueError('unsupported application')
    aws.check()
    prefix = f'applications/{app}/'
    response = aws.call('s3api', 'list-objects-v2', ['--prefix', prefix])
    # AWS CLI JSON pagination aggregates Contents. Partial object prefixes are
    # never candidates. Invalid completion IDs fail closed.
    result = []
    for item in response.get('Contents', []):
        key = item['Key']
        if key.endswith('/complete.json'):
            identifier = key.removeprefix(prefix).removesuffix('/complete.json')
            if not ID.fullmatch(identifier):
                raise ValueError('unexpected completion marker')
            result.append(identifier)
    return sorted(result)


def retention_plan(identifiers, current=None):
    """Advisory only: retain all; protect newest seven and all under 30 days."""
    current = now() if current is None else current
    identifiers = sorted(set(identifiers))
    if any(not ID.fullmatch(item) for item in identifiers):
        raise ValueError('invalid retention inventory')
    protected = set(identifiers[-7:])
    return [item for item in identifiers if item not in protected
            and current - captured(item[:16]) > 30 * 86400]


def metrics(path, app, success, stamp=0):
    data = (f'homelab_application_backup_check_success{{app="{app}"}} {int(success)}\n'
            f'homelab_application_backup_capture_timestamp_seconds{{app="{app}"}} {stamp}\n'
            f'homelab_application_backup_check_timestamp_seconds{{app="{app}"}} {now()}\n')
    temporary = path.with_name(path.name + '.partial')
    # Single scheduler invocation required; no blind overwrite of partial files.
    write(temporary, data.encode())
    temporary.replace(path)
    OFFSITE.backup.sync_directory(path.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'publish', 'retrieve', 'check', 'retention-plan'])
    parser.add_argument('--app', choices=CONTRACTS, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--id')
    parser.add_argument('--aws-cli', type=Path)
    parser.add_argument('--profile', default='application-backup')
    parser.add_argument('--metrics', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    success, stamp = False, 0
    try:
        workspace = OFFSITE.backup.private_directory(args.workspace)
        if args.command == 'prepare':
            print(prepare(args.source, workspace, args.app).name)
            return 0
        aws = OFFSITE.AWS(args.aws_cli, args.profile, target())
        if args.command == 'publish':
            if not args.id or not ID.fullmatch(args.id):
                raise ValueError('explicit prepared recovery ID required')
            if load(workspace / args.id)['app'] != args.app:
                raise ValueError('application differs from preparation')
            print(publish(workspace / args.id, workspace, aws))
        elif args.command == 'retrieve':
            print(retrieve(args.app, args.id or '', workspace, aws).name)
        else:
            identifiers = completed(aws, args.app)
            if args.command == 'retention-plan':
                print(json.dumps({'delete_authorized': False, 'actual_retention': 'indefinite',
                                  'review_candidates': retention_plan(identifiers)}))
            else:
                if not identifiers:
                    raise ValueError('no independently completed backup')
                identifier = identifiers[-1]
                fresh(identifier[:16])
                retrieve(args.app, identifier, workspace, aws)
                fresh(identifier[:16])
                success, stamp = True, captured(identifier[:16])
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        print('Application backup failed; retain private scratch. No cleanup or restore was attempted.', file=sys.stderr)
        return 1
    finally:
        if args.command == 'check' and args.metrics:
            metrics(args.metrics, args.app, success, stamp)


if __name__ == '__main__':
    sys.exit(main())
