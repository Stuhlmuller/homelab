#!/usr/bin/env python3
"""Read-only Kubernetes retirement status fixtures."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retirement_status', ROOT / 'scripts/openclaw-retirement-status.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ROOT / 'scripts/config/openclaw-enterprise.json').read_text())['legacyRetention']


class Status(unittest.TestCase):
    def setUp(self):
        self.deployment = {
            'spec': {
                'replicas': 1,
                'selector': {'matchLabels': {'app.kubernetes.io/name': 'openclaw'}},
                'template': {
                    'metadata': {'annotations': {
                        'homelab.rst.io/openclaw-assistant-sha256': CONFIG['assistantSha256']}},
                    'spec': {'containers': [{'name': 'app', 'image': CONFIG['image']}]},
                },
            },
            'status': {'readyReplicas': 1},
        }
        self.cron = {'metadata': {'uid': 'cron-uid'}, 'spec': {'suspend': False}}
        self.node = {'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        self.reader = {
            'metadata': {'name': 'retirement-pod', 'labels': {
                'app.kubernetes.io/name': 'openclaw-retirement-reader'}},
            'spec': {'nodeName': CONFIG['node']},
            'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]},
        }
        self.old = {'metadata': {'labels': {'app.kubernetes.io/name': 'openclaw'}},
                    'status': {'phase': 'Running'}}
        self.pods = [self.reader, self.old]
        self.jobs = []
        self.pvcs = {}
        self.pvs = {}
        for name in (CONFIG[key] for key in ('localClaim', 'stateClaim', 'agentClaim', 'nasClaim')):
            pv_name = name if name != 'openclaw' else 'pvc-nas-volume'
            self.pvcs[name] = {'metadata': {'uid': 'pvc-uid-' + name},
                               'spec': {'volumeName': pv_name}, 'status': {'phase': 'Bound'}}
            self.pvs[pv_name] = {'metadata': {'uid': 'pv-uid-' + name},
                                 'spec': {'claimRef': {'uid': 'pvc-uid-' + name},
                                          'persistentVolumeReclaimPolicy': 'Retain'}}

    def query(self, *args, missing=False):
        if 'exec' in args:
            return {'local': {'device': 1, 'inode': 2, 'uid': 1000},
                    'nas': {'device': 3, 'inode': 4, 'uid': 65534}}
        if args[:2] == ('get', 'node'):
            return self.node
        if args[:2] == ('get', 'pv'):
            return self.pvs[args[2]]
        kind = args[args.index('get') + 1]
        if kind == 'deployment':
            return self.deployment
        if kind == 'cronjob':
            return self.cron
        if kind == 'pods':
            return {'items': self.pods}
        if kind == 'jobs':
            return {'items': self.jobs}
        if kind == 'pvc':
            return self.pvcs[args[args.index('get') + 2]]
        raise AssertionError(args)

    def test_active_then_stopped_writer_inventory(self):
        active = module.resources(CONFIG, self.query)
        self.assertEqual((active['replicas'], active['pods'], active['cronJobSuspended']), (1, 1, False))
        self.deployment['spec']['replicas'] = 0
        self.deployment['status'] = {}
        self.cron['spec']['suspend'] = True
        self.pods = [self.reader]
        stopped = module.resources(CONFIG, self.query)
        self.assertEqual((stopped['replicas'], stopped['pods'], stopped['activeJobs']), (0, 0, 0))
        self.assertEqual(set(stopped['volumes']), set(self.pvcs))

    def test_unknown_reader_node_or_rebound_pv_fails_closed(self):
        self.reader['spec']['nodeName'] = 'other-node'
        with self.assertRaises(ValueError):
            module.resources(CONFIG, self.query)
        self.reader['spec']['nodeName'] = CONFIG['node']
        self.pvs['openclaw-runtime-local']['spec']['claimRef']['uid'] = 'rebound-uid'
        with self.assertRaises(ValueError):
            module.resources(CONFIG, self.query)

    def test_pending_job_and_backup_pod_count_as_writers(self):
        self.jobs = [{'metadata': {'uid': 'job-uid', 'ownerReferences': [
            {'kind': 'CronJob', 'name': CONFIG['cronJob'], 'uid': 'cron-uid'}]},
            'status': {'active': 0}}]
        self.pods.append({'metadata': {'ownerReferences': [{'kind': 'Job', 'uid': 'job-uid'}]},
                          'status': {'phase': 'Pending'}})
        self.assertEqual(module.resources(CONFIG, self.query)['activeJobs'], 2)
        self.cron = None
        self.assertEqual(module.resources(CONFIG, self.query)['activeJobs'], 2)

    def test_private_status_output_contract(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            path.chmod(0o700)
            destination = path / 'status.json'
            module.retirement.write_private(destination, module.resources(CONFIG, self.query))
            self.assertEqual(json.loads(destination.read_text())['roots']['local']['uid'], 1000)
            with self.assertRaises(FileExistsError):
                module.retirement.write_private(destination, {})


if __name__ == '__main__':
    unittest.main()
