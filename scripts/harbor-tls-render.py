#!/usr/bin/env python3
"""Offline HOME-59 candidate renderer. Never apply its output; no live access."""
import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / 'clusters/homelab/apps/harbor-tls-candidate'
CHART_SHA = '36d8eeb41b4df1aeff18c9af7709110a2fac2194b491d37957822b3359cd5e9a'
IDENTITY = '''
  map $proxy_host $harbor_tls_name {
    default invalid.invalid;
    core harbor-core;
    portal harbor-portal;
  }
  proxy_ssl_verify on;
  proxy_ssl_verify_depth 2;
  proxy_ssl_trusted_certificate /etc/nginx/backend-trust/ca.crt;
  proxy_ssl_server_name on;
  proxy_ssl_name $harbor_tls_name;
  proxy_ssl_protocols TLSv1.2 TLSv1.3;
  proxy_next_upstream off;
'''


def require(value):
    if not value:
        raise ValueError('TLS candidate contract mismatch')


def one(resources, kind, name):
    matches = [r for r in resources if r['kind'] == kind and r['metadata']['name'] == name]
    require(len(matches) == 1)
    return matches[0]


def harden(resources):
    resources = copy.deepcopy(resources)
    cm = one(resources, 'ConfigMap', 'harbor-nginx')
    conf = cm['data']['nginx.conf']
    require(conf.count('http {') == 1 and conf.count('proxy_ssl_verify        off;') == 1)
    require('server "harbor-core:443";' in conf and 'server "harbor-portal:443";' in conf)
    conf = conf.replace('proxy_ssl_verify        off;', '')
    conf = conf.replace('http {', 'http {' + IDENTITY, 1)
    # Remove the plaintext redirect listener, not merely the Service mapping.
    conf, count = re.subn(r'\s*server \{\s*listen 8080;\s*#server_name harbordomain.com;\s*'
                         r'return 301 https://\$host\$request_uri;\s*}', '', conf)
    require(count == 1)
    cm['data']['nginx.conf'] = conf
    deployment = one(resources, 'Deployment', 'harbor-nginx')
    pod = deployment['spec']['template']
    pod['metadata']['annotations']['checksum/home59-config'] = hashlib.sha256(conf.encode()).hexdigest()
    container = pod['spec']['containers'][0]
    require(container['name'] == 'nginx')
    container['ports'] = [{'containerPort': 8443}]
    container['volumeMounts'].append({'name': 'backend-trust', 'mountPath': '/etc/nginx/backend-trust',
                                     'readOnly': True})
    pod['spec']['volumes'].append({'name': 'backend-trust',
                                 'configMap': {'name': 'harbor-backend-trust'}})
    service = one(resources, 'Service', 'harbor')
    service['spec']['ports'] = [p for p in service['spec']['ports'] if p['port'] == 443]
    check(resources)
    return resources


def check(resources):
    conf = one(resources, 'ConfigMap', 'harbor-nginx')['data']['nginx.conf']
    require(IDENTITY in conf and not re.search(r'proxy_ssl_verify\s+off|proxy_pass\s+http:|listen\s+8080', conf))
    require(re.findall(r'proxy_pass\s+(\S+);', conf) == [
        'https://portal/', 'https://core/api/', 'https://core/c/', 'https://core/v2/', 'https://core/service/'])
    ports = one(resources, 'Service', 'harbor')['spec']['ports']
    require(len(ports) == 1 and ports[0]['port'] == 443 and ports[0]['targetPort'] == 8443)
    pod = one(resources, 'Deployment', 'harbor-nginx')['spec']['template']['spec']
    require({'name': 'backend-trust', 'configMap': {'name': 'harbor-backend-trust'}} in pod['volumes'])
    require({'name': 'backend-trust', 'mountPath': '/etc/nginx/backend-trust', 'readOnly': True}
            in pod['containers'][0]['volumeMounts'])
    for component in ('core', 'portal', 'jobservice', 'registry', 'trivy'):
        matches = [r for r in resources if r['kind'] in ('Deployment', 'StatefulSet')
                   and r['metadata']['name'] == 'harbor-' + component]
        require(len(matches) == 1)
        volumes = matches[0]['spec']['template']['spec']['volumes']
        require(any((v.get('secret') or {}).get('secretName') == 'harbor-' + component + '-tls' for v in volumes))


def supporting():
    resources = [yaml.safe_load((CANDIDATE / 'destinationrule.yaml').read_text())]
    vs = yaml.safe_load((ROOT / 'clusters/homelab/apps/harbor/virtualservice.yaml').read_text())
    vs['spec']['http'][0]['route'][0]['destination']['port']['number'] = 443
    resources.append(vs)
    # The CA Secret is supplied through the separately approved custody procedure.
    # Never generate a signing key, trust root, credential or deployment here.
    resources.append({'apiVersion': 'cert-manager.io/v1', 'kind': 'Issuer',
                      'metadata': {'name': 'harbor-internal-ca', 'namespace': 'harbor'},
                      'spec': {'ca': {'secretName': 'harbor-internal-ca'}}})
    for component in ('frontend', 'core', 'portal', 'jobservice', 'registry', 'trivy'):
        name = 'harbor-' + component
        resources.append({'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate',
                          'metadata': {'name': name + '-tls', 'namespace': 'harbor'},
                          'spec': {'secretName': name + '-tls', 'duration': '2160h', 'renewBefore': '720h',
                                   'issuerRef': {'name': 'harbor-internal-ca', 'kind': 'Issuer'},
                                   'privateKey': {'rotationPolicy': 'Always'},
                                   'usages': ['digital signature', 'key encipherment', 'server auth'],
                                   'dnsNames': [name, name + '.harbor.svc', name + '.harbor.svc.cluster.local']}})
    return resources


def render(chart, helm):
    require(hashlib.sha256(chart.read_bytes()).hexdigest() == CHART_SHA)
    result = subprocess.run([helm, 'template', 'harbor', str(chart), '--namespace', 'harbor',
                             '-f', str(ROOT / 'clusters/homelab/apps/harbor/values.yaml'),
                             '-f', str(CANDIDATE / 'values.yaml')], capture_output=True, check=True, timeout=60)
    resources = [r for r in yaml.safe_load_all(result.stdout) if r]
    return harden(resources) + supporting()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart', type=Path, required=True)
    parser.add_argument('--helm', default='helm')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        resources = render(args.chart, args.helm)
        if args.check:
            print(json.dumps({'candidate_resources': len(resources), 'execution_enabled': False}))
        else:
            # Helm may generate secret values: require --check until a reviewed
            # materialization/redaction pipeline exists. No rendered secret output.
            raise ValueError('Render output remains disabled')
        return 0
    except Exception:  # noqa: BLE001 - rendered Helm data may contain credentials
        print('TLS render failed or output disabled; private rendered content withheld.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
