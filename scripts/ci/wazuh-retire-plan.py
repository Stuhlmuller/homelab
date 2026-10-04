#!/usr/bin/env python3
"""Check the fixed Wazuh retirement scope without displaying private plan values."""
import json
from pathlib import Path
import re
import sys

NAMES = frozenset(f"/homelab/wazuh/{name}" for name in (
    "indexer-admin-password", "api-password", "dashboard-password",
    "agent-enrollment-password",
))
SSM_PREFIX = "arn:aws:ssm:us-west-2:716182248480:parameter"
ARNS = frozenset(SSM_PREFIX + name for name in NAMES)
IAM_ADDRESS = re.compile(r'aws_iam_policy\.parameter_reader\["(0[0-9])"\]')


def require(condition):
    if not condition:
        raise ValueError("Plan outside fixed retirement scope")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda _: require(False))


def known(value):
    if isinstance(value, dict):
        return all(known(item) for item in value.values())
    if isinstance(value, list):
        return all(known(item) for item in value)
    return value is False or value is None


def parameter_name(resource):
    name = resource.get("index")
    require(name in NAMES)
    require(resource.get("name") == "generated")
    require(resource["address"] == f'{resource["type"]}.generated[{json.dumps(name)}]')
    return name


def app_identity(before):
    require(isinstance(before, dict))
    manifest = before["manifest"]
    require(isinstance(manifest, dict))
    candidates = [manifest]
    if "object" in before:
        candidates.append(before["object"])
    for candidate in candidates:
        require(isinstance(candidate, dict))
        require(candidate.get("apiVersion") == "argoproj.io/v1alpha1")
        require(candidate.get("kind") == "Application")
        require(candidate.get("metadata", {}).get("name") == "wazuh")
        require(candidate.get("metadata", {}).get("namespace") == "argocd")


def policy_resources(value):
    require(isinstance(value, str))
    policy = parse_json(value)
    require(isinstance(policy, dict) and set(policy) == {"Version", "Statement"})
    require(policy["Version"] == "2012-10-17")
    statements = policy["Statement"]
    require(isinstance(statements, list) and len(statements) == 1)
    statement = statements[0]
    require(isinstance(statement, dict))
    require(set(statement) == {"Sid", "Effect", "Action", "Resource"})
    require(statement["Sid"] == "ReadManagedSsmParameters")
    require(statement["Effect"] == "Allow")
    require(isinstance(statement["Action"], list))
    require(len(statement["Action"]) == 2)
    require(set(statement["Action"]) == {"ssm:GetParameter", "ssm:GetParameters"})
    resources = statement["Resource"]
    if isinstance(resources, str):
        resources = [resources]
    require(isinstance(resources, list) and bool(resources))
    require(all(isinstance(arn, str) and arn.startswith(SSM_PREFIX + "/homelab/")
                and "*" not in arn and "?" not in arn for arn in resources))
    require(len(set(resources)) == len(resources))
    return set(resources)


def reader_change(resource):
    match = IAM_ADDRESS.fullmatch(resource["address"])
    require(match is not None)
    chunk = match[1]
    require(resource.get("name") == "parameter_reader" and resource.get("index") == chunk)
    change = resource["change"]
    require(change["actions"] in (["update"], ["no-op"]))
    require(known(change.get("after_unknown", {})))
    before, after = change["before"], change["after"]
    require(isinstance(before, dict) and isinstance(after, dict))
    expected_name = f"homelab-ssm-parameter-reader-{chunk}"
    require(before.get("name") == expected_name)
    require(before.get("arn") == f"arn:aws:iam::716182248480:policy/{expected_name}")
    require({k: v for k, v in before.items() if k != "policy"}
            == {k: v for k, v in after.items() if k != "policy"})
    # The native policy shape is fixed above, so moving an ARN between chunks
    # cannot grant it a different Action, Effect, Sid, Condition or Principal.
    return policy_resources(before["policy"]), policy_resources(after["policy"])


def validate(mode, plan):
    require(mode in {"app", "ssm"})
    require(isinstance(plan, dict))
    require(isinstance(plan.get("format_version"), str)
            and re.fullmatch(r"1\.\d+", plan["format_version"]) is not None)
    require(plan.get("errored", False) is False)
    require(plan.get("complete", True) is True)
    require(not plan.get("deferred_changes"))
    changes = plan.get("resource_changes", [])
    require(isinstance(changes, list))
    addresses = set()
    before_permissions, after_permissions = set(), set()
    for resource in changes:
        require(isinstance(resource, dict))
        address = resource["address"]
        require(isinstance(address, str) and address not in addresses)
        addresses.add(address)
        change = resource["change"]
        require(isinstance(change, dict))
        require(resource.get("previous_address") is None and not change.get("importing"))
        actions = change["actions"]
        if resource.get("mode") == "data":
            require(actions in (["read"], ["no-op"]))
            continue
        require(resource.get("mode") == "managed")
        if mode == "ssm" and resource.get("type") == "aws_iam_policy" and IAM_ADDRESS.fullmatch(address):
            before, after = reader_change(resource)
            before_permissions |= before
            after_permissions |= after
            continue
        if actions == ["no-op"]:
            continue
        require(actions == ["delete"] and change.get("after", "missing") is None)
        require(known(change.get("after_unknown", {})))
        require(isinstance(change.get("before"), dict))
        if mode == "app":
            require(address == "kubernetes_manifest.this")
            require(resource.get("type") == "kubernetes_manifest" and resource.get("name") == "this")
            app_identity(change["before"])
        else:
            require(resource.get("type") in {"aws_ssm_parameter", "random_password"})
            name = parameter_name(resource)
            if resource["type"] == "aws_ssm_parameter":
                before = change["before"]
                require(before.get("name") == name and before.get("type") == "SecureString")
                require(before.get("region") == "us-west-2")
                require(before.get("arn") == SSM_PREFIX + name)
    if mode == "ssm":
        require(after_permissions == before_permissions - ARNS)


def main():
    try:
        require(len(sys.argv) == 3)
        validate(sys.argv[1], parse_json(Path(sys.argv[2]).read_text()))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("Wazuh retirement plan rejected; private details withheld.", file=sys.stderr)
        return 1
    print("Wazuh retirement plan matches the fixed removal scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
