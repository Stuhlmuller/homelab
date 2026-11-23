#!/usr/bin/env python3
"""Read-only AdGuard identity, active-filter and direct DNS acceptance."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('private_dns', ROOT / 'scripts/tailnet-dns-check.py')
DNS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DNS)
SIGNER = DNS.SIGNER
FILTER_URL = 'https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt'
ADMIN_URL = 'https://adguard.stinkyboi.com'
CACHE_METHOD = 'macOS dscacheutil flush and mDNSResponder HUP before each sample pair and private/MagicDNS lookup'


class Failure(Exception):
    """Only fixed diagnostic messages cross the private boundary."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def run(args, timeout=15, data=None):
    try:
        result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout)
        require(result.returncode == 0, 'Read-only command failed; private output withheld')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise Failure('Read-only command failed or timed out; private output withheld') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_local_mode(status, lock):
    require(isinstance(status, dict) and isinstance(lock, dict)
            and type(lock.get('Enabled')) is bool, 'Missing or malformed Tailnet Lock mode')
    own, tailnet = status.get('Self'), status.get('CurrentTailnet')
    require(isinstance(own, dict) and isinstance(tailnet, dict)
            and status.get('BackendState') == 'Running' and own.get('Online') is True
            and own.get('Expired') is not True and tailnet.get('MagicDNSSuffix') == SIGNER.TAILNET,
            'Tailnet client must be online in the expected tailnet')
    if not lock['Enabled'] and 'NodeKey' in lock:
        key = lock['NodeKey']
        require(isinstance(key, str) and re.fullmatch(r'nodekey:[0-9a-f]{64}', key)
                and key != 'nodekey:' + '0' * 64 and key == own.get('PublicKey'),
                'Disabled Lock node key differs from device identity')
    return lock['Enabled']


def unlocked_identity(peer):
    """Validate public proxy/peer identity without relying on Lock peer lists."""
    require(isinstance(peer, dict), 'Missing AdGuard peer identity')
    key, addresses = peer.get('PublicKey'), peer.get('TailscaleIPs')
    require(isinstance(peer.get('ID'), str) and bool(peer['ID'])
            and type(peer.get('NodeID')) is int and peer['NodeID'] > 0
            and isinstance(key, str) and re.fullmatch(r'nodekey:[0-9a-f]{64}', key)
            and key != 'nodekey:' + '0' * 64
            and isinstance(peer.get('DNSName'), str)
            and peer['DNSName'].rstrip('.') == 'homelab-adguard.' + SIGNER.TAILNET
            and peer.get('Tags') == ['tag:homelab-ingress']
            and peer.get('Online') is True and peer.get('Expired') is not True,
            'AdGuard public peer identity differs')
    require(isinstance(addresses, list) and bool(addresses)
            and all(isinstance(address, str) for address in addresses)
            and len(set(addresses)) == len(addresses), 'Invalid AdGuard tailnet addresses')
    try:
        require(all(ipaddress.ip_address(address) in DNS.MESH or ipaddress.ip_address(address)
                    in ipaddress.ip_network('fd7a:115c:a1e0::/48') for address in addresses),
                'AdGuard addresses must belong to the tailnet')
    except ValueError:
        raise Failure('Invalid AdGuard tailnet addresses') from None
    return {'dns': peer['DNSName'].rstrip('.'), 'node_key': key, 'device_id': peer['ID'],
            'node_id': peer['NodeID'], 'tags': list(peer['Tags']), 'addresses': sorted(addresses)}


def validate_unlocked_peer(local, local_lock, service, pod, proxy, proxy_lock):
    require(validate_local_mode(local, local_lock) is False
            and validate_local_mode(proxy, proxy_lock) is False,
            'Client and AdGuard proxy must both explicitly report disabled Lock')
    try:
        metadata, pod_meta = service['metadata'], pod['metadata']
        require(metadata.get('name') == 'adguard-dns' and metadata.get('namespace') == 'automation'
                and isinstance(metadata.get('uid'), str) and bool(metadata['uid'])
                and not metadata.get('deletionTimestamp'), 'Unexpected AdGuard Service identity')
        expected = {'tailscale.com/managed': 'true', 'tailscale.com/parent-resource': 'adguard-dns',
                    'tailscale.com/parent-resource-ns': 'automation',
                    'tailscale.com/parent-resource-type': 'svc', 'app': metadata['uid']}
        require(pod_meta.get('namespace') == 'tailscale'
                and isinstance(pod_meta.get('uid'), str) and bool(pod_meta['uid'])
                and not pod_meta.get('deletionTimestamp')
                and all(pod_meta.get('labels', {}).get(k) == v for k, v in expected.items())
                and any(c.get('type') == 'Ready' and c.get('status') == 'True'
                        for c in pod.get('status', {}).get('conditions', [])),
                'AdGuard proxy must be ready and owned by the exact Service')
        identity = unlocked_identity(proxy['Self'])
        peers = local.get('Peer')
        require(isinstance(peers, dict) and all(isinstance(p, dict) for p in peers.values()),
                'Missing local AdGuard peer map')
        matches = [(key, peer) for key, peer in peers.items() if peer.get('ID') == identity['device_id']]
        require(len(matches) == 1, 'Exactly one matching local AdGuard peer is required')
        map_key, peer = matches[0]
        require(map_key == identity['node_key'] and peer.get('InNetworkMap') is True
                and unlocked_identity(peer) == identity, 'Local peer differs from the AdGuard proxy')
        published = service['status']['loadBalancer']['ingress']
        require(isinstance(published, list)
                and any(entry.get('hostname') == identity['dns'] for entry in published)
                and any('ip' in entry for entry in published)
                and all(entry['ip'] in identity['addresses'] for entry in published if 'ip' in entry),
                'Published AdGuard endpoint differs from the proxy')
        return dict(identity, pod_uid=pod_meta['uid'], lock_enabled=False, signed=False)
    except (KeyError, TypeError, AttributeError):
        raise Failure('Malformed AdGuard identity observation') from None


def inspect_adguard_peer():
    """Read only the fixed AdGuard target; shared signing callers remain strict."""
    def read(args):
        try:
            value = json.loads(run(args))
        except (ValueError, TypeError):
            raise Failure('Malformed identity response; private output withheld') from None
        require(isinstance(value, dict), 'Malformed identity response; private output withheld')
        return value

    def local_observation():
        status = read([SIGNER.TAILSCALE, 'status', '--json'])
        lock = read([SIGNER.TAILSCALE, 'lock', 'status', '--json'])
        return status, lock, validate_local_mode(status, lock)

    local, lock, enabled = local_observation()
    if enabled:
        peer = SIGNER.inspect_target(SIGNER.ADGUARD_TARGET, SIGNER.local_signer())
        require(peer.get('signed') is True, 'Locked AdGuard proxy must have a verified signature')
        peer = dict(peer, lock_enabled=True)
    else:
        service_args = ['kubectl', '-n', 'automation', 'get', 'service', 'adguard-dns', '-o', 'json']
        service = read(service_args)
        selector = ('tailscale.com/managed=true,tailscale.com/parent-resource-ns=automation,'
                    'tailscale.com/parent-resource=adguard-dns,tailscale.com/parent-resource-type=svc')
        pods = read(['kubectl', '-n', 'tailscale', 'get', 'pods', '-l', selector, '-o', 'json']).get('items')
        require(isinstance(pods, list) and len(pods) == 1 and isinstance(pods[0], dict),
                'Exactly one managed AdGuard proxy is required')
        pod = pods[0]
        metadata = pod.get('metadata')
        require(isinstance(metadata, dict) and isinstance(metadata.get('name'), str)
                and re.fullmatch(r'ts-[a-z0-9-]+', metadata['name']), 'Unexpected AdGuard proxy name')
        prefix = ['kubectl', '-n', 'tailscale', 'exec', metadata['name'], '-c', 'tailscale', '--', 'tailscale']
        proxy = read([*prefix, 'status', '--json'])
        proxy_lock = read([*prefix, 'lock', 'status', '--json'])
        peer = validate_unlocked_peer(local, lock, service, pod, proxy, proxy_lock)
        require(read(service_args) == service, 'AdGuard Service changed during identity verification')
    require(local_observation()[2] is enabled, 'Tailnet Lock mode changed during identity verification')
    return peer


def source_documents():
    rendered = run(['kubectl', 'kustomize', str(ROOT / 'clusters/homelab/apps/adguard')])
    docs = json.loads(run(['yq', 'ea', '-o=json', '-I=0', '[.]', '-'], data=rendered))
    return {(doc['kind'], doc['metadata']['name']): doc for doc in docs
            if doc['kind'] in ('Deployment', 'Service', 'ExternalSecret', 'ConfigMap')}


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(subset(a, b) for a, b in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def validate_snapshot(revision, server, source, objects, app, peer):
    require(re.fullmatch('[0-9a-f]{40}', revision) is not None, 'Invalid source revision')
    for key, expected in source.items():
        live = objects[key]
        require(subset(expected.get('spec', expected.get('data')), live.get('spec', live.get('data')))
                and subset(expected['metadata'], live['metadata']), 'Live resource differs from reviewed source')
    service = objects[('Service', 'adguard-dns')]
    require(DNS.published_ip(service) == server and service['metadata'].get('uid'), 'Observed DNS Service address differs')
    deployment = objects[('Deployment', 'adguard')]
    state = deployment.get('status', {})
    require(state.get('observedGeneration') == deployment['metadata'].get('generation')
            and all(state.get(k) == 1 for k in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')),
            'AdGuard Deployment is not current and ready')
    eso = objects[('ExternalSecret', 'adguard-config')]
    require(any(c.get('type') == 'Ready' and c.get('status') == 'True'
                for c in eso.get('status', {}).get('conditions', [])), 'AdGuard configuration Secret is not ready')
    require(subset({'sources': [{'repoURL': 'https://github.com/Stuhlmuller/homelab.git',
                               'path': 'clusters/homelab/apps/adguard', 'targetRevision': 'main'}],
                    'project': 'homelab-workloads',
                    'destination': {'namespace': 'automation', 'server': 'https://kubernetes.default.svc'}},
                   app.get('spec', {}))
            and not app['spec'].get('source')
            and subset({'status': 'Synced', 'revisions': [revision]}, app.get('status', {}).get('sync', {}))
            and app.get('status', {}).get('health', {}).get('status') == 'Healthy',
            'AdGuard Application must be healthy at reviewed current main')
    require(isinstance(peer, dict) and type(peer.get('lock_enabled')) is bool
            and type(peer.get('signed')) is bool and peer['signed'] is peer['lock_enabled']
            and peer.get('dns') == 'homelab-adguard.' + SIGNER.TAILNET,
            'AdGuard proxy requires explicit verified mode and its applicable signature')
    return {'source_revision': revision, 'deployed_revision': revision,
            'config_revision': deployment['spec']['template']['metadata']['annotations']['homelab.stuhlmuller.dev/config-revision'],
            'config_digest': digest(eso['spec']), 'source_digest': digest(list(source.values())),
            'service_uid': service['metadata']['uid'], 'server': server, 'peer': peer}


def snapshot(server):
    revision = SIGNER.GUARDS.verify_main()
    context = run(['kubectl', 'config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}']).strip()
    require(context == 'https://10.1.0.199:6443', 'Acceptance requires the authenticated homelab API')
    source = source_documents()
    objects = {key: json.loads(run(['kubectl', '-n', 'automation', 'get', key[0], key[1], '-o', 'json'])) for key in source}
    app = json.loads(run(['kubectl', '-n', 'argocd', 'get', 'application', 'adguard', '-o', 'json']))
    peer = inspect_adguard_peer()
    # Identity collection independently reads the Service and binds it to the
    # exact managed proxy. Re-read to reject a concurrent replacement.
    require(json.loads(run(['kubectl', '-n', 'automation', 'get', 'service', 'adguard-dns', '-o', 'json']))
            == objects[('Service', 'adguard-dns')], 'DNS Service changed during identity verification')
    return validate_snapshot(revision, server, source, objects, app, peer)


def read_password(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise Failure('Credential must be an owned private regular file') from None
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid() and info.st_size <= 73, 'Credential must be an owned private regular file')
        with os.fdopen(fd, 'r', closefd=False) as source:
            password = source.read().rstrip('\n')
        require(re.fullmatch('[A-Za-z0-9]{32}', password) is not None, 'Invalid protected credential format')
        return password
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise Failure('Administration redirects are not accepted')


class Admin:
    def __init__(self, password):
        self.authorization = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path):
        request = urllib.request.Request(ADMIN_URL + '/control/' + path,
                                         headers={'Authorization': self.authorization})
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def response_code(self, path, body=None, authenticated=False):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = self.authorization
        request = urllib.request.Request(ADMIN_URL + path, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code


def validate_admin(profile, querylog, statistics, denied, setup):
    require(profile.get('name') == 'admin', 'Expected initialized administrator is unavailable')
    # The API exposes enabled, but not file_enabled or size_memory. Those
    # settings are verified against declared config and the pinned runtime.
    require(querylog.get('enabled') is True and statistics.get('enabled') is False,
            'Recent query visibility must be enabled and statistics disabled')
    require(len(denied) == 2 and all(code in (401, 403) for code in denied),
            'Unauthenticated protected administration is not denied')
    require(setup in (403, 404), 'First-run setup is still available')


def verify_admin(api):
    # The invalid value cannot change configuration even if authentication is
    # accidentally absent: the endpoint must reject it during JSON decoding.
    denied = [api.response_code('/control/status'),
              api.response_code('/control/filtering/config', {'enabled': []})]
    setup = api.response_code('/install/get_addresses', authenticated=True)
    validate_admin(api.get('profile'), api.get('querylog/config'), api.get('stats/config'), denied, setup)


def validate_filter(status, filters, match):
    require(status.get('running') is True and status.get('protection_enabled') is True
            and status.get('version') == 'v0.107.80', 'AdGuard protection or pinned runtime is not active')
    lists = filters.get('filters', [])
    require(filters.get('enabled') is True and filters.get('interval') == 24
            and len(lists) == 1 and lists[0].get('id') == 1 and lists[0].get('url') == FILTER_URL
            and lists[0].get('enabled') is True and type(lists[0].get('rules_count')) is int
            and lists[0]['rules_count'] > 0 and 'whitelist_filters' in filters
            and filters['whitelist_filters'] in (None, [])
            and filters.get('user_rules') == [], 'Expected enabled nonempty filter is not active')
    require(match.get('reason') == 'FilteredBlackList'
            and any(rule.get('filter_list_id') == 1 and rule.get('text') for rule in match.get('rules', [])),
            'Blocked test name is not a member of the enabled filter')


def dns_answer(server, name, kind, tcp=False, port=53):
    require(type(port) is int and 1 <= port <= 65535, "Invalid DNS port")
    args = ['dig', '@' + server, '-p', str(port), name, kind, '+noall', '+comments', '+answer', '+time=3', '+tries=1']
    if tcp:
        args.append('+tcp')
    output = run(args, timeout=3)
    header = re.search(r';; ->>HEADER<<-.*status: ([A-Z]+),', output)
    require(header is not None, 'Malformed direct DNS response')
    records = set()
    for line in output.splitlines():
        if not line or line.startswith(';'):
            continue
        fields = line.split(None, 4)
        require(len(fields) == 5 and fields[1].isdigit() and fields[2] == 'IN', 'Malformed direct DNS answer')
        records.add((fields[3], fields[4]))
    return header[1], records


def direct_samples(server, names, private_ip, blocked, query=dns_answer):
    for tcp in (False, True):
        for _ in range(10):
            require(query(server, blocked, 'A', tcp) == ('NOERROR', {('A', '0.0.0.0')}), 'Blocked A sample failed')
            status, records = query(server, 'example.com', 'A', tcp)
            addresses = [v for k, v in records if k == 'A']
            require(status == 'NOERROR' and bool(addresses)
                    and all(ipaddress.ip_address(v).is_global for v in addresses), 'Permitted A sample failed')
        require(query(server, blocked, 'AAAA', tcp) == ('NOERROR', {('AAAA', '::')}), 'Blocked AAAA sample failed')
        status, records = query(server, 'example.com', 'AAAA', tcp)
        addresses = [v for k, v in records if k == 'AAAA']
        require(status == 'NOERROR' and bool(addresses)
                and all(ipaddress.ip_address(v).is_global for v in addresses), 'Permitted AAAA sample failed')
        require(query(server, 'adguard-acceptance.invalid', 'A', tcp) == ('NXDOMAIN', set()), 'NXDOMAIN sample failed')
        for name in names:
            name = name.replace('*.', 'adguard-preflight.', 1)
            require(query(server, name, 'A', tcp) == ('NOERROR', {('A', private_ip)}), 'Private A answer differs')
            require(query(server, name, 'AAAA', tcp) == ('NOERROR', set()), 'Private AAAA must be NODATA')


def verify(server, password_file, blocked='doubleclick.net'):
    require(re.fullmatch(r'[a-z0-9.-]+', blocked) is not None, 'Invalid blocked test name')
    start, utc = time.monotonic(), datetime.now(timezone.utc).isoformat()
    before = snapshot(server)
    api = Admin(read_password(password_file))
    verify_admin(api)
    filters = api.get('filtering/status')
    for kind in ('A', 'AAAA'):
        match = api.get('filtering/check_host?' + urllib.parse.urlencode({'name': blocked, 'qtype': kind}))
        validate_filter(api.get('status'), filters, match)
    require(DNS.selected_services() == {('traefik', 'traefik-private')}, 'Private DNS inventory differs')
    traefik = DNS.service('traefik', 'traefik-private')
    names, private_ip = DNS.declared_names(traefik), DNS.published_ip(traefik)
    direct_samples(server, names, private_ip, blocked)
    require(snapshot(server) == before, 'Source, configuration or endpoint changed during direct acceptance')
    require(time.monotonic() - start <= 300, 'Direct acceptance exceeded its validity window')
    return {**before, 'mode': 'direct', 'started_at': utc,
            'completed_at': datetime.now(timezone.utc).isoformat(), 'blocked_name': blocked,
            'filter_digest': digest(filters), 'private_names': names, 'private_ip': private_ip,
            'sample_count_per_transport': 10, 'client_acceptance': False, 'admin_acceptance': True}


def client_metadata(os_name, os_version, status, prefs):
    require(os_name == 'Darwin' and bool(os_version), 'Only the existing macOS client adapter is supported; other clients remain unverified')
    version = status.get('Version', '')
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
    own = status.get('Self', {})
    require(match is not None and status.get('BackendState') == 'Running' and own.get('Online') is True
            and status.get('CurrentTailnet', {}).get('MagicDNSSuffix') == SIGNER.TAILNET
            and prefs.get('CorpDNS') is True, 'Client must be online in the intended tailnet and accepting DNS')
    name = own.get('DNSName', '').rstrip('.')
    addresses = own.get('TailscaleIPs', [])
    require(bool(own.get('ID')) and name.endswith('.' + SIGNER.TAILNET) and bool(addresses)
            and all(ipaddress.ip_address(v) in DNS.MESH or ipaddress.ip_address(v) in
                    ipaddress.ip_network('fd7a:115c:a1e0::/48') for v in addresses), 'Client MagicDNS identity is incomplete')
    selected_id, selected_ip = prefs.get('ExitNodeID'), prefs.get('ExitNodeIP')
    require('ExitNodeID' in prefs and 'ExitNodeIP' in prefs and not prefs.get('AutoExitNode')
            and not (selected_id and selected_ip), 'Exit-node preferences are incomplete or use unsupported automatic selection')
    selected = bool(selected_id or selected_ip)
    exit_status = status.get('ExitNodeStatus') or {}
    if selected:
        require(tuple(map(int, match.groups())) >= (1, 88, 1) and exit_status.get('Online') is True
                and bool(exit_status.get('ID'))
                and (not selected_id or selected_id == exit_status['ID'])
                and (not selected_ip or selected_ip in exit_status.get('TailscaleIPs', [])),
                'Selected exit node is unavailable, mismatched or unsupported by this client version')
    else:
        require(not exit_status.get('ID'), 'Exit-node preference and status disagree')
    return {'os': os_name, 'os_version': os_version, 'client_version': version,
            'device_id': own['ID'], 'magic_name': name, 'magic_ips': sorted(addresses),
            'accept_dns': True, 'exit_node_mode': 'selected' if selected else 'none',
            'exit_node_id': exit_status.get('ID'), 'exit_node_verified': False,
            'available_exit_nodes': sum(p.get('Online') is True and p.get('ExitNodeOption') is True
                                        for p in (status.get('Peer') or {}).values())}


def inspect_client():
    require(platform.system() == 'Darwin', 'Normal-client acceptance needs the existing macOS adapter; cloud fixtures cannot substitute')
    status = json.loads(run([SIGNER.TAILSCALE, 'status', '--json']))
    prefs = json.loads(run([SIGNER.TAILSCALE, 'debug', 'prefs']))
    metadata = client_metadata(platform.system(), platform.mac_ver()[0], status, prefs)
    configuration = run(['/usr/sbin/scutil', '--dns'])
    require(re.search(r'nameserver\[\d+\]\s*:\s*100\.100\.100\.100\b', configuration) is not None,
            'macOS does not expose the Tailscale system resolver')
    return metadata


def flush_system_cache():
    prefix = [] if os.geteuid() == 0 else ['/usr/bin/sudo', '-n']
    run([*prefix, '/usr/bin/dscacheutil', '-flushcache'])
    run([*prefix, '/usr/bin/killall', '-HUP', 'mDNSResponder'])


def system_resolve(name):
    # getaddrinfo follows the operating system resolver. A child gives it a hard
    # deadline without leaving a blocked background resolver thread running.
    code = ('import json,socket,sys; print(json.dumps(sorted({a[4][0] for a in '
            'socket.getaddrinfo(sys.argv[1],None,socket.AF_UNSPEC,socket.SOCK_STREAM)})))')
    return set(json.loads(run([sys.executable, '-I', '-c', code, name], timeout=3)))


def client_samples(blocked, names, private_ip, magic_name, magic_ips, resolve=system_resolve, flush=flush_system_cache):
    for _ in range(10):
        flush()
        answers = resolve(blocked)
        require(bool(answers) and answers <= {'0.0.0.0', '::'}, 'System resolver did not block the test domain')
        answers = resolve('example.com')
        require(bool(answers) and all(ipaddress.ip_address(v).is_global for v in answers),
                'System resolver did not resolve the permitted domain')
    for name in names:
        flush()
        require(resolve(name.replace('*.', 'adguard-client.', 1)) == {private_ip}, 'System resolver private-name answer differs')
    flush()
    answers = resolve(magic_name)
    require(bool(answers) and answers <= set(magic_ips), 'System resolver MagicDNS answer differs')


def validate_client_evidence(value):
    client = value.get('client', {})
    require(value.get('mode') == 'client' and value.get('client_acceptance') is True
            and value.get('system_resolver') == 'socket.getaddrinfo' and value.get('cache_method') == CACHE_METHOD
            and value.get('system_sample_count_per_name') == 10 and client.get('os') == 'Darwin'
            and all(client.get(k) for k in ('os_version', 'client_version', 'device_id'))
            and client.get('accept_dns') is True and client.get('exit_node_mode') in ('none', 'selected')
            and client.get('exit_node_verified') is (client.get('exit_node_mode') == 'selected'),
            'Direct queries or incomplete metadata cannot count as normal-client acceptance')


def verify_client(server, password_file, blocked='doubleclick.net'):
    initial = inspect_client()
    direct = verify(server, password_file, blocked)
    spec = importlib.util.spec_from_file_location('dns_control', ROOT / 'scripts/adguard-dns-cutover.py')
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    reader = control.DNSReader(SIGNER)
    desired = control.read_source_policy(direct['source_revision'])
    require(desired['magic_dns'] is True and desired['override_local_dns'] is True
            and desired['nameservers'] == [{'address': server, 'use_with_exit_node': True}]
            and reader.read() == desired, 'Client acceptance requires the exact active reviewed AdGuard DNS policy')
    started = datetime.now(timezone.utc).isoformat()
    client_samples(blocked, direct['private_names'], direct['private_ip'], initial['magic_name'], initial['magic_ips'])
    require(inspect_client() == initial and reader.read() == desired, 'Client or DNS policy changed during system-resolver acceptance')
    fresh = snapshot(server)
    require(all(fresh[k] == direct[k] for k in fresh), 'Source or endpoint changed during client acceptance')
    result = {**direct, 'mode': 'client', 'client_acceptance': True,
            'system_sample_count_per_name': 10,
            'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
            'client': dict(initial, exit_node_verified=initial['exit_node_mode'] == 'selected'),
            'cache_method': CACHE_METHOD,
            'system_resolver': 'socket.getaddrinfo', 'dns_policy_digest': digest(desired)}
    validate_client_evidence(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, help='Observed AdGuard Service tailnet IPv4')
    parser.add_argument('--password-file', required=True, type=Path, help='Private mode-0600 credential file')
    parser.add_argument('--blocked-name', default='doubleclick.net', help='Name verified against the active enabled filter')
    parser.add_argument('--mode', choices=['direct', 'client'], default='direct')
    parser.add_argument('--receipt', type=Path, help='New private receipt outside the repository')
    args = parser.parse_args(argv)
    try:
        result = (verify_client if args.mode == 'client' else verify)(args.server, args.password_file, args.blocked_name)
        if args.receipt is not None:
            path = SIGNER.OAUTH.receipt_path(args.receipt)
            SIGNER.OAUTH.save_receipt(path, result, first=True)
        if args.mode == 'client':
            print('Verified normal macOS resolver filtering/private DNS/MagicDNS at source ' + result['source_revision'])
            if not result['client']['exit_node_verified']:
                print('Exit-node behavior remains unverified; repeat with an authorized existing exit node selected.')
        else:
            print('Verified AdGuard direct UDP/TCP filtering and private DNS at source ' + result['source_revision'])
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('AdGuard acceptance failed; private credentials and diagnostics withheld', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
