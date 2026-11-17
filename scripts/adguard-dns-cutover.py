#!/usr/bin/env python3
"""Validate the exact DNS-only saved-plan contract before any tailnet mutation."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import copy
import ipaddress
import math
from datetime import datetime, timezone
import time
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / 'IaC/homelab/us-west-2/operator/tailscale-access'
DNS_SOURCE = 'IaC/terragrunt-catalog/modules/tailscale-access/main.tf'
# Verified protected main before any AdGuard DNS change. Updating this recovery
# baseline requires reviewed source; a live response cannot silently replace it.
BASELINE_REVISION = '48e8b9e4627f4a37f30d00f2d28b96d64133996e'

ADDRESS = 'tailscale_dns_configuration.homelab'
FIELDS = {'magic_dns', 'override_local_dns', 'search_paths', 'nameservers', 'split_dns'}


class Failure(Exception):
    """Fixed messages only; private plan contents must not appear in diagnostics."""


def require(condition, message):
    if not condition:
        raise Failure(message)


def resolvers(value):
    require(isinstance(value, list), 'Incomplete resolver policy')
    result = []
    for item in value:
        require(isinstance(item, dict) and set(item) == {'address', 'use_with_exit_node'}
                and type(item['use_with_exit_node']) is bool and isinstance(item['address'], str),
                'Incomplete resolver policy')
        try:
            address = str(ipaddress.ip_address(item['address']))
        except ValueError:
            raise Failure('Resolver address is not an IP literal') from None
        result.append({'address': address, 'use_with_exit_node': item['use_with_exit_node']})
    require(len({x['address'] for x in result}) == len(result), 'Duplicate resolver address')
    return sorted(result, key=lambda x: x['address'])


def policy(value):
    require(isinstance(value, dict) and set(value) in (FIELDS, FIELDS | {'id'}), 'Incomplete or unexpected DNS policy fields')
    require(type(value['magic_dns']) is bool and type(value['override_local_dns']) is bool
            and isinstance(value['search_paths'], list)
            and all(isinstance(p, str) and p for p in value['search_paths'])
            and isinstance(value['split_dns'], list), 'Incomplete DNS policy')
    split = []
    for item in value['split_dns']:
        require(isinstance(item, dict) and set(item) == {'domain', 'nameservers'}
                and isinstance(item['domain'], str) and bool(item['domain']), 'Incomplete split DNS policy')
        nameservers = resolvers(item['nameservers'])
        require(bool(nameservers), 'Split DNS requires a resolver')
        split.append({'domain': item['domain'], 'nameservers': nameservers})
    require(len({x['domain'] for x in split}) == len(split), 'Duplicate split DNS domain')
    return {'magic_dns': value['magic_dns'], 'override_local_dns': value['override_local_dns'],
            'search_paths': value['search_paths'], 'nameservers': resolvers(value['nameservers']),
            'split_dns': sorted(split, key=lambda x: x['domain'])}


def validate_transition(before, after, server):
    before, after = policy(before), policy(after)
    try:
        require(ipaddress.ip_address(server) in ipaddress.ip_network('100.64.0.0/10'), 'AdGuard must use its observed tailnet IPv4')
    except ValueError:
        raise Failure('Invalid observed AdGuard endpoint') from None
    expected = copy.deepcopy(before)
    expected.update(override_local_dns=True, nameservers=[{'address': server, 'use_with_exit_node': True}])
    require(before['magic_dns'] is True and before != expected and after == expected,
            'Cutover must change only global resolvers and local DNS override')


def unknown(value):
    if isinstance(value, dict):
        return any(unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(unknown(v) for v in value)
    return value is not False and value is not None


def resources(module):
    require(isinstance(module, dict), 'Missing planned module values')
    result = list(module.get('resources', []))
    for child in module.get('child_modules', []):
        result.extend(resources(child))
    return result


def validate_provider(plan):
    configuration = plan.get('configuration', {})
    declared = [r for r in configuration.get('root_module', {}).get('resources', [])
                if r.get('address') == ADDRESS]
    require(len(declared) == 1 and isinstance(declared[0].get('provider_config_key'), str),
            'Saved DNS plan must use the default administrator Tailscale provider')
    # OpenTofu declares these map keys opaque. Resolve the resource's reference,
    # then validate the actual root/default provider, not an invented key format.
    provider = configuration.get('provider_config', {}).get(declared[0]['provider_config_key'], {})
    expected = {name: {'constant_value': 'file:' + str(Path.home() / '.config/homelab/tailscale' / filename)}
                for name, filename in (('oauth_client_id', 'terragrunt-oauth-client-id'),
                                       ('oauth_client_secret', 'terragrunt-oauth-client-secret'))}
    require(provider.get('name') == 'tailscale' and not provider.get('alias') and not provider.get('module_address')
            and provider.get('full_name') in ('registry.opentofu.org/tailscale/tailscale',
                                             'registry.terraform.io/tailscale/tailscale')
            and str(provider.get('version_constraint', '')).replace(' ', '').removeprefix('=') == '0.29.2'
            and provider.get('expressions') == expected,
            'Saved DNS plan provider version, endpoint or credential source differs')


def validate_plan(plan, before, after):
    before, after = policy(before), policy(after)
    require(isinstance(plan, dict) and str(plan.get('format_version', '')).startswith('1.')
            and plan.get('errored', False) is False and plan.get('complete', True) is True,
            'Saved plan is incomplete or unsupported')
    validate_provider(plan)
    require(isinstance(plan.get('resource_changes'), list), 'Saved plan has no resource changes')
    changes = []
    for resource in plan['resource_changes']:
        change = resource.get('change', {})
        require(not unknown(change.get('after_unknown', {})), 'Saved plan contains unknown values')
        if change.get('actions') == ['no-op']:
            continue
        require(resource.get('address') == ADDRESS and resource.get('mode') == 'managed'
                and resource.get('type') == 'tailscale_dns_configuration'
                and change.get('actions') == ['update'] and not change.get('replace_paths')
                and not resource.get('previous_address'), 'Saved plan changes an unrelated resource or replaces DNS')
        require(policy(change.get('before')) == before and policy(change.get('after')) == after,
                'Saved DNS before/after policy differs from the reviewed transition')
        require(isinstance(change['before'].get('id'), str) and bool(change['before']['id'])
                and change['before']['id'] == change['after'].get('id'), 'DNS singleton identity changed')
        changes.append(resource)
    require(len(changes) == 1, 'Saved plan must contain exactly one DNS update')
    require(all(item.get('change', {}).get('actions') == ['no-op'] for item in plan.get('resource_drift', [])),
            'Saved plan includes unreviewed resource drift')
    require(all(item.get('actions') == ['no-op'] for item in plan.get('output_changes', {}).values()),
            'Saved plan changes outputs outside the DNS transition')
    values = [r for r in resources(plan.get('planned_values', {}).get('root_module')) if r.get('address') == ADDRESS]
    require(len(values) == 1 and policy(values[0].get('values')) == after, 'Planned DNS values are incomplete or inconsistent')


def validate_timing(start, completed, now, wall_start, wall_now):
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, completed, now, wall_start, wall_now)),
            'Invalid validation clock')
    require(0 <= start <= completed <= now and completed - start <= 300 and now - completed <= 60
            and 0 <= wall_start <= wall_now, 'Validation expired or the clock moved backwards')


def validate_receipt_time(receipt, now):
    start, end = receipt.get('started_at'), receipt.get('completed_at')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, now))
            and 0 <= start <= end <= now, 'Persisted evidence has future or invalid timestamps')
    # A valid historical timestamp is audit information, never execution authority.


def validate_binding(checked, fresh):
    fields = {'source', 'config', 'service', 'peer', 'plan_sha256', 'live_policy', 'desired_policy'}
    require(isinstance(checked, dict) and set(checked) == fields and all(checked.values())
            and checked == fresh, 'Source, configuration, identity, plan or live DNS is incomplete or changed')


def iso_time(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def parse_time(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(date.tzinfo is not None, 'Saved plan timestamp lacks a timezone')
        return date.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise Failure('Invalid saved plan timestamp') from None


def binding(revision, snapshot, plan_hash, live, desired):
    require(snapshot.get('source_revision') == revision and snapshot.get('deployed_revision') == revision,
            'Direct evidence belongs to a different source revision')
    result = {'source': revision,
              'config': [snapshot.get(k) for k in ('config_revision', 'config_digest', 'source_digest')],
              'service': [snapshot.get('service_uid'), snapshot.get('server')],
              'peer': snapshot.get('peer'), 'plan_sha256': plan_hash,
              'live_policy': policy(live), 'desired_policy': policy(desired)}
    require(all(result['config']) and all(result['service']), 'Direct evidence is incomplete')
    validate_binding(result, result)
    return result


def reconcile(adapter, execute=False):
    start, wall_start = time.monotonic(), time.time()
    revision, desired = adapter.current_source()
    desired, baseline = policy(desired), policy(adapter.baseline_policy())
    previous = adapter.previous_receipt()
    if previous is not None:
        validate_receipt_time(previous, time.time())
        require(previous.get('schema') == 1 and policy(previous.get('before')) == baseline
                and policy(previous.get('after')) == desired, 'Prior DNS receipt differs from reviewed source')
        require(previous.get('phase') in ('applying', 'uncertain', 'applied', 'failed-needs-new-plan'),
                'Unsupported prior DNS receipt phase')
        observed = policy(adapter.live_policy())
        if previous['phase'] in ('applying', 'uncertain', 'applied'):
            if observed == desired:
                if execute:
                    adapter.save(dict(previous, phase='applied', inspected_at=time.time()))
                return 'already-applied'
            require(observed == baseline, 'Uncertain apply has unrelated live DNS drift')
            if execute:
                adapter.save(dict(previous, phase='failed-needs-new-plan', inspected_at=time.time()))
            raise Failure('Prior apply inspected without desired DNS; create a new saved plan before retrying')
    plan_hash, planned = adapter.read_plan()
    require(0 <= parse_time(planned.get('timestamp')) <= time.time(), 'Saved plan has a future or invalid timestamp')
    validate_plan(planned, baseline, desired)
    if previous is not None:
        require(plan_hash != previous.get('plan_sha256')
                and parse_time(planned.get('timestamp')) > previous.get('inspected_at', float('inf')),
                'An inspected failed apply requires a newly generated saved plan')
    live = policy(adapter.live_policy())
    require(live == baseline, 'Live DNS differs from the reviewed prior policy')
    direct = adapter.direct_check()
    require(direct.get('mode') == 'direct' and direct.get('admin_acceptance') is True,
            'Fresh direct DNS and administration acceptance is required')
    validate_transition(baseline, desired, direct.get('server'))
    checked = binding(revision, direct, plan_hash, live, desired)
    completed = time.monotonic()
    fresh_revision, fresh_desired = adapter.current_source()
    fresh = binding(fresh_revision, adapter.snapshot(), adapter.plan_hash(),
                    adapter.live_policy(), fresh_desired)
    validate_binding(checked, fresh)
    validate_timing(start, completed, time.monotonic(), wall_start, time.time())
    if not execute:
        return 'preview'
    record = {'schema': 1, 'phase': 'applying', 'source_revision': revision,
              'plan_sha256': plan_hash, 'before': baseline, 'after': desired,
              'started_at': wall_start, 'completed_at': time.time(), 'binding': checked,
              'direct_evidence': direct}
    adapter.save(record)
    # Receipt persistence must not push the last successful check past its bound.
    validate_timing(start, completed, time.monotonic(), wall_start, time.time())
    try:
        adapter.apply()
    except Exception:
        # Never retry a possibly completed provider write. Inspect actual DNS.
        record['phase'] = 'uncertain'
        adapter.save(record)
    try:
        observed = policy(adapter.live_policy())
    except Exception:
        adapter.save(dict(record, phase='uncertain'))
        raise Failure('Apply outcome is uncertain; rerun preview to inspect before any retry') from None
    if observed == desired:
        adapter.save(dict(record, phase='applied', inspected_at=time.time()))
        return 'applied'
    adapter.save(dict(record, phase='failed-needs-new-plan' if observed == baseline else 'uncertain',
                      inspected_at=time.time()))
    raise Failure('Desired DNS was not observed; inspect the outcome and generate a new plan before retrying')


def rollback(adapter, execute=False):
    start, wall_start = time.monotonic(), time.time()
    revision, desired = adapter.current_source()
    desired, baseline = policy(desired), policy(adapter.baseline_policy())
    record = copy.deepcopy(adapter.previous_receipt())
    require(isinstance(record, dict) and record.get('schema') == 1, 'Rollback requires the protected prior-policy receipt')
    validate_receipt_time(record, time.time())
    require(record.get('phase') in ('applying', 'uncertain', 'applied', 'failed-needs-new-plan'),
            'Unknown prior cutover receipt phase')
    require(policy(record.get('before')) == baseline and desired == baseline,
            'Rollback current source must restore the reviewed prior policy')
    activated = policy(record.get('after'))
    require(len(activated['nameservers']) == 1, 'Recorded activation must have one filtering resolver')
    validate_transition(baseline, activated, activated['nameservers'][0]['address'])
    require(policy(adapter.recorded_source(record.get('source_revision'))) == activated,
            'Recorded activated policy differs from its reviewed source')
    live = policy(adapter.live_policy())
    if live == baseline:
        return 'already-restored'
    require(live == activated, 'Rollback refuses unrelated live DNS drift')
    previous = record.get('rollback')
    if previous is not None:
        validate_receipt_time(previous, time.time())
        require(previous.get('phase') in ('applying', 'uncertain', 'applied', 'failed-needs-new-plan'),
                'Unknown rollback receipt phase')
        if previous['phase'] in ('applying', 'uncertain', 'applied'):
            if execute:
                adapter.save(dict(record, rollback=dict(previous, phase='failed-needs-new-plan', inspected_at=time.time())))
            raise Failure('Prior rollback inspected without restoration; generate a new plan before retrying')
    plan_hash, planned = adapter.read_plan()
    require(0 <= parse_time(planned.get('timestamp')) <= time.time(), 'Saved rollback plan timestamp is invalid')
    validate_plan(planned, activated, baseline)
    if previous is not None:
        require(plan_hash != previous.get('plan_sha256')
                and parse_time(planned.get('timestamp')) > previous.get('inspected_at', float('inf')),
                'Rollback retry requires a new plan after inspection')
    completed = time.monotonic()
    fresh_revision, fresh_desired = adapter.current_source()
    require(fresh_revision == revision and policy(fresh_desired) == baseline
            and adapter.plan_hash() == plan_hash and policy(adapter.live_policy()) == activated
            and adapter.previous_receipt() == record, 'Rollback source, live policy, receipt or plan changed')
    validate_timing(start, completed, time.monotonic(), wall_start, time.time())
    if not execute:
        return 'rollback-preview'
    attempt = {'phase': 'applying', 'source_revision': revision, 'plan_sha256': plan_hash,
               'before': activated, 'after': baseline, 'started_at': wall_start, 'completed_at': time.time()}
    record['rollback'] = attempt
    adapter.save(record)
    validate_timing(start, completed, time.monotonic(), wall_start, time.time())
    try:
        adapter.apply()
    except Exception:
        attempt['phase'] = 'uncertain'
        adapter.save(record)
    try:
        observed = policy(adapter.live_policy())
    except Exception:
        attempt['phase'] = 'uncertain'
        adapter.save(record)
        raise Failure('Rollback outcome is uncertain; inspect before any retry') from None
    attempt.update(phase='applied' if observed == baseline else
                   'failed-needs-new-plan' if observed == activated else 'uncertain', inspected_at=time.time())
    adapter.save(record)
    require(observed == baseline, 'Rollback was not observed; inspect and create a fresh plan before retrying')
    return 'restored'


def source_policy(document):
    entries = document.get('resource', {}).get('tailscale_dns_configuration', {}).get('homelab', [])
    require(isinstance(entries, list) and len(entries) == 1, 'Source must declare one DNS singleton')
    value = copy.deepcopy(entries[0])
    require(set(value) == FIELDS, 'Source DNS expressions or fields are unsupported')
    for resolver in value['nameservers']:
        resolver.setdefault('use_with_exit_node', False)
    for split in value['split_dns']:
        for resolver in split['nameservers']:
            resolver.setdefault('use_with_exit_node', False)
    return policy(value)


def api_policy(document):
    require(isinstance(document, dict) and set(document) <= {'nameservers', 'splitDNS', 'searchPaths', 'preferences'}
            and isinstance(document.get('preferences'), dict)
            and set(document['preferences']) <= {'magicDNS', 'overrideLocalDNS'}, 'Live API DNS shape is unsupported')
    def convert(items):
        result = []
        for item in items:
            require(set(item) <= {'address', 'useWithExitNode'} and 'address' in item, 'Live resolver shape is unsupported')
            result.append({'address': item['address'], 'use_with_exit_node': item.get('useWithExitNode', False)})
        return result
    return policy({'magic_dns': document['preferences'].get('magicDNS', False),
                   'override_local_dns': document['preferences'].get('overrideLocalDNS', False),
                   'search_paths': document.get('searchPaths') or [],
                   'nameservers': convert(document.get('nameservers') or []),
                   'split_dns': [{'domain': domain, 'nameservers': convert(items)}
                                 for domain, items in (document.get('splitDNS') or {}).items()]})


def private_path(path, existing=True):
    path = Path(path).expanduser().absolute()
    require(not path.parent.resolve().is_relative_to(ROOT), 'Private plan and receipt must be outside the repository')
    parent = path.parent.lstat()
    require(stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode) == 0o700
            and parent.st_uid == os.getuid(), 'Private directory must be owned and mode0700')
    if existing or path.exists() or path.is_symlink():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid(), 'Private file must be owned, regular and mode0600')
    return path


def private_bytes(path):
    path = private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid() and info.st_size <= 128 * 1024 * 1024, 'Private file changed or is too large')
        return source.read()


def command(args, data=None, timeout=120):
    process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise Failure('Private command timed out; inspect any uncertain apply') from None
    require(process.returncode == 0, 'Private command failed; output withheld')
    return output


class DNSReader:
    def __init__(self, signer):
        self.signer, self.token = signer, None

    def read(self):
        oauth = self.signer.OAUTH
        if self.token is None:
            client_id, client_secret = self.signer.read_oauth_credentials()
            token = oauth.api_request('/oauth/token', method='POST', basic=(client_id, client_secret),
                                      body=[('grant_type', 'client_credentials'), ('scope', 'dns')])
            require(isinstance(token.get('access_token'), str) and bool(token['access_token'])
                    and str(token.get('token_type', '')).lower() == 'bearer', 'Administrator DNS token unavailable')
            self.token = token['access_token']
        return api_policy(oauth.api_request('/tailnet/-/dns/configuration', bearer=self.token))


def read_source_policy(revision):
    raw = command(['git', 'show', revision + ':' + DNS_SOURCE])
    return source_policy(json.loads(command(['hcl2json'], data=raw)))


class Adapter:
    def __init__(self, plan, receipt, server, password_file):
        spec = importlib.util.spec_from_file_location('adguard_check', ROOT / 'scripts/adguard-check.py')
        self.check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.check)
        self.plan_path = private_path(plan) if plan is not None else None
        self.receipt_path = private_path(receipt, existing=False)
        require(self.plan_path != self.receipt_path, 'Plan and receipt paths must differ')
        self.server, self.password_file = server, password_file
        self.dns_reader = DNSReader(self.check.SIGNER)
        self.checked_plan_hash = None

    def read_source(self, revision):
        return read_source_policy(revision)

    def current_source(self):
        revision = self.check.SIGNER.GUARDS.verify_main()
        return revision, self.read_source(revision)

    def baseline_policy(self):
        command(['git', 'merge-base', '--is-ancestor', BASELINE_REVISION, 'HEAD'])
        return self.read_source(BASELINE_REVISION)

    def recorded_source(self, revision):
        import re
        require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision), 'Invalid recorded source revision')
        command(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'])
        return self.read_source(revision)

    def plan_hash(self):
        require(self.plan_path is not None, 'An exact saved DNS plan is required unless already restored')
        return hashlib.sha256(private_bytes(self.plan_path)).hexdigest()

    def read_plan(self):
        before = self.plan_hash()
        value = json.loads(command(['terragrunt', '--working-dir', str(UNIT), 'run', '--no-auto-init', '--',
                                    'show', '-json', str(self.plan_path)]))
        require(before == self.plan_hash(), 'Saved plan changed during inspection')
        self.checked_plan_hash = before
        return before, value

    def live_policy(self):
        return self.dns_reader.read()

    def direct_check(self):
        return self.check.verify(self.server, self.password_file)

    def snapshot(self):
        return self.check.snapshot(self.server)

    def previous_receipt(self):
        if not self.receipt_path.exists():
            return None
        return json.loads(private_bytes(self.receipt_path))

    def save(self, value):
        private_path(self.receipt_path, existing=False)
        self.check.SIGNER.OAUTH.save_receipt(self.receipt_path, value,
                                           first=not self.receipt_path.exists())

    def apply(self):
        require(self.checked_plan_hash and self.plan_hash() == self.checked_plan_hash,
                'Saved plan changed immediately before apply')
        # Native encrypted state/plan handling and state locking remain enabled.
        command(['terragrunt', '--working-dir', str(UNIT), 'run', '--no-auto-init', '--',
                 'apply', '-input=false', str(self.plan_path)], timeout=1800)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['cutover', 'rollback'], default='cutover')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--server')
    parser.add_argument('--password-file', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        require(args.mode == 'rollback' or (args.plan is not None and args.server and args.password_file is not None),
                'Cutover requires an observed server, private admin credential and saved plan')
        adapter = Adapter(args.plan, args.receipt, args.server, args.password_file)
        lock_path = adapter.receipt_path.with_name(adapter.receipt_path.name + '.lock')
        private_path(lock_path, existing=False)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            outcome = rollback(adapter, args.execute) if args.mode == 'rollback' else reconcile(adapter, args.execute)
        print({'preview': 'DNS cutover preview passed; no tailnet changes made.',
               'applied': 'Verified the reviewed DNS policy after saved-plan apply.',
               'already-applied': 'Verified the recorded DNS policy is already active; no write repeated.',
               'rollback-preview': 'DNS rollback preview passed; no tailnet changes made.',
               'restored': 'Verified restoration of the reviewed prior DNS policy.',
               'already-restored': 'Verified prior DNS policy is already restored; no write repeated.'}[outcome])
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('DNS cutover failed; private data withheld. Inspect the protected receipt and generate a fresh plan after any uncertain apply.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
