#!/usr/bin/env python3
"""Check cAdvisor retention and the committed EPHEMERAL rules, optionally rendering the pinned chart."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'clusters/homelab/apps/prometheus'
NAMES = ('limit_bytes', 'usage_bytes', 'inodes_free', 'inodes_total')
DEVICES = {'acer': '/dev/sda4', **{f'zimaboard-{n}': '/dev/mmcblk0p4' for n in range(3)}}


def read_yaml(path, selector='.'):
    return json.loads(subprocess.check_output(['yq', '-o=json', selector, str(path)]))


def relabel(rules, labels):
    labels = dict(labels)
    for rule in rules:
        if rule['action'] == 'labeldrop':
            labels = {k: v for k, v in labels.items() if not re.fullmatch(rule['regex'], k)}
            continue
        if re.fullmatch(rule['regex'], ';'.join(labels.get(k, '') for k in rule['sourceLabels'])):
            if rule['action'] == 'drop':
                return None
            assert rule['action'] == 'replace'
            labels[rule['targetLabel']] = rule['replacement']
    return labels


def check_retention(rules):
    # Offline CI also checks the untouched 85.2.0 drops without downloading a chart.
    prefix = json.dumps(rules[:-3], sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(prefix).hexdigest() == 'de93ffc271b1944299c23ed61522765b5521aa1e40de32d67e70539c39bdd12e', 'upstream cAdvisor drop rules changed'
    for node, device in DEVICES.items():
        for name in NAMES:
            root = {'__name__': 'container_fs_' + name, 'node': node, 'device': device, 'id': '/'}
            assert relabel(rules, root) == {**root, 'homelab_talos_volume': 'EPHEMERAL'}
            for changes in ({'device': '/run/containerd/sandbox', 'homelab_talos_volume': 'EPHEMERAL'}, {'device': '/dev'}, {'node': 'new-worker'},
                            {'device': '/dev/mmcblk0p4' if node == 'acer' else '/dev/sda4'},
                            {'id': '/kubepods'}, {'id': '/;'}, {'__name__': 'container_fs_reads_total'}):
                assert relabel(rules, {**root, **changes}) is None
            pod = {**root, 'id': '/kubepods', 'pod': 'workload'}
            assert relabel(rules, pod) == pod
    machine = {'__name__': 'machine_memory_bytes', 'node': 'acer'}
    assert relabel(rules, machine) == machine
    assert relabel(rules, {'__name__': 'container_spec_memory_limit_bytes', 'id': '/kubepods', 'pod': 'app'}) is None


def check_chart(chart, values, rules, work):
    catalog = json.loads((ROOT / 'scripts/config/harbor-helm-charts.json').read_bytes())
    matches = [r for r in catalog['charts'] if r['chart'] == 'kube-prometheus-stack']
    assert len(matches) == 1 and matches[0]['version'] == '85.2.0'
    assert hashlib.sha256(chart.read_bytes()).hexdigest() == matches[0]['sha256'], 'unexpected chart package'
    def render(values_file):
        raw = subprocess.check_output(['helm', 'template', 'prometheus', str(chart), '-n', 'monitoring', '-f', str(values_file)])
        documents = raw.split(b'\n---\n')
        marker = b'# Source: kube-prometheus-stack/templates/exporters/kubelet/servicemonitor.yaml\n'
        monitor, = [doc for doc in documents if marker in doc]
        return monitor, [doc for doc in documents if doc != monitor]
    before = work / 'before.json'
    del values['kubelet']['serviceMonitor']['cAdvisorMetricRelabelings']
    before.write_text(json.dumps(values))
    manifests = []
    old_doc, old_others = render(before)
    new_doc, new_others = render(APP / 'values.yaml')
    assert old_others == new_others, 'another chart resource changed'
    for doc in (old_doc, new_doc):
        out = work / 'monitor.yaml'
        out.write_bytes(doc)
        manifests.append(read_yaml(out))
    def cadvisor(sm):
        return next(ep for ep in sm['spec']['endpoints'] if ep.get('path') == '/metrics/cadvisor')
    old, new = manifests
    old_rules = cadvisor(old)['metricRelabelings']
    assert old_rules[-1] == {'sourceLabels': ['id', 'pod'], 'action': 'drop', 'regex': '.+;'}
    assert rules[:-3] == old_rules[:-1] and cadvisor(new)['metricRelabelings'] == rules
    cadvisor(new)['metricRelabelings'] = old_rules
    assert old == new, 'unexpected kubelet ServiceMonitor change'


def fixture(node='acer', capacity='1000x100', usage='730x100', free='1000x100', total='1000x100'):
    labels = (f'node="{node}",device="{DEVICES[node]}",job="kubelet",metrics_path="/metrics/cadvisor",'
              'id="/",homelab_talos_volume="EPHEMERAL"')
    return [{'series': 'container_fs_' + name + '{' + labels + '}', 'values': data}
            for name, data in zip(NAMES, (capacity, usage, free, total), strict=True) if data]


def check_inhibition():
    rules = read_yaml(APP / 'externalsecret.yaml', '.spec.target.template.data."alertmanager.yaml" | from_yaml | .inhibit_rules')
    critical = [r for r in rules if 'severity = "critical"' in r.get('source_matchers', [])]
    names = 'TalosEphemeralAlmostFull|TalosEphemeralFillingUp'
    assert critical == [
        {'source_matchers': ['severity = "critical"', f'alertname !~ "{names}"'],
         'target_matchers': ['severity =~ "warning|info"'], 'equal': ['namespace', 'alertname']},
        {'source_matchers': ['severity = "critical"', f'alertname =~ "{names}"'],
         'target_matchers': ['severity = "warning"'], 'equal': ['namespace', 'alertname', 'node', 'device', 'resource']},
    ], 'critical inhibition must preserve warnings on other filesystems'


def check_rules(work):
    rule = APP / 'talos-filesystem-prometheusrules.yaml'
    assert rule.name in read_yaml(APP / 'kustomization.yaml', '.resources')
    rules_file = work / 'rules.json'
    rules_file.write_text(json.dumps(read_yaml(rule, '.spec')))
    tests = []
    def case(name, rows, checks):
        tests.append({'name': name, 'interval': '5m', 'input_series': rows,
                      'promql_expr_test': [{'expr': e, 'eval_time': t,
                                            'exp_samples': [{'labels': '{}', 'value': v}]}
                                           for t, e, v in checks]})
    def alert(name, labels=''):
        return f'count(ALERTS{{alertname="{name}",alertstate="firing",node="acer"{labels}}}) or vector(0)'
    floor = alert('TalosEphemeralAlmostFull')
    trend = alert('TalosEphemeralFillingUp')
    missing = alert('TalosEphemeralTelemetryMissing')
    case('stable small worker has capacity', fixture(node='zimaboard-0'), [
        ('8h', 'count(ALERTS{alertname=~"TalosEphemeralAlmostFull|TalosEphemeralFillingUp",node="zimaboard-0"}) or vector(0)', 0),
        ('8h', 'sum(node_device:talos_ephemeral_free_bytes{node="zimaboard-0"})', 270)])
    case('zero free is critical and still observable', fixture(usage='1000x100', free='0x100'),
         [('25m', floor, 0), ('30m', floor, 4), ('30m', missing, 0)])
    case('floor clears with recovery', fixture(usage='960x8 600x90'), [('30m', floor, 1), ('50m', floor, 0)])
    case('sustained measured byte depletion', fixture(usage='600+4x100'), [
        ('4h', trend, 0), ('6h30m', alert('TalosEphemeralFillingUp', ',resource="bytes",severity="warning"'), 1),
        ('7h30m', alert('TalosEphemeralFillingUp', ',resource="bytes",severity="critical"'), 1)])
    case('sustained measured inode depletion', fixture(free='520-5x100'), [
        ('4h', trend, 0), ('6h', alert('TalosEphemeralFillingUp', ',resource="inodes",severity="warning"'), 1),
        ('7h', alert('TalosEphemeralFillingUp', ',resource="inodes",severity="critical"'), 1)])
    case('incomplete gauges', fixture(usage=None), [('10m', missing, 0), ('15m', missing, 1)])
    case('invalid inode denominator', fixture(total='0x100'), [('15m', missing, 1)])
    case('all targets disappeared', [], [('15m', 'count(ALERTS{alertname="TalosEphemeralTelemetryMissing",alertstate="firing"})', 4)])
    test_file = work / 'test.json'
    test_file.write_text(json.dumps({'rule_files': [str(rules_file)], 'evaluation_interval': '5m', 'tests': tests}))
    subprocess.run(['promtool', 'check', 'rules', str(rules_file)], check=True)
    subprocess.run(['promtool', 'test', 'rules', str(test_file)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart', type=Path, help='local pinned kube-prometheus-stack package for Helm comparison')
    args = parser.parse_args()
    values = read_yaml(APP / 'values.yaml')
    rules = values['kubelet']['serviceMonitor']['cAdvisorMetricRelabelings']
    check_retention(rules)
    check_inhibition()
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        if args.chart:
            check_chart(args.chart, values, rules, work)
        check_rules(work)
