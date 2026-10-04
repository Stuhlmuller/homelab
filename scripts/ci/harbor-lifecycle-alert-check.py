#!/usr/bin/env python3
"""Offline PromQL checks against actual unregistered lifecycle rules, not notification delivery."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / 'clusters/homelab/apps/harbor-tls-candidate/lifecycle-prometheusrule.yaml'
LABELS = '{namespace="harbor",service="harbor-vulnerability-exporter"}'


def series(name, values):
    return {'series': name + LABELS, 'values': values}


def case(name, inputs, alert, at, count):
    return {'name': name, 'interval': '1m', 'input_series': inputs,
            'promql_expr_test': [{'expr': f'count(ALERTS{{alertname="{alert}",alertstate="firing"}}) or vector(0)',
                                 'eval_time': at, 'exp_samples': [{'labels': '{}', 'value': count}]}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--promtool', default=shutil.which('promtool'))
    args = parser.parse_args()
    if not args.promtool:
        raise SystemExit('promtool is required; run inside nix develop')
    healthy = [series('harbor_collector_expiry_metadata_valid', '1x30'),
               series('harbor_collector_credential_expires_at_seconds', '1728000x30'),
               series('harbor_vulnerability_collector_last_successful_timestamp_seconds', '0+60x30')]
    tests = [
        case('healthy expiry', healthy, 'HarborCollectorRenewalDue', '5m', 0),
        case('missing metadata', [], 'HarborCollectorExpiryMetadataMissing', '2m', 1),
        case('invalid metadata', [series('harbor_collector_expiry_metadata_valid', '0x5')],
             'HarborCollectorExpiryMetadataMissing', '2m', 1),
        case('renew before ten days remain', [series('harbor_collector_credential_expires_at_seconds', '864000x5')],
             'HarborCollectorRenewalDue', '2m', 1),
        case('expired', [series('harbor_collector_credential_expires_at_seconds', '60x5')],
             'HarborCollectorCredentialExpired', '2m', 1),
        case('absent collector', [], 'HarborCollectorTelemetryInterrupted', '1m', 1),
        case('stale before stop-forward deadline',
             [series('harbor_vulnerability_collector_last_successful_timestamp_seconds', '0x30')],
             'HarborCollectorTelemetryInterrupted', '9m', 1),
        case('fresh collector', healthy, 'HarborCollectorTelemetryInterrupted', '20m', 0),
        case('other namespace cannot hide absence',
             [{'series': 'harbor_collector_expiry_metadata_valid{namespace="other",service="harbor-vulnerability-exporter"}', 'values': '1x5'}],
             'HarborCollectorExpiryMetadataMissing', '2m', 1),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / 'rules.yaml').write_text(yaml.safe_dump(yaml.safe_load(RULE.read_text())['spec']))
        (directory / 'tests.yaml').write_text(yaml.safe_dump({'rule_files': ['rules.yaml'],
                                                            'evaluation_interval': '1m', 'tests': tests}))
        subprocess.run([args.promtool, 'test', 'rules', str(directory / 'tests.yaml')], check=True)
    print('Nine alert/expiry/deadline rule cases pass; no delivery or runtime acceptance claimed.')


if __name__ == '__main__':
    main()
