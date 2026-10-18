#!/usr/bin/env python3
"""Capture a private, read-only Kubernetes writer and volume identity receipt."""

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'openclaw_retirement', ROOT / 'clusters/homelab/apps/openclaw/assistant/retirement.py')
retirement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retirement)


def kubectl(*args, missing=False):
    result = subprocess.run(['kubectl', *args], capture_output=True, text=True,
                            timeout=60, check=False)
    if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
        raise ValueError('read-only Kubernetes inspection failed')
    if missing and not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def resources(config, query=kubectl):
    namespace = config['namespace']
    def get(kind, name=None, *, missing=False):
        args = ['-n', namespace, 'get', kind]
        if name:
            args.append(name)
        args.extend(['-o', 'json'])
        if missing:
            args.append('--ignore-not-found')
        return query(*args, missing=missing)

    deployment = get('deployment', config['deployment'])
    cron = get('cronjob', config['cronJob'], missing=True)
    node = query('get', 'node', config['node'], '-o', 'json')
    old_pods = get('pods')['items']
    jobs = get('jobs')['items']
    readers = [pod for pod in old_pods if pod.get('metadata', {}).get('labels', {}).get(
        'app.kubernetes.io/name') == 'openclaw-retirement-reader']
    if len(readers) != 1 or readers[0].get('status', {}).get('phase') != 'Running':
        raise ValueError('one ready retirement reader is required')
    reader = readers[0]
    if reader.get('spec', {}).get('nodeName') != config['node'] or not any(
        condition.get('type') == 'Ready' and condition.get('status') == 'True'
        for condition in reader.get('status', {}).get('conditions', [])):
        raise ValueError('retirement reader is not ready on the expected node')
    roots = query('-n', namespace, 'exec', 'pod/' + reader['metadata']['name'],
                  '-c', 'reader', '--', 'python3', '-c',
                  'import json,os,sys; print(json.dumps({name:{"device":os.stat(path).st_dev,"inode":os.stat(path).st_ino,"uid":os.stat(path).st_uid} for name,path in zip(("local","nas"),sys.argv[1:])}))',
                  config['localRoot'], config['nasRoot'])
    claims = {key: config[key] for key in ('localClaim', 'stateClaim', 'agentClaim', 'nasClaim')}
    volumes = {}
    for claim in claims.values():
        pvc = get('pvc', claim)
        pv_name = pvc.get('spec', {}).get('volumeName')
        if not pv_name or pvc.get('status', {}).get('phase') != 'Bound':
            raise ValueError('legacy PVC is not bound')
        pv = query('get', 'pv', pv_name, '-o', 'json')
        if (pv.get('spec', {}).get('claimRef', {}).get('uid') != pvc['metadata']['uid']
                or pv.get('spec', {}).get('persistentVolumeReclaimPolicy') != 'Retain'):
            raise ValueError('legacy PV binding or retention changed')
        volumes[claim] = {'pvcUid': pvc['metadata']['uid'], 'pvName': pv_name,
                          'pvUid': pv['metadata']['uid']}
    selectors = deployment.get('spec', {}).get('selector', {}).get('matchLabels', {})
    if not selectors or selectors.get('app.kubernetes.io/name') != config['deployment']:
        raise ValueError('legacy Deployment selector changed')
    pods = [pod for pod in old_pods if all(pod.get('metadata', {}).get('labels', {}).get(k) == v
                                           for k, v in selectors.items())]
    cron_uid = cron.get('metadata', {}).get('uid') if cron else None
    cron_jobs = [job for job in jobs if any(
        ref.get('kind') == 'CronJob' and
        (ref.get('name') == config['cronJob'] or
         (cron_uid is not None and ref.get('uid') == cron_uid))
        for ref in job.get('metadata', {}).get('ownerReferences', []))]
    active_jobs = [job for job in cron_jobs if not any(
        condition.get('type') in ('Complete', 'Failed') and condition.get('status') == 'True'
        for condition in job.get('status', {}).get('conditions', []))]
    backup_uids = {job['metadata']['uid'] for job in cron_jobs}
    active_backup_pods = [pod for pod in old_pods if any(
        ref.get('uid') in backup_uids and ref.get('kind') == 'Job'
        for ref in pod.get('metadata', {}).get('ownerReferences', []))
        and pod.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
    containers = [item for item in deployment['spec']['template']['spec']['containers']
                  if item.get('name') == 'app']
    if len(containers) != 1:
        raise ValueError('legacy app container identity changed')
    ready = any(condition.get('type') == 'Ready' and condition.get('status') == 'True'
                for condition in node.get('status', {}).get('conditions', []))
    result = {
        'checkedAt': int(time.time()), 'namespace': namespace,
        'node': config['node'], 'nodeReady': ready,
        'deployment': config['deployment'], 'image': containers[0]['image'],
        'assistantSha256': deployment['spec']['template'].get('metadata', {}).get(
            'annotations', {}).get('homelab.rst.io/openclaw-assistant-sha256'),
        'replicas': deployment['spec'].get('replicas', 1),
        'readyReplicas': deployment.get('status', {}).get('readyReplicas', 0),
        'pods': len(pods), 'cronJob': config['cronJob'],
        'cronJobSuspended': cron.get('spec', {}).get('suspend') is True if cron else False,
        'cronJobAbsent': cron is None,
        'activeJobs': len(active_jobs) + len(active_backup_pods),
        'claims': claims, 'volumes': volumes, 'roots': roots,
    }
    retirement.volume_identity(result, config)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        retirement.write_private(args.output, resources(retirement.config_at(args.config)))
        print('Private legacy status captured')
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print('Legacy status capture refused; inspect private diagnostics', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
