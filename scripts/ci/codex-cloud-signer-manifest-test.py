#!/usr/bin/env python3
"""Render and check the sensitive signer mounts and narrow initializer exception."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'clusters/homelab/apps/codex-cloud-signer'


def rendered(path):
    yaml = subprocess.check_output(['kubectl', 'kustomize', str(path)], text=True)
    return json.loads(subprocess.check_output(['yq', 'ea', '-o=json', '[.]'], input=yaml, text=True))


class ManifestTests(unittest.TestCase):
    def test_state_and_privileges_are_isolated(self):
        resources = rendered(APP)
        pod = next(item['spec']['template']['spec'] for item in resources if item['kind'] == 'StatefulSet')
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'acer'})
        init, = pod['initContainers']
        self.assertEqual(init['name'], 'state-permissions')
        self.assertEqual(init['command'], ['python3', '-I', '-B', '/app/init-state.py'])
        self.assertEqual(init['securityContext']['capabilities'], {'drop': ['ALL'], 'add': ['CHOWN', 'FOWNER']})
        containers = {item['name']: item for item in pod['containers']}
        for container in containers.values():
            self.assertEqual(container['securityContext']['capabilities'], {'drop': ['ALL']})
            self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
            self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual({mount['name'] for mount in containers['api']['volumeMounts']}, {'code', 'credentials', 'socket'})
        self.assertEqual({mount['name'] for mount in containers['tailscale']['volumeMounts']}, {'code', 'enrollment', 'socket', 'state'})
        self.assertEqual(next(mount for mount in init['volumeMounts'] if mount['name'] == 'state'),
                         {'name': 'state', 'mountPath': '/state'})
        self.assertEqual(next(mount for mount in containers['tailscale']['volumeMounts'] if mount['name'] == 'state'),
                         {'name': 'state', 'mountPath': '/var/lib/tailscale'})
        volumes = {item['name']: item for item in pod['volumes']}
        self.assertEqual(volumes['state']['persistentVolumeClaim'], {'claimName': 'codex-cloud-signer-state'})
        self.assertEqual({item['key'] for item in volumes['credentials']['secret']['items']},
                         {'oauth-client-id', 'oauth-client-secret', 'webhook-secret'})
        self.assertEqual(volumes['enrollment']['secret']['items'], [{'key': 'auth-key', 'path': 'auth-key'}])
        pv = next(item for item in rendered(ROOT / 'clusters/homelab/platform/storage')
                  if item['kind'] == 'PersistentVolume' and item['metadata']['name'] == 'codex-cloud-signer-local')
        self.assertEqual(pv['spec']['claimRef'], {'name': 'codex-cloud-signer-state', 'namespace': 'automation'})
        self.assertEqual(pv['spec']['persistentVolumeReclaimPolicy'], 'Retain')
        self.assertEqual(pv['spec']['hostPath']['path'], '/var/lib/codex-cloud-signer')


if __name__ == '__main__':
    unittest.main()
