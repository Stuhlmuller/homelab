#!/usr/bin/env python3
"""Exercise retirement plan boundaries with synthetic, non-secret plans."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).with_name("wazuh-retire-plan.py")
SPEC = importlib.util.spec_from_file_location("retirement", HELPER)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
NAMES = sorted(GUARD.NAMES)
KEPT = [GUARD.SSM_PREFIX + "/homelab/test/one", GUARD.SSM_PREFIX + "/homelab/test/two"]


def plan(resources=()):
    return {"format_version": "1.2", "complete": True, "errored": False,
            "resource_changes": list(resources)}


def app():
    manifest = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
                "metadata": {"name": "wazuh", "namespace": "argocd"}}
    return {"address": "kubernetes_manifest.this", "mode": "managed",
            "type": "kubernetes_manifest", "name": "this",
            "change": {"actions": ["delete"], "after": None,
                       "before": {"manifest": manifest, "object": copy.deepcopy(manifest)}}}


def parameter(name=NAMES[0], kind="aws_ssm_parameter"):
    before = ({"name": name, "type": "SecureString", "region": "us-west-2",
               "arn": GUARD.SSM_PREFIX + name, "value": "test"}
              if kind == "aws_ssm_parameter" else {"length": 40, "result": "test"})
    return {"address": f'{kind}.generated[{json.dumps(name)}]', "mode": "managed",
            "type": kind, "name": "generated", "index": name,
            "change": {"actions": ["delete"], "before": before, "after": None}}


def policy(arns):
    return json.dumps({"Version": "2012-10-17", "Statement": [{
        "Sid": "ReadManagedSsmParameters", "Effect": "Allow",
        "Action": ["ssm:GetParameters", "ssm:GetParameter"], "Resource": arns,
    }]})


def reader(chunk, old, new, actions=("update",)):
    name = f"homelab-ssm-parameter-reader-{chunk}"
    before = {"name": name, "arn": f"arn:aws:iam::716182248480:policy/{name}",
              "policy": policy(old), "tags": {"Project": "homelab"}}
    after = dict(before, policy=policy(new))
    return {"address": f'aws_iam_policy.parameter_reader["{chunk}"]',
            "mode": "managed", "type": "aws_iam_policy", "name": "parameter_reader",
            "index": chunk, "change": {"actions": list(actions), "before": before,
                                       "after": after, "after_unknown": {"policy": False}}}


def complete_ssm():
    arns = sorted(GUARD.ARNS)
    resources = [parameter(name, kind) for name in NAMES
                 for kind in ("aws_ssm_parameter", "random_password")]
    # Existing ARNs may legitimately move between deterministic policy chunks.
    resources += [reader("00", [KEPT[0], *arns[:2]], [KEPT[1]]),
                  reader("01", [KEPT[1], *arns[2:]], [KEPT[0]])]
    return plan(resources)


class RetirementPlanTest(unittest.TestCase):
    def rejects(self, mode, candidate):
        with self.assertRaises((ValueError, TypeError, KeyError, AttributeError)):
            GUARD.validate(mode, candidate)

    def test_app_delete_noop_and_empty_rerun(self):
        GUARD.validate("app", plan([app()]))
        unchanged = app()
        unchanged["change"].update(actions=["no-op"], after=unchanged["change"]["before"])
        GUARD.validate("app", plan([unchanged]))
        GUARD.validate("app", plan())
        GUARD.validate("app", {"format_version": "1.2"})

    def test_app_identity_and_state_object_must_match(self):
        for representation in ("manifest", "object"):
            for field, wrong in (("name", "other"), ("namespace", "default")):
                with self.subTest(representation=representation, field=field):
                    item = app()
                    item["change"]["before"][representation]["metadata"][field] = wrong
                    self.rejects("app", plan([item]))
        for field, wrong in (("kind", "Namespace"), ("apiVersion", "v1")):
            item = app()
            item["change"]["before"]["manifest"][field] = wrong
            self.rejects("app", plan([item]))
        item = app()
        item["address"] = "module.other.kubernetes_manifest.this"
        self.rejects("app", plan([item]))
        self.rejects("app", plan([app(), parameter()]))

    def test_complete_partial_and_already_retired_ssm(self):
        GUARD.validate("ssm", complete_ssm())
        GUARD.validate("ssm", plan([parameter()]))
        GUARD.validate("ssm", plan([parameter(kind="random_password")]))
        GUARD.validate("ssm", plan([reader("00", KEPT, KEPT, ("no-op",))]))
        GUARD.validate("ssm", plan())

    def test_parameter_identity_is_exact(self):
        for field, wrong in (("name", "/homelab/other/password"), ("type", "String"),
                             ("region", "us-east-1"),
                             ("arn", GUARD.SSM_PREFIX.replace("716182248480", "000000000000") + NAMES[0])):
            with self.subTest(field=field):
                item = parameter()
                item["change"]["before"][field] = wrong
                self.rejects("ssm", plan([item]))
        for field in ("name", "type", "region", "arn"):
            item = parameter()
            del item["change"]["before"][field]
            self.rejects("ssm", plan([item]))
        for kind in ("aws_ssm_parameter", "random_password"):
            self.rejects("ssm", plan([parameter("/homelab/other/password", kind)]))
            item = parameter(kind=kind)
            item["address"] = "module.other." + item["address"]
            self.rejects("ssm", plan([item]))
            item = parameter(kind=kind)
            item["index"] = NAMES[1]
            self.rejects("ssm", plan([item]))

    def test_other_changes_replacements_and_unknowns_rejected(self):
        for mode, factory in (("app", app), ("ssm", parameter)):
            for actions in (["create"], ["update"], ["delete", "create"], ["create", "delete"], ["forget"], ["read"]):
                item = factory()
                item["change"]["actions"] = actions
                self.rejects(mode, plan([item]))
            for unknown in (True, {"object": {"metadata": True}}, [False, True]):
                item = factory()
                item["change"]["after_unknown"] = unknown
                self.rejects(mode, plan([item]))
            item = factory()
            item["change"]["after"] = {}
            self.rejects(mode, plan([item]))
            item = factory()
            del item["change"]["after"]
            self.rejects(mode, plan([item]))
            self.rejects(mode, plan([factory(), factory()]))
        item = parameter()
        item.update(type="aws_kms_key", address="aws_kms_key.this")
        self.rejects("ssm", plan([item]))
        self.rejects("ssm", plan([app()]))
        item = app()
        item["previous_address"] = "kubernetes_manifest.other"
        self.rejects("app", plan([item]))
        item = app()
        item["change"]["importing"] = {"id": "test"}
        self.rejects("app", plan([item]))

    def test_iam_removes_only_authorized_permissions(self):
        for replacement in ([KEPT[0]], [*KEPT, GUARD.SSM_PREFIX + "/homelab/test/new"],
                            [*KEPT, sorted(GUARD.ARNS)[0]], ["*"]):
            with self.subTest(replacement=replacement):
                item = reader("00", [*KEPT, *sorted(GUARD.ARNS)], replacement)
                self.rejects("ssm", plan([item]))
        # A no-op chunk still contributes its unchanged permissions to the union.
        GUARD.validate("ssm", plan([
            reader("00", [*KEPT, *sorted(GUARD.ARNS)], [KEPT[0]]),
            reader("01", [KEPT[1]], [KEPT[1]], ("no-op",)),
        ]))
        self.rejects("ssm", plan([reader("00", [*KEPT, *sorted(GUARD.ARNS)],
                                        [*KEPT, *sorted(GUARD.ARNS)], ("no-op",))]))

    def test_iam_headers_attributes_and_actions_cannot_change(self):
        base = reader("00", [*KEPT, *sorted(GUARD.ARNS)], KEPT)
        for key, value in (("Version", "2008-10-17"), ("Id", "new")):
            item = copy.deepcopy(base)
            document = json.loads(item["change"]["after"]["policy"])
            document[key] = value
            item["change"]["after"]["policy"] = json.dumps(document)
            self.rejects("ssm", plan([item]))
        for key, value in (("Sid", "Other"), ("Effect", "Deny"),
                           ("Action", ["ssm:*"]), ("Condition", {}), ("Principal", "*")):
            item = copy.deepcopy(base)
            document = json.loads(item["change"]["after"]["policy"])
            document["Statement"][0][key] = value
            item["change"]["after"]["policy"] = json.dumps(document)
            self.rejects("ssm", plan([item]))
        for field, value in (("tags", {}), ("name", "other"), ("description", "new")):
            item = copy.deepcopy(base)
            item["change"]["after"][field] = value
            self.rejects("ssm", plan([item]))
        for actions in (["create"], ["delete"], ["delete", "create"]):
            item = copy.deepcopy(base)
            item["change"]["actions"] = actions
            self.rejects("ssm", plan([item]))
        item = copy.deepcopy(base)
        item["change"]["after_unknown"] = {"policy": True}
        self.rejects("ssm", plan([item]))
        item = copy.deepcopy(base)
        item["address"] = 'aws_iam_policy.other["00"]'
        self.rejects("ssm", plan([item]))

    def test_read_only_data_and_unrelated_noops_do_not_expand_scope(self):
        read = {"address": "data.aws_caller_identity.current", "mode": "data",
                "type": "aws_caller_identity", "change": {"actions": ["read"], "after_unknown": True}}
        noop = {"address": "aws_kms_key.this[0]", "mode": "managed",
                "type": "aws_kms_key", "change": {"actions": ["no-op"]}}
        for mode in ("app", "ssm"):
            GUARD.validate(mode, plan([read, noop]))
            invalid = copy.deepcopy(read)
            invalid["change"]["actions"] = ["delete"]
            self.rejects(mode, plan([invalid]))

    def test_incomplete_and_malformed_plans_fail_closed(self):
        for candidate in ({}, [], None, {"format_version": "2.0"}, {"format_version": "1.invalid"}):
            self.rejects("app", candidate)
        for key, value in (("errored", True), ("complete", False),
                           ("deferred_changes", [{"reason": "unknown"}]), ("resource_changes", {})):
            candidate = plan()
            candidate[key] = value
            self.rejects("ssm", candidate)
        with self.assertRaises(ValueError):
            GUARD.parse_json('{"format_version":"1.2","format_version":"2.0"}')

    def test_cli_never_prints_plan_values_paths_or_parser_errors(self):
        marker = "private test marker"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / marker
            for content in (marker, json.dumps({"format_version": "1.2", "resource_changes": [marker]}),
                            '{"format_version":"1.2","resource_changes":NaN}'):
                path.write_text(content)
                result = subprocess.run([sys.executable, "-I", str(HELPER), "ssm", str(path)],
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "Wazuh retirement plan rejected; private details withheld.\n")
            path.write_text(json.dumps(complete_ssm()))
            result = subprocess.run([sys.executable, "-I", str(HELPER), "ssm", str(path)],
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.stdout, "Wazuh retirement plan matches the fixed removal scope.\n")


if __name__ == "__main__":
    unittest.main()
