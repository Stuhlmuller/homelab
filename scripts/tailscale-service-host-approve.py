#!/usr/bin/env python3
"""Approve only the signed Traefik canary for the private-ingress TailVIP."""
import sys

if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run this operator command with python3 -I')

import argparse
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import stat
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('guards', ROOT / 'scripts/entra-ci-configure.py')
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)
API = 'https://api.tailscale.com/api/v2'
SERVICE = 'svc:homelab-private-ingress'
SERVICE_DEFINITION_PATH = '/tailnet/-/vip-services/' + SERVICE
SERVICE_PATH = '/tailnet/-/services/' + SERVICE
TAG = 'tag:homelab-ingress-canary'
TAILNET = 'tail67beb.ts.net'
HOST = 'homelab-ingress-canary'
POD = 'traefik-sidecar-canary-0'
STATE = 'traefik-sidecar-canary-state'
SOCKET = '/run/tailscale/tailscaled.sock'
API_KEY_PREFIX = 'tskey' + '-api-'
TS_IMAGE = ('harbor.stinkyboi.com/mirror/docker.io/tailscale/tailscale:v1.102.3'
            '@sha256:8c42c4574ab066384fcb72f69e086a2ff1dd3652eb6f56856cee34bcf0d2f680')
TRAEFIK_IMAGE = ('docker.io/library/traefik:v3.7.14'
                 '@sha256:575fa15b135078fe5e50aa847987d96dbddd7b093c172429618404df73f3fa7c')
SAFE_DESTINATIONS = {
    '10.1.0.0/24', 'autogroup:member', 'tag:ci', 'tag:homelab-ci-apply',
    'tag:homelab-ci-cordium', 'tag:homelab-ci-plan', 'tag:homelab-funnel',
    'tag:homelab-ingress', 'tag:k8s', 'tag:k8s-operator', SERVICE,
}
CANARY_ENTRYPOINTS = {
    '--entrypoints.web.address=127.0.0.1:8000',
    '--entrypoints.websecure.address=127.0.0.1:8443',
    '--entrypoints.funnel.address=127.0.0.1:8080',
    '--entrypoints.registry.address=127.0.0.1:9443',
    '--entrypoints.health.address=:9000',
}


def require(condition, message):
    if not condition:
        raise GUARDS.Failure(message)


def read_api_key(path):
    path = Path(path).expanduser().absolute()
    require(not path.parent.resolve().is_relative_to(ROOT), 'API key must be outside the repository')
    parent = path.parent.lstat()
    info = path.lstat()
    require(stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode) == 0o700
            and stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
            'API key requires a 0700 directory and regular 0600 file')
    key = path.read_text().strip()
    require(key.startswith(API_KEY_PREFIX) and 12 <= len(key) <= 4096
            and not any(character.isspace() for character in key),
            'Owner/Admin Tailscale API key file required')
    return key


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise GUARDS.Failure('Credentialed Tailscale API redirect refused')


def api_json(path, key, *, method='GET', payload=None):
    require(path.startswith('/') and '..' not in path and not path.startswith('//'),
            'Invalid fixed Tailscale API path')
    headers = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload, separators=(',', ':')).encode()
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RefuseRedirect())
    with opener.open(request, timeout=20) as response:
        body = response.read(1_048_577)
    require(len(body) <= 1_048_576, 'Tailscale API response exceeded the private limit')
    result = json.loads(body)
    require(isinstance(result, dict), 'Tailscale API returned invalid JSON')
    return result


def policy_contract(source, live):
    require(isinstance(source, dict) and live == source, 'Live tailnet policy differs from current source')
    require(source.get('acls') == [] and source.get('tagOwners', {}).get(TAG) == ['tag:k8s-operator'],
            'Canary policy ownership or legacy ACLs changed')
    auto = source.get('autoApprovers', {}).get('services', {})
    require(auto == {'tag:ci': ['tag:ci']},
            'Private Service must require explicit host approval')
    grants = source.get('grants', [])
    require(isinstance(grants, list) and all(isinstance(grant, dict) for grant in grants),
            'Tailnet grants are invalid')
    require(all(isinstance(grant.get('dst'), list) and grant['dst']
                and all(destination in SAFE_DESTINATIONS for destination in grant['dst'])
                for grant in grants),
            'Canary device or unreviewed destination is reachable')
    scoped = [grant for grant in grants if SERVICE in grant.get('dst', [])]
    require(len(scoped) == 1 and set(scoped[0]) == {'src', 'dst', 'ip'}
            and scoped[0].get('dst') == [SERVICE]
            and scoped[0].get('ip') == ['tcp:443']
            and isinstance(scoped[0].get('src'), list) and len(scoped[0]['src']) == 1
            and re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+', scoped[0]['src'][0]),
            'Exactly one explicit test user may reach only Service TCP 443')
    tests = source.get('tests', [])
    require(isinstance(tests, list) and any(test.get('src') == scoped[0]['src'][0]
            and SERVICE + ':443' in test.get('accept', []) for test in tests),
            'Tailnet policy lacks a positive Service test')
    for denied_source in ('tag:k8s', 'tag:k8s-operator', 'tag:ci'):
        require(any(test.get('src') == denied_source and SERVICE + ':443' in test.get('deny', [])
                    for test in tests), 'Tailnet policy lacks a negative Service test')


def valid_tailvip_addresses(addrs):
    if not isinstance(addrs, list) or not addrs or len(addrs) != len(set(addrs)):
        return False
    try:
        values = [ipaddress.ip_address(address) for address in addrs]
    except (TypeError, ValueError):
        return False
    return (any(value.version == 4 for value in values)
            and all(value in (ipaddress.ip_network('100.64.0.0/10')
                              if value.version == 4 else ipaddress.ip_network('fd7a:115c:a1e0::/48'))
                    for value in values))


def valid_uid(value):
    return isinstance(value, str) and bool(re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value))


def canonical_lock_key(value):
    require(isinstance(value, str) and bool(re.fullmatch(r'(?:nlpub|tlpub):[0-9a-f]{64}', value)),
            'Tailnet Lock public key has an invalid format')
    return 'tlpub:' + value.split(':', 1)[1]


def service_contract(service):
    require(service.get('name') == SERVICE and service.get('ports') == ['tcp:443']
            and service.get('tags', []) == []
            and valid_tailvip_addresses(service.get('addrs')),
            'Defined TailVIP differs from the reviewed TCP-443-only Service')
    return tuple(sorted(service['addrs']))


def canary_container_contract(spec):
    containers = {item.get('name'): item for item in spec.get('containers', [])}
    require(len(spec.get('containers', [])) == 2 and set(containers) == {'traefik', 'tailscale'}
            and containers['traefik'].get('image') == TRAEFIK_IMAGE
            and containers['tailscale'].get('image') == TS_IMAGE
            and spec.get('nodeSelector') == {'kubernetes.io/hostname': 'acer'}
            and spec.get('serviceAccountName') == 'traefik-sidecar-canary'
            and spec.get('automountServiceAccountToken') is False,
            'Canary workload template or actual Pod differs')
    traefik = containers['traefik']
    args = traefik.get('args', [])
    listener_args = [arg for arg in args if isinstance(arg, str)
                     and re.match(r'^--entrypoints\.[^.]+\.address=', arg)]
    require(len(listener_args) == len(CANARY_ENTRYPOINTS)
            and set(listener_args) == CANARY_ENTRYPOINTS
            and args.count('--providers.file.directory=/etc/traefik/dynamic') == 1,
            'Canary listeners or dynamic provider differ')
    tailscale = containers['tailscale']
    require(tailscale.get('command') == ['/usr/local/bin/tailscaled']
            and tailscale.get('args') == [
                '--tun=userspace-networking', '--state=kube:' + STATE,
                '--statedir=/var/lib/tailscale', '--socket=' + SOCKET],
            'Canary daemon socket or durable state differs')
    dynamic = [volume for volume in spec.get('volumes', []) if volume.get('name') == 'dynamic']
    require(len(dynamic) == 1
            and len(dynamic[0].get('projected', {}).get('sources', [])) == 2
            and {item.get('configMap', {}).get('name') for item in dynamic[0]['projected']['sources']
                 if 'configMap' in item} == {'traefik-sidecar-canary-routes'}
            and {item.get('secret', {}).get('name') for item in dynamic[0]['projected']['sources']
                 if 'secret' in item} == {'traefik-tls'}
            and any(mount.get('name') == 'dynamic'
                    and mount.get('mountPath') == '/etc/traefik/dynamic'
                    and mount.get('readOnly') is True for mount in traefik.get('volumeMounts', [])),
            'Canary route and TLS Secret mount differ')
    return containers


def canary_pod_contract(sts, pod, state_uid):
    metadata = sts.get('metadata', {})
    pod_meta = pod.get('metadata', {})
    pod_spec = pod.get('spec', {})
    generation = metadata.get('generation')
    rollout = sts.get('status', {})
    revision = rollout.get('currentRevision')
    template_spec = sts.get('spec', {}).get('template', {}).get('spec', {})
    require(valid_uid(metadata.get('uid')) and metadata.get('name') == 'traefik-sidecar-canary'
            and metadata.get('namespace') == 'traefik' and not metadata.get('deletionTimestamp')
            and sts.get('spec', {}).get('replicas') == 1
            and sts.get('spec', {}).get('serviceName') == 'traefik-sidecar-canary'
            and type(generation) is int and generation > 0
            and rollout.get('observedGeneration') == generation
            and rollout.get('readyReplicas') == 1
            and isinstance(revision, str) and bool(revision)
            and rollout.get('updateRevision') == revision,
            'Exact canary StatefulSet is required')
    canary_container_contract(template_spec)
    require(pod_meta.get('name') == POD and pod_meta.get('namespace') == 'traefik'
            and valid_uid(pod_meta.get('uid')) and not pod_meta.get('deletionTimestamp')
            and pod_spec.get('nodeName') == 'acer'
            and len(pod_meta.get('ownerReferences', [])) == 1
            and all(pod_meta['ownerReferences'][0].get(key) == value for key, value in {
                'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
                'name': 'traefik-sidecar-canary', 'uid': metadata['uid'],
                'controller': True}.items()),
            'Canary Pod owner or placement changed')
    containers = canary_container_contract(pod_spec)
    labels = pod_meta.get('labels', {})
    require(labels.get('app.kubernetes.io/name') == 'traefik-sidecar-canary'
            and labels.get('app.kubernetes.io/instance') == 'traefik-sidecar-canary'
            and labels.get('controller-revision-hash') == revision
            and pod.get('status', {}).get('phase') == 'Running'
            and any(condition.get('type') == 'Ready' and condition.get('status') == 'True'
                    for condition in pod.get('status', {}).get('conditions', [])),
            'Canary Pod must be Running and Ready')
    container_statuses = pod.get('status', {}).get('containerStatuses', [])
    statuses = {item.get('name'): item for item in container_statuses}
    require(len(container_statuses) == len(containers) and set(statuses) == set(containers)
            and all(statuses[name].get('ready') is True for name in containers),
            'Canary images, state store, or container readiness changed')
    require(valid_uid(state_uid),
            'Persistent Tailscale state Secret UID is required')
    return (metadata['uid'], pod_meta['uid'], state_uid)


def node_contract(status, lock, serve, device, pod_ids):
    own = status.get('Self', {})
    node_id = own.get('ID')
    node_key = own.get('PublicKey')
    addresses = own.get('TailscaleIPs')
    require(status.get('BackendState') == 'Running' and own.get('Online') is True
            and own.get('Expired') is not True
            and status.get('CurrentTailnet', {}).get('MagicDNSSuffix') == TAILNET
            and own.get('DNSName', '').rstrip('.') == HOST + '.' + TAILNET
            and own.get('Tags') == [TAG]
            and isinstance(node_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', node_id)
            and isinstance(node_key, str) and re.fullmatch(r'nodekey:[0-9a-f]{64}', node_key)
            and valid_tailvip_addresses(addresses),
            'Canary daemon identity differs from the reviewed node')
    lock_key = canonical_lock_key(lock.get('PublicKey'))
    require(lock.get('Enabled') is True and lock.get('NodeKeySigned') is True
            and lock.get('NodeKey') == node_key,
            'Canary node is not signed by Tailnet Lock')
    require(set(serve) == {'version', 'services'} and serve.get('version') == '0.0.1'
            and set(serve.get('services', {})) == {SERVICE}
            and set(serve['services'][SERVICE]) <= {'endpoints', 'advertised'}
            and serve['services'][SERVICE].get('endpoints') == {'tcp:443': 'tcp://127.0.0.1:8443'}
            and serve['services'][SERVICE].get('advertised', True) is True,
            'Canary Service advertisement is not exact raw TCP 443 to loopback')
    require(device.get('nodeId') == node_id and device.get('nodeKey') == node_key
            and device.get('name', '').rstrip('.') == HOST + '.' + TAILNET
            and device.get('hostname') == HOST and device.get('tags') == [TAG]
            and device.get('authorized') is True
            and device.get('connectedToControl') is True
            and device.get('isEphemeral') is False
            and set(device.get('addresses', [])) == set(addresses)
            and not device.get('tailnetLockError')
            and canonical_lock_key(device.get('tailnetLockKey')) == lock_key
            and str(device.get('clientVersion', '')).startswith('1.102.3'),
            'Tailscale device API disagrees with canary daemon identity')
    return (*pod_ids, node_id, node_key, tuple(sorted(addresses)), lock_key)


def approval_contract(hosts, approval, node_id):
    entries = hosts.get('hosts')
    require(isinstance(entries, list) and len(entries) == 1
            and entries[0].get('stableNodeID') == node_id
            and entries[0].get('configured') == 'ready'
            and entries[0].get('approvalLevel') in ('not-approved', 'approved:manual'),
            'Service must have only the exact configured canary host')
    require(type(approval.get('approved')) is bool and approval.get('autoApproved') is False,
            'Service host approval state is ambiguous or automatic')
    require(entries[0]['approvalLevel'] == ('approved:manual' if approval['approved'] else 'not-approved'),
            'Service host list and approval state disagree')
    return approval['approved']


def inspect(key):
    source = json.loads((ROOT / 'scripts/config/tailscale-policy.json').read_text())
    live = api_json('/tailnet/-/acl', key)
    policy_contract(source, live)
    policy_digest = hashlib.sha256(json.dumps(source, sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
    server = GUARDS.command(['kubectl', 'config', 'view', '--minify', '-o',
                             'jsonpath={.clusters[0].cluster.server}'], 'Kubernetes context').strip()
    require(server == 'https://10.1.0.199:6443', 'Authenticated homelab Kubernetes context required')
    service_addrs = service_contract(api_json(SERVICE_DEFINITION_PATH, key))
    sts = GUARDS.read_json(['kubectl', '-n', 'traefik', 'get', 'statefulset',
                            'traefik-sidecar-canary', '-o', 'json'], 'canary StatefulSet')
    pod_list = GUARDS.read_json(['kubectl', '-n', 'traefik', 'get', 'pods', '-l',
                                 ('app.kubernetes.io/name=traefik-sidecar-canary,' +
                                  'app.kubernetes.io/instance=traefik-sidecar-canary'),
                                 '-o', 'json'], 'canary Pod list')
    pod = GUARDS.read_json(['kubectl', '-n', 'traefik', 'get', 'pod', POD, '-o', 'json'], 'canary Pod')
    require(isinstance(pod_list.get('items'), list) and len(pod_list['items']) == 1
            and pod_list['items'][0].get('metadata', {}).get('uid') == pod.get('metadata', {}).get('uid'),
            'Exactly one live canary Pod must match the Service labels')
    state_uid = GUARDS.command(['kubectl', '-n', 'traefik', 'get', 'secret', STATE, '-o',
                                'jsonpath={.metadata.uid}'], 'canary state UID').strip()
    pod_ids = canary_pod_contract(sts, pod, state_uid)
    prefix = ['kubectl', '-n', 'traefik', 'exec', POD, '-c', 'tailscale', '--',
              'tailscale', '--socket=' + SOCKET]
    status = GUARDS.read_json([*prefix, 'status', '--json'], 'canary public identity')
    lock = GUARDS.read_json([*prefix, 'lock', 'status', '--json'], 'canary lock identity')
    serve = GUARDS.read_json([*prefix, 'serve', 'get-config', '--all'], 'canary Serve config')
    node_id = status.get('Self', {}).get('ID')
    require(isinstance(node_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', node_id),
            'Canary node ID is invalid')
    device = api_json('/device/' + node_id, key)
    node_ids = node_contract(status, lock, serve, device, pod_ids)
    path = SERVICE_PATH + '/device/' + node_id + '/approved'
    hosts = api_json(SERVICE_PATH + '/devices', key)
    approved = approval_contract(hosts, api_json(path, key), node_id)
    return {'identity': (policy_digest, service_addrs, node_ids),
            'approved': approved, 'path': path}


def fingerprint(inspection):
    payload = json.dumps(inspection['identity'], separators=(',', ':'), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def reconcile(key, execute, expected_fingerprint=None):
    revision = GUARDS.verify_main() if execute else None
    before = inspect(key)
    if not execute:
        policy_digest, vip_addrs, node_ids = before['identity']
        sts_uid, pod_uid, state_uid, node_id, node_key, device_addrs, signer_key = node_ids
        print(json.dumps({
            'policy_sha256': policy_digest, 'tailvip': vip_addrs,
            'statefulset_uid': sts_uid, 'pod_uid': pod_uid, 'state_secret_uid': state_uid,
            'device_id': node_id, 'public_node_key': node_key,
            'tailscale_addresses': device_addrs, 'public_lock_key': signer_key,
        }, sort_keys=True))
        print('Exact signed canary host is '
              + ('already approved.' if before['approved'] else 'pending approval.')
              + ' Identity fingerprint: ' + fingerprint(before))
        return
    require(expected_fingerprint == fingerprint(before),
            'Canary identity differs from the reviewed preview')
    require(GUARDS.verify_main() == revision, 'Main moved during Service approval preflight')
    current = inspect(key)
    require(current == before, 'Canary, policy, Service, or approval changed during preflight')
    if not current['approved']:
        result = api_json(current['path'], key, method='POST', payload={'approved': True})
        require(result.get('approved') is True and result.get('autoApproved') is False,
                'Service approval result was not exact manual approval')
    after = inspect(key)
    require(after['identity'] == before['identity'] and after['approved'] is True,
            'Approved host identity changed or approval did not persist')
    print('Verified exact canary Service host approval; prove live TailVIP traffic before DNS cutover.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-key-file', type=Path, required=True,
                        help='0600 Owner/Admin API key file in a 0700 directory outside this repository')
    parser.add_argument('--execute', action='store_true', help='Approve only the verified canary host')
    parser.add_argument('--expect-fingerprint',
                        help='SHA-256 identity fingerprint printed by a reviewed preview; required with --execute')
    args = parser.parse_args(argv)
    try:
        require(not args.execute or bool(re.fullmatch(r'[0-9a-f]{64}', args.expect_fingerprint or '')),
                'Execution requires a reviewed preview fingerprint')
        require(args.execute or args.expect_fingerprint is None,
                'Preview does not accept an execution fingerprint')
        reconcile(read_api_key(args.api_key_file), args.execute, args.expect_fingerprint)
    except Exception:
        # API, Kubernetes, and private file errors can contain credentials or internal output.
        print('Service host approval stopped; private details withheld.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
