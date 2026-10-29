#!/usr/bin/env python3
"""Preview or apply the committed Sonarr/Radarr policy for QNAP/Roku playback."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "scripts/config/arr-playback-policy.json"
APPS = {"sonarr": 8989, "radarr": 7878}
ENDPOINTS = ("customformat", "qualityprofile", "qualitydefinition")


def run(command):
    return subprocess.run(command, capture_output=True, check=True, timeout=120).stdout


def reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("A full reviewed main SHA is required")
    git = ["git", "-C", str(ROOT)]
    if run(git + ["status", "--porcelain=v1", "--untracked-files=all"]):
        raise ValueError("A clean checkout is required")
    head = run(git + ["rev-parse", "HEAD"]).decode().strip()
    remote = run(git + ["ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                        "refs/heads/main"]).decode().split()[0]
    if head != expected or remote != expected:
        raise ValueError("Checkout and remote main must match the reviewed SHA")


def api(app, endpoint, body=None, method="GET"):
    command = r'''set -eu
key=$(sed -n 's:.*<ApiKey>\([^<]*\)</ApiKey>.*:\1:p' /config/config.xml)
case "$key" in *[!a-fA-F0-9]*|'') exit 1;; esac
printf 'header = "X-Api-Key: %s"\n' "$key" | curl -fsS --max-time 60 --config -'''
    command += " " + shlex.quote(f"http://127.0.0.1:{APPS[app]}/api/v3/{endpoint}")
    command += " -X " + shlex.quote(method)
    if body is not None:
        command += " -H 'Content-Type: application/json' --data " + shlex.quote(json.dumps(body))
    data = run(["kubectl", "-n", "media", "exec", f"deploy/{app}", "-c", "app",
                "--", "/bin/sh", "-ec", command])
    return json.loads(data) if data else None


def read_state(app):
    return {endpoint: api(app, endpoint) for endpoint in ENDPOINTS}


def format_fields(value):
    return {"name": value["name"],
            "includeCustomFormatWhenRenaming": value.get("includeCustomFormatWhenRenaming", False),
            "specifications": [{key: spec[key] for key in ("name", "implementation", "negate", "required")}
                               | {"fields": [{"name": f["name"], "value": f.get("value")}
                                             for f in spec["fields"]]}
                               for spec in value["specifications"]]}


def desired_format(policy):
    return {"name": policy["name"], "includeCustomFormatWhenRenaming": False,
            "specifications": [
                {"name": name, "implementation": "ReleaseTitleSpecification", "negate": negate,
                 "required": True, "fields": [{"name": "value", "value": policy[field]}]}
                for name, negate, field in (("Explicit H264", False, "requiredTitle"),
                                           ("Unsupported playback", True, "forbiddenTitle"))]}


def profile_policy(profile, policy, format_id):
    result = copy.deepcopy(profile)
    if any(item["score"] != 0 and item["format"] != format_id for item in result["formatItems"]):
        raise ValueError("Foreign custom-format scores need review before applying playback policy")
    if result["minFormatScore"] not in (0, 1) or result["cutoffFormatScore"] not in (0, 1):
        raise ValueError("Existing custom-format score requirements need review")
    safe = set(policy["safeQualities"])

    def restrict(items, fallback=False):
        for item in items:
            if item.get("items"):
                # A disabled group must not enable its individually checked children.
                if not item["allowed"] and not fallback:
                    for child in item["items"]:
                        child["allowed"] = False
                restrict(item["items"], fallback)
                item["allowed"] = any(child["allowed"] for child in item["items"])
            else:
                quality = item["quality"]
                eligible = quality["name"] in safe
                item["allowed"] = eligible and (quality["resolution"] in (720, 1080)
                                               if fallback else item["allowed"])

    restrict(result["items"])
    if not any(item["allowed"] for item in result["items"]):
        restrict(result["items"], fallback=True)
        result["name"] = policy["fallbackName"]
    allowed = [item.get("id", item.get("quality", {}).get("id"))
               for item in result["items"] if item["allowed"]]
    if not allowed:
        raise ValueError("Profile has no compatible fallback qualities")
    allowed_children = [child["quality"]["id"] for item in result["items"] if item["allowed"]
                        for child in item.get("items", []) if child["allowed"]]
    if result["cutoff"] not in allowed + allowed_children:
        result["cutoff"] = allowed[-1]
    scores = [item for item in result["formatItems"] if item["format"] != format_id]
    scores.append({"format": format_id, "name": policy["name"], "score": 1})
    result.update(formatItems=scores, minFormatScore=1, cutoffFormatScore=1)
    return result


def definition_policy(definition, policy):
    result = copy.deepcopy(definition)
    if result["quality"]["name"] not in policy["safeQualities"]:
        return result
    suffix = "1080" if result["quality"]["resolution"] == 1080 else "720"
    # Arr treats both null and zero maximum size as unlimited.
    maximum = min(result.get("maxSize") or float("inf"), policy["maxSize" + suffix])
    minimum = result.get("minSize") or 0
    if minimum > maximum:
        raise ValueError("Existing minimum file size exceeds the playback cap")
    preferred = min(result["preferredSize"] if result.get("preferredSize") is not None else float("inf"),
                    policy["preferredSize" + suffix], maximum)
    result.update(maxSize=maximum, preferredSize=max(minimum, preferred))
    return result


def plan(state, policy):
    matches = [item for item in state["customformat"] if item["name"] == policy["name"]]
    if len(matches) > 1 or not state["qualityprofile"]:
        raise ValueError("Ambiguous managed format or empty quality profiles")
    existing = matches[0] if matches else None
    format_id = existing["id"] if existing else 0
    wanted = desired_format(policy)
    if existing:
        wanted["id"] = format_id
    profiles = [(item, profile_policy(item, policy, format_id)) for item in state["qualityprofile"]]
    if len({item["name"] for _, item in profiles}) != len(profiles):
        raise ValueError("Fallback profile name would collide; review profile names")
    return {"customformat": wanted if not existing or format_fields(existing) != format_fields(wanted) else None,
            "qualityprofile": profiles,
            "qualitydefinition": [(item, definition_policy(item, policy))
                                  for item in state["qualitydefinition"]]}


def changes(planned):
    return {"customformat": int(planned["customformat"] is not None),
            **{key: sum(before != after for before, after in planned[key])
               for key in ("qualityprofile", "qualitydefinition")}}


def snapshot(path, data):
    target = Path(path).absolute()
    if target.resolve().is_relative_to(ROOT):
        raise ValueError("Snapshot must remain outside the public repository")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())


def apply(app, before, policy):
    if read_state(app) != before:
        raise RuntimeError("Settings changed after the snapshot; preview again")
    wanted = plan(before, policy)["customformat"]
    if wanted:
        endpoint = f"customformat/{wanted['id']}" if "id" in wanted else "customformat"
        api(app, endpoint, wanted, "PUT" if "id" in wanted else "POST")
    current = read_state(app)
    # Creating a custom format automatically appends a zero score to each profile.
    formats = [item for item in current["customformat"] if item["name"] == policy["name"]]
    if len(formats) != 1 or format_fields(formats[0]) != format_fields(desired_format(policy)):
        raise RuntimeError("Managed custom format readback failed")
    managed_id = formats[0]["id"]
    original = copy.deepcopy(before)
    observed = copy.deepcopy(current)
    for state in (original, observed):
        for profile in state["qualityprofile"]:
            profile["formatItems"] = [item for item in profile["formatItems"] if item["format"] != managed_id]
    if any(original[key] != observed[key] for key in ("qualityprofile", "qualitydefinition")):
        raise RuntimeError("Settings changed during format creation; preview again")
    planned = plan(current, policy)
    for endpoint in ("qualitydefinition", "qualityprofile"):
        for old, new in planned[endpoint]:
            if old != new:
                resource = f"{endpoint}/{old['id']}"
                if api(app, resource) != old:
                    raise RuntimeError("Settings changed before update; preview again")
                api(app, resource, new, "PUT")
    if any(changes(plan(read_state(app), policy)).values()):
        raise RuntimeError("Playback policy readback did not converge")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--snapshot", help="New private JSON path outside the repository; required for execution")
    args = parser.parse_args(argv)
    if args.execute:
        if not args.snapshot:
            raise ValueError("Execution requires a private snapshot")
        reviewed_main(args.expected_sha)
    policy = json.loads(POLICY.read_text())
    states = {app: read_state(app) for app in APPS}
    plans = {app: plan(state, policy) for app, state in states.items()}
    if args.snapshot:
        snapshot(args.snapshot, {"expectedSha": args.expected_sha, "policy": policy, "before": states})
    if args.execute:
        for app, state in states.items():
            apply(app, state, policy)
    print(json.dumps({"mode": "applied-and-verified" if args.execute else "preview",
                      "changes": {app: changes(value) for app, value in plans.items()}}))


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    try:
        main()
    except Exception as error:
        print(f"Playback policy failed ({type(error).__name__}); private details withheld", file=sys.stderr)
        raise SystemExit(1) from None
