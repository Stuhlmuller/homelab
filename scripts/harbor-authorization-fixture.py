#!/usr/bin/env python3
"""HOME-57 disposable Harbor fixture proposal. Default: offline check only.

Execution is disabled in committed configuration. This is not a deployment
tool: a separately approved, empty, pinned server must already exist.
Never point this runner at production or forward a production service to it.
"""

import argparse
import base64
import copy
import hashlib
import http.client
import json
import os
import re
import ssl
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'scripts/config/harbor-authorization-fixture.json'
PAYLOAD = ROOT / 'clusters/homelab/apps/harbor/vulnerability-robot.json'
LOCK = ROOT / 'scripts/fixtures/harbor-authorization/lock.json'
API = '/api/v2.0'
MANIFEST_TYPE = 'application/vnd.oci.image.manifest.v1+json'
CONFIG_TYPE = 'application/vnd.oci.image.config.v1+json'
MAX_BYTES = 4 * 1024 * 1024


class Failure(Exception):
    """Only fixed, credential-free diagnostics may escape this boundary."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def encoded(value):
    return quote(quote(value, safe=''), safe='')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def normalized_permissions(permissions):
    result = copy.deepcopy(permissions)
    for permission in result:
        for access in permission['access']:
            access.setdefault('effect', 'allow')
            require(access['effect'] == 'allow', 'Unexpected permission effect')
        permission['access'].sort(key=lambda item: (item['resource'], item['action']))
    return sorted(result, key=lambda item: (item['kind'], item['namespace']))


def indexed(records, key='id'):
    require(isinstance(records, list), 'Invalid observation collection')
    result = {item[key]: item for item in records}
    require(len(result) == len(records), 'Duplicate observed identity')
    return result


def fields_equal(record, expected):
    for key, value in expected.items():
        actual = record.get(key)
        if key == 'permissions':
            require(normalized_permissions(actual) == normalized_permissions(value),
                    'Requested permissions absent from readback')
        else:
            require(actual == value, 'Requested field absent from readback')


def updated_record(before, after, identifier, expected, key='id'):
    """Prove the specific mutation, preserving all unrelated observed records."""
    old, new = indexed(before, key), indexed(after, key)
    require(old.keys() == new.keys() and identifier in old, 'Updated identity set changed')
    fields_equal(new[identifier], expected)
    require(any((normalized_permissions(old[identifier][k]) != normalized_permissions(new[identifier][k]))
                if k == 'permissions' else old[identifier].get(k) != new[identifier].get(k) for k in expected),
            'Requested mutation was already present')
    require({k: v for k, v in old.items() if k != identifier} ==
            {k: v for k, v in new.items() if k != identifier}, 'Unrelated observed record changed')
    # Only the target's update timestamp may change as a server side effect.
    allowed = set(expected) | {'update_time'}
    require({k: v for k, v in old[identifier].items() if k not in allowed} ==
            {k: v for k, v in new[identifier].items() if k not in allowed},
            'Unrequested target field changed')


def deleted_record(before, after, identifier, key='id'):
    old, new = indexed(before, key), indexed(after, key)
    require(identifier in old and identifier not in new, 'Exact deleted identity remains or never existed')
    require({k: v for k, v in old.items() if k != identifier} == new,
            'Deletion changed unrelated observed records')


def created_record(before, after, expected, identifier=None, key='id'):
    old, new = indexed(before, key), indexed(after, key)
    added = new.keys() - old.keys()
    require(len(added) == 1 and old.keys() <= new.keys(), 'Creation identity delta is not exactly one')
    actual_id = next(iter(added))
    require(identifier is None or actual_id == identifier, 'Create response identity differs from readback')
    require({k: new[k] for k in old} == old, 'Creation changed unrelated observed records')
    fields_equal(new[actual_id], expected)
    return actual_id


def created_robot(before, after, expected, reply):
    response = reply.json()
    identifier = created_record(before, after, expected, response['id'])
    actual = indexed(after)[identifier]
    created = datetime.fromisoformat(actual['creation_time'].replace('Z', '+00:00'))
    require(created.tzinfo is not None, 'Robot creation time missing timezone')
    expires = int(created.timestamp()) + expected['duration'] * 86400
    require(actual['expires_at'] == expires and response['expires_at'] == expires,
            'Created robot expiry differs from requested lifetime')


def fixture_image(index):
    """A deterministic, layer-free OCI image; no real workload or data."""
    config = canonical({'architecture': 'amd64', 'os': 'linux',
                        'config': {'Labels': {'home57.synthetic': str(index)}},
                        'rootfs': {'type': 'layers', 'diff_ids': []}})
    manifest = canonical({'schemaVersion': 2, 'mediaType': MANIFEST_TYPE,
                          'config': {'mediaType': CONFIG_TYPE, 'size': len(config),
                                     'digest': digest(config)}, 'layers': []})
    return config, manifest


def validate_config(config):
    lock = json.loads(LOCK.read_text())
    require(config['schema'] == 1 and config['chart_version'] == '1.19.2'
            and config['harbor_version'] == 'v2.15.2', 'Unexpected fixture version')
    require(lock['chart_version'] == config['chart_version']
            and lock['harbor_version'] == config['harbor_version'], 'Fixture lock version mismatch')
    require(config['endpoint'] == 'https://127.0.0.1:8443', 'Non-fixture endpoint rejected')
    require(config['projects'] == {'homelab': False, 'mirror': True,
                                  'qa-private-other': False, 'qa-public-other': True},
            'Unexpected project contract')
    require(config['pagination_size'] == 101 and config['timeout_seconds'] == 15
            and config['deadline_seconds'] == 1200, 'Unexpected fixture bounds')
    payload = json.loads(PAYLOAD.read_text())
    require(payload['name'] == 'vulnerability-exporter' and payload['level'] == 'system'
            and payload['duration'] == 30 and payload['disable'] is False,
            'Unexpected robot identity')
    require(payload['permissions'] == [
        {'kind': 'project', 'namespace': p, 'access': [
            {'resource': 'repository', 'action': 'list', 'effect': 'allow'},
            {'resource': 'artifact', 'action': 'list', 'effect': 'allow'}]} for p in ('homelab', 'mirror')],
        'Unexpected robot scope')
    return payload


def preflight(config, expected_sha):
    """All gates run before reading credentials or creating a connection."""
    validate_config(config)
    require(config['execution_enabled'] is True, 'Server fixture execution is disabled')
    require(re.fullmatch(r'HOME-[0-9]+', config['decision'] or '') is not None,
            'Missing delegated execution decision')
    require(re.fullmatch(r'[0-9a-f]{40}', expected_sha or '') is not None,
            'Exact reviewed revision required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    require(head == expected_sha and not dirty, 'Reviewed clean revision required')
    record = config['environment_record']
    require(isinstance(record, dict), 'Missing disposable environment record')
    require(record.get('isolated') is True and record.get('production_routes') is False
            and record.get('synthetic_only') is True and record.get('empty_instance') is True,
            'Environment isolation not accepted')
    lock = json.loads(LOCK.read_text())
    require(record.get('chart_version') == config['chart_version']
            and record.get('chart_sha256') == lock['chart_sha256']
            and re.fullmatch(r'sha256:[0-9a-f]{64}', record.get('ca_sha256', '')),
            'Missing chart or CA digest')
    images = record.get('images', {})
    require(images == lock['images']
            and all(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', v) for v in images.values()),
            'Missing immutable server image inventory')
    require(isinstance(record.get('destroy_deadline_utc'), str)
            and isinstance(record.get('owner'), str) and bool(record['owner']),
            'Missing environment owner or disposal deadline')
    try:
        disposal = datetime.fromisoformat(record['destroy_deadline_utc'].replace('Z', '+00:00'))
        remaining = (disposal - datetime.now(timezone.utc)).total_seconds()
    except (ValueError, TypeError):
        raise Failure('Invalid disposal deadline') from None
    require(25 * 60 <= remaining <= 4 * 3600, 'Disposal deadline outside approved run window')


def private_json(path):
    require(not path.is_symlink(), 'Credential symlink rejected')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600, 'Credential file must be private mode 0600')
    data = json.loads(path.read_text())
    require(set(data) == {'username', 'password'} and data['username'] == 'admin'
            and isinstance(data['password'], str) and bool(data['password']),
            'Invalid disposable administrator credential contract')
    return data


@dataclass
class Reply:
    status: int
    headers: dict
    body: bytes

    def json(self):
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeError):
            raise Failure('Invalid server JSON') from None


class Transport:
    """Fixed loopback TLS destination; no DNS, proxies, redirects or retries."""

    def __init__(self, config, ca_file):
        self.config = config
        self.deadline = time.monotonic() + config['deadline_seconds']
        require(digest(ca_file.read_bytes()) == config['environment_record']['ca_sha256'],
                'Fixture CA digest mismatch')
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def request(self, method, path, credential=None, body=None, media='application/json', bearer=None):
        require(time.monotonic() < self.deadline, 'Fixture deadline reached')
        require(path.startswith(('/api/v2.0/', '/v2/', '/service/token'))
                and not any(x in path for x in ('\r', '\n', '#', '\\')),
                'Non-fixture request path rejected')
        headers = {'Accept': media}
        if credential:
            raw = (credential['username'] + ':' + credential['password']).encode()
            headers['Authorization'] = 'Basic ' + base64.b64encode(raw).decode()
        if bearer:
            headers['Authorization'] = 'Bearer ' + bearer
        if body is not None:
            body = body if isinstance(body, bytes) else canonical(body)
            headers['Content-Type'] = media
        conn = http.client.HTTPSConnection('127.0.0.1', 8443, timeout=15, context=self.context)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            content = response.read(MAX_BYTES + 1)
            require(len(content) <= MAX_BYTES, 'Oversized server response')
            require(not 300 <= response.status < 400, 'Redirect rejected')
            return Reply(response.status, {k.lower(): v for k, v in response.getheaders()}, content)
        except (OSError, http.client.HTTPException):
            raise Failure('Fixture transport failed; no retries') from None
        finally:
            conn.close()

    def location(self, value):
        parsed = urlsplit(value)
        require(not parsed.fragment and not parsed.username and not parsed.password,
                'Invalid registry location')
        require(not parsed.netloc or (parsed.scheme == 'https' and parsed.netloc == '127.0.0.1:8443'),
                'Cross-origin registry location rejected')
        require(parsed.path.startswith('/v2/'), 'Non-registry location rejected')
        return parsed.path + ('?' + parsed.query if parsed.query else '')


def expect(reply, status):
    require(reply.status == status, 'Unexpected HTTP status; case inconclusive or failed')
    return reply


def denied(reply, registry=False):
    require(reply.status in ((401, 403) if registry else (403,)),
            'Expected authorization denial absent')
    errors = reply.json().get('errors', [])
    allowed = {'DENIED', 'UNAUTHORIZED'} if registry else {'FORBIDDEN', 'DENIED'}
    require(bool(errors) and all(e.get('code') in allowed for e in errors),
            'Missing Harbor/registry authorization error code')


class Suite:
    def __init__(self, transport, config, admin):
        self.net, self.config, self.admin = transport, config, admin
        self.robot = None
        self.robot_id = None
        self.results = []
        self.digests = {}

    def api(self, method, path, credential, body=None):
        return self.net.request(method, API + path, credential, body)

    def admin_json(self, path):
        return expect(self.api('GET', path, self.admin), 200).json()

    def pages(self, path, credential):
        records, ids, total = [], set(), None
        for page in range(1, 21):
            separator = '&' if '?' in path else '?'
            response = expect(self.api('GET', f'{path}{separator}sort=id&page={page}&page_size=100',
                                       credential), 200)
            batch = response.json()
            count = int(response.headers['x-total-count'])
            require(total is None or count == total, 'Pagination total changed')
            total = count
            require(isinstance(batch, list) and len(batch) <= 100, 'Invalid page')
            for item in batch:
                identity = item.get('id', item.get('project_id'))
                require(identity is not None and identity not in ids, 'Duplicate page identity')
                ids.add(identity)
                records.append(item)
            if len(records) == total:
                return records
            require(bool(batch) and len(records) < total, 'Incomplete page')
        raise Failure('Pagination bound exceeded')

    def registry(self, method, path, credential, repository, action, body=None, media=MANIFEST_TYPE):
        # Challenge must come from the fixed fixture, never a caller-supplied realm.
        challenge = self.net.request('GET', '/v2/')
        expect(challenge, 401)
        header = challenge.headers.get('www-authenticate', '')
        match = re.fullmatch(r'Bearer realm="([^"]+)",service="([^"]+)"(?:,scope="[^"]*")?', header)
        require(match is not None, 'Unsupported registry challenge')
        require(match[1] == self.config['endpoint'] + '/service/token'
                and match[2] == 'harbor-registry', 'Unexpected registry token authority')
        token = self.net.request('GET', '/service/token?' + urlencode({
            'service': match[2], 'scope': f'repository:{repository}:{action}'}), credential)
        if token.status != 200:
            return token
        value = token.json().get('token') or token.json().get('access_token')
        require(isinstance(value, str) and bool(value), 'Missing registry token')
        return self.net.request(method, path, body=body, media=media, bearer=value)

    def seed_image(self, repository, index):
        config, manifest = fixture_image(index)
        response = expect(self.registry('POST', f'/v2/{repository}/blobs/uploads/',
                                        self.admin, repository, 'pull,push'), 202)
        location = self.net.location(response.headers['location'])
        separator = '&' if '?' in location else '?'
        expect(self.registry('PUT', location + separator + urlencode({'digest': digest(config)}),
                             self.admin, repository, 'pull,push', config,
                             'application/octet-stream'), 201)
        expect(self.registry('PUT', f'/v2/{repository}/manifests/fixture-{index}',
                             self.admin, repository, 'pull,push', manifest), 201)
        self.digests[repository] = digest(manifest)

    def setup(self):
        info = self.admin_json('/systeminfo')
        require(info.get('harbor_version') == self.config['harbor_version'], 'Server version mismatch')
        projects = self.pages('/projects', self.admin)
        require(all(p['name'] == 'library' for p in projects), 'Nonempty server rejected')
        require(not self.pages('/repositories', self.admin) and not self.pages('/robots', self.admin),
                'Existing repositories or robots rejected')
        for project, public in self.config['projects'].items():
            expect(self.api('POST', '/projects', self.admin, {
                'project_name': project, 'metadata': {'public': str(public).lower(),
                                                     'auto_scan': 'false'}}), 201)
            # Ordinary projects deliberately separate authorization from proxy-cache 405s.
            self.seed_image(project + '/nested/seed', 0)
        for project in ('homelab', 'mirror'):
            for index in range(101):
                self.seed_image(f'{project}/page-{index:03d}', index)
                if index:
                    self.seed_image(project + '/nested/seed', index)
        payload = validate_config(self.config)
        created = expect(self.api('POST', '/robots', self.admin, payload), 201).json()
        self.robot_id = created['id']
        require(isinstance(self.robot_id, int) and self.robot_id > 0
                and created['name'] == 'robot$vulnerability-exporter', 'Robot identity mismatch')
        self.robot = {'username': created['name'], 'password': created['secret']}
        current = self.admin_json(f'/robots/{self.robot_id}')
        require(current['id'] == self.robot_id and current['name'] == self.robot['username']
                and current['level'] == 'system' and current['disable'] is False
                and current['duration'] == 30, 'Robot contract mismatch')
        # Normalize only the default effect, never drop extra scopes or fields.
        require(normalized_permissions(current['permissions']) == normalized_permissions(payload['permissions']),
                'Effective robot permissions mismatch')
        remaining = current['expires_at'] - time.time()
        require(29 * 86400 < remaining <= 30 * 86400 + 60, 'Robot expiry mismatch')

    def identity_control(self):
        expect(self.api('GET', '/projects/homelab/repositories?page=1&page_size=100', self.robot), 200)

    def record(self, name):
        self.results.append({'case': name, 'result': 'pass'})

    def read_cases(self):
        for project in ('homelab', 'mirror'):
            path = f'/projects/{project}/repositories'
            expected = self.pages(path, self.admin)
            actual = self.pages(path, self.robot)
            require({r['name'] for r in actual} == {r['name'] for r in expected}
                    and len(actual) == 102, 'Repository read oracle mismatch')
            path += '/' + encoded('nested/seed') + '/artifacts?with_scan_overview=true&with_tag=false'
            expected = self.pages(path, self.admin)
            actual = self.pages(path, self.robot)
            require({a['digest'] for a in actual} == {a['digest'] for a in expected}
                    and len(actual) == 101, 'Artifact read oracle mismatch')
            self.record(project + '-paginated-reads')
        for suffix in ('', '/' + encoded('nested/seed') + '/artifacts'):
            path = '/projects/qa-private-other/repositories' + suffix
            expect(self.api('GET', path, self.admin), 200)
            self.identity_control()
            denied(self.api('GET', path, self.robot))
            anonymous = self.api('GET', path, None)
            require(anonymous.status in (401, 403), 'Private fixture is anonymously readable')
            public = path.replace('qa-private-other', 'qa-public-other')
            expect(self.api('GET', public, None), 200)
            expect(self.api('GET', public, self.robot), 200)
            self.record('private-cross-project-' + ('artifacts' if suffix else 'repositories'))
        for path, key in (('/projects', 'name'), ('/repositories', 'name')):
            records = self.pages(path, self.robot)
            require(not any(r[key].split('/')[0] == 'qa-private-other' for r in records),
                    'Private data exposed through global listing')
            self.record('filtered-' + path[1:])
        for path in ('/configurations', '/users'):
            expect(self.api('GET', path, self.admin), 200)
            self.identity_control()
            denied(self.api('GET', path, self.robot))
            self.record('admin-read-' + path[1:])

    def mutation(self, name, method, path, body, observe, positive_status, postcondition):
        """Denied request first, identical authorized request second on same target."""
        before = copy.deepcopy(observe())
        self.identity_control()
        denied(self.api(method, path, self.robot, body))
        require(observe() == before, 'Denied mutation changed fixture state')
        control = expect(self.api(method, path, self.admin, body), positive_status)
        postcondition(before, observe(), control)
        self.record(name)

    def write_cases(self):
        for project in ('homelab', 'mirror'):
            base = f'/projects/{project}/repositories/'
            # Dedicated targets ensure deletes cannot invalidate later cases.
            path = base + 'page-000'
            repository_id = self.admin_json(path)['id']
            self.mutation(project + '-repository-update', 'PUT', path,
                          {'description': 'qa-mutated'},
                          lambda: self.pages(f'/projects/{project}/repositories', self.admin), 200,
                          lambda old, new, _: updated_record(old, new, repository_id, {'description': 'qa-mutated'}))
            path = base + 'page-001/artifacts/' + self.digests[project + '/page-001'] + '/tags'
            artifact = self.admin_json(path.removesuffix('/tags'))
            self.mutation(project + '-tag-create', 'POST', path, {'name': 'qa-new-tag'},
                          lambda: self.pages(path, self.admin), 201,
                          lambda old, new, _: created_record(old, new, {
                              'name': 'qa-new-tag', 'artifact_id': artifact['id'],
                              'repository_id': artifact['repository_id']}))
            path = base + 'page-002/artifacts/' + self.digests[project + '/page-002']
            inventory = base + 'page-002/artifacts'
            self.mutation(project + '-artifact-delete', 'DELETE', path, None,
                          lambda: self.pages(inventory, self.admin), 200,
                          lambda old, new, _: deleted_record(old, new, self.digests[project + '/page-002'], key='digest'))
            path = base + 'page-003'
            repository_id = self.admin_json(path)['id']
            self.mutation(project + '-repository-delete', 'DELETE', path, None,
                          lambda: self.pages(f'/projects/{project}/repositories', self.admin), 200,
                          lambda old, new, _: deleted_record(old, new, repository_id))
        body = validate_config(self.config)
        body['name'] = 'qa-control-created'
        expected_robot = dict(body, name='robot$qa-control-created')
        self.mutation('robot-create', 'POST', '/robots', body,
                      lambda: self.pages('/robots', self.admin), 201,
                      lambda old, new, result: created_robot(old, new, expected_robot, result))
        other = next(r for r in self.pages('/robots', self.admin) if r['name'] == 'robot$qa-control-created')
        # Test other-robot expansion first; self-expansion last, then restore scope.
        for identifier in (other['id'], self.robot_id):
            path = f'/robots/{identifier}'
            original = self.admin_json(path)
            body = {k: copy.deepcopy(original[k]) for k in ('name', 'description', 'level', 'disable', 'duration', 'permissions')}
            body['permissions'][0]['access'].append({'resource': 'repository', 'action': 'delete', 'effect': 'allow'})
            self.mutation('robot-expand-' + ('self' if identifier == self.robot_id else 'other'),
                          'PUT', path, body, lambda: self.pages('/robots', self.admin), 200,
                          lambda old, new, _: updated_record(old, new, identifier, {'permissions': body['permissions']}))
            restore = {k: original[k] for k in body}
            before_restore = self.pages('/robots', self.admin)
            expect(self.api('PUT', path, self.admin, restore), 200)
            updated_record(before_restore, self.pages('/robots', self.admin), identifier,
                           {'permissions': original['permissions']})
        original = self.admin_json('/configurations')['project_creation_restriction']['value']
        changed = 'adminonly' if original != 'adminonly' else 'everyone'
        def configuration_postcondition(old, new, _):
            expected = copy.deepcopy(old)
            expected['project_creation_restriction']['value'] = changed
            require(old['project_creation_restriction']['value'] != changed and new == expected,
                    'Configuration requested value absent or unrelated configuration changed')

        self.mutation('configuration-update', 'PUT', '/configurations',
                      {'project_creation_restriction': changed},
                      lambda: self.admin_json('/configurations'), 200, configuration_postcondition)
        before_restore = self.admin_json('/configurations')
        expect(self.api('PUT', '/configurations', self.admin, {'project_creation_restriction': original}), 200)
        before_restore['project_creation_restriction']['value'] = original
        require(self.admin_json('/configurations') == before_restore, 'Configuration restore mismatch')

    def registry_cases(self):
        for project in ('homelab', 'mirror'):
            repository = project + '/nested/seed'
            config, manifest = fixture_image(100)
            for kind, reference in (('manifests', digest(manifest)), ('blobs', digest(config))):
                path = f'/v2/{repository}/{kind}/{reference}'
                expect(self.registry('GET', path, self.admin, repository, 'pull'), 200)
                self.identity_control()
                actual = self.registry('GET', path, self.robot, repository, 'pull')
                if project == 'homelab':
                    denied(actual, registry=True)
                else:
                    baseline = self.registry('GET', path, None, repository, 'pull')
                    expect(baseline, 200)
                    expect(actual, 200)
                    require(actual.body == baseline.body, 'Public pull differs from anonymous baseline')
                self.record(project + '-' + kind + '-pull')
            inventory = f'/projects/{project}/repositories/{encoded("nested/seed")}/artifacts'
            before = self.pages(inventory, self.admin)
            tag_path = inventory + '/' + digest(manifest) + '/tags'
            before_tags = self.pages(tag_path, self.admin)
            self.identity_control()
            path = f'/v2/{repository}/manifests/qa-denied'
            denied(self.registry('PUT', path, self.robot, repository, 'pull,push', manifest), registry=True)
            require(self.pages(inventory, self.admin) == before, 'Denied manifest changed inventory')
            expect(self.registry('PUT', path, self.admin, repository, 'pull,push', manifest), 201)
            tags = self.pages(tag_path, self.admin)
            after = self.pages(inventory, self.admin)
            target = next(a for a in after if a['digest'] == digest(manifest))
            created_record(before_tags, tags, {'name': 'qa-denied', 'artifact_id': target['id'],
                                               'repository_id': target['repository_id']})
            require(indexed(target['tags']) == indexed(tags), 'Artifact summary and tag readback disagree')
            updated_record(before, after, digest(manifest), {'tags': target['tags']}, key='digest')
            self.record(project + '-manifest-push')
            path = f'/v2/{repository}/blobs/uploads/'
            before_upload = self.pages(inventory, self.admin)
            self.identity_control()
            refused = self.registry('POST', path, self.robot, repository, 'pull,push')
            denied(refused, registry=True)
            require('location' not in refused.headers
                    and self.pages(inventory, self.admin) == before_upload, 'Denied upload changed fixture')
            response = expect(self.registry('POST', path, self.admin, repository, 'pull,push'), 202)
            location = self.net.location(response.headers['location'])
            # A valid administrator-created upload session probes append/commit
            # separately: denial at initiation alone cannot prove those handlers.
            chunk, _ = fixture_image(9999)
            # Distribution's Range 0-0 is ambiguous for empty vs one-byte
            # sessions. Prime with a nonempty prefix before asserting no change.
            prefix = b'home57-upload-control\n'
            primed = expect(self.registry('PATCH', location, self.admin, repository, 'pull,push',
                                          prefix, 'application/octet-stream'), 202)
            require(primed.headers.get('range') == f'0-{len(prefix)-1}', 'Upload priming control failed')
            location = self.net.location(primed.headers['location'])
            fresh = prefix + chunk
            for method, expected in (('PATCH', 202), ('PUT', 201)):
                target = location if method == 'PATCH' else (
                    location + ('&' if '?' in location else '?') + urlencode({'digest': digest(fresh)}))
                baseline = expect(self.registry('GET', location, self.admin, repository, 'pull,push'), 204)
                blob_path = f'/v2/{repository}/blobs/{digest(fresh)}'
                expect(self.registry('GET', blob_path, self.admin, repository, 'pull'), 404)
                self.identity_control()
                denied(self.registry(method, target, self.robot, repository, 'pull,push',
                                     chunk if method == 'PATCH' else b'', 'application/octet-stream'), registry=True)
                status = expect(self.registry('GET', location, self.admin, repository, 'pull,push'), 204)
                require(status.headers.get('range') == baseline.headers.get('range')
                        and 'range' in status.headers, 'Denied upload changed offset')
                expect(self.registry('GET', blob_path, self.admin, repository, 'pull'), 404)
                result = expect(self.registry(method, target, self.admin, repository, 'pull,push',
                                              chunk if method == 'PATCH' else b'', 'application/octet-stream'), expected)
                if method == 'PATCH':
                    location = self.net.location(result.headers['location'])
                    require(result.headers.get('range') == f'0-{len(fresh)-1}',
                            'Upload append positive control failed')
                else:
                    stored = expect(self.registry('GET', f'/v2/{repository}/blobs/{digest(fresh)}',
                                                   self.admin, repository, 'pull'), 200)
                    require(stored.body == fresh, 'Upload commit positive control failed')
                self.record(project + '-upload-' + method.lower())
            self.record(project + '-upload-initiate')

    def disabled_case(self):
        self.identity_control()
        wrong = dict(self.robot, password='deliberately-invalid-fixture-password')
        path = '/projects/homelab/repositories'
        expect(self.api('GET', path, wrong), 401)
        current = self.admin_json(f'/robots/{self.robot_id}')
        body = {k: current[k] for k in ('name', 'description', 'level', 'duration', 'permissions')}
        body['disable'] = True
        expect(self.api('PUT', f'/robots/{self.robot_id}', self.admin, body), 200)
        require(self.admin_json(f'/robots/{self.robot_id}')['disable'] is True, 'Disable control failed')
        expect(self.api('GET', path, self.robot), 401)
        self.record('wrong-and-disabled-private-authentication')

    def run(self):
        self.setup()
        self.read_cases()
        self.registry_cases()
        self.write_cases()
        self.disabled_case()
        return {'authorization_subset': 'pass', 'overall_acceptance': 'incomplete',
                'cases': self.results, 'not_run': self.config['required_external_gates']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-sha')
    parser.add_argument('--admin-file', type=Path)
    parser.add_argument('--ca-file', type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(CONFIG.read_text())
        validate_config(config)
        if not args.execute:
            print('Offline fixture contract valid. Server execution disabled; no credentials read.')
            return 0
        preflight(config, args.expected_sha)
        require(args.admin_file is not None and args.ca_file is not None, 'Fixture credential and CA files required')
        admin = private_json(args.admin_file)
        result = Suite(Transport(config, args.ca_file), config, admin).run()
        print(json.dumps(result, sort_keys=True))
        # Full acceptance must never become green while explicit gaps remain.
        return 2
    except Failure as error:
        print(str(error), file=sys.stderr)
    except Exception:  # noqa: BLE001 - server bodies and credentials must never enter logs
        print('Fixture failed; private diagnostics withheld. No retry; dispose approved environment.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
