#!/usr/bin/env python3
"""Offline declaration inventory; emits references only, never Secret contents."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def inventory(root=ROOT):
    consumers, stores, pushers = [], [], []
    for path in sorted((root / 'clusters').rglob('*.yaml')):
        for item in yaml.safe_load_all(path.read_text()):
            if not isinstance(item, dict):
                continue
            kind = item.get('kind')
            if kind not in ('ExternalSecret', 'ClusterExternalSecret', 'SecretStore',
                            'ClusterSecretStore', 'PushSecret', 'ClusterPushSecret'):
                continue
            meta = item.get('metadata', {})
            row = {'path': str(path.relative_to(root)), 'kind': kind,
                   'name': meta.get('name'), 'namespace': meta.get('namespace', 'CLUSTER' if kind.startswith('Cluster') else 'UNRESOLVED')}
            spec = item['spec']
            if kind == 'ExternalSecret':
                row['store'] = spec.get('secretStoreRef', {})
                consumers.append(row)
            elif kind == 'ClusterExternalSecret':
                row['store'] = spec.get('externalSecretSpec', {}).get('secretStoreRef', {})
                consumers.append(row)
            elif kind in ('PushSecret', 'ClusterPushSecret'):
                row['stores'] = spec.get('secretStoreRefs', [])
                pushers.append(row)
            else:
                row['conditions'] = spec.get('conditions', [])
                stores.append(row)
    workflows = []
    for path in sorted((root / '.github/workflows').glob('*.yml')):
        # Preserve literal references only, not resolved variable/secret contents.
        refs = [line.split('role-to-assume:', 1)[1].strip() for line in path.read_text().splitlines()
                if line.lstrip().startswith('role-to-assume:')]
        if refs:
            workflows.append({'path': str(path.relative_to(root)), 'role_references': refs})
    return {'scope': 'literal repository declarations; not registration, RBAC or effective IAM',
            'stores': stores, 'consumers': consumers, 'pushers': pushers, 'workflows': workflows}


if __name__ == '__main__':
    print(json.dumps(inventory(), indent=2, sort_keys=True))
