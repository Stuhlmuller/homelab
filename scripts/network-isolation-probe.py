#!/usr/bin/env python3
"""Render synthetic Jobs and verify transport evidence; never apply resources.

PyYAML is needed only for rendering. Inside the pinned Python probe image this
uses the standard library. No argument accepts a Secret, archive or PVC.
"""

import argparse
import errno
import hashlib
import ipaddress
import json
import socket
import struct
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "docker.io/library/python:3.13-bookworm@sha256:227b6570d6ee07061ae6ca2eb04dedfb6d2b34045835f343065b9869e4d427ea"
SOURCES = {
    "openclaw": ("ai", "openclaw"),
    "multica-runtime": ("ai", "multica-runtime"),
    "signing": ("harbor", "harbor"),
    "recovery": ("isolation-recovery-probe", "default"),
    "control": ("isolation-control-probe", "default"),
}
CATEGORIES = {"pod", "service", "node", "lan", "public", "dns"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def select(selector, labels):
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for e in selector.get("matchExpressions", []):
        key, op, values = e["key"], e["operator"], e.get("values", [])
        if op not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            raise ValueError("Unsupported selector operator")
        if op == "In" and labels.get(key) not in values:
            return False
        if op == "NotIn" and labels.get(key) in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


def validate_matrix(matrix):
    if matrix.get("families") not in [[4], [4, 6]]:
        raise ValueError("Explicit families [4] or [4, 6] required")
    targets = matrix["targets"]
    if not targets or len({t["id"] for t in targets}) != len(targets):
        raise ValueError("Unique nonempty targets required")
    for family in matrix["families"]:
        if {t["category"] for t in targets if t["family"] == family} != CATEGORIES:
            raise ValueError("Each family must cover Pod/Service/node/LAN/public/DNS")
    for t in targets:
        if t["family"] not in matrix["families"] or t["protocol"] not in [
            "tcp",
            "dns-udp",
            "dns-tcp",
        ]:
            raise ValueError("Invalid target protocol/family")
        if not 1 <= t["port"] <= 65535 or not t["host"] or "REPLACE" in t["host"]:
            raise ValueError("Unresolved target")
        if set(t["expect"]) != set(SOURCES) - {"control"}:
            raise ValueError("Every target needs all protected source expectations")
        if any(x not in ["allow", "deny", "exception"] for x in t["expect"].values()):
            raise ValueError("Invalid expectation")
        if t["protocol"].startswith("dns-"):
            ipaddress.ip_address(t["host"])  # resolver is an IP, never implicit DNS
            if not t.get("query") or t["port"] != 53:
                raise ValueError("DNS requires explicit query and port 53")
    for source in set(SOURCES) - {"control"}:
        ts = [t for t in targets if t["expect"][source] == "deny"]
        if not ts:
            raise ValueError("Negative cases required for every protected source")
        if source != "recovery" and not any(
            t["expect"][source] == "allow" for t in targets
        ):
            raise ValueError("Positive dependency required")
    return matrix


def snapshot(output):
    data = {}
    for resource in [
        "nodes",
        "namespaces",
        "pods",
        "services",
        "endpointslices",
        "networkpolicies",
        "deployments",
        "daemonsets",
    ]:
        args = ["kubectl", "get", resource, "-A", "-o", "json", "--request-timeout=20s"]
        data[resource] = json.loads(subprocess.check_output(args, timeout=30))["items"]
    # No Secrets, ConfigMaps, logs, env values or workload volume contents exported.
    # Deployment specs may contain literal env: retain only identity fields.
    data["deployments"] = [
        {
            "metadata": {
                "name": d["metadata"]["name"],
                "namespace": d["metadata"]["namespace"],
            },
            "spec": {
                "template": {
                    "metadata": d["spec"]["template"]["metadata"],
                    "spec": {
                        "serviceAccountName": d["spec"]["template"]["spec"].get(
                            "serviceAccountName", "default"
                        )
                    },
                }
            },
        }
        for d in data["deployments"]
    ]
    data["daemonsets"] = [
        {
            "metadata": {
                "name": d["metadata"]["name"],
                "namespace": d["metadata"]["namespace"],
            },
            "images": [c["image"] for c in d["spec"]["template"]["spec"]["containers"]],
            "status": d.get("status", {}),
        }
        for d in data["daemonsets"]
    ]
    data["pods"] = [
        {
            "metadata": {
                "name": p["metadata"]["name"],
                "namespace": p["metadata"]["namespace"],
                "uid": p["metadata"]["uid"],
                "labels": p["metadata"].get("labels", {}),
            },
            "spec": {
                "nodeName": p["spec"].get("nodeName"),
                "hostNetwork": p["spec"].get("hostNetwork", False),
            },
            "status": {"podIPs": p.get("status", {}).get("podIPs", [])},
        }
        for p in data["pods"]
    ]
    Path(output).write_text(json.dumps(data, indent=2) + "\n")


def render(inventory, matrix, round_name):
    import yaml

    validate_matrix(matrix)
    # The current candidate is IPv4-only. Never silently call IPv6 not applicable.
    actual_families = {
        ipaddress.ip_network(c).version
        for n in inventory["nodes"]
        for c in n["spec"].get("podCIDRs", [])
    }
    if actual_families != set(matrix["families"]) or actual_families != {4}:
        raise ValueError(
            "Node PodCIDRs must prove IPv4-only; dual-stack needs reviewed engine/policy changes"
        )
    namespaces = {
        n["metadata"]["name"]: n["metadata"].get("labels", {})
        for n in inventory["namespaces"]
    }
    identities = {}
    for name, (ns, sa) in SOURCES.items():
        if name in ["openclaw", "multica-runtime"]:
            ds = [
                d
                for d in inventory["deployments"]
                if d["metadata"]["namespace"] == ns and d["metadata"]["name"] == name
            ]
            if len(ds) != 1:
                raise ValueError("Exact Deployment identity missing: " + name)
            template = ds[0]["spec"]["template"]
            if template["spec"].get("serviceAccountName", "default") != sa:
                raise ValueError("Service account drift: " + name)
            labels = dict(template["metadata"]["labels"])
            annotations = template["metadata"].get("annotations", {})
            if annotations.get("k8s.v1.cni.cncf.io/networks"):
                raise ValueError(
                    "Secondary networks require separate enforcement proof"
                )
        elif name == "signing":
            template = yaml.safe_load(
                (ROOT / "clusters/homelab/apps/harbor/signing-job.yaml").read_text()
            )["spec"]["template"]
            labels = template["metadata"]["labels"]
            if template["spec"]["serviceAccountName"] != sa:
                raise ValueError("Signing identity changed")
        else:
            labels = {"app.kubernetes.io/name": "isolation-" + name}
        if (
            name in ["openclaw", "multica-runtime"]
            and namespaces.get(ns, {}).get("istio.io/dataplane-mode") != "ambient"
        ):
            raise ValueError("Expected ambient namespace enrollment missing")
        if (
            name == "signing"
            and namespaces.get(ns, {}).get("istio.io/dataplane-mode") == "ambient"
        ):
            raise ValueError("Unexpected Harbor mesh enrollment")
        for svc in inventory["services"]:
            if (
                svc["metadata"]["namespace"] == ns
                and svc["spec"].get("selector")
                and select({"matchLabels": svc["spec"]["selector"]}, labels)
                and svc["spec"].get("publishNotReadyAddresses")
            ):
                raise ValueError(
                    "Probe could receive production traffic: publishNotReadyAddresses"
                )
        identities[name] = {"namespace": ns, "serviceAccount": sa, "labels": labels}
    docs = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": "isolation-control-probe",
                "labels": {
                    "pod-security.kubernetes.io/enforce": "restricted",
                    "pod-security.kubernetes.io/enforce-version": "latest",
                    "pod-security.kubernetes.io/audit": "restricted",
                    "pod-security.kubernetes.io/audit-version": "latest",
                    "pod-security.kubernetes.io/warn": "restricted",
                    "pod-security.kubernetes.io/warn-version": "latest",
                    "istio.io/dataplane-mode": "none",
                },
            },
        }
    ]
    plan_hash = digest(matrix)
    for ns in sorted({ns for ns, _ in SOURCES.values()}):
        docs.append(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "isolation-probe", "namespace": ns},
                "data": {
                    "probe.py": Path(__file__).read_text(),
                    "matrix.json": json.dumps(matrix),
                },
            }
        )
    for name, identity in identities.items():
        # One source on every node; repeat with a new round name for replacement proof.
        for node in inventory["nodes"]:
            node_name = node["metadata"]["name"]
            docs.append(
                {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "metadata": {
                        "name": f"isolation-{name}-{node_name}-{round_name}",
                        "namespace": identity["namespace"],
                    },
                    "spec": {
                        "backoffLimit": 0,
                        "activeDeadlineSeconds": 1800,
                        "template": {
                            "metadata": {"labels": identity["labels"]},
                            "spec": {
                                "serviceAccountName": identity["serviceAccount"],
                                "automountServiceAccountToken": False,
                                "nodeSelector": {"kubernetes.io/hostname": node_name},
                                "tolerations": [
                                    {
                                        "key": "node-role.kubernetes.io/control-plane",
                                        "effect": "NoSchedule",
                                        "operator": "Exists",
                                    }
                                ],
                                "restartPolicy": "Never",
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 65532,
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "containers": [
                                    {
                                        "name": "probe",
                                        "image": IMAGE,
                                        "command": [
                                            "python3",
                                            "/probe/probe.py",
                                            "inside",
                                            "--source",
                                            name,
                                            "--round",
                                            round_name,
                                            "--identity",
                                            digest(identity),
                                        ],
                                        "env": [
                                            {
                                                "name": "PROBE_POD_UID",
                                                "valueFrom": {
                                                    "fieldRef": {
                                                        "fieldPath": "metadata.uid"
                                                    }
                                                },
                                            },
                                            {
                                                "name": "PROBE_NODE",
                                                "valueFrom": {
                                                    "fieldRef": {
                                                        "fieldPath": "spec.nodeName"
                                                    }
                                                },
                                            },
                                        ],
                                        # Never enter production Service endpoints despite exact labels.
                                        "readinessProbe": {
                                            "exec": {
                                                "command": [
                                                    "python3",
                                                    "-c",
                                                    "raise SystemExit(1)",
                                                ]
                                            },
                                            "periodSeconds": 1,
                                        },
                                        "securityContext": {
                                            "allowPrivilegeEscalation": False,
                                            "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]},
                                        },
                                        "resources": {
                                            "requests": {
                                                "cpu": "10m",
                                                "memory": "32Mi",
                                            },
                                            "limits": {"cpu": "100m", "memory": "64Mi"},
                                        },
                                        "volumeMounts": [
                                            {
                                                "name": "probe",
                                                "mountPath": "/probe",
                                                "readOnly": True,
                                            }
                                        ],
                                    }
                                ],
                                "volumes": [
                                    {
                                        "name": "probe",
                                        "configMap": {"name": "isolation-probe"},
                                    }
                                ],
                            },
                        },
                    },
                }
            )
    return docs, {
        "matrix": matrix,
        "matrix_hash": plan_hash,
        "identities": {k: digest(v) for k, v in identities.items()},
        "nodes": sorted(n["metadata"]["name"] for n in inventory["nodes"]),
    }


def read_exact(sock, length):
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise OSError("Incomplete DNS response")
        data += chunk
    return data


def connect(target):
    family = socket.AF_INET if target["family"] == 4 else socket.AF_INET6
    protocol = target["protocol"]
    try:
        addresses = socket.getaddrinfo(
            target["host"], target["port"], family, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return "error:dns"  # Resolution failure is never evidence of egress denial.
    # Require all returned addresses to behave alike; no lucky first-address pass.
    results = []
    for _, _, _, _, address in addresses:
        try:
            kind = socket.SOCK_DGRAM if protocol == "dns-udp" else socket.SOCK_STREAM
            with socket.socket(family, kind) as s:
                s.settimeout(3)
                s.connect(address)
                if protocol.startswith("dns-"):
                    query = (
                        b"".join(
                            bytes([len(x)]) + x.encode("ascii")
                            for x in target["query"].split(".")
                        )
                        + b"\0"
                    )
                    packet = (
                        struct.pack("!6H", 1234, 256, 1, 0, 0, 0)
                        + query
                        + struct.pack("!2H", 1 if family == socket.AF_INET else 28, 1)
                    )
                    s.sendall(
                        (
                            struct.pack("!H", len(packet))
                            if protocol == "dns-tcp"
                            else b""
                        )
                        + packet
                    )
                    if protocol == "dns-tcp":
                        length = struct.unpack("!H", read_exact(s, 2))[0]
                        if length > 4096:
                            return "error:dns-response"
                        answer = read_exact(s, length)
                    else:
                        answer = s.recv(4096)
                    if (
                        len(answer) < 12
                        or struct.unpack("!H", answer[:2])[0] != 1234
                        or not answer[2] & 128
                        or answer[3] & 15
                        or answer[6:8] == b"\0\0"
                    ):
                        return "error:dns-response"
                results.append("reachable")
        except TimeoutError:
            results.append("timeout")
        except OSError as e:
            # REJECT and a closed listener can look identical. Verification requires
            # a healthy unrestricted control to this same target in both rounds.
            results.append(
                "rejected"
                if e.errno in (errno.ECONNREFUSED, errno.EACCES, errno.EHOSTUNREACH)
                else "error:" + errno.errorcode.get(e.errno, "socket")
            )
    return results[0] if results and len(set(results)) == 1 else "error:mixed-addresses"


def inside(source, round_name, identity):
    import os

    matrix = validate_matrix(json.loads(Path("/probe/matrix.json").read_text()))
    time.sleep(15)  # allow ambient capture / policy programming to settle
    record = {
        "source": source,
        "round": round_name,
        "identity": identity,
        "matrix_hash": digest(matrix),
        "pod_uid": os.environ["PROBE_POD_UID"],
        "node": os.environ["PROBE_NODE"],
        "results": {},
    }
    for target in matrix["targets"]:
        record["results"][target["id"]] = connect(target)
    print(json.dumps(record), flush=True)


def verify(plan, records):
    matrix = validate_matrix(plan["matrix"])
    expected_keys = {
        (s, n, r)
        for s in SOURCES
        for n in plan["nodes"]
        for r in ["first", "replacement"]
    }
    keyed = {(r["source"], r["node"], r["round"]): r for r in records}
    if set(keyed) != expected_keys or len(keyed) != len(records):
        raise ValueError("Missing or duplicate source/node/round evidence")
    if len({r["pod_uid"] for r in records}) != len(records) or any(
        not r["pod_uid"] for r in records
    ):
        raise ValueError("Replacement must use new Pod UIDs")
    for (source, node, round_name), record in keyed.items():
        if record["identity"] != plan["identities"][source] or record[
            "matrix_hash"
        ] != digest(matrix):
            raise ValueError("Evidence identity/matrix drift")
        if set(record["results"]) != {t["id"] for t in matrix["targets"]}:
            raise ValueError("Missing or extra target evidence")
        for t in matrix["targets"]:
            expected = "allow" if source == "control" else t["expect"][source]
            got = record["results"][t["id"]]
            # Exceptions are visible evidence, never reported as contained.
            if expected == "exception" or (
                source != "control" and t.get("local_node") == node
            ):
                continue
            if got not in (
                ["reachable"] if expected == "allow" else ["timeout", "rejected"]
            ):
                raise ValueError(
                    f"{source}/{node}/{round_name}/{t['id']}: expected {expected}, got {got}"
                )
    return "Transport matrix passed; declared exceptions and application acceptance remain separate."


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("snapshot")
    a.add_argument("--output", required=True)
    a = sub.add_parser("render")
    a.add_argument("--snapshot", required=True)
    a.add_argument("--matrix", required=True)
    a.add_argument("--round", choices=["first", "replacement"], required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--plan", required=True)
    a = sub.add_parser("inside")
    a.add_argument("--source", choices=SOURCES, required=True)
    a.add_argument("--round", required=True)
    a.add_argument("--identity", required=True)
    a = sub.add_parser("verify")
    a.add_argument("--plan", required=True)
    a.add_argument("--records", required=True)
    args = p.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.output)
    elif args.cmd == "render":
        import yaml

        docs, plan = render(
            json.loads(Path(args.snapshot).read_text()),
            json.loads(Path(args.matrix).read_text()),
            args.round,
        )
        Path(args.output).write_text(yaml.safe_dump_all(docs, sort_keys=False))
        Path(args.plan).write_text(json.dumps(plan, indent=2) + "\n")
    elif args.cmd == "inside":
        inside(args.source, args.round, args.identity)
    else:
        print(
            verify(
                json.loads(Path(args.plan).read_text()),
                json.loads(Path(args.records).read_text()),
            )
        )


if __name__ == "__main__":
    main()
