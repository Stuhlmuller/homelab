#!/usr/bin/env python3
"""Exercise declared Traefik routes on loopback; requires traefik, node, yq, curl and openssl."""
import argparse
import atexit
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import time
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', default='traefik', help='Path to the declared Traefik version; no downloads are performed.')
options = parser.parse_args()
BINARY = shutil.which(options.binary)
if not BINARY:
    parser.error('Traefik binary not found; provide --binary /path/to/traefik')
for command in ('node', 'yq', 'curl', 'openssl'):
    if not shutil.which(command):
        parser.error(command + ' is required')
TEMPORARY = tempfile.TemporaryDirectory(prefix='traefik-runtime-')
atexit.register(TEMPORARY.cleanup)
HERE = Path(TEMPORARY.name)
DYNAMIC = HERE / 'dynamic'
DYNAMIC.mkdir(exist_ok=True)
ALLOCATED_PORTS = set()


def free_port():
    while True:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        if port not in ALLOCATED_PORTS:
            ALLOCATED_PORTS.add(port)
            return port

PORTS = {entry: free_port() for entry in ('web', 'websecure', 'funnel', 'health', 'registry')}

def yaml(path):
    return json.loads(subprocess.check_output(['yq', '-o=json', '.', str(path)], text=True))

routes = yaml(ROOT / 'clusters/homelab/apps/traefik/routes.yaml')
services = routes['http']['services']
backend_ports = {name: free_port() for name in services}
for name, service in services.items():
    original = service['loadBalancer']['servers'][0]['url']
    scheme = original.split(':', 1)[0]
    service['loadBalancer']['servers'] = [{'url': f'{scheme}://127.0.0.1:{backend_ports[name]}'}]
routes['http']['serversTransports']['octelium-console']['rootCAs'] = [str(HERE/'backend.crt')]

tls = yaml(ROOT / 'clusters/homelab/apps/traefik/tls.yaml')
for cert in tls['tls']['certificates']:
    cert['certFile'] = str(DYNAMIC / 'tls.crt')
    cert['keyFile'] = str(DYNAMIC / 'tls.key')

for version in (1, 2):
    folder = DYNAMIC / f'..version{version}'
    folder.mkdir(exist_ok=True)
    (folder/'routes.yaml').write_text(json.dumps(routes))
    (folder/'tls.yaml').write_text(json.dumps(tls))
    subprocess.run(['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-set_serial', str(version), '-subj', '/CN=*.stinkyboi.com',
                    '-addext', 'subjectAltName=DNS:stinkyboi.com,DNS:*.stinkyboi.com,DNS:*.cordium.stinkyboi.com',
                    '-keyout', str(folder/'tls.key'), '-out', str(folder/'tls.crt')], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
shutil.copyfile(DYNAMIC/'..version1'/'tls.crt', HERE/'backend.crt')
shutil.copyfile(DYNAMIC/'..version1'/'tls.key', HERE/'backend.key')
for name in ('tls.crt', 'tls.key', 'routes.yaml', 'tls.yaml', '..data'):
    link = DYNAMIC / name
    if link.is_symlink():
        link.unlink()
    link.symlink_to('..version1' if name == '..data' else f'..data/{name}')

node_code = '''
const http = require('node:http');
const http2 = require('node:http2');
const https = require('node:https');
const fs = require('node:fs');
for (const [name, port] of Object.entries(PORTS)) {
  const handle = (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({name, url: req.url, headers: req.headers, version: req.httpVersion,
      servername: req.socket.servername}));
  };
  const server = name === 'octelium-api' ? http2.createServer() :
    name === 'octelium-console' ? https.createServer({cert: fs.readFileSync(CERT), key: fs.readFileSync(KEY)}) :
    http.createServer();
  server.on('request', handle);
  server.on('upgrade', (req, socket) => {
    socket.end('HTTP/1.1 101 Switching Protocols\\r\\nConnection: Upgrade\\r\\nUpgrade: websocket\\r\\n\\r\\n');
  });
  server.listen(port, '127.0.0.1');
}
'''.replace('PORTS', json.dumps(backend_ports)).replace('CERT', json.dumps(str(HERE/'backend.crt'))).replace('KEY', json.dumps(str(HERE/'backend.key')))
args = yaml(ROOT/'clusters/homelab/apps/traefik/values.yaml')['controllers']['traefik']['containers']['app']['args']
args = [arg.replace('/etc/traefik/dynamic', str(DYNAMIC))
        .replace('address=:8000', f"address=127.0.0.1:{PORTS['web']}")
        .replace('address=:8443', f"address=127.0.0.1:{PORTS['websecure']}")
        .replace('address=:8080', f"address=127.0.0.1:{PORTS['funnel']}")
        .replace('address=:9000', f"address=127.0.0.1:{PORTS['health']}")
        .replace('address=:9443', f"address=127.0.0.1:{PORTS['registry']}")
        .replace('trustedips=10.244.0.0/16', 'trustedips=127.0.0.1/32') for arg in args]


def request(host, path='/', entry='websecure', headers=(), websocket=False):
    secure = entry in ('websecure', 'registry')
    port = PORTS[entry]
    command = ['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '3',
               '--insecure', '--path-as-is', '--resolve', f'{host}:{port}:127.0.0.1', '-w', '\n%{http_code}',
               f'{"https" if secure else "http"}://{host}:{port}{path}']
    for header in headers:
        command += ['-H', header]
    if websocket:
        command += ['--http1.1', '-H', 'Connection: Upgrade', '-H', 'Upgrade: websocket',
                    '-H', 'Sec-WebSocket-Version: 13', '-H',
                    'Sec-WebSocket-Key: '+base64.b64encode(os.urandom(16)).decode()]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode and not websocket:
        raise RuntimeError(result.stderr)
    body, status = result.stdout.rsplit('\n', 1)
    return int(status), body


def cert_digest():
    context = ssl._create_unverified_context()
    with socket.create_connection(('127.0.0.1', PORTS['websecure']), timeout=3) as raw:
        with context.wrap_socket(raw, server_hostname='fleet.stinkyboi.com') as secure:
            return hashlib.sha256(secure.getpeercert(True)).hexdigest()


def expected_cert(version):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert((DYNAMIC/f'..version{version}'/'tls.crt').read_text())).hexdigest()

log = (HERE/'traefik.log').open('w')
processes = []
checks = 0
try:
    processes.append(subprocess.Popen(['node', '-e', node_code], stdout=subprocess.DEVNULL, stderr=log))
    traefik = subprocess.Popen([str(BINARY), *args], stdout=log, stderr=log)
    processes.append(traefik)
    for _ in range(60):
        if traefik.poll() is not None:
            raise RuntimeError('Traefik exited: '+(HERE/'traefik.log').read_text())
        try:
            status, _ = request('fleet.stinkyboi.com')
            if status == 200:
                break
        except (RuntimeError, ValueError):
            pass
        time.sleep(.1)
    else:
        raise AssertionError('Traefik did not become ready')
    for name, route in routes['http']['routers'].items():
        if route['entryPoints'] != ['websecure']:
            continue
        hosts = {'cordium': 'cordium.stinkyboi.com', 'octelium-cluster': 'stinkyboi.com',
                 'octelium-alias': 'octelium.stinkyboi.com', 'octelium-console': 'console.stinkyboi.com'}
        host = hosts.get(name, name+'.stinkyboi.com')
        status, body = request(host)
        assert status == 200, (name,status,body)
        data = json.loads(body)
        assert data['name'] == route['service'], (name,data)
        if name == 'octelium-api':
            assert data['version'] == '2.0', data
        if name == 'octelium-alias':
            assert data['headers']['host'] == 'stinkyboi.com', data
        if name == 'octelium-console':
            assert data['servername'] == 'console.stinkyboi.com', data
        checks += 1
    for host in ('workspace.cordium.stinkyboi.com', 'portal.stinkyboi.com'):
        status,body = request(host)
        assert status == 200, (host,status,body)
        checks += 1
    for base in ('/setup', '/api/setup', '/api/v1/setup'):
        for suffix in ('', '/', '/anything'):
            status,body = request('fleet.stinkyboi.com', base+suffix)
            assert status == 404, (base,suffix,status,body)
            checks += 1
    for path in ('/%73etup', '/api/%73etup', '/api/v1/%73etup',
                 '//api//v1//setup', '/api/v1/./setup', '/other/../setup',
                 '/api/v1/%2e/setup', '/api%2fv1%2fsetup', '/api%5cv1%5csetup',
                 '/api%252fv1%252fsetup', '/setup%00', '/setup%3f', '/setup%3bextra'):
        status, body = request('fleet.stinkyboi.com', path)
        assert status in (400, 404), (path, status, body)
        checks += 1
    for path in ('/api/v1/osquery/enroll', '/mdm/apple/mdm', '/login'):
        assert request('fleet.stinkyboi.com',path)[0] == 200
        checks += 1
    for host, allowed in [('n8n-webhook.tail67beb.ts.net', ('/webhook','/webhook/one','/webhook-test/test','/webhook-waiting/wait')),
                          ('policy-bot-hook.tail67beb.ts.net', ('/api/github/hook',))]:
        for path in allowed:
            status,body = request(host,path,entry='funnel',headers=('X-Forwarded-Proto: https',))
            assert status == 200, (host,path,status,body)
            assert json.loads(body)['headers']['x-forwarded-proto'] == 'https', body
            checks += 1
        for path in ('/','/rest/settings','/setup','/api/v1/setup','/api/github/hook-extra','/webhook-admin'):
            assert request(host,path,entry='funnel')[0] == 404, (host,path)
            checks += 1
    for path in ('/webhook/../rest/settings', '/webhook/%2e%2e/rest/settings',
                 '/webhook/%2f../rest/settings', '/webhook/%252e%252e%252frest/settings'):
        status, body = request('n8n-webhook.tail67beb.ts.net', path, entry='funnel')
        assert status in (400, 404), (path, status, body)
        checks += 1
    for name in ('fleet','grafana','harbor','octelium-api'):
        assert request(name+'.stinkyboi.com',entry='funnel')[0] == 404
        assert request(name+'.stinkyboi.com','/webhook/test',entry='funnel',headers=(
            'X-Forwarded-Host: n8n-webhook.tail67beb.ts.net', 'X-Forwarded-Proto: https'))[0] == 404
        checks += 2
    for path in ('/v2', '/v2/', '/v2/library/example/manifests/latest', '/service/token'):
        status, body = request('harbor.stinkyboi.com', path, entry='registry',
                               headers=('Authorization: Bearer fixture',))
        assert status == 200, (path, status, body)
        data = json.loads(body)
        assert data['name'] == 'harbor', data
        assert data['headers']['authorization'] == 'Bearer fixture', data
        checks += 1
    for path in ('/', '/api/v2.0/projects', '/c/login', '/service/token-admin', '/v20'):
        assert request('harbor.stinkyboi.com', path, entry='registry')[0] == 404
        checks += 1
    for path in ('/v2/../api/v2.0/projects', '/v2/%2e%2e/api/v2.0/projects',
                 '/v2/%2f..%2fapi/v2.0/projects', '/v2/%252e%252e%252fapi/v2.0/projects'):
        status, body = request('harbor.stinkyboi.com', path, entry='registry')
        assert status in (400, 404), (path, status, body)
        checks += 1
    for host in ('fleet.stinkyboi.com', 'grafana.stinkyboi.com', 'octelium-api.stinkyboi.com'):
        assert request(host, '/v2/', entry='registry')[0] == 404
        checks += 1
    for name in ('multica', 'openclaw', 'cordium'):
        assert request(name+'.stinkyboi.com','/ws',websocket=True)[0] == 101
        checks += 1
    assert request('fleet.stinkyboi.com',entry='web')[0] in (301,308)
    checks += 1
    assert cert_digest() == expected_cert(1)
    (DYNAMIC/'..data_tmp').symlink_to('..version2')
    os.replace(DYNAMIC/'..data_tmp', DYNAMIC/'..data')
    # Kubernetes AtomicWriter removes the old timestamped directory after swapping ..data.
    expected2 = expected_cert(2)
    shutil.rmtree(DYNAMIC/'..version1')
    for _ in range(80):
        if cert_digest() == expected2:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Projected-secret rotation did not reload TLS certificate within 8 seconds')
    checks += 1
    print(f'PASS: {checks} executable checks; private routes, h2c, WebSockets, callback isolation, Fleet setup, path normalization, TLS rotation')
except Exception:
    lines = (HERE/'traefik.log').read_text().splitlines()
    print('\n'.join(lines[:3] + lines[-3:]))
    raise
finally:
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    log.close()
