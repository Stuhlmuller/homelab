#!/usr/bin/env python3
"""Publish a legacy archive only after its complete source stream is verified."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


PART_SIZE = 64 * 1024 * 1024


def aws(*args):
    return subprocess.run(['aws', 's3api', *args, '--output', 'json'], check=True,
                          capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bucket')
    parser.add_argument('key')
    parser.add_argument('expected_size', type=int)
    parser.add_argument('expected_sha256')
    args = parser.parse_args()
    if args.expected_size <= 0 or len(args.expected_sha256) != 64 or any(
            c not in '0123456789abcdef' for c in args.expected_sha256):
        parser.error('invalid expected archive size or digest')

    upload_id = json.loads(aws('create-multipart-upload', '--bucket', args.bucket,
                               '--key', args.key))['UploadId']
    digest = hashlib.sha256()
    total = 0
    parts = []
    with tempfile.TemporaryDirectory() as directory:
        body = Path(directory) / 'part'
        while chunk := sys.stdin.buffer.read(PART_SIZE):
            total += len(chunk)
            if total > args.expected_size:
                raise ValueError('archive stream exceeds source size')
            digest.update(chunk)
            body.write_bytes(chunk)
            etag = json.loads(aws('upload-part', '--bucket', args.bucket,
                                  '--key', args.key, '--upload-id', upload_id,
                                  '--part-number', str(len(parts) + 1), '--body', str(body)))['ETag']
            parts.append({'ETag': etag, 'PartNumber': len(parts) + 1})
        if total != args.expected_size or digest.hexdigest() != args.expected_sha256:
            raise ValueError('archive stream differs from verified source')
        manifest = Path(directory) / 'parts.json'
        manifest.write_text(json.dumps({'Parts': parts}))
        aws('complete-multipart-upload', '--bucket', args.bucket, '--key', args.key,
            '--upload-id', upload_id, '--multipart-upload', f'file://{manifest}')


if __name__ == '__main__':
    main()
