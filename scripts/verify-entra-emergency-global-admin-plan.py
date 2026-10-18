#!/usr/bin/env python3
"""Reject unsafe saved plans for the Entra emergency Global Administrator unit."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


EXPECTED = {
    "random_password.initial": "random_password",
    "azuread_user.this": "azuread_user",
    "azuread_directory_role_assignment.global_administrator": "azuread_directory_role_assignment",
}
GLOBAL_ADMINISTRATOR_ROLE_TEMPLATE_ID = "62e90394-69f5-4237-9190-012177145e10"


class PlanError(Exception):
    """A deliberately non-sensitive saved-plan validation failure."""


def fail(message: str) -> None:
    raise PlanError(message)


def managed_changes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        fail("saved plan does not contain resource changes")

    managed: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            fail("saved plan has an invalid resource change")
        if change.get("mode") == "managed":
            managed.append(change)
    return managed


def configured_resources(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configuration = plan.get("configuration")
    root_module = configuration.get("root_module") if isinstance(configuration, dict) else None
    resources = root_module.get("resources") if isinstance(root_module, dict) else None
    if not isinstance(resources, list):
        fail("saved plan does not contain root resource configuration")

    result: dict[str, dict[str, Any]] = {}
    for resource in resources:
        address = resource.get("address") if isinstance(resource, dict) else None
        if not isinstance(address, str) or address in result:
            fail("saved plan has invalid root resource configuration")
        result[address] = resource
    return result


def initial_domain(plan: dict[str, Any]) -> str:
    changes = plan.get("resource_changes")
    matches = [resource for resource in changes if isinstance(resource, dict)
               and resource.get("address") == "data.azuread_domains.tenant"] if isinstance(changes, list) else []
    if len(matches) != 1:
        fail("saved plan does not contain the reviewed tenant-domain read")
    resource = matches[0]
    change = resource.get("change")
    if (resource.get("mode") != "data" or resource.get("type") != "azuread_domains"
            or not isinstance(change, dict) or change.get("actions") != ["read"]
            or not isinstance(change.get("after"), dict)):
        fail("saved plan does not preserve the reviewed tenant-domain read")
    domains = change["after"].get("domains")
    candidates = [domain for domain in domains if isinstance(domain, dict)
                  and domain.get("initial") is True] if isinstance(domains, list) else []
    if len(candidates) != 1:
        fail("saved plan does not identify one initial tenant domain")
    domain = candidates[0]
    name = domain.get("domain_name")
    if (not isinstance(name, str) or domain.get("verified") is not True
            or domain.get("authentication_type") != "Managed"
            or not name.casefold().endswith(".onmicrosoft.com")):
        fail("saved plan does not preserve the reviewed initial tenant domain")
    return name


def expression_references(resource: dict[str, Any], name: str, expected: set[str]) -> None:
    expressions = resource.get("expressions")
    expression = expressions.get(name) if isinstance(expressions, dict) else None
    references = expression.get("references") if isinstance(expression, dict) else None
    if not isinstance(references, list) or set(references) != expected:
        fail("saved plan does not preserve the reviewed resource linkage")


def validate(plan: dict[str, Any]) -> None:
    managed = managed_changes(plan)
    if len(managed) != len(EXPECTED):
        fail("saved plan must contain exactly the three approved managed creates")

    by_address: dict[str, dict[str, Any]] = {}
    unknown_by_address: dict[str, dict[str, Any]] = {}
    sensitive_by_address: dict[str, dict[str, Any]] = {}
    for resource in managed:
        address = resource.get("address")
        change = resource.get("change")
        if not isinstance(address, str) or not isinstance(change, dict):
            fail("saved plan has an invalid managed resource change")
        if address not in EXPECTED or address in by_address:
            fail("saved plan contains an unapproved managed resource")
        if resource.get("type") != EXPECTED[address]:
            fail("saved plan contains an unexpected managed resource type")
        if change.get("actions") != ["create"]:
            fail("saved plan managed resources must be create-only")
        if resource.get("previous_address") is not None or change.get("importing") is not None:
            fail("saved plan must not import or move managed resources")
        if (change.get("before") is not None or not isinstance(change.get("after"), dict)
                or not isinstance(change.get("after_unknown"), dict)
                or not isinstance(change.get("after_sensitive"), dict)):
            fail("saved plan managed creates must not have prior state")
        by_address[address] = change["after"]
        unknown_by_address[address] = change["after_unknown"]
        sensitive_by_address[address] = change["after_sensitive"]

    if set(by_address) != set(EXPECTED):
        fail("saved plan is missing an approved managed resource")

    configuration = configured_resources(plan)
    if not set(EXPECTED) <= set(configuration):
        fail("saved plan is missing approved root resource configuration")

    expected_upn = f"homelab-emergency-admin@{initial_domain(plan)}"
    password = by_address["random_password.initial"]
    if any(password.get(name) != value for name, value in {
        "length": 40, "min_lower": 3, "min_upper": 3, "min_numeric": 3, "min_special": 3,
        "override_special": "!@#%*-_+=",
    }.items()) or unknown_by_address["random_password.initial"].get("result") is not True \
            or sensitive_by_address["random_password.initial"].get("result") is not True:
        fail("saved plan does not preserve the reviewed emergency password policy")

    user = by_address["azuread_user.this"]
    user_principal_name = user.get("user_principal_name")
    if user_principal_name != expected_upn:
        fail("emergency administrator must use the reviewed cloud-only sign-in name")
    if any(user.get(name) is not value for name, value in {
        "account_enabled": True,
        "force_password_change": True,
        "disable_strong_password": False,
        "disable_password_expiration": True,
    }.items()) or user.get("display_name") != "Homelab emergency administrator" or user.get("mail_nickname") != "homelab-emergency-admin" \
            or "password" in user or unknown_by_address["azuread_user.this"].get("password") is not True \
            or sensitive_by_address["azuread_user.this"].get("password") is not True:
        fail("saved plan does not preserve the reviewed emergency administrator settings")
    expression_references(configuration["azuread_user.this"], "user_principal_name", {"local.user_principal_name"})
    expression_references(configuration["azuread_user.this"], "password", {
        "random_password.initial", "random_password.initial.result",
    })

    role_assignment = by_address["azuread_directory_role_assignment.global_administrator"]
    if role_assignment.get("role_id") != GLOBAL_ADMINISTRATOR_ROLE_TEMPLATE_ID:
        fail("saved plan must assign only the Global Administrator role template")
    if role_assignment.get("directory_scope_id") != "/":
        fail("saved plan must assign the approved directory scope")
    if ("principal_object_id" in role_assignment
            or unknown_by_address["azuread_directory_role_assignment.global_administrator"].get("principal_object_id") is not True):
        fail("saved plan must assign Global Administrator only to the new emergency account")
    expression_references(configuration["azuread_directory_role_assignment.global_administrator"], "principal_object_id", {
        "azuread_user.this", "azuread_user.this.object_id",
    })


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <saved-plan.json>", file=sys.stderr)
        return 2

    try:
        plan = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            fail("saved plan must be a JSON object")
        validate(plan)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("Entra emergency administrator saved-plan check failed: unreadable JSON.", file=sys.stderr)
        return 1
    except PlanError as error:
        print(f"Entra emergency administrator saved-plan check failed: {error}.", file=sys.stderr)
        return 1

    print("Entra emergency administrator saved-plan check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
