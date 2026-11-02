"""Check the rendered v0.33.0 policy, including required strategy arguments."""

import copy
import json
from pathlib import Path
import subprocess
import sys


def check(policy):
    assert set(policy) == {"apiVersion", "kind", "profiles", "maxNoOfPodsToEvictTotal"}
    assert policy["apiVersion"] == "descheduler/v1alpha2"
    assert policy["kind"] == "DeschedulerPolicy"
    assert type(policy["maxNoOfPodsToEvictTotal"]) is int and policy["maxNoOfPodsToEvictTotal"] == 1
    assert len(policy["profiles"]) == 1
    profile = policy["profiles"][0]
    assert set(profile) == {"name", "pluginConfig", "plugins"}
    assert profile["name"] == "conservative"
    assert profile["plugins"] == {
        "balance": {"enabled": ["LowNodeUtilization"]},
        "deschedule": {"enabled": ["RemovePodsViolatingInterPodAntiAffinity"]},
    }, "Do not enable additional eviction strategies"
    configs = profile["pluginConfig"]
    assert all(set(config) <= {"name", "args"} for config in configs)
    names = [config["name"] for config in configs]
    assert len(names) == len(set(names)), "Duplicate plugin configuration"
    enabled = {name for extension in profile["plugins"].values() for name in extension["enabled"]}
    assert set(names) == enabled | {"DefaultEvictor"}, "Every enabled plugin needs a configuration"
    args = {config["name"]: config.get("args", {}) for config in configs}
    for flag in ("evictSystemCriticalPods", "ignorePvcPods", "nodeFit"):
        assert type(args["DefaultEvictor"].get(flag)) is bool
    assert type(args["DefaultEvictor"]["minReplicas"]) is int
    assert args["DefaultEvictor"] == {
        "evictSystemCriticalPods": False, "ignorePvcPods": True, "minReplicas": 2, "nodeFit": True,
    }, "Preserve the existing eviction guards"
    assert args["RemovePodsViolatingInterPodAntiAffinity"] == {}
    utilization = args["LowNodeUtilization"]
    assert set(utilization) == {"thresholds", "targetThresholds"}
    low, high = utilization["thresholds"], utilization["targetThresholds"]
    # v0.33.0 validates nonempty matching maps, percentages and low <= target.
    assert low and set(low) == set(high) == {"cpu", "memory", "pods"}
    for resource in low:
        assert type(low[resource]) in (int, float) and type(high[resource]) in (int, float)
        assert 0 <= low[resource] <= high[resource] <= 100
    assert set(low.values()) == {20} and set(high.values()) == {50}, \
        "Keep the pinned chart's reviewed 20/50 percent defaults"


def main():
    objects = json.loads(Path(sys.argv[1]).read_text())
    configs = [item for item in objects if item and item["kind"] == "ConfigMap"
               and item["metadata"]["name"] == "descheduler"]
    assert len(configs) == 1
    policy = json.loads(subprocess.check_output([
        "yq", "-o=json", ".", "-",
    ], input=configs[0]["data"]["policy.yaml"], text=True))
    check(policy)
    for defect in ("missing-anti-affinity", "missing-utilization", "duplicate", "empty",
                   "different-resources", "out-of-range", "reversed", "unsafe-guard", "extra-plugin",
                   "no-node-fit", "disabled-node-fit", "untyped-node-fit", "no-total-limit",
                   "zero-total-limit", "raised-total-limit", "untyped-total-limit"):
        changed = copy.deepcopy(policy)
        profile = changed["profiles"][0]
        configs = profile["pluginConfig"]
        utilization = next(item["args"] for item in configs if item["name"] == "LowNodeUtilization")
        evictor = next(item["args"] for item in configs if item["name"] == "DefaultEvictor")
        if defect.startswith("missing-"):
            name = ("LowNodeUtilization" if defect == "missing-utilization"
                    else "RemovePodsViolatingInterPodAntiAffinity")
            configs[:] = [item for item in configs if item["name"] != name]
        elif defect == "duplicate":
            configs.append(copy.deepcopy(configs[0]))
        elif defect == "empty":
            utilization["thresholds"] = {}
        elif defect == "different-resources":
            utilization["targetThresholds"].pop("cpu")
        elif defect == "out-of-range":
            utilization["targetThresholds"]["cpu"] = 101
        elif defect == "reversed":
            utilization["thresholds"]["cpu"] = 51
        elif defect == "unsafe-guard":
            evictor["ignorePvcPods"] = False
        elif defect == "no-node-fit":
            evictor.pop("nodeFit")
        elif defect == "disabled-node-fit":
            evictor["nodeFit"] = False
        elif defect == "untyped-node-fit":
            evictor["nodeFit"] = 1
        elif defect == "no-total-limit":
            changed.pop("maxNoOfPodsToEvictTotal")
        elif defect == "zero-total-limit":
            changed["maxNoOfPodsToEvictTotal"] = 0
        elif defect == "raised-total-limit":
            changed["maxNoOfPodsToEvictTotal"] = 2
        elif defect == "untyped-total-limit":
            changed["maxNoOfPodsToEvictTotal"] = True
        else:
            profile["plugins"]["balance"]["enabled"].append("RemoveDuplicates")
        try:
            check(changed)
        except AssertionError:
            continue
        raise AssertionError(f"Unsafe Descheduler policy accepted: {defect}")
    print("Descheduler: rendered plugin configuration, eviction guards and sixteen negative cases passed")


if __name__ == "__main__":
    main()
