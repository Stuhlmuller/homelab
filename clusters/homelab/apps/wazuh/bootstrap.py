"""Reconcile Wazuh native retention, snapshot repository and archive discovery."""

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

INDEXER = "https://wazuh-indexer.wazuh.svc.cluster.local:9200"
TLS = ssl.create_default_context(cafile="/run/admin/ca.crt")
TLS.load_cert_chain("/run/admin/tls.crt", "/run/admin/tls.key")


def request(method, path, value=None, *, dashboard=False, missing=False):
    headers = {"Content-Type": "application/json"}
    origin = INDEXER
    if dashboard:
        origin = "http://wazuh-dashboard.wazuh.svc.cluster.local:5601"
        password = Path("/run/credentials/indexer-admin-password").read_text().strip()
        headers["Authorization"] = "Basic " + base64.b64encode(
            ("admin:" + password).encode()
        ).decode()
        headers["osd-xsrf"] = "wazuh-bootstrap"
    req = urllib.request.Request(
        origin + path,
        data=None if value is None else json.dumps(value).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, context=TLS, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f"Wazuh {method} failed with HTTP {error.code}") from None


def verify_retention(assignments):
    # HTTP 200 from add can contain per-index failures, including an existing
    # different policy. Only matching, enabled assignments prove reconciliation.
    # Newly added jobs can remain null until ISM's sweep. Wait for both families
    # together so their first sweep fits inside the bootstrap Job's deadline.
    for attempt in range(46):
        pending = []
        for pattern, policy_id, added in assignments:
            failed = {item["index_name"] for item in added["failed_indices"]}
            if added["failures"] != bool(failed):
                raise RuntimeError(f"Inconsistent ISM add result for {pattern}")
            explained = request("GET", f"/_plugins/_ism/explain/{pattern}")
            indices = {name: state for name, state in explained.items()
                       if name != "total_managed_indices"}
            if failed - indices.keys():
                raise RuntimeError(f"ISM add failures missing from readback for {pattern}")
            if len(indices) < added["updated_indices"] + len(failed):
                pending.append(pattern)
            for name, state in indices.items():
                actual = state.get("policy_id")
                if actual and actual != policy_id:
                    raise RuntimeError(f"Conflicting ISM policy on {name}: expected {policy_id}, found {actual}")
                if actual != policy_id or state.get("enabled") is not True:
                    pending.append(name)
        if not pending:
            return
        if attempt < 45:
            time.sleep(10)
    raise RuntimeError("ISM retention assignments not confirmed: " + ", ".join(pending))


def main():
    # PostSync already requires healthy workloads; tolerate brief reconciliation.
    for attempt in range(12):
        try:
            health = request("GET", "/_cluster/health?wait_for_status=yellow&timeout=30s")
            if health["status"] in ("green", "yellow"):
                break
        except (RuntimeError, OSError):
            pass
        time.sleep(5)
    else:
        raise RuntimeError("Wazuh indexer did not become available")

    assignments = []
    for kind, days in (("archives", 30), ("alerts", 90)):
        policy_id = f"homelab-{kind}-{days}d"
        path = f"/_plugins/_ism/policies/{policy_id}"
        existing = request("GET", path, missing=True)
        if existing:
            path += f"?if_seq_no={existing['_seq_no']}&if_primary_term={existing['_primary_term']}"
        request("PUT", path, {"policy": {
            "description": f"Retain homelab Wazuh {kind} for {days} days",
            "default_state": "retain",
            "states": [
                {"name": "retain", "actions": [], "transitions": [
                    {"state_name": "delete", "conditions": {"min_index_age": f"{days}d"}}
                ]},
                {"name": "delete", "actions": [{"delete": {}}], "transitions": []},
            ],
            "ism_template": [{"index_patterns": [f"wazuh-{kind}-*"], "priority": 100}],
        }})
        # New-index templates do not retroactively attach to already-created data.
        pattern = f"wazuh-{kind}-*"
        added = request("POST", f"/_plugins/_ism/add/{pattern}", {"policy_id": policy_id})
        assignments.append((pattern, policy_id, added))
    verify_retention(assignments)

    request("PUT", "/_snapshot/homelab", {
        "type": "fs", "settings": {"location": "indexer", "compress": True}
    })
    request("POST", "/_snapshot/homelab/_verify", {})
    request("POST", "/api/saved_objects/index-pattern/wazuh-archives?overwrite=true", {
        "attributes": {"title": "wazuh-archives-*", "timeFieldName": "timestamp"}
    }, dashboard=True)
    print("Wazuh retention, snapshot repository and archive index pattern reconciled")


if __name__ == "__main__":
    main()
