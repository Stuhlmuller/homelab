#!/usr/bin/env python3
"""Offline contract and state machine for Harbor image automation.

The workflow owns network access; this module owns deterministic validation,
rendering and operation gates so proposal input cannot widen the write scope.
"""
import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "clusters/homelab/apps/harbor/image-automation.json"
STATE = ROOT / "scripts/config/image-automation-state.json"

KNOWN_RECIPES = {
    "curl-release-v1",
    "curl-workload-v1",
    "python-release-v1",
    "python-workload-v1",
    "stateless-recovery-v1",
}
RECIPE_FIELDS = {
    "curl-workload-v1": {"command", "retry", "timeout", "run_as_non_root", "read_only_root", "health_endpoint"},
    "python-workload-v1": {"uid", "read_only_root", "ca_trust", "health_endpoint", "data_paths"},
    "stateless-recovery-v1": {"known_good_digest", "data_safety", "single_attempt"},
}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
IMAGE = re.compile(r"^[a-z0-9.-]+(?:/[a-z0-9._-]+)+(?::[A-Za-z0-9._-]+)?(?:@sha256:[0-9a-f]{64})?$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def read(path):
    return json.loads(Path(path).read_text())


def fail(message):
    raise SystemExit(message)


def validate_workload_evidence(recipe, evidence):
    """Require the fixed compatibility evidence before a recipe can enroll."""
    required = RECIPE_FIELDS.get(recipe)
    if required is None or not isinstance(evidence, dict) or set(evidence) != required:
        return False, "workload evidence fields do not match the fixed recipe"
    if recipe == "curl-workload-v1" and (
        evidence["command"] != ["curl"] or evidence["retry"] < 1 or evidence["timeout"] <= 0
        or evidence["run_as_non_root"] is not True or evidence["read_only_root"] is not True
        or not isinstance(evidence["health_endpoint"], str)
    ):
        return False, "curl compatibility evidence is incomplete"
    if recipe == "python-workload-v1" and (
        not isinstance(evidence["uid"], int) or evidence["uid"] <= 0
        or evidence["read_only_root"] is not True or evidence["ca_trust"] is not True
        or not isinstance(evidence["health_endpoint"], str) or not isinstance(evidence["data_paths"], list)
    ):
        return False, "python compatibility evidence is incomplete"
    if recipe == "stateless-recovery-v1" and (
        not SHA256.fullmatch(evidence["known_good_digest"])
        or evidence["data_safety"] != "safe" or evidence["single_attempt"] is not True
    ):
        return False, "recovery compatibility evidence is incomplete"
    return True, "workload evidence verified"


def validate_application_evidence(application):
    evidence = application.get("evidence")
    if evidence is None:
        return True, "no evidence supplied"
    if not isinstance(evidence, dict) or set(evidence) != {"preflight", "health", "recovery"}:
        return False, "application evidence must cover all fixed recipes"
    for phase, recipe in (("preflight", application["preflight_recipe"]),
                          ("health", application["health_recipe"]),
                          ("recovery", application["recovery_recipe"])):
        valid, reason = validate_workload_evidence(recipe, evidence[phase])
        if not valid:
            return False, f"{phase}: {reason}"
    return True, "application evidence verified"


def validate(config):
    if config.get("schema_version") != 1:
        fail("schema_version must be 1")
    if set(config) - {"schema_version", "imports_paused", "import_schedule", "verification_interval_minutes", "images", "consumers", "applications"}:
        fail("unknown top-level field")
    if (type(config.get("imports_paused")) is not bool
            or not isinstance(config.get("import_schedule"), str)
            or type(config.get("verification_interval_minutes")) is not int
            or not 1 <= config["verification_interval_minutes"] <= 1440):
        fail("imports_paused and import_schedule must be explicit")
    if not isinstance(config.get("images"), list) or not isinstance(config.get("consumers"), list) or not isinstance(config.get("applications"), list):
        fail("images, consumers and applications must be arrays")
    ids = set()
    for image in config["images"]:
        required = {"image_id", "source", "destination", "access_class", "required_platforms", "release_recipe"}
        if set(image) - required or not required <= set(image):
            fail(f"invalid image fields: {image.get('image_id')}")
        key = image["image_id"]
        if not ID.fullmatch(key) or key in ids:
            fail(f"duplicate or invalid image_id: {key}")
        ids.add(key)
        if image["access_class"] not in {"public", "restricted"} or not image["required_platforms"]:
            fail(f"invalid image access/platforms: {key}")
        if image["release_recipe"] not in KNOWN_RECIPES:
            fail(f"unknown release recipe: {image['release_recipe']}")
        if not IMAGE.fullmatch(image["source"]) or not IMAGE.fullmatch(image["destination"]):
            fail(f"invalid image ref: {key}")
        if image["access_class"] == "restricted" and not image["destination"].startswith("harbor.stinkyboi.com/"):
            fail(f"restricted image must have private destination: {key}")
    consumer_ids = set()
    for consumer in config["consumers"]:
        required = {"consumer_id", "application_id", "image_id", "target", "migration_status", "automation_status", "owner"}
        if set(consumer) - required or not required <= set(consumer):
            fail(f"invalid consumer fields: {consumer.get('consumer_id')}")
        cid = consumer["consumer_id"]
        if not ID.fullmatch(cid) or cid in consumer_ids or consumer["image_id"] not in ids:
            fail(f"invalid consumer: {cid}")
        if consumer["migration_status"] not in {"candidate", "migrated", "exception"} or consumer["automation_status"] not in {"not-enrolled", "enrolled", "exception"}:
            fail(f"invalid consumer status: {cid}")
        if not isinstance(consumer["target"], str) or not consumer["target"].startswith("/") or ".." in Path(consumer["target"]).parts:
            fail(f"unsafe target: {cid}")
        consumer_ids.add(cid)
    app_ids = set()
    for app in config["applications"]:
        if set(app) - {"application_id", "consumer_ids", "preflight_recipe", "health_recipe", "recovery_recipe", "deadline_minutes", "evidence"}:
            fail(f"unknown application fields: {app.get('application_id')}")
        aid = app["application_id"]
        if not ID.fullmatch(aid) or aid in app_ids or not set(app["consumer_ids"]).issubset(consumer_ids):
            fail(f"invalid application: {aid}")
        if any(next(c for c in config["consumers"] if c["consumer_id"] == cid)["application_id"] != aid
               for cid in app["consumer_ids"]):
            fail(f"application consumers are not coordinated: {aid}")
        for recipe in (app["preflight_recipe"], app["health_recipe"], app["recovery_recipe"]):
            if recipe not in KNOWN_RECIPES:
                fail(f"unknown workload recipe: {recipe}")
        valid, reason = validate_application_evidence(app)
        if not valid:
            fail(f"invalid application evidence: {aid}: {reason}")
        app_ids.add(aid)
    return True


def render(config):
    validate(config)
    entries = []
    for app in sorted(config["applications"], key=lambda x: x["application_id"]):
        consumers = [next(c for c in config["consumers"] if c["consumer_id"] == cid) for cid in app["consumer_ids"]]
        if any(c["automation_status"] == "enrolled" for c in consumers):
            entries.append({"application": app["application_id"], "images": sorted({c["image_id"] for c in consumers}), "platforms": sorted({p for i in config["images"] if i["image_id"] in {c["image_id"] for c in consumers} for p in i["required_platforms"]}), "strategy": "digest", "alias": "verified-stable", "write_back": "git:secret:github-app", "branch": "main:codex/image-updater-proposals", "poll_seconds": 120})
    return {"apiVersion": "image-automation.homelab/v1", "kind": "ManagedImages", "spec": entries}


def operation_allowed(state, application, operation):
    item = state.get("applications", {}).get(application)
    if not item:
        return False, "unknown application"
    if operation == "update":
        if item.get("paused") or item.get("unresolved_deployment_id"):
            return False, "application paused or rollout unresolved"
        if item.get("candidate_rejected"):
            return False, "candidate rejected"
    elif operation == "rollback":
        if not item.get("failed_deployment_id") or not item.get("known_good_deployment_id"):
            return False, "rollback is not bound to failed and known-good deployments"
        if item.get("operator_pause") or item.get("recovery_attempt") in {"failed", "terminal"}:
            return False, "operator pause or terminal recovery state"
        if item.get("current_data_safety") != "safe":
            return False, "current data is unsafe or unknown"
    elif operation == "pause-reject":
        if not item.get("failed_deployment_id") or not item.get("failed_digest"):
            return False, "pause-reject requires a bound failure"
    else:
        return False, "unknown operation"
    return True, "allowed"


def atomic_write(path, value):
    """Write state atomically; a killed runner cannot leave half a journal."""
    path = Path(path)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def observe(state, application, deployment_id, candidate_sha, desired_images, deadline):
    """Upsert one native-deployment-shaped journal record, never a second attempt."""
    applications = state.setdefault("applications", {})
    current = applications.setdefault(application, {})
    if current.get("deployment_id") == deployment_id and current.get("outcome") in {"healthy", "failed"}:
        return state
    current.update({"deployment_id": deployment_id, "candidate_sha": candidate_sha,
                    "desired_images": list(desired_images), "deadline_minutes": deadline,
                    "outcome": "observing", "stage": "observation",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "auto_merge": False, "auto_inactive": False})
    current.setdefault("recovery_attempt", None)
    return state


def recover(state, application, current_data_safety, app_unchanged=True):
    allowed, reason = operation_allowed(state, application, "rollback")
    if not allowed or not app_unchanged or current_data_safety != "safe":
        return False, reason if not allowed else "application changed or current data is unsafe", state
    item = state["applications"][application]
    if item.get("recovery_attempt") in {"pending", "failed", "terminal"}:
        return False, "recovery attempt already persisted", state
    item["recovery_attempt"] = "pending"
    item["recovery_target"] = item["known_good_deployment_id"]
    item["current_data_safety"] = "safe"
    return True, "recovery attempt persisted", state


def pause_reject(state, application, reason):
    allowed, message = operation_allowed(state, application, "pause-reject")
    if not allowed:
        return False, message, state
    item = state["applications"][application]
    item["paused"] = True
    item["pause_origin"] = item.get("failed_deployment_id")
    item["pause_reason"] = reason
    item.setdefault("rejected_digests", []).append(item["failed_digest"])
    item["rejected_digests"] = sorted(set(item["rejected_digests"]))
    return True, "pause and rejection persisted", state


def validate_candidate(state, candidate, base_sha):
    """Reject proposal-branch trees outside the operation's small field set."""
    required = {"base_sha", "candidate_sha", "parents", "application", "operation", "changes"}
    if set(candidate) - required or not required <= set(candidate):
        return False, "candidate fields are incomplete or unknown"
    if candidate["base_sha"] != base_sha or not SHA.fullmatch(candidate["candidate_sha"]):
        return False, "candidate base or SHA is invalid"
    if candidate["parents"] != [base_sha] or not isinstance(candidate["changes"], dict):
        return False, "candidate must have one exact parent and a structured diff"
    operation = candidate["operation"]
    allowed, reason = operation_allowed(state, candidate["application"], operation)
    if not allowed:
        return False, reason
    fields = set(candidate["changes"])
    permitted = {
        "update": {"images", "receipts"},
        "rollback": {"images", "receipts", "rejected_digests"},
        "pause-reject": {"paused", "pause_origin", "pause_reason", "rejected_digests"},
    }[operation]
    if not fields <= permitted:
        return False, "candidate changes exceed operation scope"
    if operation == "pause-reject" and "images" in fields:
        return False, "pause-reject cannot change images"
    changes = candidate["changes"]
    if "images" in changes and (not isinstance(changes["images"], list)
                                 or any(not isinstance(image, str) or not IMAGE.fullmatch(image)
                                        for image in changes["images"])):
        return False, "candidate image changes are invalid"
    if "rejected_digests" in changes and (not isinstance(changes["rejected_digests"], list)
                                           or any(not SHA256.fullmatch(digest)
                                                  for digest in changes["rejected_digests"])):
        return False, "candidate rejected digests are invalid"
    if "receipts" in changes and (not isinstance(changes["receipts"], list)
                                  or any(not isinstance(receipt, dict) or not verify_release(receipt)[0]
                                         for receipt in changes["receipts"])):
        return False, "candidate receipts are invalid"
    return True, "candidate scope valid"


def verify_release(receipt):
    """Validate immutable release evidence before a `verified-stable` advance."""
    required = {"image_id", "source_ref", "source_digest", "destination_ref", "destination_digest", "version", "platforms", "consumer_access"}
    if set(receipt) - required or not required <= set(receipt):
        return False, "release receipt fields are incomplete or unknown"
    if not ID.fullmatch(receipt["image_id"]):
        return False, "release image_id is invalid"
    if not SHA256.fullmatch(receipt["source_digest"]) or receipt["source_digest"] != receipt["destination_digest"]:
        return False, "source and destination digests do not match"
    if not IMAGE.fullmatch(receipt["source_ref"]) or not IMAGE.fullmatch(receipt["destination_ref"]):
        return False, "release references are invalid"
    version = str(receipt["version"])
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or "-" in version:
        return False, "release is not a stable semantic version"
    platforms = receipt["platforms"]
    if not isinstance(platforms, dict) or not platforms or any(not SHA256.fullmatch(digest) for digest in platforms.values()):
        return False, "required platform digests are incomplete"
    if receipt["consumer_access"] is not True:
        return False, "intended consumer pulls were not complete"
    return True, "release receipt verified"


def release_eligible(receipt, previous_version=None, rejected_digests=()):
    """Allow stable upgrades and rebuilds, never downgrades or rejected digests."""
    valid, reason = verify_release(receipt)
    if not valid:
        return False, reason
    if receipt["destination_digest"] in set(rejected_digests):
        return False, "release digest was previously rejected"
    if previous_version is not None:
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(previous_version)):
            return False, "retained version is invalid"
        current = tuple(int(part) for part in receipt["version"].split("."))
        previous = tuple(int(part) for part in str(previous_version).split("."))
        if current < previous:
            return False, "release is older than the retained version"
    return True, "release is eligible"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "render", "render-check", "verify", "gate", "candidate-check", "recipe-check", "observe", "recover", "pause-reject"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--application")
    parser.add_argument("--operation")
    parser.add_argument("--deployment-id")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--deadline", type=int, default=30)
    parser.add_argument("--data-safety", choices=("safe", "unsafe", "unknown"), default="unknown")
    parser.add_argument("--reason", default="operator review required")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--base-sha")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--previous-version")
    parser.add_argument("--rejected-digest", action="append", default=[])
    parser.add_argument("--recipe")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    config = read(args.config)
    if args.command == "check":
        validate(config)
        print("image automation configuration valid")
    elif args.command in {"render", "render-check"}:
        output = render(config)
        target = ROOT / "clusters/homelab/apps/argocd-image-updater/managed-images.yaml"
        rendered = "# generated from image-automation.json\n" + json.dumps(output, indent=2) + "\n"
        if args.command == "render-check":
            if not target.exists() or target.read_text() != rendered:
                fail(f"generated output drift: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered)
        print(rendered, end="")
    elif args.command == "verify":
        if not args.receipt:
            fail("verify requires --receipt")
        valid, reason = release_eligible(read(args.receipt), args.previous_version, args.rejected_digest)
        print(json.dumps({"verified": valid, "reason": reason}))
        raise SystemExit(0 if valid else 1)
    elif args.command == "gate":
        state = read(args.state)
        allowed, reason = operation_allowed(state, args.application, args.operation)
        print(json.dumps({"application": args.application, "operation": args.operation, "allowed": allowed, "reason": reason}))
        raise SystemExit(0 if allowed else 1)
    elif args.command == "candidate-check":
        if not args.candidate or not args.base_sha:
            fail("candidate-check requires --candidate and --base-sha")
        valid, reason = validate_candidate(read(args.state), read(args.candidate), args.base_sha)
        print(json.dumps({"valid": valid, "reason": reason}))
        raise SystemExit(0 if valid else 1)
    elif args.command == "recipe-check":
        if not args.recipe or not args.evidence:
            fail("recipe-check requires --recipe and --evidence")
        valid, reason = validate_workload_evidence(args.recipe, read(args.evidence))
        print(json.dumps({"valid": valid, "reason": reason}))
        raise SystemExit(0 if valid else 1)
    else:
        state = read(args.state)
        if args.command == "observe":
            if not args.application or not args.deployment_id or not args.candidate_sha:
                fail("observe requires --application, --deployment-id and --candidate-sha")
            observe(state, args.application, args.deployment_id, args.candidate_sha, args.image, args.deadline)
            atomic_write(args.state, state)
            print(json.dumps(state["applications"][args.application], sort_keys=True))
        elif args.command == "recover":
            ok, reason, state = recover(state, args.application, args.data_safety)
            if ok:
                atomic_write(args.state, state)
            print(json.dumps({"allowed": ok, "reason": reason}))
            raise SystemExit(0 if ok else 1)
        else:
            ok, reason, state = pause_reject(state, args.application, args.reason)
            if ok:
                atomic_write(args.state, state)
            print(json.dumps({"allowed": ok, "reason": reason}))
            raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
