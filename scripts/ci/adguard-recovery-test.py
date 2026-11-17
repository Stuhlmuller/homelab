#!/usr/bin/env python3
"""Recovery boundaries with synthetic credentials; no AWS or Docker calls."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'scripts/adguard-recovery.py')
RECOVERY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RECOVERY)


class RecoveryTests(unittest.TestCase):
    def test_wrong_account_stops_before_secret_read(self):
        with patch.object(RECOVERY.CHECK, 'run', return_value='000000000000') as run:
            with self.assertRaises(RECOVERY.CHECK.Failure):
                RECOVERY.credential()
            self.assertEqual(run.call_count, 1)

    def test_exact_protected_parameter_and_metadata_only(self):
        account = re.search(r'account_id\s*=\s*"(\d{12})"',
                            (ROOT / 'IaC/application-backup-storage.hcl').read_text())[1]
        parameter = {'ARN': f'arn:aws:ssm:us-west-2:{account}:parameter/homelab/adguard/admin-password',
                     'Name': RECOVERY.PARAMETER, 'Type': 'SecureString', 'Version': 1,
                     'Value': 'fixture1' * 4}
        with patch.object(RECOVERY.CHECK, 'run', side_effect=[account, json.dumps({'Parameter': parameter})]):
            password, metadata = RECOVERY.credential()
        self.assertEqual(password, parameter['Value'])
        self.assertEqual(metadata, {'ARN': parameter['ARN'], 'Version': 1})
        for field, invalid in [('ARN', 'wrong'), ('Name', '/wrong'), ('Type', 'String'),
                               ('Version', True), ('Version', 0), ('Value', 'invalid')]:
            changed = copy.deepcopy(parameter); changed[field] = invalid
            with self.subTest(field=field), patch.object(RECOVERY.CHECK, 'run',
                    side_effect=[account, json.dumps({'Parameter': changed})]):
                with self.assertRaises(RECOVERY.CHECK.Failure):
                    RECOVERY.credential()

    def test_remote_docker_is_rejected(self):
        for endpoint in ('tcp://example.invalid:2376', 'ssh://example.invalid'):
            with patch.object(RECOVERY.CHECK, 'run', return_value=endpoint):
                with self.assertRaises(RECOVERY.CHECK.Failure): RECOVERY.LocalDocker()

    def test_invalid_query_ports_rejected_before_command(self):
        with patch.object(RECOVERY.CHECK, 'run') as run:
            for port in (0, 65536, True, '53'):
                with self.assertRaises(RECOVERY.CHECK.Failure):
                    RECOVERY.CHECK.dns_answer('127.0.0.1', 'example.com', 'A', port=port)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
