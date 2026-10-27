#!/usr/bin/env python3
"""Source-only backup transaction and tenant Pod watch boundary.

The caller must use a protected exact-main guard and an authenticated,
whole-namespace Kubernetes watch. This module does not create Pods, read
Secrets, mark recovery material publishable, or dispatch a backup.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from functools import wraps


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_backup_coordinator_reconciler", ROOT / "scripts/openclaw-enterprise.py")
OCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCE)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


class Blocked(RuntimeError):
    pass


def require(condition, message="Enterprise backup coordinator input changed"):
    if not condition:
        raise Blocked(message)


def _poison_on_rejection(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            if self.started is not None:
                self.failed = True
            raise
    return guarded


def select_backup_id(config, requested_id=None):
    """Reuse the durable unfinished ID; require an explicit ID for a new cycle.

    The existing reconciler journals this ID before its stop POST. A retry
    without its original caller input recovers the journaled ID; a completed
    cycle never silently starts another backup.
    """
    OCE._validate_config(config)
    require(requested_id is None or
            (isinstance(requested_id, str) and HEX64.fullmatch(requested_id)),
            "Enterprise backup ID is invalid")
    with OCE.ProtectedJournal(config["privateJournal"]["mountPath"],
                              config["source"]["revision"],
                              OCE._identity_hash(config), create_lock=False) as journal:
        state = journal.state
        require(state.get("installationId") and state.get("pending") is None,
                "Enterprise backup journal is incomplete")
        backup = state.get("backup")
        if backup is not None and backup["phase"] != "complete":
            require(requested_id is None or requested_id == backup["id"],
                    "Enterprise backup ID differs from unfinished journal")
            return backup["id"]
        require(requested_id is not None,
                "new Enterprise backup needs an explicit durable ID")
        return requested_id


def _pod_list(listing, expected_reader):
    metadata = listing.get("metadata") if isinstance(listing, dict) else None
    require(isinstance(metadata, dict) and listing.get("kind") == "PodList" and
            isinstance(metadata.get("resourceVersion"), str) and
            bool(metadata["resourceVersion"]) and
            metadata.get("continue") in (None, "") and
            isinstance(listing.get("items"), list),
            "Enterprise tenant Pod list changed")
    items = listing["items"]
    if expected_reader is None:
        require(items == [], "Enterprise tenant Pod list changed")
    else:
        reader = expected_reader["metadata"]
        observed = items[0].get("metadata") if len(items) == 1 and isinstance(items[0], dict) else None
        require(isinstance(observed, dict) and
                observed.get("namespace") == "openclaw-agents" and
                observed.get("name") == reader["name"] and
                observed.get("uid") == reader["uid"] and
                observed.get("deletionTimestamp") is None,
                "Enterprise tenant Pod list changed")
    return metadata["resourceVersion"]


class TenantWriterFence:
    """Fail closed on any foreign Pod event or gap in a live watch.

    ``watch.open_from(namespace, rv)`` must open an authenticated, unfiltered
    watch from the initial List resourceVersion. ``watch.drain_until(rv)`` must
    deliver every intervening event in order, wait until the stream passes the
    checkpoint List's resourceVersion, and raise on EOF, timeout, 410 Gone,
    reconnect, or a missed bookmark. A rejected step poisons this instance;
    retry only from a fresh authenticated List and watch. This class covers
    reader transfer only. A future coordinator must extend watch continuity
    through publication and independent restore before promoting a recovery
    marker. The adapter is not implemented here, so this class cannot certify
    a complete live fence.
    """

    def __init__(self, source_sha, backup_id, watch):
        require(isinstance(source_sha, str) and SHA.fullmatch(source_sha) and
                isinstance(backup_id, str) and HEX64.fullmatch(backup_id),
                "Enterprise fence identity is invalid")
        self.source_sha = source_sha
        self.backup_id = backup_id
        self.watch = watch
        self.reader = None
        self.started = None
        self.reader_seen = False
        self.reader_deleted = False
        self.during = False
        self.capture_bound = False
        self.observation_sha256 = None
        self.finished = False
        self.failed = False

    def _drain(self, resource_version):
        require(not self.failed and not self.finished,
                "Enterprise tenant watch is no longer usable")
        try:
            events = self.watch.drain_until(resource_version)
            require(isinstance(events, list), "Enterprise tenant watch has no barrier")
            for event in events:
                kind = event.get("type") if isinstance(event, dict) else None
                obj = event.get("object") if isinstance(event, dict) else None
                metadata = obj.get("metadata") if isinstance(obj, dict) else None
                require(kind in ("ADDED", "MODIFIED", "DELETED", "BOOKMARK") and
                        isinstance(metadata, dict) and
                        isinstance(metadata.get("resourceVersion"), str) and
                        bool(metadata["resourceVersion"]),
                        "Enterprise tenant watch event is invalid")
                if kind == "BOOKMARK":
                    continue
                require(obj.get("kind") == "Pod" and
                        metadata.get("namespace") == "openclaw-agents" and
                        self.reader is not None and
                        metadata.get("name") == self.reader["metadata"]["name"] and
                        metadata.get("uid") == self.reader["metadata"]["uid"],
                        "Enterprise tenant writer appeared during backup")
                if kind == "ADDED":
                    require(not self.reader_seen and not self.reader_deleted,
                            "Enterprise tenant reader was recreated")
                    self.reader_seen = True
                elif kind == "MODIFIED":
                    require(self.reader_seen and not self.reader_deleted,
                            "Enterprise tenant reader watch skipped creation")
                else:
                    require(self.reader_seen and not self.reader_deleted,
                            "Enterprise tenant reader watch skipped deletion")
                    self.reader_deleted = True
        except Exception as error:
            self.failed = True
            if isinstance(error, Blocked):
                raise
            raise Blocked("Enterprise tenant watch lost continuity") from None

    @_poison_on_rejection
    def start(self, listing):
        require(self.started is None and not self.failed,
                "Enterprise tenant watch already started")
        resource_version = _pod_list(listing, None)
        try:
            self.watch.open_from("openclaw-agents", resource_version)
        except Exception:
            self.failed = True
            raise Blocked("Enterprise tenant watch could not start") from None
        self.started = resource_version
        self._drain(resource_version)

    @_poison_on_rejection
    def bind_reader(self, pod):
        require(self.started is not None and self.reader is None and not self.failed,
                "Enterprise tenant reader binding is invalid")
        metadata = pod.get("metadata") if isinstance(pod, dict) else None
        annotations = metadata.get("annotations") if isinstance(metadata, dict) else None
        require(isinstance(metadata, dict) and
                metadata.get("namespace") == "openclaw-agents" and
                metadata.get("name") == "occ-reader-tenant-" + self.backup_id[:40] and
                isinstance(metadata.get("uid"), str) and UID.fullmatch(metadata["uid"]) and
                isinstance(metadata.get("resourceVersion"), str) and
                bool(metadata["resourceVersion"]) and
                isinstance(annotations, dict) and
                annotations.get("homelab.dev/source-sha") == self.source_sha and
                annotations.get("homelab.dev/backup-id") == self.backup_id,
                "Enterprise tenant reader identity changed")
        self.reader = copy.deepcopy(pod)

    @_poison_on_rejection
    def checkpoint(self, listing):
        require(self.started is not None and self.reader is not None and
                not self.failed and not self.finished,
                "Enterprise tenant fence is not active")
        resource_version = _pod_list(listing, self.reader)
        self._drain(resource_version)
        require(self.reader_seen and not self.reader_deleted,
                "Enterprise tenant reader watch missed creation")
        self.during = True

    @_poison_on_rejection
    def bind_capture_reference(self, marker, observations, transaction):
        """Bind a staged marker digest, without validating the full recovery set."""
        require(self.during and not self.failed and not self.finished and
                not self.capture_bound,
                "Enterprise tenant fence has no active capture")
        require(isinstance(transaction, dict) and
                set(transaction) == {"backupId", "namespaceId", "agentId", "revisionId"} and
                transaction["backupId"] == self.backup_id,
                "Enterprise backup transaction changed")
        required = {"schemaVersion", "sourceSha", "identity", "before", "after",
                    "readers", "duringTenantPods"}
        readers = observations.get("readers") if isinstance(observations, dict) else None
        during = observations.get("duringTenantPods") if isinstance(observations, dict) else None
        identity = observations.get("identity") if isinstance(observations, dict) else None
        operator = readers.get("operator") if isinstance(readers, dict) else None
        operator_metadata = operator.get("metadata") if isinstance(operator, dict) else None
        require(isinstance(observations, dict) and
                set(observations) == required and
                type(observations.get("schemaVersion")) is int and
                observations["schemaVersion"] == 1 and
                observations.get("sourceSha") == self.source_sha and
                isinstance(identity, dict) and
                set(identity) == {"installationId", "namespaceId", "agentId", "revisionId"} and
                OCE._valid_resource_id(identity.get("installationId"), "ins_") and
                all(identity.get(key) == transaction[key]
                    for key in ("namespaceId", "agentId", "revisionId")) and
                isinstance(readers, dict) and set(readers) == {"operator", "tenant"} and
                isinstance(operator_metadata, dict) and
                isinstance(operator_metadata.get("uid"), str) and
                UID.fullmatch(operator_metadata["uid"]) and
                readers["tenant"] == self.reader and
                isinstance(during, dict) and during.get("items") == [self.reader],
                "Enterprise capture observations changed")
        _pod_list(during, self.reader)
        for phase in ("before", "after"):
            snapshot = observations.get(phase)
            tenant_pods = snapshot.get("tenantPods") if isinstance(snapshot, dict) else None
            require(isinstance(snapshot, dict) and
                    all(isinstance(snapshot.get(key), dict) for key in (
                        "claims", "volumes", "systemSecrets", "tenantSecrets",
                        "agent", "deployment", "runtime")) and
                    isinstance(snapshot.get("journalSha256"), str) and
                    HEX64.fullmatch(snapshot["journalSha256"]) and
                    isinstance(tenant_pods, dict),
                    "Enterprise capture snapshot is incomplete")
            require(tenant_pods.get("items") == [],
                    "Enterprise capture writer stop changed")
            _pod_list(tenant_pods, None)
        try:
            digest = hashlib.sha256(json.dumps(
                observations, sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError, UnicodeError):
            raise Blocked("Enterprise capture observations are invalid") from None
        require(isinstance(marker, dict) and marker.get("schemaVersion") == 2 and
                marker.get("sourceSha") == self.source_sha and
                marker.get("observationSha256") == digest and
                marker.get("installationId") == identity["installationId"] and
                marker.get("operatorReaderPodUid") == operator_metadata["uid"] and
                marker.get("tenantReaderPodUid") == self.reader["metadata"]["uid"] and
                marker.get("namespaceId") == transaction["namespaceId"] and
                marker.get("agentId") == transaction["agentId"] and
                marker.get("revisionId") == transaction["revisionId"] and
                marker.get("writerStopped") is True and
                marker.get("continuousFenceVerified") is False,
                "Enterprise staged recovery marker changed")
        self.observation_sha256 = digest
        self.capture_bound = True

    @_poison_on_rejection
    def finish(self, listing):
        """Return watch-only reader-transfer evidence.

        This method never authorizes the packager or changes recovery.json; it
        does not cover subsequent publication or independent restore.
        """
        require(self.during and self.capture_bound and
                not self.failed and not self.finished,
                "Enterprise tenant fence has no bound capture")
        resource_version = _pod_list(listing, None)
        self._drain(resource_version)
        require(self.reader_deleted, "Enterprise tenant reader watch missed deletion")
        self.finished = True
        return {"scope": "tenant-pod-watch", "publishable": False,
                "sourceSha": self.source_sha, "backupId": self.backup_id,
                "tenantReaderPodUid": self.reader["metadata"]["uid"],
                "observationSha256": self.observation_sha256,
                "startResourceVersion": self.started,
                "endResourceVersion": resource_version}
