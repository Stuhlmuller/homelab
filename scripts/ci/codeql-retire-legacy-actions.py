#!/usr/bin/env python3
"""Preview fixed obsolete CodeQL history; execute only in approved main CI."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = 'scripts/config/codeql-legacy-actions-retirement.json'
REPO = 'Stuhlmuller/homelab'
PREFIX = 'repos/' + REPO
REF = 'refs/heads/main'
OLD_KEY = '.github/workflows/codeql.yml:analyze'
OLD_CATEGORY = '/language:actions'
CURRENT = '.github/workflows/codeql.yml:analyze-actions'
ENVIRONMENT = '{"build-mode":"none","language":"actions"}'
FIELDS = ('id', 'ref', 'commit_sha', 'category', 'analysis_key', 'environment', 'created_at', 'tool')
MAX_BYTES = 8 * 1024 * 1024
WORKFLOW = '.github/workflows/codeql-retire-legacy-actions.yml'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def scope_digest(scope):
    return hashlib.sha256(canonical(scope)).hexdigest()


def command(args, allow_failure=False):
    """Bound both streams; expose only successful stdout, never vendor errors."""
    process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')})
    streams = [process.stdout, process.stderr]
    output = bytearray()
    size = 0
    deadline = time.monotonic() + 45
    try:
        while streams:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'Command deadline exceeded')
            ready, _, _ = select.select(streams, [], [], remaining)
            for stream in ready:
                data = os.read(stream.fileno(), 65536)
                if not data:
                    streams.remove(stream)
                    continue
                size += len(data)
                require(size <= MAX_BYTES, 'Command output bound exceeded')
                if stream is process.stdout:
                    output.extend(data)
        code = process.wait(timeout=max(.01, deadline-time.monotonic()))
        require(allow_failure or code == 0, 'Command failed; vendor output withheld')
        return (code, bytes(output)) if allow_failure else bytes(output)
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # Owned process exited between poll and kill.
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


LAST_ANALYSIS_MESSAGE = ('Analysis is last of its type and deletion may result in the loss of historical '
                         'alert data. Please specify confirm_delete.')


class LastAnalysis(RuntimeError):
    """Only the documented HTTP 400 last-in-set condition can request confirmation."""


class API:
    def request(self, method, path):
        require(method in ('GET', 'DELETE') and path.startswith(PREFIX + '/') and
                not any(text in path for text in ('..', '://', '#', '\\')), 'Invalid fixed-repository API route')
        code, raw = command(['gh', 'api', '--hostname', 'github.com', '--method', method, '--include',
                             '-H', 'Accept: application/vnd.github+json',
                             '-H', 'X-GitHub-Api-Version: 2022-11-28', path], allow_failure=True)
        parts = re.split(rb'\r?\n\r?\n', raw, maxsplit=1)
        require(len(parts) == 2, 'API response headers missing')
        match = re.match(rb'HTTP/[0-9.]+ ([0-9]{3})(?: |\r?\n)', parts[0])
        require(match is not None, 'Invalid API response status')
        status = int(match[1])
        body = json.loads(parts[1])
        if method == 'DELETE' and code == 1 and status == 400 and isinstance(body, dict) and body.get('message') == LAST_ANALYSIS_MESSAGE:
            raise LastAnalysis('Final analysis requires explicit history-loss confirmation')
        require(code == 0 and status == 200, 'API request failed; vendor details withheld')
        return body


def identity(row):
    return {key: row[key] for key in FIELDS}


def validate_scope(scope):
    require(set(scope) == {'schema', 'repository', 'ref', 'analysis_key', 'category',
                           'environment', 'workflow_sha256', 'analyses'}, 'Invalid scope fields')
    require(scope['schema'] == 1 and scope['repository'] == REPO and scope['ref'] == REF and
            scope['analysis_key'] == OLD_KEY and scope['category'] == OLD_CATEGORY and
            scope['environment'] == ENVIRONMENT, 'Scope is not the fixed legacy main configuration')
    require(re.fullmatch(r'[0-9a-f]{64}', scope['workflow_sha256']), 'Invalid workflow digest')
    rows = scope['analyses']
    require(isinstance(rows, list) and len(rows) == 97, 'Scope must contain exactly 97 analyses')
    ids = set()
    for row in rows:
        require(set(row) == set(FIELDS) and type(row['id']) is int and row['id'] > 0 and
                row['id'] not in ids, 'Invalid or duplicate scope ID')
        ids.add(row['id'])
        require(isinstance(row['tool'], dict) and set(row['tool']) == {'name', 'guid', 'version'},
                'Invalid exact tool identity')
        require(row['ref'] == REF and row['analysis_key'] == OLD_KEY and row['category'] == OLD_CATEGORY and
                row['environment'] == ENVIRONMENT and row['tool']['name'] == 'CodeQL' and
                row['tool']['guid'] is None and re.fullmatch(r'\d+\.\d+\.\d+', row['tool']['version']) and
                re.fullmatch(r'[0-9a-f]{40}', row['commit_sha']) and
                re.fullmatch(r'2026-\d\d-\d\dT\d\d:\d\d:\d\dZ', row['created_at']), 'Scope metadata mismatch')
    require(rows == sorted(rows, key=lambda r: (r['created_at'], r['id']), reverse=True),
            'Scope is not newest first')
    return scope


def load_scope(root=ROOT):
    path = root / SCOPE_PATH
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES, 'Scope file unavailable')
    return validate_scope(json.loads(path.read_bytes()))


def inventory(api, main_only=False):
    rows = []
    seen = set()
    for page in range(1, 101):
        batch = api.request('GET', PREFIX + '/code-scanning/analyses?per_page=100&page=' + str(page) +
                            ('&ref=refs%2Fheads%2Fmain' if main_only else ''))
        require(isinstance(batch, list) and len(batch) <= 100, 'Invalid analysis page')
        for row in batch:
            require(type(row.get('id')) is int and row['id'] not in seen, 'Duplicate or invalid analysis ID')
            require(set(FIELDS) <= set(row) and isinstance(row['ref'], str) and
                    isinstance(row['category'], str) and isinstance(row['analysis_key'], str) and
                    isinstance(row['environment'], str) and isinstance(row['tool'], dict) and
                    isinstance(row['tool'].get('name'), str) and
                    re.fullmatch(r'[0-9a-f]{40}', row['commit_sha']) and
                    (not main_only or row['ref'] == REF), 'Malformed or foreign analysis row')
            seen.add(row['id'])
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError('Analysis pagination exceeded bound')


def run_binding():
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    main_sha = os.environ.get('GITHUB_SHA', '')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == REPO and
            os.environ.get('GITHUB_REF') == REF and
            os.environ.get('GITHUB_WORKFLOW_REF') == REPO + '/' + WORKFLOW + '@' + REF and
            re.fullmatch(r'[1-9][0-9]*', run_id) and re.fullmatch(r'[0-9a-f]{40}', main_sha),
            'Recovery requires the original main retirement workflow run')
    return run_id, main_sha


def read_private(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES and
            stat.S_IMODE(path.stat().st_mode) == 0o600, 'Receipt must be a private regular file')
    return json.loads(path.read_bytes())


def read_authorization(path, scope):
    value = read_private(path)
    run_id, main_sha = run_binding()
    require(set(value) == {'schema', 'run_id', 'main_sha', 'scope_sha256', 'retained_identities'} and
            value['schema'] == 1 and value['run_id'] == run_id and value['main_sha'] == main_sha and
            value['scope_sha256'] == scope_digest(scope), 'Authorization run or scope binding mismatch')
    rows = value['retained_identities']
    approved = {row['id'] for row in scope['analyses']}
    require(isinstance(rows, list) and all(set(row) == set(FIELDS) and type(row['id']) is int and
            row['id'] > 0 and row['id'] not in approved for row in rows) and
            len({row['id'] for row in rows}) == len(rows), 'Invalid authorized retained identities')
    return value


def restore_authorization(scope, api, output):
    """Only the immutable artifact from this exact workflow run can authorize recovery."""
    run_id, main_sha = run_binding()
    name = 'codeql-retirement-authorized-' + run_id
    listing = api.request('GET', PREFIX + '/actions/runs/' + run_id + '/artifacts?name=' + name + '&per_page=100')
    artifacts = listing['artifacts']
    require(listing['total_count'] == len(artifacts) and len(artifacts) <= 1, 'Ambiguous authorization artifact')
    require(not output.exists() and not output.is_symlink(), 'Recovery output already exists')
    if not artifacts:
        return False
    artifact = artifacts[0]
    require(artifact['name'] == name and artifact['expired'] is False and
            artifact['workflow_run']['id'] == int(run_id) and artifact['workflow_run']['head_sha'] == main_sha and
            0 < artifact['size_in_bytes'] <= MAX_BYTES, 'Authorization artifact provenance mismatch')
    with tempfile.TemporaryDirectory(prefix='codeql-authorization-') as directory:
        command(['gh', 'run', 'download', run_id, '--repo', REPO, '--name', name, '--dir', directory])
        source = Path(directory) / 'authorization.json'
        require(list(Path(directory).iterdir()) == [source] and source.is_file() and not source.is_symlink(),
                'Unexpected authorization artifact files')
        source.chmod(0o600)
        value = read_authorization(source, scope)
        persist(output, value)
    return True


def authorize(scope, api, output, approved_hash, expected_main_sha, confirm_history_loss=False):
    require(approved_hash == scope_digest(scope) and confirm_history_loss,
            'Exact scope and explicit final history-loss confirmation required')
    require(os.environ.get('GITHUB_JOB') == 'retire', 'Authorization requires the protected retirement job')
    execution_guard(ROOT, api, expected_main_sha, scope)
    run_id, main_sha = run_binding()
    require(main_sha == expected_main_sha and not output.exists() and not output.is_symlink(),
            'Authorization must be new and bound to approved main')
    state = preview(scope, api)  # All 97 IDs must exist before creating durable authorization.
    value = {'schema': 1, 'run_id': run_id, 'main_sha': main_sha, 'scope_sha256': approved_hash,
             'retained_identities': state['retained_identities']}
    persist(output, value)
    return value


def read_receipt(path, scope):
    if not path.exists():
        require(not path.is_symlink(), 'Receipt is a dangling symlink')
        return None
    receipt = read_private(path)
    require(set(receipt) == {'schema', 'run_id', 'scope_sha256', 'main_sha', 'retained', 'retained_main',
                             'retained_identities', 'recovered', 'attempts'} and
            receipt['schema'] == 2 and receipt['scope_sha256'] == scope_digest(scope) and
            (receipt['run_id'], receipt['main_sha']) == run_binding(), 'Receipt binding mismatch')
    expected = {row['id'] for row in scope['analyses']}
    require(isinstance(receipt['recovered'], list) and set(receipt['recovered']) <= expected and
            all(type(value) is int for value in receipt['recovered']), 'Invalid recovered inventory')
    require(isinstance(receipt['retained_identities'], list) and
            all(set(row) == set(FIELDS) for row in receipt['retained_identities']) and
            sorted(row['id'] for row in receipt['retained_identities']) == receipt['retained'],
            'Invalid retained identities')
    attempts = receipt['attempts']
    require(isinstance(attempts, dict) and all(str(int(key)) == key and int(key) in expected and
            value in ('pending', 'complete') for key, value in attempts.items()), 'Invalid receipt attempts')
    require(isinstance(receipt['retained'], list) and len(set(receipt['retained'])) == len(receipt['retained']) and
            all(type(value) is int and value > 0 and value not in expected for value in receipt['retained']),
            'Invalid retained inventory')
    require(isinstance(receipt['retained_main'], list) and
            len(set(receipt['retained_main'])) == len(receipt['retained_main']) and
            set(receipt['retained_main']) <= set(receipt['retained']), 'Invalid retained main inventory')
    return receipt


def persist(path, value):
    require(not path.is_symlink() and path.parent.is_dir(), 'Invalid output path')
    encoded = canonical(value) + b'\n'
    require(len(encoded) <= MAX_BYTES, 'Receipt exceeds bound')
    fd, name = tempfile.mkstemp(prefix='.codeql-receipt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def preview(scope, api, receipt=None, main_only=False, authorization=None):
    validate_scope(scope)
    rows = inventory(api, main_only)
    indexed = {row['id']: row for row in rows}
    expected = {row['id']: row for row in scope['analyses']}
    legacy = {row['id']: row for row in rows if row['ref'] == REF and
              (row['category'] == OLD_CATEGORY or row['analysis_key'] == OLD_KEY)}
    require(not set(legacy) - set(expected), 'Unapproved legacy main analyses appeared')
    require(not legacy or any(row.get('deletable') is True for row in legacy.values()),
            'Legacy inventory has no approved deletable head')
    attempts = receipt['attempts'] if receipt else {}
    for analysis_id, row in expected.items():
        current = indexed.get(analysis_id)
        if current is None:
            require(str(analysis_id) in attempts or (receipt and analysis_id in receipt['recovered']) or
                    authorization is not None, 'Unattempted approved analysis is absent')
        else:
            require(identity(current) == row and analysis_id in legacy, 'Approved analysis metadata drifted')
            require(attempts.get(str(analysis_id)) != 'complete', 'Completed analysis reappeared')
    retained = sorted(set(indexed) - set(expected))
    retained_main = sorted(row['id'] for row in rows if row['ref'] == REF and row['id'] not in expected)
    if receipt:
        require(set(receipt['retained_main']) <= set(retained_main), 'Retained main analysis disappeared')
    if receipt and not main_only:
        require(set(receipt['retained']) <= set(retained), 'Retained analysis disappeared')
    for baseline in (receipt, authorization):
        if baseline:
            for row in baseline['retained_identities']:
                if not main_only or row['ref'] == REF:
                    require(row['id'] in indexed and identity(indexed[row['id']]) == row,
                            'Retained analysis identity changed or disappeared')
    main = api.request('GET', PREFIX + '/git/ref/heads/main')['object']['sha']
    require(re.fullmatch(r'[0-9a-f]{40}', main), 'Invalid main revision')
    if not main_only:
        workflow = api.request('GET', PREFIX + '/contents/.github/workflows/codeql.yml?ref=' + main)
        require(workflow.get('type') == 'file' and workflow.get('encoding') == 'base64', 'Invalid main workflow response')
        source = base64.b64decode(workflow['content'].replace('\n', ''), validate=True)
        require(hashlib.sha256(source).hexdigest() == scope['workflow_sha256'], 'Current main workflow changed')
    for baseline in (receipt, authorization):
        if baseline:
            require(baseline['main_sha'] == main, 'Main changed since receipt creation')
    require(any(row['ref'] == REF and row['commit_sha'] == main and row['analysis_key'] == CURRENT and
                row['category'] == CURRENT and row['tool']['name'] == 'CodeQL' and row.get('error') == '' and
                row.get('warning') == '' and type(row.get('rules_count')) is int and row['rules_count'] > 0
                for row in rows), 'Successful current-main Actions analysis required')
    return {'scope_sha256': scope_digest(scope), 'main_sha': main, 'remaining': sorted(legacy),
            'retained': retained, 'retained_main': retained_main,
            'retained_identities': [identity(indexed[value]) for value in retained], 'retained_sha256': hashlib.sha256(canonical(retained)).hexdigest()}


def execution_guard(root, api, expected_main_sha, scope):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == REF and
            os.environ.get('GITHUB_REPOSITORY') == REPO and bool(os.environ.get('GH_TOKEN')),
            'Execution requires credential-injected main GitHub Actions')
    require(command(['git', 'status', '--porcelain=v1', '--untracked-files=all']) == b'', 'Execute requires a clean checkout')
    head = command(['git', 'rev-parse', 'HEAD']).decode().strip()
    require(head == expected_main_sha == api.request('GET', PREFIX + '/git/ref/heads/main')['object']['sha'],
            'Execute requires the approved exact current main commit')
    for relative in (SCOPE_PATH, 'scripts/ci/codeql-retire-legacy-actions.py', '.github/workflows/codeql.yml', WORKFLOW):
        path = root / relative
        require(not path.is_symlink() and path.is_file() and
                path.read_bytes() == command(['git', 'show', 'HEAD:' + relative]), 'Execute source differs from HEAD')
    require(hashlib.sha256((root / '.github/workflows/codeql.yml').read_bytes()).hexdigest() == scope['workflow_sha256'],
            'Current scanning workflow changed')


def execute(scope, api, receipt_path, approved_hash, expected_main_sha, confirm_history_loss=False,
            authorization_path=None):
    require(approved_hash == scope_digest(scope), 'Approved scope digest mismatch')
    require(confirm_history_loss, 'Explicit final history-loss confirmation required')
    execution_guard(ROOT, api, expected_main_sha, scope)
    require(authorization_path is not None, 'Durable authorization artifact required before deletion')
    authorization = read_authorization(authorization_path, scope)
    receipt = read_receipt(receipt_path, scope)
    state = preview(scope, api, receipt, authorization=authorization if receipt is None else None)
    require(state['main_sha'] == expected_main_sha, 'Approved main revision changed')
    if receipt is None:
        receipt = {'schema': 2, 'run_id': authorization['run_id'],
                   'scope_sha256': approved_hash, 'main_sha': expected_main_sha,
                   'retained': state['retained'], 'retained_main': state['retained_main'],
                   'retained_identities': state['retained_identities'],
                   'recovered': sorted({row['id'] for row in scope['analyses']} - set(state['remaining'])),
                   'attempts': {}}
        persist(receipt_path, receipt)
    deadline = time.monotonic() + 1200
    for row in scope['analyses']:
        require(time.monotonic() < deadline, 'Execution deadline exceeded; receipt retained')
        analysis_id = row['id']
        if analysis_id not in state['remaining']:
            receipt['attempts'][str(analysis_id)] = 'complete'
            persist(receipt_path, receipt)
            continue
        current = api.request('GET', PREFIX + '/code-scanning/analyses/' + str(analysis_id))
        require(identity(current) == row and current.get('deletable') is True, 'Next approved analysis is not deletable')
        require(api.request('GET', PREFIX + '/git/ref/heads/main')['object']['sha'] == expected_main_sha,
                'Main changed before deletion')
        # Write intent durably before sending DELETE; uncertain responses never invent permission.
        receipt['attempts'][str(analysis_id)] = 'pending'
        persist(receipt_path, receipt)
        path = PREFIX + '/code-scanning/analyses/' + str(analysis_id)
        remaining = set(state['remaining']) - {analysis_id}
        confirmed = False
        reconciled = False
        for attempt in range(3):
            try:
                response = api.request('DELETE', path + ('?confirm_delete=true' if confirmed else ''))
                break
            except LastAnalysis:
                # Only this precise server condition enables final-history confirmation.
                require(not confirmed, 'Repeated final-confirmation refusal; receipt retained')
                fresh = preview(scope, api, receipt, main_only=True)
                require(fresh['remaining'] == state['remaining'], 'Legacy inventory changed before final confirmation')
                confirmed = True
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                # A timeout/status failure is not evidence of deletion or permission to retry.
                # Full inventory also protects retained PR/tool histories on this recovery path.
                fresh = preview(scope, api, receipt)
                receipt['retained'] = sorted(set(receipt['retained']) | set(fresh['retained']))
                receipt['retained_main'] = sorted(set(receipt['retained_main']) | set(fresh['retained_main']))
                receipt['retained_identities'] = fresh['retained_identities']
                persist(receipt_path, receipt)
                if set(fresh['remaining']) == remaining:
                    reconciled = True
                    break
                require(fresh['remaining'] == state['remaining'], 'Uncertain deletion changed unexpected analyses')
            current = api.request('GET', path)
            require(identity(current) == row and current.get('deletable') is True,
                    'Analysis changed before confirmed or reconciled retry')
            require(api.request('GET', PREFIX + '/git/ref/heads/main')['object']['sha'] == expected_main_sha,
                    'Main changed before confirmed or reconciled retry')
        else:
            raise RuntimeError('Deletion retry bound exhausted; pending receipt retained')
        if not reconciled:
            require(isinstance(response, dict) and set(response) == {'next_analysis_url', 'confirm_delete_url'},
                    'Unexpected deletion response; pending receipt retained')
            # Returned scope/URL violations are never caught as transport uncertainty.
            for key, url in response.items():
                if url is None:
                    continue
                match = re.fullmatch(r'https://api\.github\.com/repos/Stuhlmuller/homelab/code-scanning/analyses/(\d+)(\?confirm_delete(?:=true)?)?', url)
                require(match is not None and int(match[1]) in remaining and
                        (key == 'confirm_delete_url' or match[2] is None), 'Deletion chain left approved scope')
        after = preview(scope, api, receipt, main_only=True)
        require(set(after['remaining']) == remaining, 'Deletion readback differs from approved remaining inventory')
        receipt['retained_main'] = sorted(set(receipt['retained_main']) | set(after['retained_main']))
        receipt['retained'] = sorted(set(receipt['retained']) | set(after['retained_main']))
        identities = {row['id']: row for row in receipt['retained_identities']}
        identities.update({row['id']: row for row in after['retained_identities']})
        receipt['retained_identities'] = [identities[value] for value in sorted(identities)]
        receipt['attempts'][str(analysis_id)] = 'complete'
        persist(receipt_path, receipt)
        state = after
    require(not preview(scope, api, receipt)['remaining'], 'Legacy retirement incomplete')
    return {'scope_sha256': approved_hash, 'main_sha': expected_main_sha, 'completed': len(receipt['attempts'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    check = sub.add_parser('preview')
    check.add_argument('--output', type=Path, required=True)
    check.add_argument('--authorization', type=Path)
    restore = sub.add_parser('restore')
    restore.add_argument('--output', type=Path, required=True)
    prepare = sub.add_parser('authorize')
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--approved-scope-sha256', required=True)
    prepare.add_argument('--expected-main-sha', required=True)
    prepare.add_argument('--confirm-history-loss', action='store_true')
    apply = sub.add_parser('execute')
    apply.add_argument('--receipt', type=Path, required=True)
    apply.add_argument('--authorization', type=Path, required=True)
    apply.add_argument('--approved-scope-sha256', required=True)
    apply.add_argument('--expected-main-sha', required=True)
    apply.add_argument('--confirm-history-loss', action='store_true')
    args = parser.parse_args()
    scope, api = load_scope(), API()
    if args.mode == 'preview':
        authorization = read_authorization(args.authorization, scope) if args.authorization else None
        state = preview(scope, api, authorization=authorization)
        persist(args.output, state)
        print(json.dumps({key: state[key] for key in ('scope_sha256', 'main_sha', 'retained_sha256')}))
    elif args.mode == 'restore':
        available = restore_authorization(scope, api, args.output)
        print('available=' + str(available).lower())
    elif args.mode == 'authorize':
        authorize(scope, api, args.output, args.approved_scope_sha256,
                  args.expected_main_sha, args.confirm_history_loss)
    else:
        print(json.dumps(execute(scope, api, args.receipt, args.approved_scope_sha256,
                                 args.expected_main_sha, args.confirm_history_loss, args.authorization)))


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise SystemExit('CodeQL retirement failed; private diagnostics withheld') from None
