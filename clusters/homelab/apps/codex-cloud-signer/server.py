#!/usr/bin/env python3
"""Sign only ephemeral Codex-tagged nodes after an authenticated Tailscale event."""
import base64
from datetime import datetime
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SECRETS = Path('/secrets')
SUFFIX = 'tail67beb.ts.net'
TAG = 'tag:codex-cloud'
HOOK = '/webhooks/tailscale'
MAX_BODY = 65536
# Tailscale retries failed deliveries hourly for 24h; recheck live eligibility.
MAX_AGE = 25 * 60 * 60


class Denied(ValueError):
    """An authenticated request is ineligible; acknowledge without signing."""


class NotReady(RuntimeError):
    """An eligible enrollment is still connecting to the control plane."""


def secret(name):
    value = (SECRETS / name).read_text().strip()
    if not value or len(value) > 4096 or value == 'REPLACE_ME' or '\n' in value:
        raise RuntimeError('credential unavailable')
    if name != 'oauth-client-id' and len(value) < 16:
        raise RuntimeError('credential unavailable')
    return value


def verify_signature(body, header, key, now):
    fields = header.split(',')
    timestamps = [part[2:] for part in fields if part.startswith('t=')]
    signatures = [part[3:] for part in fields if part.startswith('v1=')]
    if len(timestamps) != 1 or not re.fullmatch(r'[0-9]{1,12}', timestamps[0]):
        return False
    timestamp = timestamps[0]
    if not -60 <= now - int(timestamp) <= MAX_AGE:
        return False
    expected = hmac.new(key.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures
               if re.fullmatch(r'[0-9a-f]{64}', signature))


def api(path, token):
    request = Request('https://api.tailscale.com/api/v2' + path,
                      headers={'Authorization': 'Bearer ' + token})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        error.close()
        if error.code == 404:
            raise Denied('device no longer exists') from None
        raise


def access_token():
    # This client has devices:core:read only; it cannot enroll or authorize nodes.
    credentials = (secret('oauth-client-id') + ':' + secret('oauth-client-secret')).encode()
    request = Request('https://api.tailscale.com/api/v2/oauth/token',
                      data=b'grant_type=client_credentials&scope=devices%3Acore%3Aread',
                      headers={'Authorization': 'Basic ' + base64.b64encode(credentials).decode(),
                               'Content-Type': 'application/x-www-form-urlencoded'})
    with urlopen(request, timeout=10) as response:
        return json.load(response)['access_token']


def local_api(path, payload=None):
    connection = HTTPConnection('local-tailscaled.sock', timeout=10)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(10)
    try:
        connection.sock.connect('/run/tailscale/tailscaled.sock')
        connection.request('GET' if payload is None else 'POST', '/localapi/v0/' + path,
                           None if payload is None else json.dumps(payload),
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError('local Tailscale operation failed')
        return json.loads(body) if body else None
    finally:
        connection.close()


def signer_status():
    status = local_api('status')
    lock = local_api('tka/status')
    if not (status.get('BackendState') == 'Running'
            and status.get('CurrentTailnet', {}).get('MagicDNSSuffix') == SUFFIX
            and lock.get('Enabled') is True and lock.get('NodeKeySigned') is True
            and lock.get('PublicKey') in {key.get('Key') for key in lock.get('TrustedKeys', [])}):
        raise RuntimeError('trusted signer unavailable')
    return lock


def eligible(device, node_id, now):
    if not (device.get('nodeId') == node_id and device.get('tags') == [TAG]
            and device.get('isEphemeral') is True and device.get('isExternal') is False
            and device.get('os') == 'linux'
            and device.get('name', '').endswith('.' + SUFFIX)):
        raise Denied('device outside enrollment policy')
    try:
        created = datetime.fromisoformat(device['created'].replace('Z', '+00:00'))
        age = now - created.timestamp() if created.tzinfo else float('inf')
    except (KeyError, TypeError, ValueError):
        raise Denied('invalid creation time') from None
    if not -60 <= age <= MAX_AGE:
        raise Denied('not a newly enrolled device')
    node_key, rotation = device.get('nodeKey', ''), device.get('tailnetLockKey', '')
    if not (re.fullmatch(r'nodekey:[0-9a-f]{64}', node_key)
            and re.fullmatch(r'(tlpub|nlpub):[0-9a-f]{64}', rotation)):
        raise Denied('invalid public keys')
    if device.get('connectedToControl') is not True or device.get('authorized') is not True:
        raise NotReady('device still connecting')
    return node_key, rotation


def process(events, now):
    if not isinstance(events, list) or not events:
        raise Denied('invalid event batch')
    token = None
    for event in events:
        try:
            if not isinstance(event, dict) or event.get('version') != 1:
                raise Denied('invalid event')
            if event.get('type') != 'nodeNeedsSignature':
                continue
            data = event.get('data')
            node_id = data.get('nodeID') if isinstance(data, dict) else None
            if not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', node_id):
                raise Denied('invalid node ID')
            token = token or access_token()
            for attempt in range(3):
                device = api('/device/' + node_id + '?fields=all', token)
                try:
                    keys = eligible(device, node_id, now)
                    break
                except NotReady:
                    if attempt == 2:
                        raise
                    time.sleep(1)
            if not device.get('tailnetLockError'):
                continue  # Duplicate deliveries of an already-signed node are harmless.
            signer_status()
            current = api('/device/' + node_id + '?fields=all', token)
            if eligible(current, node_id, now) != keys:
                raise Denied('device keys changed')
            local_api('tka/sign', {'NodeKey': keys[0], 'RotationPublic':
                                 base64.b64encode(bytes.fromhex(keys[1].split(':')[1])).decode()})
            print('eligible Codex node signed', flush=True)
        except Denied:
            # One permanent rejection must not acknowledge away later enrollments.
            print('event ignored: device outside enrollment policy', flush=True)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # Never log headers, request bodies, credentials or device metadata.

    def respond(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def do_GET(self):
        if self.path == '/healthz':
            return self.respond(200)
        if self.path != '/readyz':
            return self.respond(404)
        try:
            for name in ('webhook-secret', 'oauth-client-id', 'oauth-client-secret'):
                secret(name)
            signer_status()
        except Exception:
            return self.respond(503)
        return self.respond(200)

    def do_POST(self):
        if self.path != HOOK:
            return self.respond(404)
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.respond(400)
        length = self.headers['Content-Length']
        if not re.fullmatch(r'[0-9]{1,6}', length) or not 0 < int(length) <= MAX_BODY:
            return self.respond(413)
        if len(self.headers.get_all('Tailscale-Webhook-Signature', [])) != 1:
            return self.respond(401)
        try:
            body = self.rfile.read(int(length))
            now = time.time()
            if len(body) != int(length) or not verify_signature(
                    body, self.headers['Tailscale-Webhook-Signature'], secret('webhook-secret'), now):
                return self.respond(401)
            process(json.loads(body), now)
        except (Denied, json.JSONDecodeError, UnicodeDecodeError):
            # Permanent failures must not block subsequent webhook deliveries.
            print('authenticated event ignored', flush=True)
            return self.respond(204)
        except Exception:
            print('signing temporarily unavailable; details withheld', flush=True)
            return self.respond(503)
        return self.respond(204)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
