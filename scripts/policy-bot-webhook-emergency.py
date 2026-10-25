#!/usr/bin/env python3
"""One-time Policy Bot callback rollback from the reviewed, unmerged recovery PR.

Run only after explicit user approval while the required Policy Bot check is
unavailable. This script cannot select another URL, PR branch, or repository.
"""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = 'Stuhlmuller/homelab'
BRANCH = 'codex/policy-bot-webhook-rollback'
FAILED_DELIVERY_ID = 3850311852634406912
FAILED_PR = 1679
FAILED_CHECK_SHA = '6cfc2b4e48d7ff56df08fe36ca6ff78d49af05ec'
REDELIVERY_RECEIPT = Path.home() / '.local/state/homelab/policy-bot-webhook-redelivery.json'


def command(*args):
    result = subprocess.run(args, capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise RuntimeError('Emergency source verification failed; private output withheld')
    return result.stdout


def verify_reviewed_head(expected_head):
    if not re.fullmatch(r'[0-9a-f]{40}', expected_head or ''):
        raise RuntimeError('Full reviewed PR head SHA is required')
    if command('git', '-C', str(ROOT), 'status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none'):
        raise RuntimeError('Emergency execution requires a clean checkout')
    head = command('git', '-C', str(ROOT), 'rev-parse', 'HEAD').decode().strip()
    if head != expected_head:
        raise RuntimeError('Checkout does not match the reviewed PR head')
    for path in ('scripts/policy-bot-webhook.py', 'scripts/policy-bot-webhook-emergency.py'):
        command('git', '-C', str(ROOT), 'cat-file', '-e', f'HEAD:{path}')
    commit = json.loads(command('gh', 'api', f'repos/{REPO}/commits/{expected_head}'))
    if commit.get('sha') != expected_head or commit.get('commit', {}).get('verification', {}).get('verified') is not True:
        raise RuntimeError('Recovery PR head is not GitHub-verified signed')


def verify_emergency_source(expected_main, expected_head):
    if not re.fullmatch(r'[0-9a-f]{40}', expected_main or ''):
        raise RuntimeError('Full fresh main SHA is required for mutation')
    if expected_main == expected_head:
        raise RuntimeError('Emergency execution requires a distinct reviewed PR head')
    verify_reviewed_head(expected_head)
    remote_main = command('git', 'ls-remote', 'https://github.com/Stuhlmuller/homelab.git', 'refs/heads/main').decode().split()[0]
    if remote_main != expected_main:
        raise RuntimeError('Remote main differs from the reviewed SHA')
    if command('git', '-C', str(ROOT), 'merge-base', expected_main, expected_head).decode().strip() != expected_main:
        raise RuntimeError('The reviewed PR must descend from current main')
    pull_path = ('repos/' + REPO + '/pulls?head=Stuhlmuller%3A'
                 + BRANCH.replace('/', '%2F') + '&state=open')
    pulls = json.loads(command('gh', 'api', pull_path))
    if len(pulls) != 1:
        raise RuntimeError('Expected exactly one open recovery PR from the fixed branch')
    pull = pulls[0]
    if (pull.get('state') != 'open' or pull.get('head', {}).get('sha') != expected_head
            or pull['head'].get('ref') != BRANCH or pull['head']['repo']['full_name'] != REPO
            or pull.get('base', {}).get('ref') != 'main' or pull['base'].get('sha') != expected_main):
        raise RuntimeError('Recovery PR head or base differs from the reviewed SHAs')


def require_active_funnel(api, webhook):
    if webhook.ROLLBACK_RECEIPT.exists():
        raise RuntimeError('Emergency rollback receipt already exists; refusing a second execution')
    if api('GET', webhook.CONFIG_PATH).get('url') != webhook.URL:
        raise RuntimeError('Emergency rollback applies only to the active Funnel callback')


def matches_fixed_gate(delivery, webhook, url, redelivery):
    payload = delivery.get('request', {}).get('payload', {})
    check = payload.get('check_run', {})
    prs = check.get('pull_requests', [])
    return (delivery.get('url') == url and delivery.get('event') == 'check_run'
            and delivery.get('action') == 'completed' and delivery.get('redelivery') is redelivery
            and payload.get('action') == 'completed' and payload.get('repository', {}).get('full_name') == REPO
            and check.get('name') == 'Terragrunt Gate' and check.get('status') == 'completed'
            and check.get('conclusion') == 'success' and check.get('head_sha') == FAILED_CHECK_SHA
            and check.get('check_suite', {}).get('head_sha') == FAILED_CHECK_SHA
            and isinstance(prs, list) and [item.get('number') for item in prs] == [FAILED_PR])


def require_failed_pr_head():
    pull = json.loads(command('gh', 'api', f'repos/{REPO}/pulls/{FAILED_PR}'))
    if (pull.get('state') != 'open' or pull.get('head', {}).get('sha') != FAILED_CHECK_SHA
            or pull.get('base', {}).get('ref') != 'main'):
        raise RuntimeError('Recovery PR #1679 head changed; fixed redelivery is no longer authorized')


def redeliver_failed_gate(api, webhook):
    rollback = webhook.read_receipt(webhook.ROLLBACK_RECEIPT, webhook.PREVIOUS_URL)
    if rollback is None or REDELIVERY_RECEIPT.exists():
        raise RuntimeError('Expected one completed rollback receipt and no prior redelivery receipt')
    if api('GET', webhook.CONFIG_PATH).get('url') != webhook.PREVIOUS_URL:
        raise RuntimeError('Previous callback readback is required before redelivery')
    delivery = api('GET', f'/app/hook/deliveries/{FAILED_DELIVERY_ID}')
    guid = delivery.get('guid')
    if (delivery.get('id') != FAILED_DELIVERY_ID or delivery.get('status_code') != 500
            or not matches_fixed_gate(delivery, webhook, webhook.URL, False)
            or not isinstance(guid, str) or not guid
            or rollback['previous_delivery_id'] < FAILED_DELIVERY_ID
            or webhook.timestamp(delivery['delivered_at']) >= webhook.timestamp(rollback['started_at'])):
        raise RuntimeError('Fixed failed Gate delivery no longer matches the reviewed rollback')
    require_failed_pr_head()
    path = f'/app/hook/deliveries/{FAILED_DELIVERY_ID}/attempts'
    webhook.save_receipt(REDELIVERY_RECEIPT, {
        'delivery_id': FAILED_DELIVERY_ID, 'guid': guid,
        'started_at': datetime.now(timezone.utc).isoformat(),
    })
    if api('POST', path) != 202:
        raise RuntimeError('GitHub redelivery outcome uncertain; attempt receipt retained for read-only diagnosis')
    print('GitHub accepted one redelivery of the fixed failed Gate delivery; verify fresh 2xx separately')


def verify_redelivery(api, webhook):
    rollback = webhook.read_receipt(webhook.ROLLBACK_RECEIPT, webhook.PREVIOUS_URL)
    if rollback is None or not REDELIVERY_RECEIPT.exists():
        raise RuntimeError('Rollback and one-attempt redelivery receipts are required')
    attempt = json.loads(REDELIVERY_RECEIPT.read_text())
    if (set(attempt) != {'delivery_id', 'guid', 'started_at'}
            or attempt['delivery_id'] != FAILED_DELIVERY_ID or not isinstance(attempt['guid'], str)
            or not attempt['guid'] or webhook.timestamp(attempt['started_at']) < webhook.timestamp(rollback['started_at'])
            or webhook.timestamp(attempt['started_at']) > webhook.time.time()):
        raise RuntimeError('One-attempt redelivery receipt is invalid')
    if api('GET', webhook.CONFIG_PATH).get('url') != webhook.PREVIOUS_URL:
        raise RuntimeError('Previous callback readback is required for acceptance')
    cursor = ''
    seen = set()
    for _ in range(30):
        path = '/app/hook/deliveries?per_page=100&status=success' + ('&cursor=' + cursor if cursor else '')
        items = api('GET', path)
        for item in items:
            if (item.get('guid') != attempt['guid'] or item.get('redelivery') is not True
                    or not isinstance(item.get('id'), int) or item['id'] <= rollback['previous_delivery_id']
                    or webhook.timestamp(item['delivered_at']) < webhook.timestamp(attempt['started_at'])):
                continue
            detail = api('GET', f"/app/hook/deliveries/{item['id']}")
            status = detail.get('status_code')
            if (detail.get('id') == item['id'] and detail.get('guid') == attempt['guid']
                    and isinstance(status, int) and 200 <= status < 300
                    and matches_fixed_gate(detail, webhook, webhook.PREVIOUS_URL, True)
                    and webhook.timestamp(detail['delivered_at']) >= webhook.timestamp(attempt['started_at'])):
                print(f"Exact #1679 Gate redelivery: {item['id']}, HTTP {status}")
                break
        else:
            if len(items) < 100 or not items:
                raise RuntimeError('Exact fresh signed redelivery is not in the available success history')
            oldest = items[-1]
            if oldest.get('id') in seen or webhook.timestamp(oldest['delivered_at']) < webhook.timestamp(attempt['started_at']):
                raise RuntimeError('Exact fresh signed redelivery was not found')
            seen.add(oldest['id'])
            cursor = str(oldest['id'])
            continue
        break
    else:
        raise RuntimeError('Exact redelivery search exceeded its bounded history window')
    status = json.loads(command('gh', 'api', f'repos/{REPO}/commits/{FAILED_CHECK_SHA}/status'))
    latest = next((item for item in status.get('statuses', []) if item.get('context') == 'policy-bot: main'), None)
    if status.get('sha') != FAILED_CHECK_SHA or latest is None or latest.get('state') != 'success':
        raise RuntimeError('Exact redelivery succeeded; required policy-bot: main status on #1679 is not successful')
    print('Required policy-bot: main status on #1679 head: success')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-main', help='Fresh full SHA of remote main, required for mutation')
    parser.add_argument('--expected-head', required=True, help='Full reviewed and signed recovery PR head SHA')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--rollback', action='store_true', help='Set only the fixed previous callback')
    mode.add_argument('--redeliver', action='store_true', help='Redeliver only the fixed failed #1679 Gate delivery')
    mode.add_argument('--verify', action='store_true', help='Read only the exact redelivery and #1679 Policy Bot status')
    parser.add_argument('--execute', action='store_true', help='Perform the selected one-time action after explicit user approval')
    args = parser.parse_args()
    if args.execute == args.verify:
        raise RuntimeError('Mutating modes require --execute; read-only --verify forbids it')
    if args.verify:
        verify_reviewed_head(args.expected_head)
        current_main = command('git', 'ls-remote', 'https://github.com/Stuhlmuller/homelab.git', 'refs/heads/main').decode().split()[0]
        print('Current remote main: ' + current_main)
    else:
        verify_emergency_source(args.expected_main, args.expected_head)

    spec = importlib.util.spec_from_file_location('policy_bot_webhook', ROOT/'scripts/policy-bot-webhook.py')
    webhook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(webhook)
    app_id, key = webhook.credentials()
    api = webhook.github_client(webhook.app_jwt(app_id, key))
    if str(api('GET', '/app').get('id')) != app_id:
        raise RuntimeError('GitHub App identity does not match the configured Policy Bot identity')
    if args.rollback:
        require_active_funnel(api, webhook)
        webhook.reconcile(api, execute=True, rollback=True)
    elif args.redeliver:
        redeliver_failed_gate(api, webhook)
    else:
        verify_redelivery(api, webhook)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        if isinstance(error, RuntimeError):
            raise SystemExit(str(error)) from None
        raise SystemExit('Emergency rollback failed; credentials and private response output withheld') from None
