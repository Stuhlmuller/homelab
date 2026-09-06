#!/usr/bin/env python3
"""Check privately collected Istio logs within an explicit trailing 24-hour window."""
import argparse
import calendar
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat
import sys

TIMESTAMP = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z')
SIGNATURE = re.compile(r'readiness.*(500|fail)|500.*readiness|\[::1\]:15053|::/0|ipv6.*(fail|error)', re.I)
DAY_NS = 24 * 60 * 60 * 1_000_000_000


class InvalidInput(ValueError):
    """The retained input cannot establish a clean signature check."""


def timestamp_ns(value):
    match = TIMESTAMP.fullmatch(value)
    if match is None:
        raise InvalidInput('Expected a UTC RFC3339 timestamp with at most nine fractional digits')
    try:
        whole = datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise InvalidInput('Invalid timestamp date or time') from error
    return calendar.timegm(whole.utctimetuple()) * 1_000_000_000 + int((match[2] or '').ljust(9, '0'))


def format_ns(value):
    seconds, fraction = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{fraction:09d}Z'


def inspect(directory, end):
    start = end - DAY_NS
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise InvalidInput('Expected a regular log directory, without a symbolic link')
    paths = sorted(directory.iterdir())
    if not paths:
        raise InvalidInput('Log inventory is empty')
    counts = {'files': len(paths), 'records': 0, 'in_window_records': 0, 'matches': 0}
    for path in paths:
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size == 0:
            raise InvalidInput('Every log must be a nonempty regular file, without symbolic links')
        if path.suffix.lower() == '.gz':
            raise InvalidInput('Decompress retained rotations before inspection')
        with path.open(encoding='utf-8', errors='strict') as stream:
            for line in stream:
                stamp, separator, message = line.rstrip('\r\n').partition(' ')
                if not separator:
                    raise InvalidInput('Every log record needs a timestamp and message')
                recorded = timestamp_ns(stamp)
                fields = message.split(' ', 2)
                if fields[0] in ('stdout', 'stderr'):
                    if len(fields) != 3 or fields[1] != 'F':
                        raise InvalidInput('CRI records must have complete F payloads; partial records are unverified')
                    message = fields[2]
                counts['records'] += 1
                if start < recorded <= end:
                    counts['in_window_records'] += 1
                    counts['matches'] += bool(SIGNATURE.search(message))
    return {'window_start_exclusive': format_ns(start), 'window_end_inclusive': format_ns(end), **counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-end', required=True, help='Captured UTC RFC3339 endpoint, ending in Z')
    parser.add_argument('directory', type=Path, help='Private directory containing only uncompressed retained logs')
    args = parser.parse_args()
    try:
        result = inspect(args.directory, timestamp_ns(args.window_end))
    except InvalidInput as error:
        print('Invalid log input: ' + str(error), file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError, OverflowError):
        print('Invalid log input: unreadable log data or unsupported timestamp', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result['matches'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
