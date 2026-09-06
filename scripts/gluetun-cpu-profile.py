#!/usr/bin/env python3
"""Inspect or privately capture the declared Deluge Gluetun CPU profile."""
import argparse
from datetime import datetime, timezone
import http.client
import gzip
import zlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
API_SERVER = 'https://10.1.0.199:6443'
API_FLAGS = ['--server=' + API_SERVER, '--insecure-skip-tls-verify=false', '--tls-server-name=10.1.0.199']
VALUES = 'clusters/homelab/apps/deluge/values.yaml'
IMAGE = 'ghcr.io/qdm12/gluetun:v3.41.3@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027'
LIMIT = 16 * 1024 * 1024
EXPANDED_LIMIT = 64 * 1024 * 1024


class CleanupFailure(RuntimeError):
    """An owned private directory could not be removed."""


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def stop(process):
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            # The owned process can exit between poll() and terminate().
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                # It may also exit after wait times out but before kill().
                pass
            process.wait(timeout=3)
    for stream in (process.stdout, process.stderr):
        if stream:
            stream.close()


def command(args, timeout=15, limit=4 * 1024 * 1024):
    process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = bytearray()
    size = 0
    deadline = time.monotonic() + timeout
    streams = [process.stdout, process.stderr]
    try:
        while streams:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'Inspection command exceeded deadline')
            ready, _, _ = select.select(streams, [], [], remaining)
            for stream in ready:
                data = os.read(stream.fileno(), 65536)
                if not data:
                    streams.remove(stream)
                    continue
                size += len(data)
                require(size <= limit, 'Inspection command exceeded output bound')
                if stream is process.stdout:
                    output.extend(data)
        require(process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
                'Inspection command failed; vendor output withheld')
        return bytes(output)
    finally:
        stop(process)


def check_context():
    # Local, redacted projection only; never export kubeconfig or trust --raw.
    config = json.loads(command(['kubectl', 'config', 'view', '--minify', '-o', 'json']))
    clusters = config.get('clusters', [])
    contexts = config.get('contexts', [])
    require(len(clusters) == len(contexts) == 1 and
            contexts[0].get('name') == config.get('current-context') and
            contexts[0].get('context', {}).get('cluster') == clusters[0].get('name'),
            'Expected one current Kubernetes context and cluster')
    cluster = clusters[0].get('cluster', {})
    require(cluster.get('server') == API_SERVER and
            cluster.get('insecure-skip-tls-verify', False) is False and
            cluster.get('tls-server-name', '') in ('', '10.1.0.199'),
            'Current Kubernetes context must use the reviewed API endpoint with TLS verification')


def kubectl(*args):
    # Explicit flags prevent an ambient context change redirecting later calls.
    return command(['kubectl', *API_FLAGS, '-n', 'media', *args])


def document(*args):
    return json.loads(kubectl('get', *args, '-o', 'json'))


def owner(resource, kind, uid):
    refs = resource.get('metadata', {}).get('ownerReferences', [])
    controllers = [ref for ref in refs if ref.get('controller') is True]
    return len(controllers) == 1 and controllers[0].get('kind') == kind and controllers[0].get('uid') == uid


def declared_image(enabled):
    # HEAD and matching local bytes own desired state, never shell overrides.
    raw = command(['git', 'show', f'HEAD:{VALUES}'])
    require(not command(['git', 'status', '--porcelain', '--untracked-files=all', '--', VALUES]).strip() and
            (ROOT / VALUES).is_file() and not (ROOT / VALUES).is_symlink() and
            (ROOT / VALUES).read_bytes() == raw, 'Profiling values are not committed and unchanged')
    query = ('{"image": (.controllers.deluge.initContainers.gluetun.image | '
             '.repository + ":" + .tag), "profiling": .configMaps.gluetun-profiling.data}')
    process = subprocess.run(['yq', '-o=json', query],
                             input=raw, capture_output=True, timeout=10, check=False)
    require(process.returncode == 0, 'Cannot read committed profiling contract')
    projection = json.loads(process.stdout)
    require(projection['image'] == IMAGE and projection['profiling'] == {
        'pprof_enabled': 'on' if enabled else 'off', 'pprof_http_server_address': '127.0.0.1:6060'},
        'Committed profiling settings or image differ from the reviewed contract')


def snapshot():
    deployment = document('deployment', 'deluge')
    metadata = deployment['metadata']
    require(metadata.get('name') == 'deluge' and metadata.get('namespace') == 'media' and
            not metadata.get('deletionTimestamp') and metadata.get('uid'), 'Deployment identity is invalid')
    uid = metadata['uid']
    replicas = document('replicasets')['items']
    rs_uids = {item['metadata']['uid'] for item in replicas if owner(item, 'Deployment', uid)}
    pods = [pod for pod in document('pods')['items']
            if any(owner(pod, 'ReplicaSet', rs_uid) for rs_uid in rs_uids)]
    ready = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp') and
             pod.get('status', {}).get('phase') == 'Running' and
             [item.get('status') for item in pod.get('status', {}).get('conditions', [])
              if item.get('type') == 'Ready'] == ['True']]
    require(len(ready) == 1, 'Expected exactly one Ready Deployment-owned Pod')
    pod = ready[0]
    name = pod['metadata']['name']
    require(re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}', name) and pod['metadata'].get('uid') and
            pod['metadata'].get('namespace') == 'media', 'Pod identity is invalid')
    node = document('node', pod['spec']['nodeName'])
    require(node['metadata'].get('labels', {}).get('kubernetes.io/os') == 'linux' and
            node['metadata'].get('labels', {}).get('kubernetes.io/arch') == 'amd64' and
            node['metadata'].get('uid'), 'Gluetun node must be Linux amd64')
    specs = [item for item in pod['spec'].get('initContainers', []) if item.get('name') == 'gluetun']
    statuses = [item for item in pod['status'].get('initContainerStatuses', []) if item.get('name') == 'gluetun']
    require(len(specs) == len(statuses) == 1, 'Expected one Gluetun restartable init container')
    spec, status = specs[0], statuses[0]
    require(spec.get('image') == IMAGE and spec.get('restartPolicy') == 'Always' and
            status.get('ready') is True and status.get('state', {}).get('running', {}).get('startedAt'),
            'Gluetun image or running/readiness state differs')
    require(isinstance(status.get('imageID'), str) and
            re.search(r'@?sha256:[0-9a-f]{64}$', status['imageID']) and
            isinstance(status.get('containerID'), str) and status['containerID'] and
            type(status.get('restartCount')) is int and status['restartCount'] >= 0,
            'Gluetun runtime identity is incomplete')
    return {'node_uid': node['metadata']['uid'], 'node': pod['spec']['nodeName'], 'deployment_uid': uid, 'replicaset_uid': next(ref['uid'] for ref in pod['metadata']['ownerReferences']
                                                       if ref.get('controller') is True),
            'pod': name, 'pod_uid': pod['metadata']['uid'], 'image': IMAGE,
            'image_id': status['imageID'], 'container_id': status['containerID'],
            'started_at': status['state']['running']['startedAt'], 'restarts': status['restartCount']}


def listener(identity, enabled):
    raw = kubectl('exec', f'pod/{identity["pod"]}', '-c', 'gluetun', '--',
                  'cat', '/proc/net/tcp', '/proc/net/tcp6').decode('ascii')
    listeners = []
    require(sum(line.split()[:1] == ['sl'] for line in raw.splitlines()) == 2,
            'Incomplete IPv4/IPv6 socket inventory')
    for line in raw.splitlines():
        fields = line.split()
        if not fields or fields[0] == 'sl':
            continue
        require(len(fields) >= 4 and ':' in fields[1], 'Malformed socket inventory')
        require(re.fullmatch(r'(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{32}):[0-9A-Fa-f]{4}', fields[1]) and
                re.fullmatch(r'[0-9A-Fa-f]{2}', fields[3]), 'Malformed socket address or state')
        address, port = fields[1].split(':')
        if port.upper() == '17AC' and fields[3] == '0A':
            listeners.append(address.upper())
    require(listeners == (['0100007F'] if enabled else []),
            'Profiling listener is absent, ambiguous, or not exclusively IPv4 loopback' if enabled else
            'Profiling listener remains enabled')


def forward(identity):
    return subprocess.Popen(['kubectl', *API_FLAGS, '-n', 'media', 'port-forward', '--address=127.0.0.1',
                             f'pod/{identity["pod"]}', ':6060'], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def forwarded_port(process):
    deadline = time.monotonic() + 10
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    size = 0
    while buffers:
        remaining = deadline - time.monotonic()
        require(remaining > 0 and process.poll() is None, 'Port-forward startup failed or timed out')
        ready, _, _ = select.select(list(buffers), [], [], remaining)
        for stream in ready:
            data = os.read(stream.fileno(), 4096)
            require(data, 'Port-forward closed before readiness')
            size += len(data)
            require(size <= 65536, 'Port-forward startup output exceeded bound')
            buffers[stream].extend(data)
            while b'\n' in buffers[stream]:
                line, _, rest = buffers[stream].partition(b'\n')
                buffers[stream] = bytearray(rest)
                match = re.fullmatch(rb'Forwarding from 127\.0\.0\.1:([0-9]+) -> 6060\r?', line)
                if match:
                    port = int(match[1])
                    require(0 < port <= 65535, 'Invalid forwarded port')
                    return port
    raise RuntimeError('No forwarding listener')


def download(port, path):
    # HTTPConnection never uses proxy environment or follows redirects.
    deadline = time.monotonic() + 45
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=45)
    timer = None
    try:
        connection.connect()
        transport = connection.sock
        require(transport is not None, 'Profile connection is unavailable')
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'Profile exceeded 45-second deadline')
        # A socket timeout alone resets for each header read. Close this exact
        # socket at the absolute deadline, including a trickling header/body.
        def expire():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                # The peer or normal cleanup may have already closed this socket.
                pass
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        transport.settimeout(remaining)
        connection.request('GET', '/debug/pprof/profile?seconds=30')
        response = connection.getresponse()
        require(time.monotonic() < deadline, 'Profile exceeded 45-second deadline')
        require(response.status == 200, 'Profile request failed or redirected')
        require(response.getheader('Content-Type', '').split(';', 1)[0].strip().lower() ==
                'application/octet-stream', 'Unexpected profile content type')
        length = response.getheader('Content-Length')
        if length is not None:
            require(re.fullmatch(r'[0-9]+', length) and int(length) <= LIMIT, 'Invalid profile length')
            length = int(length)
        size = 0
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'Profile exceeded 45-second deadline')
                # read1 performs at most one underlying read, avoiding a trickle
                # resetting a per-read timeout indefinitely inside read(n).
                transport.settimeout(remaining)
                data = response.read1(65536)
                require(time.monotonic() < deadline, 'Profile exceeded 45-second deadline')
                if not data:
                    break
                size += len(data)
                require(size <= LIMIT, 'Profile exceeded 16 MiB bound')
                output.write(data)
        require(length is None or size == length, 'Incomplete profile body')
        with path.open('rb') as profile:
            require(size > 0 and profile.read(2) == b'\x1f\x8b', 'Profile is empty or not gzip pprof')
        # Validate complete gzip members and CRC; never retain expanded content.
        expanded = 0
        with gzip.open(path, 'rb') as profile:
            while True:
                data = profile.read(65536)
                require(time.monotonic() < deadline, 'Profile exceeded 45-second deadline')
                if not data:
                    break
                expanded += len(data)
                require(expanded <= EXPANDED_LIMIT, 'Expanded profile exceeded 64 MiB bound')
        require(expanded > 0, 'Empty expanded profile')
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        connection.close()


def operate(mode):
    declared_image(mode != 'check-disabled')
    check_context()
    before = snapshot()
    listener(before, mode != 'check-disabled')
    require(snapshot() == before, 'Pod identity changed during inspection')
    if mode != 'capture':
        return {'status': mode, **before}
    directory = Path(tempfile.mkdtemp(prefix='gluetun-cpu-profile-', dir='/tmp'))
    os.chmod(directory, 0o700)
    process = None
    retained = False
    try:
        process = forward(before)
        port = forwarded_port(process)
        require(snapshot() == before, 'Pod identity changed before capture')
        capture_start = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        download(port, directory / 'cpu.pprof')
        duration = time.monotonic() - start
        capture_end = datetime.now(timezone.utc).isoformat()
        require(process.poll() is None, 'Port-forward exited during capture')
        listener(before, True)
        require(snapshot() == before, 'Pod identity or readiness changed; profile discarded')
        with (directory / 'metadata.json').open('x') as output:
            os.chmod(directory / 'metadata.json', 0o600)
            json.dump({'seconds': 30, 'capture_start_utc': capture_start, 'capture_end_utc': capture_end,
                       'elapsed_seconds': duration, 'bytes': (directory / 'cpu.pprof').stat().st_size,
                       **before}, output, indent=2)
        stop(process)
        process = None
        retained = True
        return {'status': 'captured', 'directory': str(directory), **before}
    finally:
        try:
            if process is not None:
                stop(process)
        finally:
            if not retained:
                try:
                    shutil.rmtree(directory)
                except FileNotFoundError:
                    try:
                        directory.lstat()
                    except FileNotFoundError:
                        # Already-absent root means cleanup completed, unlike a missing child.
                        pass
                    except OSError:
                        raise CleanupFailure(f'Private capture cleanup failed; inspect/remove {directory}') from None
                    else:
                        raise CleanupFailure(f'Private capture cleanup failed; inspect/remove {directory}') from None
                except OSError:
                    raise CleanupFailure(f'Private capture cleanup failed; inspect/remove {directory}') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'capture', 'check-disabled'])
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise RuntimeError('Profiling interrupted')

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        print(json.dumps(operate(args.command), indent=2))
    except CleanupFailure as error:
        parser.exit(1, str(error) + '\n')
    except (RuntimeError, OSError, EOFError, zlib.error, ValueError, KeyError, TypeError, subprocess.SubprocessError, http.client.HTTPException):
        parser.exit(1, 'Gluetun profiling check failed; no profile retained. Check ownership, readiness, listener, and access.\n')
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
