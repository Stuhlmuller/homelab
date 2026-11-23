#!/usr/bin/env python3
"""Discover affected Terragrunt units by repository-relative path."""

import json
import re
import subprocess
from pathlib import Path

DEPLOYMENT = Path("IaC/homelab/us-west-2")
CATALOG = Path("IaC/terragrunt-catalog/units")


def affected_units(components):
    paths = set()
    for component in components:
        if component["type"] != "unit":
            continue
        path = component["path"]
        # These paths are passed back into Terragrunt's filter grammar.
        if not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)*", path, re.ASCII) or (
            {"..", "."} & set(path.split("/"))
        ):
            raise ValueError(f"Unexpected affected unit path: {path!r}")
        paths.add(Path(path))

    # Terragrunt reports a changed catalog configuration as a unit. Generated
    # configurations are verbatim copies, so include its deployed instances.
    templates = set()
    for path in paths:
        config = path / "terragrunt.hcl"
        if path.is_relative_to(CATALOG) and config.is_file():
            templates.add(config.read_bytes())
    if templates:
        paths.update(config.parent for config in DEPLOYMENT.rglob("terragrunt.hcl")
                     if ".terragrunt-cache" not in config.parts
                     and config.read_bytes() in templates)
    return sorted(paths)


def main():
    output = subprocess.check_output(
        ["terragrunt", "find", "--filter-affected", "--json", "--log-level", "warn"], text=True
    )
    for unit in affected_units(json.loads(output)):
        print(unit)


if __name__ == "__main__":
    main()
