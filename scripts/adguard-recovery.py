#!/usr/bin/env python3
"""Reconstruct and verify AdGuard in disposable local Docker storage."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import base64
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = load('recovery_check', ROOT / 'scripts/adguard-check.py')
INIT = load('recovery_init', ROOT / 'clusters/homelab/apps/adguard/init-config.py')
PARAMETER = '/homelab/adguard/admin-password'
REGION = 'us-west-2'


def render_config(template, password):
    """Use ESO's Sprig functions with a private temporary Helm values file."""
    with tempfile.TemporaryDirectory(prefix='adguard-render-', dir='/tmp') as temp:
        chart = Path(temp)
        (chart / 'templates').mkdir()
        (chart / 'Chart.yaml').write_text('apiVersion: v2\nname: recovery\nversion: 0.1.0\n')
        values = chart / 'values.yaml'
        with os.fdopen(os.open(values, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            json.dump({'password': password}, output)
        (chart / 'templates/config.yaml').write_text(
            '{{- define "config" -}}' + template + '{{- end -}}\n'
            'apiVersion: v1\nkind: ConfigMap\nmetadata: {name: recovery}\ndata:\n'
            '  config.json: {{ include "config" (dict "password" .Values.password) | quote }}\n')
        rendered = CHECK.run(['helm', 'template', 'recovery', str(chart)], timeout=30)
        result = json.loads(CHECK.run(['yq', '-o=json', '.', '-'], data=rendered))
        return json.loads(result['data']['config.json'])


class LocalDocker:
    def __init__(self):
        self.endpoint = CHECK.run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).strip()
        CHECK.require(self.endpoint.startswith('unix:///'), 'Recovery requires a local Unix Docker endpoint')

    def run(self, *args):
        return CHECK.run(['docker', '--host', self.endpoint, *args], timeout=90).strip()


class IsolatedRuntime:
    def __init__(self, docker, root, image, config, password):
        self.docker, self.root, self.image = docker, root, image
        self.name, self.closed = 'adguard-recovery-' + uuid4().hex, False
        self.authorization = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), CHECK.NoRedirect())
        for name in ('conf', 'work'):
            (root / name).mkdir(mode=0o700, exist_ok=True)
        self.seed = root / 'config.json'
        self.seed.write_text(json.dumps(config))
        self.seed.chmod(0o600)
        self.config = copy.deepcopy(config)
        try:
            self.seed_config()
            self.start()
        except Exception:
            self.close()
            raise

    def seed_config(self):
        self.docker.run('run', '--rm', '--pull=never', '--network=none', '--read-only', '--user', '0:0',
                        '--cap-drop=ALL', '--cap-add=CHOWN', '--cap-add=DAC_OVERRIDE', '--cap-add=FOWNER',
                        '--security-opt=no-new-privileges:true', '--entrypoint', '/bin/sh',
                        '--mount', f'type=bind,src={self.seed},dst=/seed.json,readonly',
                        '--mount', f'type=bind,src={self.root / "conf"},dst=/conf',
                        '--mount', f'type=bind,src={self.root / "work"},dst=/work', self.image,
                        '-ec', 'cp /seed.json /conf/AdGuardHome.yaml; chmod 700 /conf /work; '
                              'chmod 600 /conf/AdGuardHome.yaml; chown -R 65534:65534 /conf /work')

    def start(self):
        self.docker.run('run', '--detach', '--name', self.name, '--pull=never', '--user', '65534:65534',
                        '--read-only', '--cap-drop=ALL', '--cap-add=NET_BIND_SERVICE',
                        '--security-opt=no-new-privileges:true', '--sysctl', 'net.ipv4.ip_unprivileged_port_start=1024',
                        '--label', 'homelab.fixture=adguard-recovery', '--memory=512m', '--cpus=0.5',
                        '--dns=1.1.1.2', '--dns=1.0.0.2',
                        '--mount', f'type=bind,src={self.root / "conf"},dst=/conf',
                        '--mount', f'type=bind,src={self.root / "work"},dst=/work',
                        '-p', '127.0.0.1::53/udp', '-p', '127.0.0.1::53/tcp', '-p', '127.0.0.1::3000/tcp',
                        self.image, '--no-check-update', '-c', '/conf/AdGuardHome.yaml', '-w', '/work')
        self.ports = {}
        for protocol in ('53/udp', '53/tcp', '3000/tcp'):
            value = self.docker.run('port', self.name, protocol)
            CHECK.require(re.fullmatch(r'127\.0\.0\.1:\d+', value) is not None, 'Recovery ports must bind only loopback')
            self.ports[protocol] = int(value.rsplit(':', 1)[1])
        self.origin = 'http://127.0.0.1:' + str(self.ports['3000/tcp'])

    def request(self, path, body=None, authenticated=True):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = self.authorization
        request = urllib.request.Request(self.origin + path, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        return self.opener.open(request, timeout=3)

    def get(self, path):
        with self.request('/control/' + path) as response:
            return json.load(response)

    def response_code(self, path, body=None, authenticated=False):
        try:
            with self.request(path, body, authenticated) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def ready(self):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if self.get('status')['running'] and any(f.get('enabled') and f.get('rules_count', 0) > 0
                                                        for f in self.get('filtering/status')['filters']):
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.5)
        raise CHECK.Failure('Isolated recovery never became filter-ready')

    def stop(self):
        # Removal is scoped to this invocation's unguessable local container name.
        existing = self.docker.run('ps', '-a', '--filter', 'name=^/' + self.name + '$', '--format', '{{.Names}}')
        if existing:
            CHECK.require(existing == self.name, 'Recovery cleanup identity differs')
            self.docker.run('rm', '--force', self.name)

    def replace(self, config):
        self.stop()
        self.config = copy.deepcopy(config)
        self.seed.write_text(json.dumps(config))
        self.seed_config()
        self.start()

    def close(self):
        if self.closed:
            return
        self.stop()
        self.docker.run('run', '--rm', '--pull=never', '--network=none', '--read-only', '--user', '0:0',
                        '--cap-drop=ALL', '--cap-add=DAC_OVERRIDE', '--cap-add=CHOWN', '--entrypoint', '/bin/sh',
                        '--mount', f'type=bind,src={self.root / "conf"},dst=/conf',
                        '--mount', f'type=bind,src={self.root / "work"},dst=/work', self.image,
                        '-ec', 'find /conf /work -mindepth 1 -delete; chown ' + str(os.getuid()) + ':' + str(os.getgid()) + ' /conf /work')
        self.closed = True


def verify_runtime(runtime, blocked):
    runtime.ready()
    CHECK.verify_admin(runtime)
    filters = runtime.get('filtering/status')
    CHECK.require(filters['filters'][0]['url'] == runtime.config['filters'][0]['url'], 'Recovered filter source differs')
    # Synthetic fixtures use their local filter server; CLI configuration is
    # reconstructed exclusively from reviewed source with the production URL.
    filters['filters'][0]['url'] = CHECK.FILTER_URL
    for kind in ('A', 'AAAA'):
        match = runtime.get('filtering/check_host?name=' + blocked + '&qtype=' + kind)
        CHECK.validate_filter(runtime.get('status'), filters, match)
    dns = runtime.get('dns_info')
    CHECK.require(dns['upstream_dns'] == runtime.config['dns']['upstream_dns'] and dns['fallback_dns'] == [],
                  'Recovered upstream configuration differs')
    for tcp in (False, True):
        port = runtime.ports['53/tcp' if tcp else '53/udp']
        CHECK.require(CHECK.dns_answer('127.0.0.1', blocked, 'A', tcp, port) == ('NOERROR', {('A', '0.0.0.0')}),
                      'Recovered filter did not block A')
        CHECK.require(CHECK.dns_answer('127.0.0.1', blocked, 'AAAA', tcp, port) == ('NOERROR', {('AAAA', '::')}),
                      'Recovered filter did not block AAAA')
        status, answers = CHECK.dns_answer('127.0.0.1', 'example.com', 'A', tcp, port)
        CHECK.require(status == 'NOERROR' and any(kind == 'A' and value != '0.0.0.0' for kind, value in answers),
                      'Recovered resolver did not permit an ordinary name')


def recover(config_factory, password, image, blocked='doubleclick.net'):
    docker = LocalDocker()
    CHECK.require(re.search(r'@sha256:[a-f0-9]{64}$', image) is not None, 'Recovery image must be digest-pinned')
    docker.run('image', 'inspect', image)  # Never implicitly pull during recovery.
    with tempfile.TemporaryDirectory(prefix='adguard-recovery-', dir='/tmp') as temp:
        base = Path(temp).resolve()
        CHECK.require(',' not in str(base) and not base.is_relative_to(ROOT), 'Invalid isolated recovery directory')
        root = base / 'replacement'; root.mkdir()
        runtime = IsolatedRuntime(docker, root, image, config_factory(), password)
        try:
            verify_runtime(runtime, blocked)
            with runtime.request('/control/filtering/config', {'enabled': False, 'interval': 24}):
                pass
            CHECK.require(runtime.get('filtering/status')['enabled'] is False, 'Isolated replacement precondition failed')
            runtime.replace(config_factory())
            verify_runtime(runtime, blocked)
        finally:
            runtime.close()
        root = base / 'fresh-restore'; root.mkdir()
        runtime = IsolatedRuntime(docker, root, image, config_factory(), password)
        try:
            verify_runtime(runtime, blocked)
        finally:
            runtime.close()
    return {'mode': 'isolated-recovery', 'replacement_verified': True, 'fresh_restore_verified': True,
            'administrator_access_verified': True, 'filtering_verified': True,
            'private_routing_verified': False, 'client_acceptance': False}


def credential():
    accounts = re.findall(r'account_id\s*=\s*"(\d{12})"', (ROOT / 'IaC/application-backup-storage.hcl').read_text())
    CHECK.require(len(accounts) == 1, 'Declared homelab AWS account is ambiguous')
    account = CHECK.run(['aws', 'sts', 'get-caller-identity', '--query', 'Account', '--output', 'text']).strip()
    CHECK.require(account == accounts[0], 'Recovery AWS account differs from the homelab account')
    parameter = json.loads(CHECK.run(['aws', 'ssm', 'get-parameter', '--region', REGION, '--name', PARAMETER,
                                     '--with-decryption', '--output', 'json']))['Parameter']
    arn = f'arn:aws:ssm:{REGION}:{account}:parameter{PARAMETER}'
    CHECK.require(parameter.get('ARN') == arn and parameter.get('Name') == PARAMETER and parameter.get('Type') == 'SecureString'
                  and type(parameter.get('Version')) is int and parameter['Version'] > 0
                  and re.fullmatch('[A-Za-z0-9]{32}', parameter.get('Value', '')) is not None,
                  'Protected AdGuard credential source is invalid')
    return parameter['Value'], {'ARN': arn, 'Version': parameter['Version']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = CHECK.SIGNER.OAUTH.receipt_path(args.receipt)
        CHECK.require(not receipt.exists(), 'Use a new protected recovery receipt path')
        revision = CHECK.SIGNER.GUARDS.verify_main()
        context = CHECK.run(['kubectl', 'config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}']).strip()
        CHECK.require(context == 'https://10.1.0.199:6443', 'Recovery source requires the authenticated homelab API')
        docs = CHECK.source_documents()
        template = docs[('ExternalSecret', 'adguard-config')]['spec']['target']['template']['data']['config.json']
        image = docs[('Deployment', 'adguard')]['spec']['template']['spec']['containers'][0]['image']
        LocalDocker().run('image', 'inspect', image)
        service = CHECK.DNS.service('tailnet-dns', 'tailnet-dns')
        private_ip = service['spec']['clusterIP']
        password, version = credential()
        def factory():
            return INIT.prepare_config(render_config(template, password),
                lambda *_: [(socket.AF_INET, socket.SOCK_DGRAM, 17, '', (private_ip, 53))])
        result = recover(factory, password, image)
        current_version = json.loads(CHECK.run(['aws', 'ssm', 'get-parameter', '--region', REGION, '--name', PARAMETER,
                                               '--query', 'Parameter.{ARN:ARN,Version:Version}', '--output', 'json']))
        fresh_service = CHECK.DNS.service('tailnet-dns', 'tailnet-dns')
        CHECK.require(CHECK.SIGNER.GUARDS.verify_main() == revision and current_version == version
                      and fresh_service['metadata']['uid'] == service['metadata']['uid']
                      and fresh_service['spec']['clusterIP'] == private_ip, 'Recovery sources changed during verification')
        result.update(source_revision=revision, credential_source=version, image=image,
                      private_resolver_service_uid=service['metadata']['uid'], private_upstream=private_ip,
                      completed_at=datetime.now(timezone.utc).isoformat())
        CHECK.SIGNER.OAUTH.save_receipt(receipt, result, first=True)
        print('Verified isolated AdGuard replacement and fresh configuration/credential restore; production storage was untouched.')
    except Exception:
        print('Isolated AdGuard recovery failed; private credential details withheld', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
