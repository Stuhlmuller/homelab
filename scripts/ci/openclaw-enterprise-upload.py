#!/usr/bin/env python3
"""Publish a legacy archive only after every bounded source range is verified."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


PART_SIZE = 64 * 1024 * 1024
RANGE_READ = '''import os, stat, sys
path, offset, count, expected_size = sys.argv[1:]
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size != int(expected_size):
        sys.exit(2)
    os.lseek(fd, int(offset), os.SEEK_SET)
    remaining = int(count)
    while remaining:
        chunk = os.read(fd, min(remaining, 1024 * 1024))
        if not chunk:
            sys.exit(2)
        while chunk:
            written = os.write(1, chunk)
            chunk = chunk[written:]
            remaining -= written
finally:
    os.close(fd)
'''


def aws(*args):
    return subprocess.run(['aws', 's3api', *args, '--output', 'json'], check=True,
                          capture_output=True, text=True).stdout


def source_range(pod, path, offset, count, expected_size):
    command = ['kubectl', '-n', 'ai', 'exec', pod, '-c', 'reader', '--',
               'python3', '-c', RANGE_READ, path, str(offset), str(count),
               str(expected_size)]
    for _ in range(3):
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=180,
                                    check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and len(result.stdout) == count:
            return result.stdout
    raise ValueError('archive range read failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bucket')
    parser.add_argument('key')
    parser.add_argument('expected_size', type=int)
    parser.add_argument('expected_sha256')
    parser.add_argument('reader_pod')
    parser.add_argument('source_path')
    args = parser.parse_args()
    if args.expected_size <= 0 or len(args.expected_sha256) != 64 or any(
            c not in '0123456789abcdef' for c in args.expected_sha256) or not re.fullmatch(
            r'openclaw-retirement-reader-[a-z0-9-]+', args.reader_pod) or not re.fullmatch(
            r'/archive/private/legacy-[0-9a-f]{64}/legacy\.tar\.gz', args.source_path):
        parser.error('invalid archive identity')
    if (args.expected_size + PART_SIZE - 1) // PART_SIZE > 10000:
        parser.error('archive exceeds multipart part limit')

    upload_id = json.loads(aws('create-multipart-upload', '--bucket', args.bucket,
                               '--key', args.key))['UploadId']
    digest = hashlib.sha256()
    total = 0
    parts = []
    try:
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / 'part'
            while total < args.expected_size:
                count = min(PART_SIZE, args.expected_size - total)
                chunk = source_range(args.reader_pod, args.source_path, total,
                                     count, args.expected_size)
                digest.update(chunk)
                body.write_bytes(chunk)
                etag = json.loads(aws('upload-part', '--bucket', args.bucket,
                                      '--key', args.key, '--upload-id', upload_id,
                                      '--part-number', str(len(parts) + 1), '--body', str(body)))['ETag']
                parts.append({'ETag': etag, 'PartNumber': len(parts) + 1})
                total += count
            if digest.hexdigest() != args.expected_sha256:
                raise ValueError('archive ranges differ from verified source')
            manifest = Path(directory) / 'parts.json'
            manifest.write_text(json.dumps({'Parts': parts}))
            aws('complete-multipart-upload', '--bucket', args.bucket, '--key', args.key,
                '--upload-id', upload_id, '--multipart-upload', f'file://{manifest}')
    except BaseException:
        try:
            aws('abort-multipart-upload', '--bucket', args.bucket, '--key', args.key,
                '--upload-id', upload_id)
        except (OSError, subprocess.CalledProcessError):
            # Preserve the original failure; bucket lifecycle clears an abandoned upload.
            pass
        raise


if __name__ == '__main__':
    main()
