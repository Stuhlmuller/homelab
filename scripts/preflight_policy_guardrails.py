#!/usr/bin/env python3
"""Validate restore decryption RBAC and dual-control guardrails."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

POLICY_PATH = Path("policies/restore_decryption_policy.json")


class ValidationError(Exception):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValidationError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc


def _roles_for(principal: str, role_bindings: list[dict[str, Any]]) -> set[str]:
    for binding in role_bindings:
        if binding.get("principal") == principal:
            return set(binding.get("roles", []))
    return set()


def _validate_role_coverage(policy: dict[str, Any], role_bindings: list[dict[str, Any]]) -> None:
    required_roles = set(policy["restore_decryption"]["required_functional_roles"])
    found_roles: set[str] = set()
    for binding in role_bindings:
        found_roles.update(binding.get("roles", []))

    missing = sorted(required_roles - found_roles)
    if missing:
        raise ValidationError(
            f"missing required functional roles in role_bindings: {', '.join(missing)}"
        )


def _validate_mutual_exclusion(policy: dict[str, Any], role_bindings: list[dict[str, Any]]) -> None:
    pairs = policy["restore_decryption"].get("mutually_exclusive_roles", [])
    for binding in role_bindings:
        principal = binding.get("principal")
        roles = set(binding.get("roles", []))
        for pair in pairs:
            overlap = set(pair) & roles
            if len(overlap) == len(pair):
                joined = " + ".join(pair)
                raise ValidationError(
                    f"principal '{principal}' violates mutual exclusion for roles: {joined}"
                )


def validate_request(request: dict[str, Any], policy: dict[str, Any]) -> None:
    tier = request.get("tier")
    tiers = policy["restore_decryption"]["tiers"]
    if tier not in tiers:
        raise ValidationError(f"unknown tier '{tier}'")

    tier_policy = tiers[tier]
    role_bindings = request.get("role_bindings", [])
    approvers = request.get("approvers", [])
    requester = request.get("requester_principal")
    executor_principal = request.get("executor_principal")
    grant_ttl = request.get("grant_ttl_minutes")

    if requester is None or executor_principal is None:
        raise ValidationError("requester_principal and executor_principal are required")

    if not isinstance(grant_ttl, int):
        raise ValidationError("grant_ttl_minutes must be an integer")

    _validate_role_coverage(policy, role_bindings)
    _validate_mutual_exclusion(policy, role_bindings)

    if grant_ttl > tier_policy["max_grant_ttl_minutes"]:
        raise ValidationError(
            f"grant TTL {grant_ttl}m exceeds {tier} limit {tier_policy['max_grant_ttl_minutes']}m"
        )

    executor_roles = _roles_for(executor_principal, role_bindings)
    if "restore_executor" not in executor_roles:
        raise ValidationError(
            f"executor '{executor_principal}' is missing required role 'restore_executor'"
        )

    approver_principals: set[str] = set()
    approver_roles_flat: set[str] = set()
    for approver in approvers:
        principal = approver.get("principal")
        if principal is None:
            raise ValidationError("approver principal is required")
        approver_principals.add(principal)

        roles = set(approver.get("roles", []))
        approver_roles_flat.update(roles)
        if "restore_approver" not in roles:
            raise ValidationError(
                f"approver '{principal}' is missing required role 'restore_approver'"
            )

    missing_approver_roles = sorted(
        set(tier_policy["required_approver_roles"]) - approver_roles_flat
    )
    if missing_approver_roles:
        raise ValidationError(
            "missing tier-required approver roles: " + ", ".join(missing_approver_roles)
        )

    if tier_policy.get("require_distinct_requester_approver_executor", False):
        if requester == executor_principal:
            raise ValidationError("requester and executor must be different principals")

        if requester in approver_principals:
            raise ValidationError("requester cannot also be an approver")

        if executor_principal in approver_principals:
            raise ValidationError("executor cannot also be an approver")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Path to restore request JSON")
    args = parser.parse_args()

    policy = _load_json(POLICY_PATH)
    request = _load_json(Path(args.request))

    try:
        validate_request(request, policy)
    except ValidationError as exc:
        print(f"FAIL: {exc}")
        return 1

    print("PASS: restore decryption guardrails satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
