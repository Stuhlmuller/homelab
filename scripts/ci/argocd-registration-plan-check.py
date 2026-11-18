#!/usr/bin/env python3
"""Validate narrowly scoped native updater transitions in saved unit plans."""
import argparse
import json
from pathlib import Path
import sys


def identity(document, kind, api):
    if not isinstance(document, dict):
        return None
    metadata = document.get("metadata") or {}
    name = metadata.get("name")
    if (document.get("kind") == kind and document.get("apiVersion") == api
            and metadata.get("namespace") == "argocd"
            and isinstance(name, str) and name and not any(c in name for c in "*?[]")):
        return name
    return None


def without_null_fields(value):
    # Provider object state may materialize absent optional CRD fields as null.
    if isinstance(value, dict):
        cleaned = {key: without_null_fields(item) for key, item in value.items() if item is not None}
        return {key: item for key, item in cleaned.items() if item != {}}
    if isinstance(value, list):
        return [without_null_fields(item) for item in value]
    return value


def native(document, paused=False):
    document = without_null_fields(document)
    name = identity(document, "ImageUpdater", "argocd-image-updater.argoproj.io/v1alpha1")
    if not name:
        return None
    spec = document.get("spec") or {}
    settings = spec.get("commonUpdateSettings") or {}
    refs = spec.get("applicationRefs")
    if (spec.get("writeBackConfig") != {"method": "argocd"}
            or settings.get("updateStrategy") != "digest"
            or settings.get("ignoreTags") not in (["*"], [])
            or (paused and settings.get("ignoreTags") != ["*"])
            or not isinstance(refs, list) or len(refs) != 1):
        return None
    ref = refs[0]
    if (not isinstance(ref, dict) or set(ref) - {"namePattern", "useAnnotations", "images"}
            or ref.get("namePattern") != name or ref.get("useAnnotations") is not False):
        return None
    images = ref.get("images")
    if not isinstance(images, list) or not images:
        return None
    for image in images:
        if (not isinstance(image, dict)
                or set(image) != {"alias", "imageName", "manifestTargets"}
                or not isinstance(image["alias"], str) or not image["alias"]
                or not isinstance(image["imageName"], str) or not image["imageName"]
                or not isinstance(image["manifestTargets"], dict)):
            return None
        targets = image["manifestTargets"]
        if set(targets) == {"helm"}:
            mapping = targets["helm"]
            if not isinstance(mapping, dict) or set(mapping) not in ({"spec"}, {"name", "tag"}):
                return None
        elif set(targets) == {"kustomize"}:
            mapping = targets["kustomize"]
            if not isinstance(mapping, dict) or set(mapping) != {"name"}:
                return None
        else:
            return None
        if not all(isinstance(value, str) and value for value in mapping.values()):
            return None
    return name


def retained(changes, name):
    apps = [r for r in changes if r.get("address") == "kubernetes_manifest.this"]
    if len(apps) != 1:
        return False
    app = apps[0]
    change = app.get("change") or {}
    return (app.get("mode") == "managed" and app.get("type") == "kubernetes_manifest"
            and change.get("actions") in (["no-op"], ["update"])
            and all(identity((change.get(side) or {}).get("manifest"), "Application",
                             "argoproj.io/v1alpha1") == name for side in ("before", "after")))


def validate(plan, existing_only=False):
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise ValueError("Invalid resource changes")
    for resource in changes:
        if resource.get("type") != "kubernetes_manifest":
            continue
        change = resource.get("change") or {}
        actions = change.get("actions", [])
        deleting = "delete" in actions
        creating = existing_only and "create" in actions
        if not deleting and not creating:
            continue
        name = None
        exact = (resource.get("mode") == "managed"
                 and resource.get("address") == "kubernetes_manifest.image_updater")
        if exact and actions == ["delete"]:
            before = change.get("before") or {}
            name = native(before.get("manifest"), paused=True)
            if native(before.get("object"), paused=True) != name:
                name = None
        elif exact and actions == ["create"]:
            name = native((change.get("after") or {}).get("manifest"))
        if not name or not retained(changes, name):
            raise ValueError("Plan would create an Application or delete/replace protected registration; "
                             "native updater transitions require an exact retained Application "
                             "and observed pause before deletion")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-only", choices=("true", "false"), required=True)
    parser.add_argument("plans", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        for path in args.plans:
            validate(json.loads(path.read_text()), args.existing_only == "true")
    except (ValueError, TypeError, AttributeError, OSError) as error:
        print(f"Argo CD registration plan rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
