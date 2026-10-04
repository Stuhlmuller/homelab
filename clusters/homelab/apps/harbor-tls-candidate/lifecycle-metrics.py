#!/usr/bin/env python3
"""Read expiry metadata only. No Harbor/AWS access and no credential mount."""
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EXPIRY = Path('/lifecycle/expires-at')


def metrics(now):
    try:
        value = EXPIRY.read_text().strip()
        if not re.fullmatch(r'[1-9][0-9]{8,10}', value):
            raise ValueError('Invalid expiry metadata')
        expires = int(value)
        if expires > now + 30 * 86400 + 60:
            raise ValueError('Expiry beyond collector contract')
    except (OSError, UnicodeError, ValueError):
        return 'harbor_collector_expiry_metadata_valid 0\n'
    return ('harbor_collector_expiry_metadata_valid 1\n'
            f'harbor_collector_credential_expires_at_seconds {expires}\n')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = metrics(time.time()).encode() if self.path == '/metrics' else b'not found\n'
        self.send_response(200 if self.path == '/metrics' else 404)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8081), Handler).serve_forever()
