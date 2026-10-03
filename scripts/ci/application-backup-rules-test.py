#!/usr/bin/env python3
"""Exercise candidate freshness alerts: absent, failed, stale, healthy, stopped."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--promtool', default='promtool')
    parser.add_argument('--rules-json', type=Path, help='Optional pre-rendered full PrometheusRule JSON')
    args = parser.parse_args()
    document = json.loads(args.rules_json.read_text() if args.rules_json else subprocess.check_output(
        ['yq', '-o=json', '.', str(ROOT / 'recovery/application-backups/prometheusrule.yaml')]))
    summary = 'Independent application recovery copy is missing, stale, or unreadable'
    description = 'Inspect the private publisher and retrieval checker. A successful local backup Job is insufficient.'
    def alerts(apps):
        return [{'exp_labels': {'app': app, 'severity': 'warning'},
                 'exp_annotations': {'summary': summary, 'description': description}} for app in apps]
    cases = []
    for name in ('absent', 'healthy', 'failed', 'stale', 'stopped'):
        series = []
        for app in ('octelium', 'media-postgres'):
            if name == 'absent':
                continue
            values = {
                'check_success': '0+0x2000' if name == 'failed' else '1+0x2000',
                'capture_timestamp_seconds': '0+0x2000' if name == 'stale' else '0+60x2000',
                'check_timestamp_seconds': '0+0x2000' if name == 'stopped' else '0+60x2000',
            }
            for suffix, data in values.items():
                series.append({'series': f'homelab_application_backup_{suffix}{{app="{app}"}}', 'values': data})
        evaluation = '31h' if name == 'stale' else '3h' if name == 'stopped' else '20m'
        cases.append({'name': name, 'interval': '1m', 'input_series': series,
                      'alert_rule_test': [{'eval_time': evaluation, 'alertname': 'IndependentApplicationBackupUnavailable',
                      'exp_alerts': [] if name == 'healthy' else alerts(('octelium', 'media-postgres'))}]})
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'rules.yaml').write_text(json.dumps(document['spec']))
        (root / 'tests.yaml').write_text(json.dumps({'rule_files': ['rules.yaml'], 'evaluation_interval': '1m', 'tests': cases}))
        subprocess.run([args.promtool, 'test', 'rules', str(root / 'tests.yaml')], check=True, timeout=60)


if __name__ == '__main__':
    main()
