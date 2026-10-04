#!/usr/bin/env python3
"""HOME-62 offline direct-API recipes and evidence oracles; no execution adapter.

Never reads management credentials, opens sockets, or provisions identities.
The rejected issuer is a synthetic research subject, not an accepted design.
"""

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v2.15.2'
UPDATE_FIELDS = ('name', 'description', 'level', 'disable', 'duration', 'permissions')


class Inconclusive(Exception):
    """Fixed public diagnostics only; no raw API content."""


def require(condition, message):
    if not condition:
        raise Inconclusive(message)


def child_payload():
    result = json.loads((ROOT / 'clusters/homelab/apps/harbor/vulnerability-robot.json').read_text())
    result['name'] = 'home62-new-child'
    result['description'] = 'HOME-62 disposable synthetic subject'
    return result


def identity_recipes():
    """Non-secret create bodies; provisioning and custody deliberately absent."""
    issuer = json.loads((ROOT / 'scripts/config/harbor-vulnerability-issuer-proposal.json').read_text())
    issuer['name'] = 'home62-issuer'
    issuer['description'] = 'Rejected HOME-62 authority; disposable research subject only'
    result = {'issuer': issuer}
    for alias in ('child', 'unrelated', 'session-subject'):
        result[alias] = dict(child_payload(), name='home62-' + alias)
    # Only this distinct session-control identity has private pull permission.
    # It must never replace the collector or rejected issuer baseline scopes.
    result['session-subject']['permissions'] = add_permission(
        result['session-subject']['permissions'], 'project', 'homelab', 'repository', 'pull')
    for project in ('homelab', 'mirror'):
        permissions = [{'kind': 'project', 'namespace': project, 'access': [
            {'resource': 'repository', 'action': 'list', 'effect': 'allow'},
            {'resource': 'artifact', 'action': 'list', 'effect': 'allow'}]}]
        result['project-child-' + project] = dict(child_payload(), level='project',
            name='home62-project-child-' + project, permissions=copy.deepcopy(permissions))
        for action in ('create', 'read', 'list', 'update'):
            permissions = add_permission(permissions, 'project', project, 'robot', action)
        result['project-' + project] = dict(child_payload(), level='project', duration=1,
            name='home62-project-' + project, permissions=permissions)
    return result


def add_permission(permissions, kind, namespace, resource, action):
    result = copy.deepcopy(permissions)
    block = next((p for p in result if (p['kind'], p['namespace']) == (kind, namespace)), None)
    if block is None:
        block = {'kind': kind, 'namespace': namespace, 'access': []}
        result.append(block)
    access = {'resource': resource, 'action': action, 'effect': 'allow'}
    require(access not in block['access'], 'Capability already present in baseline')
    block['access'].append(access)
    return result


def cases():
    result = []

    def add(actor, target, operation, variation):
        result.append({'id': f'{actor}-{target}-{operation}-{variation}', 'actor': actor,
                       'target': target, 'operation': operation, 'variation': variation,
                       'server_status': 'unexecuted'})

    for target in ('child', 'unrelated'):
        for operation, variation in (('refresh', 'secret'), ('update', 'description'), ('update', 'disable')):
            add('issuer', target, operation, variation)
    for target in ('issuer', 'child'):
        for variation in ('extra-system', 'duration-extended', 'duration-never'):
            add('issuer', target, 'update', variation)
    for variation in ('within-ceiling', 'extra-project', 'extra-system', 'duration-extended', 'duration-never'):
        add('issuer', 'new-child', 'create', variation)
    add('issuer', 'child', 'update', 'extra-project')
    for actor, own, other in (('project-homelab', 'project-child-homelab', 'project-child-mirror'),
                              ('project-mirror', 'project-child-mirror', 'project-child-homelab')):
        for target in (own, other, 'unrelated'):
            for operation, variation in (('refresh', 'secret'), ('update', 'disable')):
                add(actor, target, operation, variation)
        for variation in ('extra-local', 'duration-extended', 'duration-never'):
            add(actor, actor, 'update', variation)
    for target in ('issuer', 'child', 'session-subject'):
        for boundary in ('rotation', 'disable', 'expiry'):
            for protocol in ('registry-bearer', 'api-session'):
                add('independent-observer', target, 'session', boundary + ':' + protocol)
    return result


def safe_metadata(value):
    """Reject credential-bearing objects in this offline-only API."""
    if isinstance(value, dict):
        require(not any(k.lower() in {'secret', 'password', 'authorization', 'token', 'cookie', 'private_key'}
                        for k in value), 'Credential-bearing evidence rejected')
        for item in value.values():
            safe_metadata(item)
    elif isinstance(value, list):
        for item in value:
            safe_metadata(item)


def synthetic_robot(value):
    safe_metadata(value)
    require(isinstance(value['id'], int) and value['id'] > 0, 'Invalid synthetic identity ID')
    require(re.fullmatch(r'robot\$(?:(?:homelab|mirror)\+)?home62-[a-z-]+', value['name']) is not None,
            'Non-synthetic identity rejected')


def validate_graph(identities):
    recipes = identity_recipes()
    require(set(identities) == set(recipes), 'Incomplete or unexpected synthetic identity graph')
    ids = []
    for alias, value in identities.items():
        synthetic_robot(value)
        ids.append(value['id'])
        recipe = recipes[alias]
        prefix = 'robot$' if recipe['level'] == 'system' else 'robot$' + recipe['permissions'][0]['namespace'] + '+'
        require(value['name'] == prefix + recipe['name'] and value['level'] == recipe['level']
                and value['duration'] == recipe['duration'] and value['disable'] is False
                and normalized(value)['permissions'] == normalized(recipe)['permissions'],
                'Synthetic baseline differs from declared authority')
    require(len(set(ids)) == len(ids), 'Synthetic identities alias the same immutable ID')
    require(identities['child']['creator_ref'] == identities['issuer']['id']
            and identities['unrelated']['creator_ref'] != identities['issuer']['id'],
            'Intended/unrelated creator relationship not established')


def changes(case, target):
    variant = case['variation']
    if variant == 'description':
        return {'description': 'HOME-62 requested mutation'}
    if variant == 'disable':
        return {'disable': True}
    if variant == 'duration-extended':
        return {'duration': target['duration'] + 1}
    if variant == 'duration-never':
        return {'duration': -1}
    if variant == 'extra-system':
        return {'permissions': add_permission(target['permissions'], 'system', '/', 'robot', 'delete')}
    if variant == 'extra-project':
        return {'permissions': add_permission(target['permissions'], 'project', 'qa-private-other', 'repository', 'list')}
    if variant == 'extra-local':
        namespace = target['permissions'][0]['namespace']
        return {'permissions': add_permission(target['permissions'], 'project', namespace, 'repository', 'delete')}
    if variant == 'within-ceiling':
        return {}
    raise Inconclusive('Unsupported capability variation')


def request(case, identities):
    require(case in cases() and case['operation'] != 'session', 'Unknown direct-API case')
    validate_graph(identities)
    if case['operation'] == 'create':
        body = child_payload()
        body.update(changes(case, body))
        return {'method': 'POST', 'path': '/api/v2.0/robots', 'body': body}
    target = identities[case['target']]
    if case['operation'] == 'refresh':
        return {'method': 'PATCH', 'path': f'/api/v2.0/robots/{target["id"]}', 'body': {}}
    body = {key: copy.deepcopy(target[key]) for key in UPDATE_FIELDS}
    body.update(changes(case, target))
    return {'method': 'PUT', 'path': f'/api/v2.0/robots/{target["id"]}', 'body': body}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def session_recipe(case, identities):
    require(case in cases() and case['operation'] == 'session', 'Unknown session case')
    validate_graph(identities)
    target = identities[case['target']]
    synthetic_robot(target)
    boundary, protocol = case['variation'].split(':')
    path = f'/api/v2.0/robots/{target["id"]}'
    if boundary == 'rotation':
        operation = {'method': 'PATCH', 'path': path, 'body': {}}
    elif boundary == 'disable':
        body = {key: copy.deepcopy(target[key]) for key in UPDATE_FIELDS}
        body['disable'] = True
        operation = {'method': 'PUT', 'path': path, 'body': body}
    else:
        require(target['expires_at'] > 0, 'Nonexpiring baseline cannot test expiry')
        operation = {'wait_until_server_expiry': target['expires_at'], 'clock_mutation': False}
    return {'boundary_operation': operation, 'protocol': protocol,
            'executor': 'separately-approved-isolated-custodian',
            'baseline': 'same usable session on existing private resource; anonymous denial',
            'replay': 'same session handle and exact request before/after boundary through expiry',
            'missing_or_unsupported_session': 'inconclusive; never add issuer grants to force success'}


def normalized(value):
    result = copy.deepcopy(value)
    if isinstance(result, dict) and 'permissions' in result:
        for block in result['permissions']:
            for access in block['access']:
                access.setdefault('effect', 'allow')
            block['access'].sort(key=lambda a: (a['resource'], a['action'], a['effect']))
        result['permissions'].sort(key=lambda p: (p['kind'], p['namespace']))
    return result


def expiry(created_at, duration):
    if duration == -1:
        return -1
    parsed = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Missing creation-time timezone')
    return int(parsed.timestamp()) + duration * 86400


def transition(case, before, after, reply_id=None, auth=None):
    """Check exact metadata effects; never infer rotation from update_time."""
    safe_metadata(before)
    safe_metadata(after)
    if case['operation'] == 'create':
        added = set(after) - set(before)
        require(len(added) == 1 and set(before) <= set(after), 'Invalid creation delta')
        handle = next(iter(added))
        require(all(after[k] == before[k] for k in before), 'Unrelated identity changed')
        created = after[handle]
        synthetic_robot(created)
        require(created['id'] == reply_id and reply_id not in [r['id'] for r in before.values()],
                'Create response/readback ID mismatch')
        expected = child_payload()
        expected.update(changes(case, expected))
        expected['name'] = 'robot$' + expected['name']
        for key, value in normalized(expected).items():
            require(normalized(created).get(key) == value, 'Created identity differs from requested contract')
        require(created['expires_at'] == expiry(created['creation_time'], expected['duration']),
                'Created expiry differs from requested lifetime')
        return
    target = case['target']
    require(set(before) == set(after) and target in before, 'Identity graph changed')
    require(all(after[k] == before[k] for k in before if k != target), 'Unrelated identity changed')
    old, new = normalized(before[target]), normalized(after[target])
    synthetic_robot(old)
    synthetic_robot(new)
    expected = copy.deepcopy(old)
    if case['operation'] == 'refresh':
        require(auth == {'old_before': 200, 'old_after': 401, 'new_after': 200},
                'Secret refresh lacks independent old/new authentication proof')
    else:
        delta = changes(case, old)
        require(any(old.get(k) != normalized(dict(old, **delta)).get(k) for k in delta),
                'Requested capability was already present')
        expected.update(delta)
        if 'duration' in delta:
            expected['expires_at'] = expiry(old['creation_time'], delta['duration'])
    expected.pop('update_time', None)
    new.pop('update_time', None)
    require(normalized(new) == normalized(expected), 'Requested postcondition absent or unrequested target change')


def evaluate(case, identities, evidence):
    """Offline oracle for a future adapter; output never accepts issuer authority."""
    safe_metadata(evidence)
    expected = request(case, identities)
    require(evidence['request_sha256'] == fingerprint(expected), 'Evidence bound to different request')
    require(evidence['actor_baseline_status'] == 200 and evidence['observer_before_status'] == 200
            and evidence['observer_after_status'] == 200, 'Missing identity/observer controls')
    require(evidence['before'] == identities, 'Evidence baseline does not match bound identities')
    control = evidence['control']
    require(control['request_sha256'] == fingerprint(expected) and control['before'] == identities,
            'Authorized control baseline or request differs')
    require(control['status'] == (201 if case['operation'] == 'create' else 200),
            'Authorized control request did not succeed')
    transition(case, control['before'], control['after'], control.get('reply_id'), control.get('auth'))
    if evidence['status'] == 403 and evidence.get('error_code') in ('FORBIDDEN', 'DENIED'):
        require(evidence['after'] == identities, 'Denied request changed observed state')
        if case['operation'] == 'refresh':
            require(evidence.get('old_credential_after_status') == 200,
                    'Denied refresh lacks unchanged credential proof')
        outcome = 'denied-with-controls'
    else:
        require(evidence['status'] == (201 if case['operation'] == 'create' else 200),
                'Request was neither authorized nor a proven authorization denial')
        transition(case, identities, evidence['after'], evidence.get('reply_id'), evidence.get('auth'))
        outcome = 'capability-present'
    return {'case': case['id'], 'observation': outcome, 'issuer_authority_accepted': False,
            'operational_acceptance': 'not-established'}


def session_survival(case, evidence):
    """Do not confuse loss of Basic access with termination of existing tokens."""
    require(case in cases() and case['operation'] == 'session', 'Unknown session case')
    safe_metadata(evidence)
    require(evidence['private_resource'] is True and evidence['anonymous_status'] in (401, 403),
            'Public access cannot establish session survival')
    require(evidence['same_request'] is True and evidence['same_session_handle'] is True
            and evidence['baseline_status'] == 200 and evidence['fresh_basic_before_status'] == 200,
            'Missing usable authenticated session baseline')
    require(evidence['subject_id'] == evidence['boundary_subject_id'] and evidence['boundary_verified'] is True,
            'Credential boundary not independently verified for this identity')
    require(evidence['fresh_basic_after_status'] == 401, 'Old Basic credential still usable or inconclusive')
    minted, boundary, expires = evidence['minted_at'], evidence['boundary_at'], evidence['expires_at']
    require(minted < boundary < expires and evidence['clock_skew_seconds'] >= 0,
            'Session was not valid across the boundary')
    probes = evidence['probes']
    require(bool(probes) and all(p['at'] > boundary and p['status'] in (200, 401, 403) for p in probes),
            'Missing or inconclusive session probes')
    require(all(a['at'] < b['at'] for a, b in zip(probes, probes[1:])), 'Session probes out of order')
    survived = any(p['at'] < expires and p['status'] == 200 for p in probes)
    ended = probes[-1]['at'] >= expires + evidence['clock_skew_seconds'] and probes[-1]['status'] in (401, 403)
    # Never infer immediate revocation from a single denial or a stopped process.
    return {'case': case['id'], 'survival_observed': survived,
            'usable_after_expiry': any(p['at'] >= expires + evidence['clock_skew_seconds']
                                       and p['status'] == 200 for p in probes),
            'termination_observed_after_expiry': ended,
            'observation_complete': ended and any(p['at'] < expires for p in probes),
            'issuer_authority_accepted': False, 'operational_acceptance': 'not-established'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        print('HOME-62 execution is hard-disabled; no credential or network adapter exists.')
        return 1
    print(json.dumps({'version': VERSION, 'execution_enabled': False, 'cases': cases(),
                      'synthetic_identity_recipes': identity_recipes(),
                      'issuer_authority_accepted': False, 'server_execution': 'unexecuted'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
