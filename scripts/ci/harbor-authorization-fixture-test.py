#!/usr/bin/env python3
"""Offline runner tests: never start Harbor or execute a server fixture."""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('authorization_fixture', ROOT / 'scripts/harbor-authorization-fixture.py')
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
spec.loader.exec_module(fixture)


def response(status=200, value=None, headers=None):
    return fixture.Reply(status, headers or {}, json.dumps(value).encode())


class Gates(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(fixture.CONFIG.read_text())

    def test_default_is_offline(self):
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/harbor-authorization-fixture.py')],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no credentials read', result.stdout)

    def test_execute_stops_before_credentials_and_network(self):
        with patch.object(sys, 'argv', ['fixture', '--execute']), \
                patch.object(fixture, 'private_json') as credential, \
                patch.object(fixture, 'Transport') as transport:
            self.assertEqual(fixture.main(), 1)
            credential.assert_not_called()
            transport.assert_not_called()

    def test_non_fixture_destinations_rejected(self):
        for endpoint in ('http://127.0.0.1:8443', 'https://harbor.stinkyboi.com',
                         'https://localhost:8443', 'https://127.0.0.1:443'):
            config = dict(self.config, endpoint=endpoint)
            with self.subTest(endpoint=endpoint), self.assertRaises(fixture.Failure):
                fixture.validate_config(config)

    def test_wrong_versions_and_scope_rejected(self):
        for key, value in (('chart_version', 'latest'), ('harbor_version', 'v2.14.0'),
                           ('pagination_size', 1), ('projects', {'homelab': True})):
            with self.subTest(key=key), self.assertRaises(fixture.Failure):
                fixture.validate_config(dict(self.config, **{key: value}))

    def test_missing_environment_record_rejected(self):
        config = dict(self.config, execution_enabled=True, decision='HOME-99')
        with patch.object(fixture.subprocess, 'check_output', side_effect=['a' * 40, '']):
            with self.assertRaisesRegex(fixture.Failure, 'environment record'):
                fixture.preflight(config, 'a' * 40)

    def test_dirty_or_wrong_revision_rejected(self):
        config = dict(self.config, execution_enabled=True, decision='HOME-99')
        for head, dirty in (('b' * 40, ''), ('a' * 40, ' M config')):
            with patch.object(fixture.subprocess, 'check_output', side_effect=[head, dirty]):
                with self.assertRaisesRegex(fixture.Failure, 'clean revision'):
                    fixture.preflight(config, 'a' * 40)

    def test_environment_pin_and_disposal_window(self):
        lock = json.loads(fixture.LOCK.read_text())
        record = {'isolated': True, 'production_routes': False, 'synthetic_only': True,
                  'empty_instance': True, 'owner': 'fixture-owner', 'chart_version': '1.19.2',
                  'chart_sha256': lock['chart_sha256'], 'images': lock['images'],
                  'ca_sha256': 'sha256:' + 'a' * 64,
                  'destroy_deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        config = dict(self.config, execution_enabled=True, decision='HOME-99', environment_record=record)
        with patch.object(fixture.subprocess, 'check_output', side_effect=['a' * 40, '']):
            fixture.preflight(config, 'a' * 40)
        for key, value in (('production_routes', True), ('images', {}),
                           ('chart_sha256', 'sha256:' + 'b' * 64),
                           ('destroy_deadline_utc', '2000-01-01T00:00:00Z')):
            changed = copy.deepcopy(config)
            changed['environment_record'][key] = value
            with patch.object(fixture.subprocess, 'check_output', side_effect=['a' * 40, '']):
                with self.subTest(key=key), self.assertRaises(fixture.Failure):
                    fixture.preflight(changed, 'a' * 40)

    def test_permissions_allow_reordering_but_not_extra_or_denied_grants(self):
        permissions = json.loads(fixture.PAYLOAD.read_text())['permissions']
        reordered = copy.deepcopy(permissions[::-1])
        for permission in reordered:
            permission['access'].reverse()
        self.assertEqual(fixture.normalized_permissions(permissions), fixture.normalized_permissions(reordered))
        expanded = copy.deepcopy(permissions)
        expanded[0]['access'].append({'resource': 'repository', 'action': 'delete'})
        self.assertNotEqual(fixture.normalized_permissions(permissions), fixture.normalized_permissions(expanded))
        permissions[0]['access'][0]['effect'] = 'deny'
        with self.assertRaises(fixture.Failure):
            fixture.normalized_permissions(permissions)

    def test_private_file_mode_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'admin.json'
            path.write_text(json.dumps({'username': 'admin', 'password': 'synthetic-only'}))
            path.chmod(0o644)
            with self.assertRaises(fixture.Failure):
                fixture.private_json(path)
            path.chmod(0o600)
            self.assertEqual(fixture.private_json(path)['username'], 'admin')
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(fixture.Failure):
                fixture.private_json(link)

    def test_fixture_is_deterministic_and_contains_no_layers(self):
        config, manifest = fixture.fixture_image(1)
        self.assertEqual(fixture.fixture_image(1), (config, manifest))
        self.assertNotEqual(fixture.fixture_image(2), (config, manifest))
        parsed = json.loads(manifest)
        self.assertEqual(parsed['layers'], [])
        self.assertEqual(parsed['config']['digest'], fixture.digest(config))
        self.assertEqual(parsed['config']['size'], len(config))


class Denials(unittest.TestCase):
    @staticmethod
    def requested_value(before, after, _):
        fixture.updated_record([before], [after], 1, {'v': 2})

    def test_only_real_authorization_status_and_code_accepted(self):
        for status in (200, 201, 301, 400, 401, 404, 405, 409, 500):
            with self.subTest(status=status), self.assertRaises(fixture.Failure):
                fixture.denied(response(status, {'errors': [{'code': 'FORBIDDEN'}]}))
        for value in ({}, {'errors': []}, {'errors': [{'code': 'NOT_FOUND'}]}):
            with self.assertRaises(fixture.Failure):
                fixture.denied(response(403, value))
        fixture.denied(response(403, {'errors': [{'code': 'FORBIDDEN'}]}))
        fixture.denied(response(401, {'errors': [{'code': 'UNAUTHORIZED'}]}), registry=True)

    def suite(self, replies):
        suite = fixture.Suite(MagicMock(), {}, {'username': 'admin'})
        suite.robot = {'username': 'robot'}
        suite.identity_control = MagicMock()
        suite.api = MagicMock(side_effect=replies)
        return suite

    def test_denial_and_positive_control_use_identical_request(self):
        suite = self.suite([response(403, {'errors': [{'code': 'FORBIDDEN'}]}), response(200)])
        observer = MagicMock(side_effect=[{'id': 1, 'v': 1}, {'id': 1, 'v': 1}, {'id': 1, 'v': 2}])
        suite.mutation('update', 'PUT', '/target', {'v': 2}, observer, 200, self.requested_value)
        first, second = suite.api.call_args_list
        self.assertEqual(first.args[:2], second.args[:2])
        self.assertEqual(first.args[3], second.args[3])
        self.assertEqual(first.args[2], suite.robot)
        self.assertEqual(second.args[2], suite.admin)
        self.assertEqual(suite.results, [{'case': 'update', 'result': 'pass'}])

    def test_denied_mutation_with_side_effect_fails_before_positive_control(self):
        suite = self.suite([response(403, {'errors': [{'code': 'FORBIDDEN'}]})])
        with self.assertRaisesRegex(fixture.Failure, 'changed fixture state'):
            suite.mutation('update', 'PUT', '/target', {}, MagicMock(side_effect=[1, 2]), 200, self.requested_value)
        self.assertEqual(suite.api.call_count, 1)
        self.assertFalse(suite.results)

    def test_invalid_positive_control_cannot_pass(self):
        suite = self.suite([response(403, {'errors': [{'code': 'FORBIDDEN'}]}), response(400)])
        with self.assertRaises(fixture.Failure):
            suite.mutation('update', 'PUT', '/target', {}, lambda: 1, 200, self.requested_value)
        self.assertFalse(suite.results)

    def test_positive_status_without_state_change_cannot_pass(self):
        suite = self.suite([response(403, {'errors': [{'code': 'FORBIDDEN'}]}), response(200)])
        with self.assertRaisesRegex(fixture.Failure, 'Requested field absent'):
            suite.mutation('update', 'PUT', '/target', {}, lambda: {'id': 1, 'v': 1}, 200, self.requested_value)
        self.assertFalse(suite.results)

    def test_timestamp_only_repository_update_false_positive(self):
        suite = self.suite([response(403, {'errors': [{'code': 'FORBIDDEN'}]}), response(200)])
        before = [{'id': 7, 'description': 'old', 'update_time': 'before'}]
        after = [{'id': 7, 'description': 'old', 'update_time': 'after'}]
        with self.assertRaisesRegex(fixture.Failure, 'Requested field absent'):
            suite.mutation('repo-update', 'PUT', '/repository', {'description': 'qa-mutated'},
                           MagicMock(side_effect=[before, before, after]), 200,
                           lambda old, new, _: fixture.updated_record(old, new, 7, {'description': 'qa-mutated'}))
        self.assertFalse(suite.results)


class Postconditions(unittest.TestCase):
    def test_requested_description_and_only_target_timestamp_can_change(self):
        before = [{'id': 1, 'description': 'old', 'update_time': 'a'}, {'id': 2, 'description': 'other'}]
        after = [{'id': 1, 'description': 'new', 'update_time': 'b'}, {'id': 2, 'description': 'other'}]
        fixture.updated_record(before, after, 1, {'description': 'new'})
        for extra in ('description', 'update_time'):
            corrupted = copy.deepcopy(after)
            corrupted[1][extra] = 'unrelated change'
            with self.assertRaisesRegex(fixture.Failure, 'Unrelated'):
                fixture.updated_record(before, corrupted, 1, {'description': 'new'})

    def test_target_identity_or_unrequested_field_change_fails(self):
        before = [{'id': 1, 'description': 'old', 'name': 'original'}]
        for after in ([{'id': 2, 'description': 'new', 'name': 'original'}],
                      [{'id': 1, 'description': 'new', 'name': 'renamed'}]):
            with self.assertRaises(fixture.Failure):
                fixture.updated_record(before, after, 1, {'description': 'new'})

    def test_exact_delete_and_unrelated_preservation(self):
        before = [{'id': 1, 'digest': 'a'}, {'id': 2, 'digest': 'b'}]
        fixture.deleted_record(before, [before[1]], 'a', key='digest')
        for after in (before, [before[0]], [], [dict(before[1], update_time='changed')]):
            with self.assertRaises(fixture.Failure):
                fixture.deleted_record(before, after, 'a', key='digest')

    def test_creation_requires_exact_name_id_and_no_unrelated_changes(self):
        before = [{'id': 1, 'name': 'existing'}]
        after = before + [{'id': 2, 'name': 'qa-new-tag'}]
        fixture.created_record(before, after, {'name': 'qa-new-tag'}, 2)
        for invalid in (before + [{'id': 2, 'name': 'wrong'}],
                        [dict(before[0], update_time='changed'), after[1]],
                        after + [{'id': 3, 'name': 'extra'}]):
            with self.assertRaises(fixture.Failure):
                fixture.created_record(before, invalid, {'name': 'qa-new-tag'}, 2)
        with self.assertRaises(fixture.Failure):
            fixture.created_record(before, after, {'name': 'qa-new-tag'}, 99)

    def test_permission_postcondition_rejects_timestamp_only_or_extra_grants(self):
        original = json.loads(fixture.PAYLOAD.read_text())['permissions']
        requested = copy.deepcopy(original)
        requested[0]['access'].append({'resource': 'repository', 'action': 'delete', 'effect': 'allow'})
        before = [{'id': 1, 'permissions': original, 'duration': 30}]
        for permissions in (original, requested + [original[0]]):
            after = [{'id': 1, 'permissions': permissions, 'duration': 30, 'update_time': 'new'}]
            with self.assertRaises(fixture.Failure):
                fixture.updated_record(before, after, 1, {'permissions': requested})
        fixture.updated_record(before, [{'id': 1, 'permissions': requested, 'duration': 30}],
                               1, {'permissions': requested})

    def test_created_robot_requires_actual_expiry_not_only_duration_field(self):
        expected = dict(json.loads(fixture.PAYLOAD.read_text()), name='robot$qa-control-created')
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expires = int(created_at.timestamp()) + 30 * 86400
        actual = dict(expected, id=9, creation_time=created_at.isoformat(), expires_at=expires)
        fixture.created_robot([], [actual], expected, response(201, {'id': 9, 'expires_at': expires}))
        with self.assertRaisesRegex(fixture.Failure, 'expiry differs'):
            fixture.created_robot([], [dict(actual, expires_at=-1)], expected,
                                  response(201, {'id': 9, 'expires_at': -1}))


class Protocol(unittest.TestCase):
    def test_pagination_detects_duplicates_changed_totals_and_empty_pages(self):
        for pages in (([{'id': 1}], [{'id': 1}], '2'),
                      ([{'id': 1}], [{'id': 2}], '3'),
                      ([{'id': 1}], [], '2')):
            suite = fixture.Suite(MagicMock(), {}, {})
            suite.api = MagicMock(side_effect=[response(200, pages[0], {'x-total-count': '2'}),
                                               response(200, pages[1], {'x-total-count': pages[2]})])
            with self.assertRaises(fixture.Failure):
                suite.pages('/projects', {})

    def test_pagination_reads_second_page(self):
        suite = fixture.Suite(MagicMock(), {}, {})
        suite.api = MagicMock(side_effect=[response(200, [{'id': 1}], {'x-total-count': '2'}),
                                           response(200, [{'id': 2}], {'x-total-count': '2'})])
        self.assertEqual(len(suite.pages('/projects', {})), 2)
        self.assertIn('page=2&page_size=100', suite.api.call_args.args[1])
        self.assertEqual(fixture.encoded('nested/seed'), 'nested%252Fseed')

    def test_registry_does_not_treat_token_200_as_permission(self):
        net = MagicMock()
        net.request.side_effect = [response(401, headers={'www-authenticate':
            'Bearer realm="https://127.0.0.1:8443/service/token",service="harbor-registry"'}),
            response(200, {'token': 'synthetic-token'}), response(401, {'errors': [{'code': 'UNAUTHORIZED'}]})]
        suite = fixture.Suite(net, {'endpoint': 'https://127.0.0.1:8443'}, {})
        actual = suite.registry('GET', '/v2/homelab/test/manifests/fixture', {}, 'homelab/test', 'pull')
        fixture.denied(actual, registry=True)
        self.assertEqual(net.request.call_count, 3)
        self.assertEqual(net.request.call_args.kwargs['bearer'], 'synthetic-token')

    def test_registry_external_realm_rejected_before_credentials(self):
        net = MagicMock()
        net.request.return_value = response(401, headers={'www-authenticate':
            'Bearer realm="https://example.invalid/service/token",service="harbor-registry"'})
        suite = fixture.Suite(net, {'endpoint': 'https://127.0.0.1:8443'}, {})
        with self.assertRaises(fixture.Failure):
            suite.registry('GET', '/v2/test/manifests/latest', {}, 'test', 'pull')
        self.assertEqual(net.request.call_count, 1)

    def test_upload_locations_refuse_external_or_non_registry_paths(self):
        transport = object.__new__(fixture.Transport)
        for location in ('https://example.invalid/v2/x', 'http://127.0.0.1:8443/v2/x',
                         '//example.invalid/v2/x', '/api/v2.0/robots', '/v2/x#fragment',
                         'https://user:password@127.0.0.1:8443/v2/x'):
            with self.subTest(location=location), self.assertRaises(fixture.Failure):
                transport.location(location)
        self.assertEqual(transport.location('https://127.0.0.1:8443/v2/x?state=opaque'), '/v2/x?state=opaque')

    def test_transport_redirect_and_errors_are_sanitized(self):
        transport = object.__new__(fixture.Transport)
        transport.deadline = float('inf')
        transport.context = MagicMock()
        for status in (301, 302, 303, 307, 308):
            with patch.object(fixture.http.client, 'HTTPSConnection') as connection:
                connection.return_value.getresponse.return_value.status = status
                connection.return_value.getresponse.return_value.read.return_value = b''
                with self.assertRaisesRegex(fixture.Failure, 'Redirect rejected'):
                    transport.request('GET', '/api/v2.0/robots')
                self.assertEqual(connection.return_value.request.call_count, 1)
        with patch.object(fixture.http.client, 'HTTPSConnection') as connection:
            connection.return_value.request.side_effect = OSError('private-secret')
            with self.assertRaisesRegex(fixture.Failure, '^Fixture transport failed; no retries$'):
                transport.request('GET', '/api/v2.0/robots')
            connection.return_value.close.assert_called_once()

    def test_remaining_gates_prevent_overall_pass(self):
        config = json.loads(fixture.CONFIG.read_text())
        suite = fixture.Suite(MagicMock(), config, {})
        with patch.multiple(suite, setup=MagicMock(), read_cases=MagicMock(),
                            registry_cases=MagicMock(), write_cases=MagicMock(), disabled_case=MagicMock()):
            self.assertEqual(suite.run()['overall_acceptance'], 'incomplete')
            self.assertTrue(suite.run()['not_run'])


class RegistryStateMachine(unittest.TestCase):
    """Exercise upload sequencing and assertions, not Harbor's authorizer."""

    def suite(self, tamper=False):
        suite = fixture.Suite(object.__new__(fixture.Transport), {}, 'administrator')
        suite.robot = 'collector'
        suite.identity_control = MagicMock()
        config, manifest = fixture.fixture_image(100)
        blobs = {p + '/nested/seed': {fixture.digest(config): config} for p in ('homelab', 'mirror')}
        tags = {p: ['fixture-100'] for p in ('homelab', 'mirror')}
        sessions = {}

        def pages(path, _credential):
            project = path.split('/')[2]
            observed_tags = [{'id': i, 'name': tag, 'artifact_id': 1, 'repository_id': 10}
                             for i, tag in enumerate(tags[project])]
            if path.endswith('/tags'):
                return observed_tags
            return [{'id': 1, 'repository_id': 10, 'digest': fixture.digest(manifest), 'tags': observed_tags}]

        def registry(method, path, credential, repository, _action, body=None, _media=None):
            project = repository.split('/')[0]
            if credential == 'collector' and method != 'GET':
                if tamper and method == 'PATCH':
                    sessions[repository]['body'] += b'x'
                return response(401, {'errors': [{'code': 'UNAUTHORIZED'}]})
            if credential == 'collector' and project == 'homelab':
                return response(401, {'errors': [{'code': 'UNAUTHORIZED'}]})
            if '/blobs/uploads/' in path:
                if method == 'POST':
                    sessions[repository] = {'body': b'', 'version': 0}
                    return response(202, headers={'location': f'/v2/{repository}/blobs/uploads/id?state=0'})
                state = sessions[repository]
                if method == 'GET':
                    return response(204, headers={'range': f'0-{max(0, len(state["body"])-1)}'})
                self.assertIn(f'state={state["version"]}', path)
                if method == 'PATCH':
                    state['body'] += body
                    state['version'] += 1
                    return response(202, headers={'range': f'0-{len(state["body"])-1}',
                        'location': f'/v2/{repository}/blobs/uploads/id?state={state["version"]}'})
                self.assertEqual(method, 'PUT')
                blobs[repository][fixture.digest(state['body'])] = state['body']
                return response(201)
            if '/blobs/' in path:
                value = blobs[repository].get(path.split('/blobs/')[1])
                return fixture.Reply(200 if value else 404, {}, value or b'{}')
            if method == 'GET':
                return fixture.Reply(200, {}, manifest)
            self.assertEqual(method, 'PUT')
            tags[project].append('qa-denied')
            return response(201)

        suite.pages = pages
        suite.registry = registry
        return suite

    def test_registry_controls_use_latest_upload_location_and_observe_bytes(self):
        suite = self.suite()
        suite.registry_cases()
        self.assertEqual(len(suite.results), 12)

    def test_denied_append_with_side_effect_cannot_pass(self):
        with self.assertRaisesRegex(fixture.Failure, 'changed offset'):
            self.suite(tamper=True).registry_cases()


if __name__ == '__main__':
    unittest.main()
