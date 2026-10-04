#!/usr/bin/env python3
"""Offline pinned-chart render assertions. Never prints generated Secret data."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'scripts/fixtures/harbor-authorization'


def check(resources, expected_images):
    images = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('image'), str):
                images.add(value['image'])
            assert not any(key in value for key in ('hostPath', 'persistentVolumeClaim', 'volumeClaimTemplates'))
            assert value.get('hostNetwork') is not True
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for resource in resources:
        assert resource['kind'] not in ('Ingress', 'Gateway', 'HTTPRoute', 'PersistentVolume', 'PersistentVolumeClaim')
        if resource['kind'] == 'Service':
            assert resource['spec'].get('type', 'ClusterIP') == 'ClusterIP'
        walk(resource)
    assert images == expected_images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart', type=Path, required=True)
    parser.add_argument('--helm', default='helm')
    args = parser.parse_args()
    try:
        lock = json.loads((FIXTURE / 'lock.json').read_text())
        actual = 'sha256:' + hashlib.sha256(args.chart.read_bytes()).hexdigest()
        assert actual == lock['chart_sha256']
        render = subprocess.run([args.helm, 'template', 'home57-fixture', str(args.chart),
                                 '--namespace', 'home57-fixture', '--values', str(FIXTURE / 'values.yaml')],
                                capture_output=True, check=True, timeout=60)
        resources = [r for r in yaml.safe_load_all(render.stdout) if r]
        check(resources, set(lock['images'].values()))
        print(f'Fixture render passed: {len(resources)} resources, exact locked images, no persistent or external resources.')
        return 0
    except Exception:  # noqa: BLE001 - Helm errors can contain generated secret material
        print('Fixture render failed; generated content withheld.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
