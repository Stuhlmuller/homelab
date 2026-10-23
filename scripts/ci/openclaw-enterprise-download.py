#!/usr/bin/env python3
"""Restore one immutable S3 version through bounded, verified reader slices."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path


RANGE_SIZE = 128 * 1024 * 1024
SLICE_SIZE = 8 * 1024 * 1024


class SourceReadError(Exception):
    pass


class ReaderTransferError(Exception):
    pass


REMOTE = r'''import fcntl, glob, hashlib, os, stat, sys
os.umask(0o077)
op = sys.argv[1]

def regular(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('not a regular file')
    return fd

def read_at(fd, offset, count):
    result = bytearray()
    while len(result) < count:
        part = os.pread(fd, count - len(result), offset + len(result))
        if not part:
            break
        result.extend(part)
    return bytes(result)

if op == 'init':
    destination, partial = sys.argv[2:]
    if os.path.lexists(destination) or os.path.lexists(partial):
        raise ValueError('restore destination exists')
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
elif op == 'upload':
    chunk, count, expected = sys.argv[2:]
    count = int(count)
    fd = os.open(chunk, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    complete = False
    try:
        digest = hashlib.sha256()
        received = 0
        while received <= count:
            part = os.read(0, min(1024 * 1024, count - received + 1))
            if not part:
                break
            if received + len(part) > count:
                raise ValueError('oversized reader slice')
            digest.update(part)
            while part:
                written = os.write(fd, part)
                part = part[written:]
                received += written
        if received != count or digest.hexdigest() != expected:
            raise ValueError('reader slice differs from runner')
        os.fsync(fd)
        complete = True
    finally:
        os.close(fd)
        if not complete:
            os.unlink(chunk)
elif op == 'commit':
    chunk, partial, offset, count, expected = sys.argv[2:]
    offset, count = int(offset), int(count)
    fd = regular(chunk, os.O_RDONLY)
    try:
        if os.fstat(fd).st_size != count:
            raise ValueError('reader slice length changed')
        data = read_at(fd, 0, count)
        if len(data) != count or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('reader slice digest changed')
    finally:
        os.close(fd)
    fd = regular(partial, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.fstat(fd).st_size
        if size == offset + count:
            prior = read_at(fd, offset, count)
            if len(prior) != count or hashlib.sha256(prior).hexdigest() != expected:
                raise ValueError('prior committed slice differs')
        else:
            if not offset <= size < offset + count:
                raise ValueError('unexpected aggregate offset')
            if size != offset:
                os.ftruncate(fd, offset)
                os.fsync(fd)
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                remaining = memoryview(data)
                while remaining:
                    remaining = remaining[os.write(fd, remaining):]
                os.fsync(fd)
                if os.fstat(fd).st_size != offset + count:
                    raise ValueError('incomplete aggregate append')
            except BaseException:
                os.ftruncate(fd, offset)
                os.fsync(fd)
                raise
    finally:
        os.close(fd)
    os.unlink(chunk)
elif op == 'finish':
    partial, destination, count, expected = sys.argv[2:]
    count = int(count)
    if os.path.lexists(partial) and os.path.lexists(destination) and not os.path.samefile(partial, destination):
        raise ValueError('restore destination differs from aggregate')
    path = destination if os.path.isfile(destination) and not os.path.islink(destination) else partial
    fd = regular(path, os.O_RDONLY)
    try:
        if os.fstat(fd).st_size != count:
            raise ValueError('aggregate length differs from S3 version')
        digest = hashlib.sha256()
        while part := os.read(fd, 1024 * 1024):
            digest.update(part)
        if digest.hexdigest() != expected:
            raise ValueError('aggregate digest differs from published receipt')
    finally:
        os.close(fd)
    if path == partial:
        os.link(partial, destination, follow_symlinks=False)
    if os.path.lexists(partial):
        os.unlink(partial)
elif op == 'discard':
    chunk = sys.argv[2]
    if os.path.lexists(chunk):
        os.unlink(chunk)
elif op == 'cleanup':
    partial, chunk_prefix = sys.argv[2:]
    if os.path.lexists(partial):
        os.unlink(partial)
    for chunk in glob.glob(glob.escape(chunk_prefix) + '*'):
        os.unlink(chunk)
else:
    raise ValueError('invalid reader operation')
'''


def reader(pod, operation, *arguments, data=None, timeout=180):
    command = ['kubectl', '-n', 'ai', 'exec']
    if data is not None:
        command.append('-i')
    command += [pod, '-c', 'reader', '--', 'python3', '-c', REMOTE,
                operation, *map(str, arguments)]
    try:
        result = subprocess.run(command, input=data, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReaderTransferError from error
    if result.returncode:
        raise ReaderTransferError


def source_range(bucket, key, version, total, start, count, body):
    end = start + count - 1
    for _ in range(3):
        body.unlink(missing_ok=True)
        command = ['aws', 's3api', 'get-object', '--bucket', bucket, '--key', key,
                   '--version-id', version, '--range', f'bytes={start}-{end}',
                   str(body), '--output', 'json']
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=300, check=False)
            if result.returncode:
                continue
            response = json.loads(result.stdout)
            if (response.get('VersionId') == version and
                    response.get('ContentRange') == f'bytes {start}-{end}/{total}' and
                    response.get('ContentLength') == count and
                    body.is_file() and body.stat().st_size == count):
                return
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
    raise SourceReadError


def restore_version(bucket, key, version, destination, total, expected, pod):
    token = uuid.uuid4().hex
    partial = destination + '.partial-' + token
    chunk_prefix = destination + '.chunk-' + token + '-'
    complete = False
    try:
        reader(pod, 'init', destination, partial)
        with tempfile.TemporaryDirectory(prefix='oce-restore-range-') as directory:
            body = Path(directory) / 'range'
            committed = 0
            while committed < total:
                count = min(RANGE_SIZE, total - committed)
                source_range(bucket, key, version, total, committed, count, body)
                with body.open('rb') as source:
                    remaining = count
                    while remaining:
                        slice_bytes = source.read(min(SLICE_SIZE, remaining))
                        if not slice_bytes:
                            raise SourceReadError
                        slice_sha = hashlib.sha256(slice_bytes).hexdigest()
                        for _ in range(3):
                            chunk = f'{chunk_prefix}{committed}-{uuid.uuid4().hex}'
                            try:
                                reader(pod, 'upload', chunk, len(slice_bytes), slice_sha,
                                       data=slice_bytes)
                                reader(pod, 'commit', chunk, partial, committed,
                                       len(slice_bytes), slice_sha)
                                break
                            except ReaderTransferError:
                                try:
                                    reader(pod, 'discard', chunk)
                                except ReaderTransferError:
                                    # Retry names are unique; failed restores clean run-owned scratch.
                                    pass
                        else:
                            raise ReaderTransferError
                        committed += len(slice_bytes)
                        remaining -= len(slice_bytes)
            for _ in range(2):
                try:
                    reader(pod, 'finish', partial, destination, total, expected, timeout=1200)
                    break
                except ReaderTransferError:
                    continue
            else:
                raise ReaderTransferError
        complete = True
    finally:
        if not complete:
            try:
                reader(pod, 'cleanup', partial, chunk_prefix)
            except ReaderTransferError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bucket')
    parser.add_argument('key')
    parser.add_argument('version')
    parser.add_argument('destination')
    parser.add_argument('size', type=int)
    parser.add_argument('sha256')
    parser.add_argument('reader_pod')
    args = parser.parse_args()
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or not run_id.isdigit() or
            not re.fullmatch(r'homelab-application-backups-[0-9]{12}-us-east-1', args.bucket) or
            not args.key or not args.version or args.size <= 0 or
            not re.fullmatch(r'[0-9a-f]{64}', args.sha256) or
            not re.fullmatch(r'openclaw-retirement-reader-[a-z0-9-]+', args.reader_pod) or
            not re.fullmatch(rf'/archive/private/offsite-{run_id}/(legacy\.tar\.gz|receipt\.json)',
                             args.destination)):
        parser.error('invalid immutable restore identity')
    restore_version(args.bucket, args.key, args.version, args.destination,
                    args.size, args.sha256, args.reader_pod)


if __name__ == '__main__':
    try:
        main()
    except (SourceReadError, ReaderTransferError):
        raise SystemExit(1) from None
