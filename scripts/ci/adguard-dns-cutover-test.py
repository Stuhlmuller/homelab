#!/usr/bin/env python3
"""Negative fixtures for DNS-only saved-plan and freshness guards."""
import copy
import importlib.util
from pathlib import Path
import unittest
import time
from unittest.mock import patch
import tempfile
import json

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cutover', ROOT / 'scripts/adguard-dns-cutover.py')
CUTOVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUTOVER)


def policies():
    fixture = json.loads((ROOT / 'IaC/terragrunt-catalog/modules/tailscale-access/tests/fixtures/adguard-dns-cutover.json').read_text())
    assert fixture['fixture_only'] is True
    return fixture['before'], fixture['after']


def plan():
    before, after = policies()
    return {'format_version': '1.2', 'configuration': {
        'provider_config': {'tailscale': {'name': 'tailscale',
            'full_name': 'registry.opentofu.org/tailscale/tailscale', 'version_constraint': '0.29.2',
            'expressions': {name: {'constant_value': 'file:' + str(Path.home() / '.config/homelab/tailscale' / filename)}
                            for name, filename in (('oauth_client_id', 'terragrunt-oauth-client-id'),
                                                   ('oauth_client_secret', 'terragrunt-oauth-client-secret'))}}},
        'root_module': {'resources': [{'address': CUTOVER.ADDRESS, 'provider_config_key': 'tailscale'}]}},
        'resource_changes': [
        {'address': CUTOVER.ADDRESS, 'mode': 'managed', 'type': 'tailscale_dns_configuration',
         'change': {'actions': ['update'], 'before': dict(before, id='dns_configuration'),
                    'after': dict(after, id='dns_configuration'), 'after_unknown': {}}}],
        'planned_values': {'root_module': {'resources': [
            {'address': CUTOVER.ADDRESS, 'values': dict(after, id='dns_configuration')}]}},
        'output_changes': {}, 'resource_drift': []}


class CutoverContracts(unittest.TestCase):
    def test_plan_provider_must_match_existing_admin_identity(self):
        valid = plan()
        valid['configuration']['root_module']['resources'][0]['provider_config_key'] = 'opaque-reference'
        valid['configuration']['provider_config']['opaque-reference'] = valid['configuration']['provider_config'].pop('tailscale')
        CUTOVER.validate_plan(valid, *policies())
        mutations = (
            lambda p: p.pop('configuration'),
            lambda p: p['configuration']['root_module']['resources'][0].update(provider_config_key='tailscale.other'),
            lambda p: p['configuration']['provider_config']['tailscale'].update(version_constraint='>= 0.29.2'),
            lambda p: p['configuration']['provider_config']['tailscale'].update(full_name='other.example/tailscale/tailscale'),
            lambda p: p['configuration']['provider_config']['tailscale'].update(alias='other'),
            lambda p: p['configuration']['provider_config']['tailscale'].update(module_address='module.other'),
            lambda p: p['configuration']['provider_config']['tailscale']['expressions'].update(tailnet={'constant_value': 'other'}),
            lambda p: p['configuration']['provider_config']['tailscale']['expressions'].update(api_key={'constant_value': 'synthetic'}),
            lambda p: p['configuration']['provider_config']['tailscale']['expressions'].update(base_url={'constant_value': 'https://other.example'}),
            lambda p: p['configuration']['provider_config']['tailscale']['expressions'].update(oauth_client_secret={'references': ['var.secret']}),
        )
        for index, mutate in enumerate(mutations):
            value = plan(); mutate(value)
            with self.subTest(index=index), self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_plan(value, *policies())

    def test_exact_dns_only_update(self):
        before, after = policies()
        CUTOVER.validate_plan(plan(), before, after)
        CUTOVER.validate_transition(before, after, '100.99.0.1')

    def test_source_defaults_and_api_complete_policy(self):
        before, _ = policies()
        source = copy.deepcopy(before)
        for resolver in source['nameservers']:
            resolver.pop('use_with_exit_node')
        self.assertEqual(CUTOVER.source_policy({'resource': {'tailscale_dns_configuration': {'homelab': [source]}}}),
                         CUTOVER.policy(before))
        api = {'nameservers': [{'address': r['address']} for r in before['nameservers']],
               'splitDNS': {'stinkyboi.com': [{'address': '100.71.150.27', 'useWithExitNode': True}]},
               'searchPaths': [], 'preferences': {'magicDNS': True, 'overrideLocalDNS': False}}
        self.assertEqual(CUTOVER.api_policy(api), CUTOVER.policy(before))
        api['unmodeled_setting'] = True
        with self.assertRaises(CUTOVER.Failure): CUTOVER.api_policy(api)

    def test_rejects_unrelated_delete_replace_unknown_and_incomplete(self):
        mutations = (
            lambda p: p['resource_changes'].append({'address': 'tailscale_acl.homelab', 'change': {'actions': ['update']}}),
            lambda p: p['resource_changes'][0]['change'].update(actions=['delete']),
            lambda p: p['resource_changes'][0]['change'].update(actions=['delete', 'create']),
            lambda p: p['resource_changes'][0]['change'].update(after_unknown={'nameservers': [{'address': True}]}),
            lambda p: p['resource_changes'][0]['change']['after'].pop('magic_dns'),
            lambda p: p['resource_changes'][0]['change']['after'].update(unreviewed=True),
            lambda p: p['resource_changes'][0]['change']['after'].update(id='replacement'),
            lambda p: p['planned_values']['root_module']['resources'].clear(),
            lambda p: p.update(errored=True),
            lambda p: p.update(output_changes={'keys': {'actions': ['update']}}),
            lambda p: p.update(resource_drift=[{'change': {'actions': ['update']}}]),
        )
        for index, mutate in enumerate(mutations):
            value = plan(); mutate(value)
            with self.subTest(index=index), self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_plan(value, *policies())

    def test_preserves_full_private_magicdns_and_search_policy(self):
        before, after = policies()
        for change in (lambda p: p.update(magic_dns=False), lambda p: p.update(search_paths=['example.com']),
                       lambda p: p.update(split_dns=[]), lambda p: p.update(override_local_dns=False),
                       lambda p: p['nameservers'].append({'address': '1.1.1.2', 'use_with_exit_node': False}),
                       lambda p: p['nameservers'][0].update(use_with_exit_node=False)):
            changed = copy.deepcopy(after); change(changed)
            with self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_transition(before, changed, '100.99.0.1')

    def test_freshness_bounds_and_clock_regression(self):
        CUTOVER.validate_timing(0, 300, 360, 1000, 1360)
        for args in ((0,301,301,1000,1301), (0,300,361,1000,1361),
                     (1,0,1,1000,1001), (0,1,0,1000,1001), (0,1,1,1000,999)):
            with self.subTest(args=args), self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_timing(*args)
        CUTOVER.validate_receipt_time({'started_at': 1000, 'completed_at': 1001}, 1002)
        for record in ({'started_at':1000,'completed_at':1003}, {'started_at':1002,'completed_at':1001},
                       {'started_at':-1,'completed_at':1001}):
            with self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_receipt_time(record,1002)

    def test_final_binding_rejects_every_changed_surface(self):
        value = {'source': 'source', 'config': 'config', 'service': 'service', 'peer': 'peer',
                 'plan_sha256': 'plan', 'live_policy': policies()[0], 'desired_policy': policies()[1]}
        CUTOVER.validate_binding(value, copy.deepcopy(value))
        for incomplete in ({}, {k:v for k,v in value.items() if k != 'peer'}, dict(value, peer=None),
                           dict(value, config=''), dict(value, service={})):
            with self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_binding(incomplete, copy.deepcopy(incomplete))
        for field in value:
            changed = copy.deepcopy(value); changed[field] = 'changed'
            with self.subTest(field=field), self.assertRaises(CUTOVER.Failure):
                CUTOVER.validate_binding(value, changed)


class FakeAdapter:
    def __init__(self):
        self.before, self.after = policies()
        self.live = self.before
        self.saved = None
        self.applies = 0
        self.checks = 0
        self.fail_after_write = False
        self.fail_before_write = False
        self.plan_digest = '1' * 64
        self.plan_time = time.time()
        self.drift = None
        self.snapshot_value = {'source_revision': 'a' * 40, 'deployed_revision': 'a' * 40,
                               'config_revision': 'v1', 'config_digest': 'config', 'source_digest': 'source',
                               'service_uid': 'service', 'server': '100.99.0.1',
                               'peer': {'node_key': 'node', 'signed': True}}
    def current_source(self): return 'a' * 40, self.after
    def baseline_policy(self): return self.before
    def read_plan(self):
        value = plan(); value['timestamp'] = CUTOVER.iso_time(self.plan_time)
        return self.plan_digest, value
    def plan_hash(self): return self.plan_digest
    def live_policy(self): return self.live
    def direct_check(self):
        self.checks += 1
        value = dict(copy.deepcopy(self.snapshot_value), mode='direct', admin_acceptance=True)
        if self.drift:
            self.drift(self)
        return value
    def snapshot(self): return copy.deepcopy(self.snapshot_value)
    def previous_receipt(self): return self.saved
    def save(self, value): self.saved = copy.deepcopy(value)
    def apply(self):
        self.applies += 1
        if self.fail_before_write: raise CUTOVER.Failure('synthetic apply failure')
        self.live = self.after
        if self.fail_after_write: raise CUTOVER.Failure('synthetic lost response')


class ExecutionContract(unittest.TestCase):
    def test_unreadable_apply_outcome_stays_uncertain_until_inspected(self):
        adapter = FakeAdapter()
        apply = adapter.apply
        def unreadable():
            apply()
            adapter.live_policy = lambda: (_ for _ in ()).throw(CUTOVER.Failure('unavailable'))
        adapter.apply = unreadable
        with self.assertRaises(CUTOVER.Failure): CUTOVER.reconcile(adapter, True)
        self.assertEqual(adapter.saved['phase'], 'uncertain')
        self.assertEqual(adapter.applies, 1)
        adapter.live_policy = lambda: adapter.live
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'already-applied')
        self.assertEqual(adapter.applies, 1)

    def test_future_plan_or_receipt_cannot_authorize_execution(self):
        adapter = FakeAdapter(); adapter.plan_time = time.time() + 60
        with self.assertRaises(CUTOVER.Failure): CUTOVER.reconcile(adapter, True)
        self.assertEqual(adapter.applies, 0)
        adapter.plan_time = time.time()
        CUTOVER.reconcile(adapter, True)
        adapter.saved['completed_at'] = time.time() + 60
        with self.assertRaises(CUTOVER.Failure): CUTOVER.reconcile(adapter, True)
        self.assertEqual(adapter.applies, 1)

    def test_private_plan_paths_and_native_apply_keep_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'saved.plan'
            path.write_bytes(b'synthetic encrypted plan fixture')
            path.chmod(0o600)
            self.assertEqual(CUTOVER.private_bytes(path), b'synthetic encrypted plan fixture')
            path.chmod(0o644)
            with self.assertRaises(CUTOVER.Failure): CUTOVER.private_bytes(path)
            path.chmod(0o600)
            link = Path(temp) / 'link'; link.symlink_to(path)
            with self.assertRaises(CUTOVER.Failure): CUTOVER.private_bytes(link)
            adapter = CUTOVER.Adapter.__new__(CUTOVER.Adapter)
            adapter.plan_path = path
            adapter.checked_plan_hash = adapter.plan_hash()
            with patch.object(CUTOVER, 'command') as command:
                adapter.apply()
            args = command.call_args.args[0]
            self.assertEqual(args[-3:], ['apply', '-input=false', str(path)])
            self.assertFalse(any('lock=false' in arg or 'auto-approve' in arg for arg in args))
            path.write_bytes(b'changed')
            with patch.object(CUTOVER, 'command') as command:
                with self.assertRaises(CUTOVER.Failure): adapter.apply()
                command.assert_not_called()

    def test_preview_never_writes_and_execute_checks_then_applies_once(self):
        adapter = FakeAdapter()
        self.assertEqual(CUTOVER.reconcile(adapter, False), 'preview')
        self.assertEqual(adapter.applies, 0)
        self.assertIsNone(adapter.saved)
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'applied')
        self.assertEqual(adapter.applies, 1)
        self.assertEqual(adapter.checks, 2)
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'already-applied')
        self.assertEqual(adapter.applies, 1)

    def test_each_drift_prevents_write(self):
        mutations = (lambda a: a.snapshot_value.update(config_digest='changed'),
                     lambda a: a.snapshot_value.update(service_uid='changed'),
                     lambda a: a.snapshot_value.update(peer={'node_key': 'different'}),
                     lambda a: setattr(a, 'plan_digest', '2' * 64),
                     lambda a: setattr(a, 'live', a.after),
                     lambda a: setattr(a, 'current_source', lambda: ('b' * 40, a.after)))
        for index, mutation in enumerate(mutations):
            adapter = FakeAdapter(); adapter.drift = mutation
            with self.subTest(index=index), self.assertRaises(CUTOVER.Failure):
                CUTOVER.reconcile(adapter, True)
            self.assertEqual(adapter.applies, 0)

    def test_uncertain_success_is_read_back_not_reapplied(self):
        adapter = FakeAdapter(); adapter.fail_after_write = True
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'applied')
        self.assertEqual(adapter.applies, 1)
        self.assertEqual(adapter.saved['phase'], 'applied')

    def test_failure_before_write_requires_a_new_plan(self):
        adapter = FakeAdapter(); adapter.fail_before_write = True
        with self.assertRaises(CUTOVER.Failure): CUTOVER.reconcile(adapter, True)
        self.assertEqual(adapter.saved['phase'], 'failed-needs-new-plan')
        with self.assertRaises(CUTOVER.Failure): CUTOVER.reconcile(adapter, True)
        self.assertEqual(adapter.applies, 1)
        adapter.plan_digest = '2' * 64
        adapter.plan_time = time.time()
        adapter.fail_before_write = False
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'applied')

    def test_interrupted_apply_is_only_inspected(self):
        adapter = FakeAdapter()
        CUTOVER.reconcile(adapter, True)
        adapter.saved['phase'] = 'uncertain'
        self.assertEqual(CUTOVER.reconcile(adapter, True), 'already-applied')
        self.assertEqual(adapter.applies, 1)


class RollbackAdapter(FakeAdapter):
    def __init__(self):
        active = FakeAdapter()
        CUTOVER.reconcile(active, True)
        self.__dict__.update(active.__dict__)
        self.applies = 0
        self.current_source = lambda: ('b' * 40, self.before)
        self.recorded_source = lambda revision: self.after
        self.direct_check = self.snapshot = lambda: (_ for _ in ()).throw(AssertionError('AdGuard is offline'))

    def read_plan(self):
        value = plan()
        change = value['resource_changes'][0]['change']
        change['before'], change['after'] = change['after'], change['before']
        value['planned_values']['root_module']['resources'][0]['values'] = change['after']
        value['timestamp'] = CUTOVER.iso_time(self.plan_time)
        return self.plan_digest, value

    def apply(self):
        self.applies += 1
        self.live = self.before


class RollbackContract(unittest.TestCase):
    def test_exact_restoration_succeeds_with_adguard_unavailable(self):
        adapter = RollbackAdapter()
        self.assertEqual(CUTOVER.rollback(adapter, False), 'rollback-preview')
        self.assertEqual(adapter.applies, 0)
        self.assertEqual(CUTOVER.rollback(adapter, True), 'restored')
        self.assertEqual(adapter.applies, 1)
        self.assertEqual(adapter.saved['after'], CUTOVER.policy(adapter.after))
        self.assertEqual(adapter.saved['rollback']['phase'], 'applied')

    def test_already_restored_is_noop_without_plan_or_health(self):
        adapter = RollbackAdapter(); adapter.live = adapter.before
        adapter.read_plan = lambda: (_ for _ in ()).throw(AssertionError('No plan needed'))
        self.assertEqual(CUTOVER.rollback(adapter, True), 'already-restored')
        self.assertEqual(adapter.applies, 0)

    def test_missing_record_wrong_source_and_unrelated_drift_reject(self):
        for mutate in (lambda a: setattr(a, 'saved', None),
                       lambda a: setattr(a, 'recorded_source', lambda r: a.before),
                       lambda a: setattr(a, 'live', dict(a.after, magic_dns=False)),
                       lambda a: setattr(a, 'current_source', lambda: ('b' * 40, a.after))):
            adapter = RollbackAdapter(); mutate(adapter)
            with self.assertRaises(CUTOVER.Failure): CUTOVER.rollback(adapter, True)
            self.assertEqual(adapter.applies, 0)

    def test_recorded_activation_cannot_smuggle_private_dns_changes(self):
        adapter = RollbackAdapter()
        adapter.saved['after']['split_dns'] = []
        adapter.recorded_source = lambda revision: adapter.saved['after']
        with self.assertRaises(CUTOVER.Failure): CUTOVER.rollback(adapter, True)
        self.assertEqual(adapter.applies, 0)

    def test_last_moment_live_drift_prevents_rollback_write(self):
        adapter = RollbackAdapter()
        read = adapter.read_plan
        def changed():
            value = read()
            adapter.live = dict(adapter.after, magic_dns=False)
            return value
        adapter.read_plan = changed
        with self.assertRaises(CUTOVER.Failure): CUTOVER.rollback(adapter, True)
        self.assertEqual(adapter.applies, 0)

    def test_uncertain_rollback_is_inspected_without_repeat_write(self):
        adapter = RollbackAdapter()
        apply = adapter.apply
        def lost():
            apply()
            raise CUTOVER.Failure('lost reply')
        adapter.apply = lost
        self.assertEqual(CUTOVER.rollback(adapter, True), 'restored')
        self.assertEqual(adapter.applies, 1)
        adapter.saved['rollback']['phase'] = 'uncertain'
        self.assertEqual(CUTOVER.rollback(adapter, True), 'already-restored')
        self.assertEqual(adapter.applies, 1)


if __name__ == '__main__':
    unittest.main()
