"""Elect and fence one Gluetun gateway using a predeclared Kubernetes Lease."""

from datetime import datetime, timezone
from functools import partial
from http.client import HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import ipaddress
import logging
import os
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request


LEASE = 'deluge-gluetun'
LEASE_SECONDS = 15
RECONCILE_SECONDS = 2
FENCE_SECONDS = 7
START_SECONDS = 35
UNHEALTHY_SECONDS = 12
COOLDOWN_SECONDS = 20
SA_DIR = Path('/var/run/secrets/kubernetes.io/serviceaccount')
LEADER = Path('/run/deluge-vpn/leader')
NETWORK = Path(__file__).with_name('network.py')


class KubernetesLease:
    def __init__(self, namespace):
        self.host = os.environ['KUBERNETES_SERVICE_HOST']
        self.port = int(os.environ['KUBERNETES_SERVICE_PORT_HTTPS'])
        self.context = ssl.create_default_context(cafile=str(SA_DIR / 'ca.crt'))
        self.lease_path = f'/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/{LEASE}'
        self.endpoint_path = f'/apis/discovery.k8s.io/v1/namespaces/{namespace}/endpointslices/{LEASE}'
        self.pod = {'kind': 'Pod', 'namespace': namespace, 'uid': os.environ['POD_UID'], 'name': os.environ['POD_NAME']}
        self.address = str(ipaddress.IPv4Address(os.environ['POD_IP']))

    def request(self, method, path, body=None):
        connection = HTTPSConnection(self.host, self.port, context=self.context, timeout=1)
        try:
            token = (SA_DIR / 'token').read_text().strip()
            connection.request(method, path, body=body, headers={
                'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
            })
            with connection.getresponse() as response:
                if response.status != 200:
                    raise RuntimeError(f'Kubernetes request failed with HTTP {response.status}')
                return json.loads(response.read(16384))
        finally:
            connection.close()

    def get(self):
        return self.request('GET', self.lease_path)

    def put(self, lease, identity):
        # The resourceVersion makes renewal, takeover, and relinquish conditional writes.
        version = lease['metadata']['resourceVersion']
        old = lease.get('spec', {})
        old_holder = old.get('holderIdentity')
        transitioned = identity != old_holder
        now = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        spec = {
            'holderIdentity': identity,
            'leaseDurationSeconds': LEASE_SECONDS,
            'acquireTime': now if transitioned else old.get('acquireTime', now),
            'renewTime': now,
            'leaseTransitions': old.get('leaseTransitions', 0) + int(transitioned and bool(identity)),
        }
        return self.request('PUT', self.lease_path, json.dumps({
            'apiVersion': 'coordination.k8s.io/v1', 'kind': 'Lease',
            'metadata': {'name': LEASE, 'resourceVersion': version}, 'spec': spec,
        }))

    def get_endpoints(self):
        return self.request('GET', self.endpoint_path)

    def publish(self, resource, enabled):
        current = resource.get('endpoints', [])
        if enabled:
            desired = [{
                'addresses': [self.address], 'targetRef': self.pod,
                'conditions': {'ready': True, 'serving': True, 'terminating': False},
            }]
        else:
            desired = [entry for entry in current if entry.get('targetRef', {}).get('uid') != self.pod['uid']]
        if desired != current:
            # Kubernetes rejects the write if another controller changed this version.
            resource['endpoints'] = desired
            self.request('PUT', self.endpoint_path, json.dumps(resource))


def fence(deadline=None):
    args = [sys.executable, str(NETWORK), 'fence']
    if deadline is not None:
        args.append(str(deadline))
    subprocess.run(args, check=True, timeout=2)


def marker(deadline=None):
    if deadline is None:
        LEADER.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(mode='w', dir=LEADER.parent, delete=False) as pending:
        path = Path(pending.name)
        try:
            pending.write(f'{deadline // 1_000_000_000}\n')
            pending.flush()
            path.replace(LEADER)
        finally:
            path.unlink(missing_ok=True)


def http_healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=0.7) as response:
            return response.status == 200
    except (OSError, HTTPException):
        return False


def boottime_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


class Leader:
    def __init__(self, lease, identity, *, monotonic=time.monotonic, boot_ns=boottime_ns,
                 set_fence=fence, set_marker=marker, healthy=partial(http_healthy, 9999)):
        self.lease = lease
        self.identity = identity
        self.monotonic = monotonic
        self.boot_ns = boot_ns
        self.set_fence = set_fence
        self.set_marker = set_marker
        self.healthy = healthy
        self.observed = None
        self.observed_at = 0
        self.ready_until = 0
        self.active = False
        self.published = False
        self.elected_at = 0
        self.last_healthy_at = None
        self.retry_at = 0

    def ready(self):
        return self.boot_ns() < self.ready_until

    def withdraw(self, *, initial=False):
        self.ready_until = 0
        self.active = False
        try:
            self.set_fence()
        finally:
            self.set_marker()
        if initial or self.published:
            self.lease.publish(self.lease.get_endpoints(), False)
            self.published = False

    def shutdown(self):
        was_active = self.active
        self.withdraw()
        if was_active:
            lease = self.lease.get()
            if lease.get('spec', {}).get('holderIdentity') == self.identity:
                self.lease.put(lease, '')

    def reconcile(self):
        lease = self.lease.get()
        spec = lease.get('spec', {})
        holder = spec.get('holderIdentity')
        observation = lease['metadata']['resourceVersion']
        now = self.monotonic()
        if observation != self.observed:
            self.observed = observation
            self.observed_at = now
        if holder and holder != self.identity:
            if self.active:
                self.withdraw()
            if now - self.observed_at < LEASE_SECONDS:
                return
        if now < self.retry_at:
            return

        healthy = self.active and self.healthy()
        now = self.monotonic()
        if healthy:
            self.last_healthy_at = now
        if self.active and not healthy:
            self.ready_until = 0
            last_seen = self.last_healthy_at
            timed_out = (now - self.elected_at >= START_SECONDS if last_seen is None
                         else now - last_seen >= UNHEALTHY_SECONDS)
            if timed_out:
                self.retry_at = now + COOLDOWN_SECONDS
                self.withdraw()
                if holder == self.identity:
                    self.lease.put(lease, '')
                logging.warning('Relinquished the Gluetun Lease after tunnel health failed')
                return

        # Snapshot before renewing. A process paused after renewing cannot overwrite
        # the EndpointSlice version already published by a replacement leader.
        endpoints = self.lease.get_endpoints() if healthy or self.published else None
        # Deadline comes from before the conditional write, so a late response or
        # a paused process cannot extend the old leader's firewall permissions.
        started = self.monotonic()
        deadline = self.boot_ns() + FENCE_SECONDS * 1_000_000_000
        self.lease.put(lease, self.identity)
        if self.boot_ns() >= deadline - 1_000_000_000:
            raise RuntimeError('Lease renewal took too long')
        self.set_fence(deadline)
        self.set_marker(deadline)
        if not self.active:
            self.active = True
            self.elected_at = started
            self.last_healthy_at = None
            logging.info('Acquired Gluetun Lease')
        if endpoints is not None:
            if self.boot_ns() >= deadline - 1_000_000_000:
                raise RuntimeError('Lease renewal expired before EndpointSlice publication')
            if healthy:
                # Record intent before the write so an ambiguous API failure withdraws it.
                self.published = True
            self.lease.publish(endpoints, healthy)
            self.published = healthy
        self.ready_until = deadline - 1_000_000_000 if healthy else 0


class ReadinessHandler(BaseHTTPRequestHandler):
    def __init__(self, leader, *args):
        self.leader = leader
        super().__init__(*args)

    def do_GET(self):
        self.send_response(200 if self.path == '/' and self.leader.ready() else 503)
        self.end_headers()

    def log_message(self, *_args):
        pass


def main():
    if sys.argv[1:] == ['check']:
        return 0 if http_healthy(9998) else 1
    if sys.argv[1:]:
        raise SystemExit('Expected no arguments or check')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    namespace = os.environ['POD_NAMESPACE']
    identity = os.environ['POD_UID']
    if namespace != 'media' or not identity:
        raise SystemExit('Missing Deluge gateway identity')
    leader = Leader(KubernetesLease(namespace), identity)
    leader.withdraw(initial=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    with ThreadingHTTPServer(('127.0.0.1', 9998), partial(ReadinessHandler, leader)) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            while not stop.is_set():
                started = time.monotonic()
                try:
                    leader.reconcile()
                except (OSError, HTTPException, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
                    logging.warning('Gluetun Lease reconciliation failed')
                    leader.withdraw()
                stop.wait(max(0, started + RECONCILE_SECONDS - time.monotonic()))
        finally:
            try:
                leader.shutdown()
            finally:
                server.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
