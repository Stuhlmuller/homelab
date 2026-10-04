#!/usr/bin/env python3
"""Validate Wazuh's activation, source, transport and identity boundaries offline."""
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
        if name in ('wazuh-indexer', 'wazuh-manager'):
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
c = lambda size, **kw: {'resources': {'requests': {'memory': size}}, **kw}
assert module.pod_request({'containers': [c('1Gi')], 'initContainers': [c('2Gi')]}) == 2 * 1024**3
assert module.pod_request({'containers': [c('1Gi')], 'initContainers': [c('512Mi', restartPolicy='Always'), c('2Gi')]}) == 2560 * 1024**2
assert module.pod_request({'containers': [c('1Gi')], 'overhead': {'memory': '32Mi'}}) == 1056 * 1024**2
print('Wazuh rendering, source coverage, TLS, secret, RBAC and capacity contracts passed')
