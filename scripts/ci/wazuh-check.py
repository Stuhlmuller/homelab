#!/usr/bin/env python3
"""Validate Wazuh's activation, source, transport and identity boundaries offline."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'clusters/homelab/apps/wazuh'
rendered = subprocess.check_output(['kubectl', 'kustomize', str(APP)], text=True)
docs = json.loads(subprocess.check_output(['yq', 'ea', '-o=json', '-I=0', '[.]', '-'], input=rendered, text=True))
objects = {(o['kind'], o['metadata']['name']): o for o in docs if o}
config = ET.parse(APP / 'ossec.conf').getroot()
assert config.findtext('global/logall_json') == 'yes'
assert config.findtext('global/logall') == 'no'
assert all(x.findtext('protocol') == 'tcp' for x in config.findall('remote'))
assert config.find('active-response') is None
locations = [item.findtext('location') for item in config.findall('localfile')]
assert len(locations) == len(set(locations))
assert '/var/ossec/logs/api.json' in locations
secret = objects['ExternalSecret', 'wazuh-credentials']['spec']
assert len({item['remoteRef']['key'] for item in secret['data']}) == 4
assert all(item['remoteRef']['key'].startswith('/homelab/wazuh/') for item in secret['data'])
filebeat = secret['target']['template']['data']['filebeat.yml']
assert 'archives:\n      enabled: true' in filebeat
assert 'ssl.verification_mode: full' in filebeat
assert not any(o['kind'] == 'Secret' for o in docs if o)
for kind in ('StatefulSet', 'Deployment', 'DaemonSet'):
    for (object_kind, name), obj in objects.items():
        if object_kind != kind:
            continue
        spec = obj['spec']['template']['spec']
        assert not spec.get('hostNetwork') and not spec.get('hostPID')
        for container in spec.get('containers', []) + spec.get('initContainers', []):
            assert '@sha256:' in container['image'], name
            assert not container.get('securityContext', {}).get('privileged'), name
            assert not any('secretKeyRef' in item.get('valueFrom', {}) for item in container.get('env', [])), name
        if name in ('wazuh-indexer', 'wazuh-manager', 'wazuh-dashboard'):
            assert spec['nodeSelector']['kubernetes.io/hostname'] == 'acer'
node = objects['DaemonSet', 'wazuh-node-logs']['spec']['template']['spec']
logs = [v for v in node['containers'][0]['volumeMounts'] if v['name'] == 'logs']
assert logs == [{'name': 'logs', 'mountPath': '/var/log', 'readOnly': True}]
role = objects['ClusterRole', 'wazuh-collector']['rules']
assert len(role) == 1 and set(role[0]['resources']) == {'pods', 'namespaces', 'events'}
assert set(role[0]['verbs']) == {'get', 'list', 'watch'}
service = objects['Service', 'wazuh-collector']['spec']
assert service['externalTrafficPolicy'] == 'Local'
assert service['ports'][0]['nodePort'] == 30517
strict = objects['PeerAuthentication', 'wazuh-strict']['spec']
assert strict['mtls']['mode'] == 'STRICT'
for configfile in ('collector-node.conf', 'collector-central.conf'):
    text = (APP / configfile).read_text()
    assert 'Format                    json_lines' in text
    assert 'storage.type              filesystem' in text
    assert 'Retry_Limit               False' in text
    assert 'storage.total_limit_size  2G' in text
assert 'K8S-Logging.Exclude        Off' in (APP / 'collector-node.conf').read_text()
assert '/var/log/audit/kube/kube-apiserver.log' in (APP / 'collector-node.conf').read_text()
assert objects['CronJob', 'wazuh-canary']['spec']['schedule'] == '*/5 * * * *'
# Real scheduler edge cases for the read-only capacity gate.
spec = importlib.util.spec_from_file_location('preflight', ROOT / 'scripts/wazuh-preflight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert sum(module.memory(obj['spec']['capacity']['storage'])
           for (kind, _), obj in objects.items()
           if kind == 'PersistentVolume' and obj['spec'].get('storageClassName') == 'wazuh-local') == module.CENTRAL_DATA


def c(size, **kw):
    return {'resources': {'requests': {'memory': size}}, **kw}


assert module.pod_request({'containers': [c('1Gi')], 'initContainers': [c('2Gi')]}) == 2 * 1024**3
assert module.pod_request({'containers': [c('1Gi')], 'initContainers': [c('512Mi', restartPolicy='Always'), c('2Gi')]}) == 2560 * 1024**2
assert module.pod_request({'containers': [c('1Gi')], 'overhead': {'memory': '32Mi'}}) == 1056 * 1024**2

# Filesystem accounting: a shared Talos disk is not two pools of free bytes.
Gi = 1024**3
node = {'metadata': {'name': 'worker'}, 'status': {'conditions': [
    {'type': 'DiskPressure', 'status': 'False'}]}}
fs = {'capacityBytes': 100 * Gi, 'availableBytes': 18 * Gi + 1,
      'usedBytes': 20 * Gi, 'inodes': 100000, 'inodesFree': 9097}
stats = {'node': {'fs': copy.deepcopy(fs), 'runtime': {'imageFs': copy.deepcopy(fs)}}}
kubelet = {'evictionHard': {'nodefs.available': '10%', 'imagefs.available': '15%',
                          'nodefs.inodesFree': '5%', 'imagefs.inodesFree': '5%'}}
checks = module.disk_checks(node, stats, kubelet)
assert all(c['fits'] and c['required'] == 18 * Gi for c in checks)
stats['node']['runtime']['imageFs']['usedBytes'] = 60 * Gi
assert all(c['fits'] for c in module.disk_checks(node, stats, kubelet))
# Equality is unsafe: after queue/image growth, free space would reach eviction.
stats['node']['runtime']['imageFs']['availableBytes'] -= 1
assert not all(c['fits'] for c in module.disk_checks(node, stats, kubelet))
stats['node']['runtime']['imageFs']['availableBytes'] += 1
for insufficient in (5000, 5001, 9096):
    stats['node']['fs']['inodesFree'] = insufficient
    assert not all(c['fits'] for c in module.disk_checks(node, stats, kubelet))
stats['node']['fs']['inodesFree'] = 9097
checks = module.disk_checks(node, stats, kubelet)
assert all(c['fits'] and c['inodes_required'] == 9096 for c in checks)
# Shared views use the strictest threshold plus operating reserve, not their sum.
inode_config = copy.deepcopy(kubelet)
inode_config['evictionHard']['imagefs.inodesFree'] = '6%'
inode_stats = copy.deepcopy(stats)
for filesystem in (inode_stats['node']['fs'], inode_stats['node']['runtime']['imageFs']):
    filesystem['inodesFree'] = 10097
assert all(c['fits'] and c['inodes_required'] == 10096
           for c in module.disk_checks(node, inode_stats, inode_config))
for filesystem in (inode_stats['node']['fs'], inode_stats['node']['runtime']['imageFs']):
    filesystem.update(inodes=1000000, inodesFree=70001)
assert all(c['fits'] and c['inodes_required'] == 70000
           for c in module.disk_checks(node, inode_stats, inode_config))
for pressure in ('True', 'Unknown'):
    blocked = copy.deepcopy(node)
    blocked['status']['conditions'][0]['status'] = pressure
    assert not any(c['fits'] for c in module.disk_checks(blocked, stats, kubelet))
blocked['status']['conditions'] = []
assert not any(c['fits'] for c in module.disk_checks(blocked, stats, kubelet))

# Separate filesystems reserve queues on nodefs and image growth on imagefs.
split = copy.deepcopy(stats)
split['node']['fs']['availableBytes'] = 12 * Gi + 1
split['node']['runtime']['imageFs'].update(capacityBytes=200 * Gi, availableBytes=31 * Gi + 1)
checks = module.disk_checks(node, split, kubelet)
assert [c['required'] for c in checks] == [12 * Gi, 31 * Gi]
assert all(c['fits'] for c in checks)
# Honor stricter configured soft thresholds, absolute quantities and reclaim.
stricter = copy.deepcopy(kubelet)
stricter['evictionSoft'] = {'imagefs.available': '20%'}
stricter['evictionMinimumReclaim'] = {'imagefs.available': '1Gi'}
assert module.disk_checks(node, stats, stricter)[0]['required'] == 24 * Gi
assert module.eviction_threshold({'evictionHard': {'nodefs.available': '2Gi'}},
                                 'nodefs.available', 100 * Gi) == 2 * Gi

# Central data growth must leave eviction headroom; 200Gi remains a minimum.
central = copy.deepcopy(node)
central['metadata']['name'] = 'acer'
central_stats = copy.deepcopy(stats)
central_floor_config = copy.deepcopy(kubelet)
central_floor_config['evictionHard']['imagefs.available'] = '10%'
for filesystem in (central_stats['node']['fs'], central_stats['node']['runtime']['imageFs']):
    filesystem.update(capacityBytes=250 * Gi, availableBytes=201 * Gi)
assert all(c['fits'] and c['required'] == 200 * Gi
           for c in module.disk_checks(central, central_stats, central_floor_config))
for filesystem in (central_stats['node']['fs'], central_stats['node']['runtime']['imageFs']):
    filesystem.update(capacityBytes=1000 * Gi, availableBytes=201 * Gi)
assert all(not c['fits'] and c['required'] == 320 * Gi
           for c in module.disk_checks(central, central_stats, kubelet))
for filesystem in (central_stats['node']['fs'], central_stats['node']['runtime']['imageFs']):
    filesystem['availableBytes'] = 320 * Gi + 1
assert all(c['fits'] and c['required'] == 320 * Gi
           for c in module.disk_checks(central, central_stats, kubelet))
for filesystem in (central_stats['node']['fs'], central_stats['node']['runtime']['imageFs']):
    filesystem.update(capacityBytes=2000 * Gi, availableBytes=470 * Gi + 1)
assert all(c['fits'] and c['required'] == 470 * Gi
           for c in module.disk_checks(central, central_stats, kubelet))

for missing in ('availableBytes', 'capacityBytes', 'usedBytes', 'inodes', 'inodesFree'):
    incomplete = copy.deepcopy(stats)
    del incomplete['node']['runtime']['imageFs'][missing]
    try:
        module.disk_checks(node, incomplete, kubelet)
    except ValueError:
        pass
    else:
        raise AssertionError(f'Missing {missing} must block activation')
try:
    module.disk_checks(node, stats, {'evictionHard': {}})
except KeyError:
    pass
else:
    raise AssertionError('Unknown eviction configuration must block activation')
print('Wazuh rendering, source coverage, TLS, secret, RBAC and capacity contracts passed')
