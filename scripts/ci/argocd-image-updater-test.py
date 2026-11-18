#!/usr/bin/env python3
"""Exercise the actual enrollment HCL and pinned controller chart contract."""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "IaC/terragrunt-catalog/modules/argocd-application-image-updater"


def fixture(kind="helm", multi=False):
    source = {"repoURL": "https://example.invalid/repo", "targetRevision": "main", "path": "clusters/homelab/apps/fixture", kind: {}}
    spec = {"sources": [source, {"repoURL": "https://example.invalid/repo", "targetRevision": "main", "ref": "values"}]} if multi else {"source": source}
    target = {"helm": {"name": "image.repository", "tag": "image.tag"}} if kind == "helm" else {"kustomize": {"name": "registry.example/app"}}
    return {"manifest": {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "fixture", "namespace": "argocd"}, "spec": spec},
            "image_update": {"images": [{"alias": "app", "image_name": "registry.example/app:stable", "source_paths": ["clusters/homelab/apps/fixture/values.yaml"], **target}]}}


def evaluate(scratch, values):
    (scratch / "terraform.tfvars.json").write_text(json.dumps(values))
    result = subprocess.run(["tofu", "plan", "-input=false", "-no-color", "-out=fixture.tfplan"], cwd=scratch,
                            text=True, capture_output=True, timeout=30)
    if result.returncode or result.stderr.strip():
        return None, result.stderr + result.stdout
    shown = subprocess.run(["tofu", "show", "-json", "fixture.tfplan"], cwd=scratch,
                           text=True, capture_output=True, timeout=30, check=True)
    planned = json.loads(shown.stdout)["planned_values"]["outputs"]
    source = values["manifest"]["spec"].get("source")
    prefix = "spec.source" if source else "spec.sources[0]"
    source = source or values["manifest"]["spec"]["sources"][0]
    image_path = prefix + (".helm.parameters" if "helm" in source else ".kustomize.images")
    computed = planned["computed_fields"]["value"]
    assert image_path in computed
    assert all(path in {"metadata.annotations", "metadata.labels", "spec.destination.name", image_path}
               or re.fullmatch(r"spec\.sources\[\d+\]\.path", path) for path in computed), computed
    return planned["manifest"]["value"], ""


def module_contract(module):
    # The pinned Nix shell supplies hcl2 via its Checkov Python environment.
    # Exclude user-site/current-directory imports while retaining that dependency path.
    parser = """import json, sys
from pathlib import Path
import hcl2
def semantic(value):
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items()
                if key not in {"__start_line__", "__end_line__"}}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value
parsed = [semantic(hcl2.loads(Path(path).read_text())) for path in sys.argv[1:]]
terraform = [block for file in parsed for block in file.get("terraform", [])]
kms = [block for file in parsed for block in file.get("variable", [])
       if any(name.startswith("kms_") for name in block)]
print(json.dumps({"terraform": sorted(terraform, key=lambda x: json.dumps(x, sort_keys=True)),
                  "kms": sorted(kms, key=lambda x: json.dumps(x, sort_keys=True))}))
"""
    with tempfile.TemporaryDirectory(prefix="module-contract-parser-") as directory:
        result = subprocess.run(["python3", "-s", "-P", "-c", parser,
                                 *(str(path.resolve()) for path in sorted(module.glob("*.tf")))],
                                cwd=directory, text=True, capture_output=True, timeout=30, check=True)
    contract = json.loads(result.stdout)
    assert contract["terraform"] and contract["kms"], "provider/encryption or KMS contract missing"
    return contract


def contract_cases(default_module):
    actual = module_contract(MODULE)
    assert actual == module_contract(default_module), "provider/encryption or KMS contract diverged"
    with tempfile.TemporaryDirectory(prefix="module-layout-") as directory:
        relocated = Path(directory)
        # Different filename, whitespace and comments must not change the contract.
        text = "\n".join(path.read_text() for path in sorted(default_module.glob("*.tf")))
        (relocated / "renamed.tf").write_text("# relocated declarations\n" + text)
        assert module_contract(relocated) == actual, "relocation changed semantic contract"
        for before, after in (('version = "3.2.1"', 'version = "3.2.2"'),
                              ("enforced = true", "enforced = false"),
                              ('"AES_256"', '"OTHER"')):
            assert before in text, before
            (relocated / "renamed.tf").write_text(text.replace(before, after, 1))
            assert module_contract(relocated) != actual, "meaningful contract divergence was ignored"
    print("Module contract: filename-independent HCL parity and three divergence cases passed")


def hcl_cases():
    source = (MODULE / "main.tf").read_text()
    default_module = ROOT / "IaC/terragrunt-catalog/modules/argocd-application-kubernetes"
    contract_cases(default_module)
    blocks = re.findall(r"(?ms)^locals \{.*?^\}", source)
    assert blocks, "module must expose its actual native CR locals"
    with tempfile.TemporaryDirectory(prefix="image-updater-hcl-") as directory:
        scratch = Path(directory)
        precondition = re.search(r"(?ms)^    precondition \{.*?^    \}", source).group(0)
        output = 'output "manifest" {\n  value = local.image_updater_manifest\n' + precondition + '\n}\n' + 'output "computed_fields" { value = local.computed_field_defaults }\n'
        (scratch / "main.tf").write_text('variable "manifest"' + (MODULE / "variables.tf").read_text().split('variable "manifest"', 1)[1] + "\n" + "\n".join(blocks) + "\n" + output)
        outputs = []
        for kind in ("helm", "kustomize"):
            for multi in (False, True):
                values = fixture(kind, multi)
                actual, error = evaluate(scratch, values)
                assert not error, error
                assert actual["spec"]["writeBackConfig"] == {"method": "argocd"}
                assert actual["spec"]["commonUpdateSettings"] == {"updateStrategy": "digest", "ignoreTags": []}
                ref = actual["spec"]["applicationRefs"][0]
                assert ref["namePattern"] == "fixture" and ref["useAnnotations"] is False
                assert ref["images"][0]["imageName"] == "registry.example/app:stable"
                assert ref["images"][0]["manifestTargets"] == {kind: values["image_update"]["images"][0][kind]}
                outputs.append(actual)
                same, error = evaluate(scratch, values)
                assert not error and same == actual
                values["image_update"]["images"][0]["image_name"] = "registry.example/app:next"
                changed, error = evaluate(scratch, values)
                assert not error and changed["spec"]["applicationRefs"][0]["images"][0]["imageName"].endswith(":next")
                values["image_update"]["paused"] = True
                paused, error = evaluate(scratch, values)
                assert not error and paused["spec"]["commonUpdateSettings"]["ignoreTags"] == ["*"]
                outputs.append(paused)
        # A chart with a values ref must own the exact referenced values file.
        values = fixture("helm", True)
        chart = values["manifest"]["spec"]["sources"][0]
        chart["path"] = "."
        chart["helm"]["valueFiles"] = ["$values/clusters/homelab/apps/fixture/values.yaml"]
        actual, error = evaluate(scratch, values)
        assert not error, error
        outputs.append(actual)
        values["image_update"]["images"][0]["helm"] = {"spec": "container.image"}
        actual, error = evaluate(scratch, values)
        assert not error, error
        assert actual["spec"]["applicationRefs"][0]["images"][0]["manifestTargets"] == {"helm": {"spec": "container.image"}}
        outputs.append(actual)
        negatives = []
        def bad(label, mutate):
            values = fixture()
            mutate(values)
            negatives.append((label, values))
        bad("empty images", lambda x: x["image_update"].update(images=[]))
        bad("duplicate alias", lambda x: x["image_update"]["images"].append(copy.deepcopy(x["image_update"]["images"][0])))
        bad("digest", lambda x: x["image_update"]["images"][0].update(image_name="registry.example/app:stable@sha256:" + "a" * 64))
        bad("missing tag", lambda x: x["image_update"]["images"][0].update(image_name="registry.example/app"))
        bad("wildcard app", lambda x: x["manifest"]["metadata"].update(name="*"))
        bad("traversal", lambda x: x["image_update"]["images"][0].update(source_paths=["clusters/homelab/../secret.yaml"]))
        bad("glob", lambda x: x["image_update"]["images"][0].update(source_paths=["clusters/homelab/apps/*/values.yaml"]))
        bad("absolute path", lambda x: x["image_update"]["images"][0].update(source_paths=["/tmp/values.yaml"]))
        bad("outside sources", lambda x: x["image_update"]["images"][0].update(source_paths=["clusters/homelab/apps/other/values.yaml"]))
        bad("nonimage parameter", lambda x: x["manifest"]["spec"]["source"]["helm"].update(parameters=[{"name": "replicas", "value": "2"}]))
        bad("wrong renderer", lambda x: x["manifest"]["spec"]["source"].update(kustomize={}))
        bad("two source forms", lambda x: x["manifest"]["spec"].update(sources=[x["manifest"]["spec"]["source"]]))
        bad("plugin", lambda x: x["manifest"]["spec"]["source"].update(plugin={}))
        bad("second renderer", lambda x: x["manifest"]["spec"].update(source=None, sources=[{"helm": {}}, {"helm": {}, "ref": "values"}]))
        bad("partial override ownership", lambda x: x["manifest"]["spec"]["source"]["helm"].update(parameters=[{"name": "image.tag", "value": "stable"}, {"name": "otherImage.tag", "value": "old"}]))
        bad("duplicate parameter target", lambda x: x["image_update"]["images"].append({**copy.deepcopy(x["image_update"]["images"][0]), "alias": "second"}))
        bad("empty Helm overrides", lambda x: x["manifest"]["spec"]["source"]["helm"].update(parameters=[]))
        bad("seeded Helm overrides", lambda x: x["manifest"]["spec"]["source"]["helm"].update(parameters=[{"name": "image.tag", "value": "stable"}]))
        bad("active and handoff", lambda x: x.update(image_update_handoff={**x["image_update"], "paused": True}))
        for seeded in ([], ["registry.example/app:stable"]):
            values = fixture("kustomize")
            values["manifest"]["spec"]["source"]["kustomize"]["images"] = seeded
            negatives.append(("configured Kustomize override", values))
        for label, values in negatives:
            actual, error = evaluate(scratch, values)
            assert error and actual is None, f"accepted invalid enrollment: {label}"
        print(f"Image Updater: 4 native HCL source forms, transitions, and {len(negatives)} invalid enrollments passed")
        return outputs


def validate_schema(value, schema, path="root"):
    """Validate our small native CR payload against the chart's OpenAPI shape."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    if kind in types:
        assert isinstance(value, types[kind]), (path, kind, value)
    if isinstance(value, dict):
        assert set(schema.get("required", [])) <= value.keys(), path
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                validate_schema(child, properties[key], path + "." + key)
            else:
                assert path == "root.metadata" or schema.get("additionalProperties"), (path, "unknown field", key)
    elif isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0), path
        for child in value:
            validate_schema(child, schema.get("items", {}), path + "[]")
    elif isinstance(value, str) and "pattern" in schema:
        assert re.search(schema["pattern"], value), (path, value)


def chart_cases(rendered, outputs):
    result = subprocess.run(["yq", "eval-all", "-o=json", "[.]", str(rendered)],
                            text=True, capture_output=True, check=True, timeout=30)
    documents = [d for d in json.loads(result.stdout) if d]
    crd = next(d for d in documents if d["kind"] == "CustomResourceDefinition" and d["metadata"]["name"] == "imageupdaters.argocd-image-updater.argoproj.io")
    schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    for output in outputs:
        validate_schema(output, schema)
    config = next(d for d in documents if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "argocd-image-updater-config")
    assert config["data"]["log.level"] == "info"
    assert not set(config["data"]) & {"applicationsAPI", "gitWriteBackMethod", "gitBranch", "updateStrategy", "logLevel", "interval"}
    deployment = next(d for d in documents if d["kind"] == "Deployment")
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--interval=2m" in args and not any("git-commit-method" in arg for arg in args)
    print("Pinned chart: native CR payload shapes and effective controller arguments/config passed")


def unit_cases():
    unit = ROOT / "IaC/terragrunt-catalog/units/live/argocd-app/terragrunt.hcl"
    defaults = {
        "repo_url": "https://example.invalid/repo", "target_revision": "main",
        "source_root": "clusters/homelab/apps",
        "manifest": {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
                     "metadata": {"namespace": "argocd", "labels": {}},
                     "spec": {"project": "homelab", "destination": {"server": "https://kubernetes.default.svc"},
                              "syncPolicy": {"automated": {}, "retry": {"backoff": {}}}}},
    }
    # Exercise the actual shared unit with its real includes. Nothing is applied.
    with tempfile.TemporaryDirectory(prefix=".image-updater-unit-", dir=ROOT / "IaC") as directory:
        scratch = Path(directory) / "fixture" / "argocd"
        scratch.mkdir(parents=True)
        shutil.copyfile(unit, scratch / "terragrunt.hcl")
        for form in ("default", "single", "multi"):
            values = {"defaults": defaults}
            if form != "default":
                values["spec"] = fixture(multi=form == "multi")["manifest"]["spec"]
            for enrolled in (False, True):
                if enrolled:
                    values["image_update"] = fixture()["image_update"]
                else:
                    values.pop("image_update", None)
                (scratch / "terragrunt.values.hcl").write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n")
                result = subprocess.run(["terragrunt", "render", "--json", "--write=false", "--no-color"],
                                        cwd=scratch, capture_output=True, text=True, timeout=60)
                assert result.returncode == 0, result.stderr
                rendered = json.loads(result.stdout)
                actual = rendered["inputs"]["manifest"]["spec"]
                assert ("source" in actual) == (form == "single"), actual
                assert ("sources" in actual) == (form != "single"), actual
                if form == "default":
                    assert actual["sources"] == [{"repoURL": defaults["repo_url"], "targetRevision": "main", "path": "clusters/homelab/apps/fixture"}]
                expected_module = "argocd-application-image-updater" if enrolled else "argocd-application-kubernetes"
                assert rendered["terraform"]["source"].endswith("/" + expected_module)
                assert ("image_update" in rendered["inputs"]) == enrolled
        # Handoff stays visible to policy, while ordinary registration owns the resource.
        values = {"defaults": defaults, "spec": fixture()["manifest"]["spec"],
                  "image_update_handoff": {**fixture()["image_update"], "paused": True}}
        (scratch / "terragrunt.values.hcl").write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n")
        result = subprocess.run(["terragrunt", "render", "--json", "--write=false", "--no-color"],
                                cwd=scratch, capture_output=True, text=True, timeout=60, check=True)
        rendered = json.loads(result.stdout)
        assert rendered["terraform"]["source"].endswith("/argocd-application-kubernetes")
        assert rendered["inputs"]["image_update_handoff"]["paused"] is True
        assert "image_update" not in rendered["inputs"]
    print("Shared unit: 7 actual renders preserve default/single/multi forms and paused handoff metadata")


def handoff_cases():
    default_module = ROOT / "IaC/terragrunt-catalog/modules/argocd-application-kubernetes"
    variables = 'variable "manifest"' + (default_module / "variables.tf").read_text().split('variable "manifest"', 1)[1]
    with tempfile.TemporaryDirectory(prefix="image-handoff-") as directory:
        scratch = Path(directory)
        (scratch / "main.tf").write_text(variables + '\noutput "manifest" { value = var.manifest }\n')
        for kind in ("helm", "kustomize"):
            for multi in (False, True):
                base = fixture(kind, multi)
                values = {"manifest": base["manifest"], "image_update_handoff": {**base["image_update"], "paused": True}}
                for case in ("valid", "unpaused", "configured-empty"):
                    current = copy.deepcopy(values)
                    if case == "unpaused":
                        current["image_update_handoff"]["paused"] = False
                    elif case == "configured-empty":
                        source = current["manifest"]["spec"].get("source") or current["manifest"]["spec"]["sources"][0]
                        source[kind]["parameters" if kind == "helm" else "images"] = []
                    (scratch / "terraform.tfvars.json").write_text(json.dumps(current))
                    result = subprocess.run(["tofu", "plan", "-input=false", "-no-color"], cwd=scratch,
                                            text=True, capture_output=True, timeout=30)
                    assert (result.returncode == 0) == (case == "valid"), (kind, multi, case, result.stderr)
    print("Default module: 4 valid paused handoffs and 8 unpaused/configured-collection rejections passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rendered-chart", type=Path)
    parser.add_argument("--unit", action="store_true")
    args = parser.parse_args()
    outputs = hcl_cases()
    if args.unit:
        unit_cases()
        handoff_cases()
    if args.rendered_chart:
        chart_cases(args.rendered_chart, outputs)


if __name__ == "__main__":
    main()
