#!/usr/bin/env python3
"""Offline synthetic tests only. No credentials, server, or fixture execution."""

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('issuer_plan', ROOT / 'scripts/harbor-issuer-capability-plan.py')
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


def graph():
    result = {}
    for number, (alias, body) in enumerate(plan.identity_recipes().items(), 1):
        prefix = 'robot$' if body['level'] == 'system' else 'robot$' + body['permissions'][0]['namespace'] + '+'
        result[alias] = dict(body, name=prefix + body['name'], id=number,
                            creator_ref=10000,
                            creation_time='2026-01-01T00:00:00Z',
                            expires_at=plan.expiry('2026-01-01T00:00:00Z', body['duration']))
    result['child']['creator_ref'] = result['issuer']['id']
    return result


def case(target='child', variation='description', operation='update', actor='issuer'):
    return next(c for c in plan.cases() if (c['target'], c['variation'], c['operation'], c['actor']) ==
                (target, variation, operation, actor))


def mutated(c, identities):
    after = copy.deepcopy(identities)
    if c['operation'] == 'create':
        body = plan.request(c, identities)['body']
        after['created'] = dict(body, id=99, name='robot$' + body['name'],
                                creation_time='2026-01-01T00:00:00Z',
                                expires_at=plan.expiry('2026-01-01T00:00:00Z', body['duration']))
    elif c['operation'] == 'update':
        target = after[c['target']]
        delta = plan.changes(c, target)
        target.update(delta)
        if 'duration' in delta:
            target['expires_at'] = plan.expiry(target['creation_time'], target['duration'])
    return after


def evidence(c, identities, allowed=False):
    changed = mutated(c, identities)
    fingerprint = plan.fingerprint(plan.request(c, identities))
    return {'request_sha256': fingerprint, 'actor_baseline_status': 200,
            'observer_before_status': 200, 'observer_after_status': 200,
            'before': copy.deepcopy(identities), 'after': changed if allowed else copy.deepcopy(identities),
            'status': (201 if c['operation'] == 'create' else 200) if allowed else 403,
            'error_code': 'FORBIDDEN', 'reply_id': 99,
            'auth': {'old_before': 200, 'old_after': 401, 'new_after': 200},
            'old_credential_after_status': 200,
            'control': {'request_sha256': fingerprint, 'before': copy.deepcopy(identities),
                        'after': copy.deepcopy(changed), 'status': 201 if c['operation'] == 'create' else 200,
                        'reply_id': 99, 'auth': {'old_before': 200, 'old_after': 401, 'new_after': 200}}}


class Recipes(unittest.TestCase):
    def test_all_direct_cases_compile_and_have_control_oracles(self):
        identities = graph()
        for c in plan.cases():
            if c['operation'] == 'session':
                plan.session_recipe(c, identities)
                continue
            with self.subTest(case=c['id']):
                for allowed in (False, True):
                    result = plan.evaluate(c, identities, evidence(c, identities, allowed))
                    self.assertEqual(result['observation'], 'capability-present' if allowed else 'denied-with-controls')
                    self.assertFalse(result['issuer_authority_accepted'])

    def test_refresh_is_direct_patch_without_password_in_recipe(self):
        value = plan.request(case(operation='refresh', variation='secret'), graph())
        self.assertEqual(value, {'method': 'PATCH', 'path': '/api/v2.0/robots/2', 'body': {}})

    def test_non_synthetic_names_and_credential_metadata_rejected(self):
        for value in (dict(graph()['child'], name='robot$production'),
                      dict(graph()['child'], secret='not-a-real-secret')):
            with self.assertRaises(plan.Inconclusive):
                plan.synthetic_robot(value)

    def test_plan_default_and_execution_hard_stop(self):
        path = ROOT / 'scripts/harbor-issuer-capability-plan.py'
        result = subprocess.run([sys.executable, '-I', str(path)], capture_output=True, text=True, check=True)
        document = json.loads(result.stdout)
        self.assertFalse(document['execution_enabled'])
        self.assertTrue(all(c['server_status'] == 'unexecuted' for c in document['cases']))
        # No configuration flag, credential argument or network adapter to enable.
        with patch.object(sys, 'argv', ['plan', '--execute']):
            self.assertEqual(plan.main(), 1)

    def test_project_alternative_covers_same_cross_and_system_targets(self):
        targets = {c['target'] for c in plan.cases() if c['actor'] == 'project-homelab'}
        self.assertEqual(targets, {'project-child-homelab', 'project-child-mirror', 'unrelated', 'project-homelab'})

    def test_aliasing_authority_drift_and_creator_aliasing_rejected(self):
        for field, value in (('id', 1), ('creator_ref', 1), ('duration', -1)):
            identities = graph()
            identities['unrelated'][field] = value
            with self.subTest(field=field), self.assertRaises(plan.Inconclusive):
                plan.request(case(target='unrelated'), identities)


class Oracles(unittest.TestCase):
    def test_timestamp_only_positive_control_rejected(self):
        identities, c = graph(), case()
        record = evidence(c, identities)
        record['control']['after'] = copy.deepcopy(identities)
        record['control']['after']['child']['update_time'] = 'new'
        with self.assertRaises(plan.Inconclusive):
            plan.evaluate(c, identities, record)

    def test_wrong_request_invalid_controls_and_authentication_failures(self):
        identities, c = graph(), case()
        for field, value in (('request_sha256', 'wrong'), ('actor_baseline_status', 401),
                             ('status', 400), ('status', 401), ('status', 404), ('status', 500)):
            record = evidence(c, identities)
            record[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(plan.Inconclusive):
                plan.evaluate(c, identities, record)

    def test_unrelated_change_fails_granted_and_denied_cases(self):
        identities, c = graph(), case()
        for allowed in (False, True):
            record = evidence(c, identities, allowed)
            record['after']['unrelated']['update_time'] = 'unexpected'
            with self.assertRaises(plan.Inconclusive):
                plan.evaluate(c, identities, record)

    def test_duration_without_persisted_expiry_is_inconclusive(self):
        identities, c = graph(), case(target='issuer', variation='duration-never')
        record = evidence(c, identities, True)
        record['after']['issuer']['expires_at'] = identities['issuer']['expires_at']
        with self.assertRaises(plan.Inconclusive):
            plan.evaluate(c, identities, record)

    def test_refresh_requires_independent_old_and_new_credential_proofs(self):
        identities, c = graph(), case(operation='refresh', variation='secret')
        for allowed in (False, True):
            record = evidence(c, identities, allowed)
            if allowed:
                record['auth']['old_after'] = 200
            else:
                record['old_credential_after_status'] = 401
            with self.assertRaises(plan.Inconclusive):
                plan.evaluate(c, identities, record)


class Sessions(unittest.TestCase):
    def sample(self):
        return {'private_resource': True, 'anonymous_status': 401, 'same_request': True,
                'same_session_handle': True, 'baseline_status': 200, 'fresh_basic_before_status': 200,
                'subject_id': 4, 'boundary_subject_id': 4, 'boundary_verified': True,
                'fresh_basic_after_status': 401, 'minted_at': 10, 'boundary_at': 20,
                'expires_at': 100, 'clock_skew_seconds': 5,
                'probes': [{'at': 21, 'status': 200}, {'at': 105, 'status': 401}]}

    def test_basic_rejection_does_not_hide_surviving_bearer(self):
        c = case('session-subject', 'rotation:registry-bearer', 'session', 'independent-observer')
        result = plan.session_survival(c, self.sample())
        self.assertTrue(result['survival_observed'])
        self.assertTrue(result['observation_complete'])
        self.assertFalse(result['issuer_authority_accepted'])

    def test_missing_expiry_observation_stays_incomplete(self):
        c = case('issuer', 'disable:registry-bearer', 'session', 'independent-observer')
        sample = self.sample()
        sample['probes'] = [{'at': 21, 'status': 401}]
        self.assertFalse(plan.session_survival(c, sample)['observation_complete'])

    def test_token_usable_after_expiry_is_reported(self):
        c = case('child', 'expiry:api-session', 'session', 'independent-observer')
        sample = self.sample()
        sample['probes'][-1]['status'] = 200
        result = plan.session_survival(c, sample)
        self.assertTrue(result['usable_after_expiry'])
        self.assertFalse(result['observation_complete'])

    def test_public_unsupported_wrong_identity_and_failed_requests_are_inconclusive(self):
        c = case('issuer', 'rotation:registry-bearer', 'session', 'independent-observer')
        for field, value in (('anonymous_status', 200), ('baseline_status', 401),
                             ('boundary_subject_id', 99), ('fresh_basic_after_status', 200),
                             ('probes', [{'at': 21, 'status': 500}])):
            sample = self.sample()
            sample[field] = value
            with self.subTest(field=field), self.assertRaises(plan.Inconclusive):
                plan.session_survival(c, sample)


if __name__ == '__main__':
    unittest.main()
