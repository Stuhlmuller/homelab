#!/usr/bin/env python3
"""Validate exact runtime image ownership from resolved Application inputs."""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RULE_DESCRIPTION = "Argo CD runtime digest ownership"
REPOSITORY = "https://github.com/Stuhlmuller/homelab"
MIRROR = "harbor.stinkyboi.com/mirror/"


def documents(path):
    return json.loads(subprocess.check_output([
        "yq", "ea", "-o=json", "-I=0",
        '[., (.. | select(tag == "!!map" and has("helm")) | .helm.values | select(tag == "!!str") | from_yaml)]',
        str(path)], text=True, timeout=30))


def references(value):
    """Keep occurrence counts; a set would hide partially owned containers."""
    result = []
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, str) and image != "auto":
            result.append(image)
        if isinstance(value.get("repository"), str) and (value.get("tag") or value.get("digest")):
            image = value["repository"]
            if value.get("registry"):
                image = str(value["registry"]) + "/" + image
            if value.get("tag"):
                image += ":" + str(value["tag"])
            if value.get("digest") or value.get("sha"):
                image = image.split("@", 1)[0] + "@" + str(value.get("digest") or value["sha"])
            result.append(image)
        repository = value.get("newName")
        if "newName" not in value and value.get("newTag"):
            repository = value.get("name")
        if isinstance(repository, str):
            result.append(repository + ("@" + str(value["digest"]) if value.get("digest")
                          else ":" + str(value["newTag"]) if value.get("newTag") else ""))
        for child in value.values():
            if isinstance(child, (dict, list)):
                result.extend(references(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(references(child))
    return result


def package(image):
    ref = image.split("@", 1)[0]
    return ref.rsplit(":", 1)[0] if ":" in ref.rsplit("/", 1)[-1] else ref


def owns_path(manifest, path):
    spec = manifest["spec"]
    sources = spec.get("sources") or [spec.get("source", {})]
    source = sources[0]
    def local_repo(item):
        return item.get("repoURL", "").rstrip("/").removesuffix(".git") == REPOSITORY
    if local_repo(source) and source.get("path") and path.startswith(source["path"].rstrip("/") + "/"):
        return True
    for value_file in source.get("helm", {}).get("valueFiles", []):
        if value_file.startswith("$") and "/" in value_file:
            ref, relative = value_file[1:].split("/", 1)
            if relative == path and any(item.get("ref") == ref and local_repo(item) for item in sources):
                return True
    return False


def validate(entries, renovate, root, by_path):
    root = root.resolve()
    allowed, owned_pairs = set(), set()
    rules = renovate.get("packageRules", [])
    for entry in entries:
        active, handoff = entry.get("image_update"), entry.get("image_update_handoff")
        if active is not None and handoff is not None:
            raise ValueError("image_update and image_update_handoff are mutually exclusive")
        enrollment = active if active is not None else handoff
        if enrollment is None:
            continue
        if handoff is not None and handoff.get("paused") is not True:
            raise ValueError("Temporary ownership handoff must retain paused=true")
        app_spec = entry["manifest"]["spec"]
        for source in app_spec.get("sources") or [app_spec.get("source", {})]:
            if "parameters" in (source.get("helm") or {}) or "images" in (source.get("kustomize") or {}):
                raise ValueError("Runtime override collections must remain absent during enrollment and temporary handoff")
        images = enrollment.get("images", [])
        if not images or len({image.get("alias") for image in images}) != len(images):
            raise ValueError("Enrollment requires nonempty, unique image aliases")
        for image in images:
            selector = image.get("image_name", "")
            if not re.fullmatch(r"[^@\s]+/[^@\s:]+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", selector):
                raise ValueError("Runtime ownership requires an explicit tag without a digest")
            repo = package(selector)
            paths = image.get("source_paths", [])
            if not paths:
                raise ValueError("Runtime ownership requires exact source_paths")
            for path in paths:
                file = root / path
                if (not path.startswith("clusters/homelab/") or
                    re.search(r"(^|/)\.\.?(/|$)|[\\*?\[\]{}]|//", path) or
                    not file.is_file() or file.resolve() != file.absolute() or
                    not owns_path(entry["manifest"], path)):
                    raise ValueError(f"Source path is not owned by this Application: {path}")
                pair = (path, repo)
                if pair in owned_pairs:
                    raise ValueError(f"Duplicate image ownership: {path} {repo}")
                matches = [ref for ref in references(by_path[path]) if package(ref) == repo]
                if matches != [selector]:
                    raise ValueError(f"Require exactly one matching mutable image occurrence: {path} {repo}")
                exact = [index for index, rule in enumerate(rules) if
                         rule.get("description") == RULE_DESCRIPTION and rule.get("enabled") is False and
                         rule.get("matchDatasources") == ["docker"] and
                         rule.get("matchPackageNames") == [repo] and rule.get("matchFileNames") == [path] and
                         set(rule) <= {"description", "enabled", "matchDatasources", "matchPackageNames", "matchFileNames"}]
                if len(exact) != 1 or any(reenables(rule, path, repo) for rule in rules[exact[0] + 1:] if exact):
                    raise ValueError(f"Missing or overridden exact Renovate exclusion: {path} {repo}")
                owned_pairs.add(pair)
                allowed.add((path, selector))
    for rule in rules:
        if rule.get("description") == RULE_DESCRIPTION:
            pairs = {(path, repo) for path in rule.get("matchFileNames", []) for repo in rule.get("matchPackageNames", [])}
            if not pairs or not pairs <= owned_pairs:
                raise ValueError("Remove orphaned runtime-owned Renovate exclusions during permanent handoff")
    return allowed


def reenables(rule, path, repo):
    if rule.get("enabled") is not True:
        return False
    for key, value in (("matchDatasources", "docker"), ("matchPackageNames", repo), ("matchFileNames", path)):
        patterns = rule.get(key)
        # Renovate uses minimatch, not Python glob semantics. Treat regex,
        # negative, brace/extglob, character classes and escapes as possible matches.
        # Case folding is conservative for both package names and file paths.
        if patterns and not any(
            pattern.startswith(("/", "!")) or any(char in pattern for char in "{}()[]\\") or
            fnmatchcase(value.lower(), pattern.lower()) for pattern in patterns
        ):
            return False
    return True


def permits(allowed, path, image, known_tags):
    """Only an exact enrolled mirror channel with reviewed provenance may float."""
    return (path, image) in allowed and image.startswith(MIRROR) and "@" not in image and image.removeprefix(MIRROR) in known_tags


def validate_legacy(allowed, legacy):
    destinations = {image["image_id"]: package(image["destination"]) for image in legacy.get("images", [])}
    pairs = {(path, package(image)) for path, image in allowed}
    for consumer in legacy.get("consumers", []):
        pair = (consumer.get("target", "").lstrip("/"), destinations.get(consumer.get("image_id")))
        if consumer.get("automation_status") == "enrolled" and pair in pairs:
            raise ValueError("An image cannot have both legacy Git and runtime digest owners")


def resolved_entries(root):
    # Render the authoritative inputs, never infer ownership from an HCL regex.
    # Literal unit source/path parsing only discovers the existing shared units.
    units = []
    for stack in sorted((root / "IaC/homelab/us-west-2/apps").glob("*/terragrunt.stack.hcl")):
        for block in re.findall(r'(?ms)^unit "[^"]+" \{(.*?)^\}', stack.read_text()):
            if "/units/live/argocd-app" not in block:
                continue
            match = re.search(r'(?m)^\s*path\s*=\s*"([a-zA-Z0-9_-]+)"\s*$', block)
            if not match:
                raise ValueError(f"Application unit needs an explicit local path: {stack}")
            units.append(stack.parent / match[1])
    if not units:
        return []
    subprocess.run(["terragrunt", "--log-disable", "--working-dir", str(root / "IaC"), "stack", "generate"],
                   check=True, capture_output=True, text=True, timeout=120)
    def render(unit):
        result = subprocess.run(["terragrunt", "--log-disable", "--working-dir", str(unit),
                                 "render", "--json", "--write=false"], check=True,
                                capture_output=True, text=True, timeout=60)
        return json.loads(result.stdout)["inputs"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(render, units))


@lru_cache(maxsize=1)
def load(root=ROOT):
    root = Path(root).resolve()
    entries = resolved_entries(root)
    paths = {path for entry in entries for key in ("image_update", "image_update_handoff")
             for image in (entry.get(key) or {}).get("images", []) for path in image.get("source_paths", [])}
    # Validate path boundaries before reading source content.
    for path in paths:
        candidate = root / path
        if not candidate.resolve().is_relative_to(root) or candidate.resolve() != candidate.absolute():
            raise ValueError("Enrollment source escapes the repository or uses a symlink")
    renovate = root / "renovate.json"
    allowed = validate(entries, json.loads(renovate.read_text()) if renovate.exists() else {}, root,
                       {path: documents(root / path) for path in paths})
    legacy = root / "clusters/homelab/apps/harbor/image-automation.json"
    if legacy.exists():
        validate_legacy(allowed, json.loads(legacy.read_text()))
    return allowed


if __name__ == "__main__":
    print(f"Image Updater policy: {len(load())} exact owned image/file pairs validated")
