#!/usr/bin/env python3
"""Guard the AzureAD SAML module's human object-ID input validations."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VARIABLES = ROOT / "IaC/modules/azuread-saml-application/variables.tf"
EXPECTED_FIELDS = {"owner_user_object_ids", "allowed_user_object_ids"}
EXPECTED_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def main() -> int:
    source = VARIABLES.read_text(encoding="utf-8")
    matches = re.findall(
        r"for object_id in values\(var\.([a-z_]+)\)\s*:\s*can\(regex\(\"([^\"]+)\", object_id\)\)",
        source,
    )
    patterns = dict(matches)
    if set(patterns) != EXPECTED_FIELDS:
        raise SystemExit("Expected both human object-ID validations in the SAML module.")
    if any(pattern != EXPECTED_PATTERN for pattern in patterns.values()):
        raise SystemExit("Owner and allowed-user inputs must use the canonical UUID shape.")

    valid_uuid = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
    malformed_uuid = "08dfba7f-71ea-4eae-b3fb6cb2ad45"
    for field, pattern in patterns.items():
        if re.fullmatch(pattern, valid_uuid) is None:
            raise SystemExit(f"{field} rejected a standard Entra object ID.")
        if re.fullmatch(pattern, malformed_uuid) is not None:
            raise SystemExit(f"{field} accepted a UUID missing one four-character group.")

    print("AzureAD SAML owner and allowed-user UUID validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
