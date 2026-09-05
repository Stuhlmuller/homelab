"""Offline safety checks for key migration; no AWS calls or real secrets."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "migration", Path(__file__).with_name("migrate-ssm-aws-managed.py")
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationSafety(unittest.TestCase):
    def run_case(self, *, changed=False, wrong_key=False, migrated=False, write=True):
        config = {
            "region": "us-west-2", "target_key_alias": "alias/aws/ssm",
            "source_key_id": "old", "parameters": ["/homelab/test"],
        }
        writes = []
        value = "changed-fixture" if changed else "fixture-only"

        def aws(region, service, operation, **request):
            if operation == "describe-parameters":
                return {"Parameters": [{"Name": "/homelab/test", "Tier": "Standard",
                                        "KeyId": "alias/aws/ssm" if migrated else "old"}]}
            if operation == "describe-key":
                if request["KeyId"] == "alias/aws/ssm":
                    return {"KeyMetadata": {"KeyManager": "AWS", "KeyId": "managed", "Arn": "managed-arn"}}
                return {"KeyMetadata": {"KeyId": "unexpected" if wrong_key else "old"}}
            if operation == "get-parameter":
                return {"Parameter": {"Value": value, "Version": 1}}
            if operation == "put-parameter":
                writes.append(request)
                return {}
            raise AssertionError(operation)

        archive = {"history": {"/homelab/test": [{"Value": "fixture-only", "Version": 1}]}}
        with patch.object(migration, "read_archive", return_value=archive), patch.object(migration, "aws", side_effect=aws):
            if changed or wrong_key:
                with self.assertRaises(AssertionError):
                    migration.migrate(config, write)
                self.assertEqual(writes, [])
            else:
                migration.migrate(config, write)
        return writes

    def test_preserves_value_and_tier(self):
        writes = self.run_case()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["Value"], "fixture-only")
        self.assertEqual(writes[0]["KeyId"], "alias/aws/ssm")
        self.assertEqual(writes[0]["Tier"], "Standard")

    def test_changed_value_aborts_before_write(self):
        self.run_case(changed=True)

    def test_unexpected_source_key_aborts_before_write(self):
        self.run_case(wrong_key=True)

    def test_rerun_and_verification_never_rewrite_migrated_values(self):
        self.assertEqual(self.run_case(migrated=True), [])
        self.assertEqual(self.run_case(migrated=True, write=False), [])


if __name__ == "__main__":
    unittest.main()
