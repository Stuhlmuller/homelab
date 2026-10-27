#!/usr/bin/env python3
"""Source-only, fail-closed tenant Pod list/watch transport for T051.

The caller owns a protected kubeconfig and must keep this object alive from
the empty pre-reader List through publication and independent restore. This
transport never creates a Pod, publishes recovery material, or closes a writer
fence successfully on its own.
"""

import codecs
import json
import math
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time


NAMESPACE = "openclaw-agents"
PODS_PATH = f"/api/v1/namespaces/{NAMESPACE}/pods"
RV = re.compile(r"[1-9][0-9]*\Z")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class WatchGap(RuntimeError):
    """Continuity or authentication could not be proved; discard the fence."""


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\+?", value):
        raise WatchGap("Kubernetes server version is unsupported")
    return int(value.rstrip("+"))


def _resource_version(value):
    # Kubernetes 1.35+ defines built-in Pod RVs as monotonic decimal integers.
    if not isinstance(value, str) or RV.fullmatch(value) is None:
        raise WatchGap("tenant Pod resourceVersion is unsupported")
    return int(value)


class KubectlPodWatch:
    """Unfiltered PodList plus one exact-RV kubectl raw watch, without reconnect.

    An empty-namespace List is checked by TenantWriterFence. Each later List
    must be followed by a watch barrier at a strictly newer RV; equal or stale
    barriers cannot establish ordering and fail closed. Kubernetes bookmarks
    are optional, so an idle watch may time out rather than produce evidence.
    """

    def __init__(self, kubeconfig, *, kubectl="kubectl", timeout_seconds=30,
                 run=subprocess.run, popen=subprocess.Popen,
                 selector_factory=selectors.DefaultSelector,
                 clock=time.monotonic):
        path = Path(kubeconfig)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
                stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise WatchGap("protected kubeconfig is unavailable")
        if (type(timeout_seconds) not in (int, float) or
                not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise WatchGap("tenant Pod watch timeout is invalid")
        config_stat = path.stat()
        self._config_identity = (config_stat.st_dev, config_stat.st_ino,
                                 config_stat.st_size, config_stat.st_mtime_ns)
        self.kubeconfig = str(path)
        self.kubectl = kubectl
        self.timeout_seconds = timeout_seconds
        self._run = run
        self._popen = popen
        self._selector_factory = selector_factory
        self._clock = clock
        self._version_checked = False
        self._list_generation = 0
        self._barrier_generation = 0
        self._listed_rv = None
        self._barrier_rv = None
        self._last_event_rv = None
        self._process = None
        self._selector = None
        self._buffer = ""
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self._json = json.JSONDecoder()
        self._failed = False

    def _command(self, *args):
        return [self.kubectl, "--kubeconfig", self.kubeconfig, *args]

    def _check_config(self):
        try:
            path = Path(self.kubeconfig)
            current = path.stat()
            identity = (current.st_dev, current.st_ino, current.st_size,
                        current.st_mtime_ns)
            if (path.is_symlink() or stat.S_IMODE(current.st_mode) & 0o077
                    or identity != self._config_identity):
                raise WatchGap("protected kubeconfig changed during watch")
        except OSError:
            raise WatchGap("protected kubeconfig changed during watch") from None

    def _checked_json(self, *args):
        try:
            self._check_config()
            result = self._run(self._command(*args), stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               timeout=self.timeout_seconds, check=False)
            if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE_BYTES:
                raise WatchGap("authenticated tenant Pod request failed")
            return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            raise WatchGap("authenticated tenant Pod request failed") from None

    def _check_version(self):
        if self._version_checked:
            return
        data = self._checked_json("version", "-o", "json")
        server = data.get("serverVersion") if isinstance(data, dict) else None
        if (not isinstance(server, dict) or
                (_version(server.get("major")), _version(server.get("minor"))) < (1, 35)):
            raise WatchGap("Kubernetes server version is unsupported")
        self._version_checked = True

    def list_pods(self, namespace=NAMESPACE):
        """Return an authenticated complete, unfiltered namespace PodList."""
        if self._failed or namespace != NAMESPACE:
            raise WatchGap("tenant Pod namespace changed")
        try:
            self._check_version()
            data = self._checked_json("--request-timeout=15s", "get", "--raw",
                                      PODS_PATH)
            metadata = data.get("metadata") if isinstance(data, dict) else None
            if (not isinstance(data, dict) or data.get("kind") != "PodList"
                    or not isinstance(metadata, dict)
                    or metadata.get("continue") not in (None, "")
                    or "shardInfo" in metadata
                    or "remainingItemCount" in metadata
                    or not isinstance(data.get("items"), list)):
                raise WatchGap("tenant Pod list is incomplete")
            observed = _resource_version(metadata.get("resourceVersion"))
            if self._last_event_rv is not None and observed < self._last_event_rv:
                raise WatchGap("tenant Pod list regressed")
            for pod in data["items"]:
                identity = pod.get("metadata") if isinstance(pod, dict) else None
                if (not isinstance(pod, dict) or pod.get("kind") != "Pod"
                        or not isinstance(identity, dict)
                        or identity.get("namespace") != NAMESPACE):
                    raise WatchGap("tenant Pod list has invalid identity")
            self._listed_rv = observed
            self._list_generation += 1
            return data
        except Exception:
            self._failed = True
            raise

    def open_from(self, namespace, resource_version):
        """Open once from the exact RV of this adapter's authenticated List."""
        try:
            requested = _resource_version(resource_version)
        except WatchGap:
            self._failed = True
            raise
        if (self._failed or self._process is not None or namespace != NAMESPACE
                or self._list_generation != 1 or requested != self._listed_rv):
            self._failed = True
            raise WatchGap("tenant Pod watch start does not match its List")
        path = (PODS_PATH + "?watch=1&resourceVersion=" + resource_version
                + "&allowWatchBookmarks=true&timeoutSeconds=3600")
        process = None
        try:
            self._check_config()
            process = self._popen(self._command("--request-timeout=0", "get",
                                                 "--raw", path),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, bufsize=0)
            selector = self._selector_factory()
            selector.register(process.stdout, selectors.EVENT_READ)
            self._process = process
            self._selector = selector
            self._last_event_rv = self._listed_rv
        except Exception:
            if process is not None and process.poll() is None:
                process.terminate()
            self._failed = True
            raise WatchGap("tenant Pod watch could not start") from None

    def _next_event(self, deadline):
        while True:
            candidate = self._buffer.lstrip()
            if candidate:
                try:
                    event, offset = self._json.raw_decode(candidate)
                    self._buffer = candidate[offset:]
                    return event
                except json.JSONDecodeError:
                    pass
            elif self._buffer:
                self._buffer = ""
            if len(self._buffer.encode("utf-8")) >= MAX_RESPONSE_BYTES:
                raise WatchGap("tenant Pod watch event is oversized")
            if self._process.poll() is not None:
                raise WatchGap("tenant Pod watch exited")
            remaining = deadline - self._clock()
            try:
                if remaining <= 0 or not self._selector.select(remaining):
                    raise WatchGap("tenant Pod watch barrier timed out")
                chunk = os.read(self._process.stdout.fileno(), 65536)
            except (OSError, ValueError):
                raise WatchGap("tenant Pod watch stream failed") from None
            if not chunk:
                raise WatchGap("tenant Pod watch ended")
            try:
                self._buffer += self._utf8.decode(chunk)
            except UnicodeDecodeError:
                raise WatchGap("tenant Pod watch event is invalid") from None

    def drain_until(self, resource_version):
        """Return every event through a fresh, ordered List RV barrier."""
        try:
            requested = _resource_version(resource_version)
        except WatchGap:
            self._failed = True
            raise
        if (self._failed or self._process is None
                or self._list_generation <= self._barrier_generation
                or requested != self._listed_rv
                or (self._barrier_rv is not None
                    and self._listed_rv <= self._barrier_rv)):
            self._failed = True
            raise WatchGap("tenant Pod watch has no fresh List barrier")
        target = self._listed_rv
        deadline = self._clock() + self.timeout_seconds
        events = []
        try:
            while True:
                event = self._next_event(deadline)
                kind = event.get("type") if isinstance(event, dict) else None
                obj = event.get("object") if isinstance(event, dict) else None
                metadata = obj.get("metadata") if isinstance(obj, dict) else None
                if kind == "ERROR" or (isinstance(obj, dict)
                                       and obj.get("kind") == "Status"):
                    raise WatchGap("tenant Pod watch was rejected")
                if (kind not in ("ADDED", "MODIFIED", "DELETED", "BOOKMARK")
                        or not isinstance(metadata, dict)):
                    raise WatchGap("tenant Pod watch event is invalid")
                observed = _resource_version(metadata.get("resourceVersion"))
                if (observed < self._last_event_rv
                        or (kind != "BOOKMARK" and observed == self._last_event_rv)):
                    raise WatchGap("tenant Pod watch events are out of order")
                self._last_event_rv = observed
                events.append(event)
                # A Pod event alone is not a barrier: only BOOKMARK states
                # that all changes through its RV have been delivered.
                if kind == "BOOKMARK" and observed >= target:
                    if self._process.poll() is not None:
                        raise WatchGap("tenant Pod watch exited")
                    self._barrier_rv = observed
                    self._barrier_generation = self._list_generation
                    return events
        except Exception:
            self._failed = True
            raise

    def close(self):
        """Release the transport; closure is never a successful fence receipt."""
        self._failed = True
        if self._selector is not None:
            self._selector.close()
            self._selector = None
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            self._process.stdout.close()
            self._process = None
