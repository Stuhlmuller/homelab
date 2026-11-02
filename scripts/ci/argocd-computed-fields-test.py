#!/usr/bin/env python3
"""Evaluate the real Application module's computed paths without providers/state."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "IaC/terragrunt-catalog/modules/argocd-application-kubernetes"
BASE = ["metadata.annotations", "metadata.labels", "spec.destination.name"]


def main():
    source = (MODULE / "main.tf").read_text()
    # Keep the actual HCL expression and locals; no copied Python implementation.
    locals_blocks = re.findall(r"(?ms)^locals \{.*?^\}", source)
    fields = re.findall(r"(?m)^  computed_fields\s*= (.+)$", source)
    manifest = re.findall(r'(?ms)^variable "manifest" \{.*?^\}',
                          (MODULE / "variables.tf").read_text())
    assert len(locals_blocks) == len(fields) == len(manifest) == 1
    cases = [
        ({}, []),
        ({"sources": []}, []),
        ({"sources": [{"chart": "chart"}]}, []),
        ({"sources": [{"chart": "chart"}, {"ref": "values"}]}, [0, 1]),
        ({"sources": [{"directory": {}, "path": "."}, {"ref": "values", "path": None}]}, [0, 1]),
        ({"sources": [{"chart": "chart", "path": "explicit"}, {"path": "explicit"}]}, []),
        ({"sources": [{"path": "."}, {"path": None}]}, []),
        ({"sources": [{"directory": {}, "path": "explicit"}, {"chart": "chart", "path": "."},
                      {"ref": "values"}]}, [1, 2]),
    ]
    with tempfile.TemporaryDirectory(prefix="argocd-computed-fields-") as directory:
        scratch = Path(directory)
        (scratch / "main.tf").write_text(manifest[0] + "\n" + locals_blocks[0] + "\n")
        for spec, indices in cases:
            (scratch / "terraform.tfvars.json").write_text(json.dumps({"manifest": {
                "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "spec": spec,
            }}))
            result = subprocess.run(["tofu", "console", "-no-color"], cwd=scratch,
                                    input=f"jsonencode({fields[0]})\n", text=True,
                                    capture_output=True, timeout=30, check=True)
            # Console can emit a diagnostic yet exit zero: require actual JSON.
            assert not result.stderr.strip(), result.stderr
            actual = json.loads(json.loads(result.stdout))
            expected = BASE + [f"spec.sources[{index}].path" for index in indices]
            assert actual == expected, (spec, actual, expected)
    print(f"Application computed fields: {len(cases)} native HCL cases passed")


if __name__ == "__main__":
    main()
