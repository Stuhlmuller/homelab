#!/usr/bin/env python3
"""Exact ownership must never exempt a different file, tag or package."""
import copy
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location("policy", Path(__file__).with_name("argocd-image-updater-policy.py"))
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def main():
    image = "harbor.stinkyboi.com/mirror/docker.io/library/example:stable"
    package = image.rsplit(":", 1)[0]
    path = "clusters/homelab/apps/example/values.yaml"
    enrollment = {"images": [{"alias": "app", "image_name": image, "source_paths": [path]}]}
    entry = {"manifest": {"metadata": {"name": "example"}, "spec": {"source": {
        "repoURL": "https://github.com/Stuhlmuller/homelab.git", "path": "clusters/homelab/apps/example", "helm": {}}}},
        "image_update": enrollment}
    rule = {"description": policy.RULE_DESCRIPTION, "matchDatasources": ["docker"],
            "matchPackageNames": [package], "matchFileNames": [path], "enabled": False}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / path
        source.parent.mkdir(parents=True)
        source.write_text("fixture")
        documents = {path: [{"image": image}]}
        def validate(entries=None, rules=None, docs=None):
            return policy.validate(entries if entries is not None else [entry],
                                   {"packageRules": rules if rules is not None else [rule]},
                                   root, docs if docs is not None else documents)
        allowed = validate()
        assert allowed == {(path, image)}
        tag_only = {"images": [{"name": package, "newTag": "stable"}]}
        assert validate(docs={path: [tag_only]}) == allowed
        assert validate(rules=[rule, {"enabled": True, "matchPackageNames": ["unrelated/package"]}]) == allowed
        assert policy.permits(allowed, path, image, {"docker.io/library/example:stable"})
        for wrong_path, wrong_image, known in (
            ("clusters/homelab/apps/other/values.yaml", image, {"docker.io/library/example:stable"}),
            (path, image.replace(":stable", ":other"), {"docker.io/library/example:other"}),
            (path, image.replace("/example:", "/other:"), {"docker.io/library/other:stable"}),
            (path, image, set()),
        ):
            assert not policy.permits(allowed, wrong_path, wrong_image, known)
        handoff = copy.deepcopy(entry)
        handoff["image_update_handoff"] = handoff.pop("image_update")
        handoff["image_update_handoff"]["paused"] = True
        assert validate([handoff]) == allowed
        invalid = []
        invalid.append(([], [rule], documents))  # orphaned runtime exclusion
        invalid.append(([entry], [], documents))
        invalid.append(([entry], [{**rule, "matchFileNames": ["**/*.yaml"]}], documents))
        invalid.append(([entry], [{**rule, "matchPackageNames": ["*"]}], documents))
        invalid.append(([entry], [rule, {"enabled": True}], documents))
        for later in (
            {"matchPackageNames": [package.replace("/example", "/{example,other}")]},
            {"matchFileNames": [path.replace("/example/", "/{example,other}/")]},
            {"matchPackageNames": [package.replace("/example", "/@(example|other)")]},
            {"matchPackageNames": [package.upper()]},
            {"matchPackageNames": [package[:-1] + "[^x]"]},
            {"matchDatasources": ["*"]},
            {"matchDatasources": ["/docker/"]},
            {"matchPackageNames": [package.replace("stinkyboi.com", r"stinkyboi\.com")]},
        ):
            invalid.append(([entry], [rule, {"enabled": True, **later}], documents))
        invalid.append(([entry, entry], [rule], documents))
        invalid.append(([entry], [rule], {path: [{"image": image}, {"image": image}]}))
        invalid.append(([entry], [rule], {path: [{"image": image.replace(":stable", ":old")}]}))
        invalid.append(([{**entry, "image_update_handoff": enrollment}], [rule], documents))
        invalid.append(([{**handoff, "image_update_handoff": enrollment}], [rule], documents))
        for base in (entry, handoff):
            for multi in (False, True):
                for renderer, collection in (("helm", "parameters"), ("kustomize", "images")):
                    configured = copy.deepcopy(base)
                    app_spec = configured["manifest"]["spec"]
                    app_spec["source"][renderer] = {collection: []}
                    if multi:
                        app_spec["sources"] = [app_spec.pop("source")]
                    invalid.append(([configured], [rule], documents))
        outside = copy.deepcopy(entry)
        outside["manifest"]["spec"]["source"]["repoURL"] = "https://example.invalid/other"
        invalid.append(([outside], [rule], documents))
        for entries, rules, docs in invalid:
            try:
                validate(entries, rules, docs)
            except ValueError:
                pass
            else:
                raise AssertionError((entries, rules, docs))
        assert validate([], [], {}) == set()
        legacy = {"images": [{"image_id": "app", "destination": image}], "consumers": [
            {"image_id": "app", "target": "/" + path, "automation_status": "enrolled"}]}
        try:
            policy.validate_legacy(allowed, legacy)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted dual Git/runtime ownership")
        legacy["consumers"][0]["automation_status"] = "not-enrolled"
        policy.validate_legacy(allowed, legacy)
        checker_spec = importlib.util.spec_from_file_location("harbor_check", Path(__file__).with_name("harbor-images-check.py"))
        checker = importlib.util.module_from_spec(checker_spec)
        checker_spec.loader.exec_module(checker)
        checker.ROOT = root
        source.write_text(f"image: {image}\n")
        known = {"docker.io/library/example:stable"}
        assert checker.runtime_unmirrored([source], set(), set(), known, allowed) == []
        other = source.with_name("other.yaml")
        other.write_text(f"image: {image}\n")
        assert checker.runtime_unmirrored([source, other], set(), set(), known, allowed) == [image]
        assert checker.runtime_unmirrored([source], set(), set(), set(), allowed) == [image]
        source.write_text(f"image: {image}@sha256:{'a' * 64}\n")
        assert checker.runtime_unmirrored([source], set(), set(), known, allowed)
    print(f"Image ownership policy: exact allowance, handoff, removal and {len(invalid)} rejection cases passed")


if __name__ == "__main__":
    main()
