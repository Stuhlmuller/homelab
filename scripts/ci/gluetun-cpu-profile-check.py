#!/usr/bin/env python3
"""Offline ownership, race, bounded HTTP, and cleanup contracts; no live access."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('profile_helper', Path(__file__).resolve().parents[1] / 'gluetun-cpu-profile.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def reference(kind, uid):
    return {'kind': kind, 'uid': uid, 'controller': True}


def inventory():
    return {
        ('deployment', 'deluge'): {'metadata': {'name': 'deluge', 'namespace': 'media', 'uid': 'd'}},
        ('replicasets',): {'items': [{'metadata': {'uid': 'r', 'ownerReferences': [reference('Deployment', 'd')]}}]},
        ('pods',): {'items': [{'metadata': {'name': 'deluge-abc', 'namespace': 'media', 'uid': 'p',
                                           'ownerReferences': [reference('ReplicaSet', 'r')]},
                              'spec': {'nodeName': 'worker', 'initContainers': [
                                  {'name': 'gluetun', 'image': M.IMAGE, 'restartPolicy': 'Always'}]},
                              'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                                         'initContainerStatuses': [{'name': 'gluetun', 'ready': True, 'restartCount': 0,
                                            'imageID': 'containerd://sha256:' + 'a' * 64,
                                            'containerID': 'containerd://instance',
                                            'state': {'running': {'startedAt': '2026-09-06T00:00:00Z'}}}]}}]},
        ('node', 'worker'): {'metadata': {'uid': 'n', 'labels': {
            'kubernetes.io/os': 'linux', 'kubernetes.io/arch': 'amd64'}}},
    }


class Tests(unittest.TestCase):
    def test_context_tls_contract_before_api_and_pinned_inspection(self):
        config = {'current-context': 'homelab', 'contexts': [{'name': 'homelab', 'context': {'cluster': 'home'}}],
                  'clusters': [{'name': 'home', 'cluster': {'server': M.API_SERVER}}]}
        with patch.object(M, 'command', return_value=json.dumps(config).encode()) as command:
            M.check_context()
            command.assert_called_once_with(['kubectl', 'config', 'view', '--minify', '-o', 'json'])
        for field, value in (('server', 'https://unrelated.example:6443'), ('server', 'http://10.1.0.199:6443'),
                             ('insecure-skip-tls-verify', True), ('tls-server-name', 'unrelated.example')):
            changed = copy.deepcopy(config)
            changed['clusters'][0]['cluster'][field] = value
            with patch.object(M, 'command', return_value=json.dumps(changed).encode()), \
                    patch.object(M, 'declared_image'), patch.object(M, 'snapshot') as api:
                with self.assertRaises(RuntimeError):
                    M.operate('check')
                api.assert_not_called()
        with patch.object(M, 'command', return_value=b'{}') as command:
            M.kubectl('get', 'pods', '-o', 'json')
            self.assertEqual(command.call_args.args[0], ['kubectl', '--server=https://10.1.0.199:6443',
                '--insecure-skip-tls-verify=false', '--tls-server-name=10.1.0.199', '-n', 'media',
                'get', 'pods', '-o', 'json'])

    def test_ownership_readiness_and_container_identity(self):
        fixtures = inventory()
        with patch.object(M, 'document', side_effect=lambda *args: fixtures[args]):
            identity = M.snapshot()
        self.assertEqual(identity['pod_uid'], 'p')
        for fault in ('orphan', 'duplicate', 'not-ready', 'restarting', 'wrong-image', 'missing-id', 'arm', 'ambiguous-owner'):
            fixtures = inventory()
            pod = fixtures[('pods',)]['items'][0]
            status = pod['status']['initContainerStatuses'][0]
            if fault == 'orphan':
                pod['metadata']['ownerReferences'][0]['uid'] = 'unrelated'
            elif fault == 'duplicate':
                fixtures[('pods',)]['items'].append(copy.deepcopy(pod))
            elif fault == 'not-ready':
                pod['status']['conditions'][0]['status'] = 'False'
            elif fault == 'restarting':
                status['state'] = {'waiting': {}}
            elif fault == 'wrong-image':
                pod['spec']['initContainers'][0]['image'] = 'wrong:latest'
            elif fault == 'missing-id':
                del status['imageID']
            elif fault == 'arm':
                fixtures[('node', 'worker')]['metadata']['labels']['kubernetes.io/arch'] = 'arm64'
            else:
                pod['metadata']['ownerReferences'].append(reference('ReplicaSet', 'other'))
            with self.subTest(fault=fault), patch.object(M, 'document', side_effect=lambda *args: fixtures[args]):
                with self.assertRaises(RuntimeError):
                    M.snapshot()

    def test_listener_exclusively_ipv4_loopback(self):
        def table(address):
            return f' 0: {address}:17AC 00000000:0000 0A\n'.encode()
        for addresses, enabled, accepted in ((['0100007F'], True, True), ([], False, True),
                ([], True, False), (['0100007F'], False, False), (['00000000'], True, False),
                (['00000000000000000000000001000000'], True, False),
                (['0100007F', '00000000'], True, False), (['0100007F', '0100007F'], True, False)):
            with self.subTest(addresses=addresses, enabled=enabled), patch.object(M, 'kubectl',
                    return_value=b' sl local_address rem_address st\n' +
                    b''.join(table(address) for address in addresses) + b' sl local_address rem_address st\n'):
                if accepted:
                    M.listener({'pod': 'deluge-abc'}, enabled)
                else:
                    with self.assertRaises(RuntimeError):
                        M.listener({'pod': 'deluge-abc'}, enabled)

        with patch.object(M, 'kubectl', return_value=b''):
            with self.assertRaises(RuntimeError):
                M.listener({'pod': 'deluge-abc'}, False)

    def test_local_contract_rejects_dirty_values_before_live_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / M.VALUES
            path.parent.mkdir(parents=True)
            path.write_bytes(b'fixture')
            projection = {'image': M.IMAGE, 'profiling': {
                'pprof_enabled': 'on', 'pprof_http_server_address': '127.0.0.1:6060'}}
            result = subprocess.CompletedProcess([], 0, json.dumps(projection).encode())
            with patch.object(M, 'ROOT', root), patch.object(M, 'command', side_effect=[b'fixture', b'']), \
                    patch.object(M.subprocess, 'run', return_value=result):
                M.declared_image(True)
            for source, status in ((b'fixture', b' M values'), (b'different', b'')):
                with patch.object(M, 'ROOT', root), patch.object(M, 'command', side_effect=[source, status]), \
                        patch.object(M, 'snapshot') as live:
                    with self.assertRaises(RuntimeError):
                        M.operate('capture')
                    live.assert_not_called()
            with patch.object(M, 'ROOT', root), patch.object(M, 'command', side_effect=[b'fixture', b'']), \
                    patch.object(M.subprocess, 'run', return_value=result):
                with self.assertRaises(RuntimeError):
                    M.declared_image(False)

    def test_capture_identity_races_and_cleanup(self):
        identity = {'pod': 'deluge-abc', 'pod_uid': 'p', 'restarts': 0}
        for fault in ('none', 'startup', 'download', 'replaced', 'restarted', 'unready', 'forward-exit'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as parent:
                directory = Path(parent) / 'capture'
                directory.mkdir()
                process = Mock()
                process.poll.return_value = 1 if fault == 'forward-exit' else None
                after = {**identity, 'pod_uid': 'new'} if fault == 'replaced' else dict(identity)
                if fault == 'restarted':
                    after['restarts'] = 1
                snapshots = [identity, identity, identity,
                             RuntimeError('unready') if fault == 'unready' else after]
                def download(port, path):
                    path.write_bytes(b'\x1f\x8bfixture')
                    path.chmod(0o600)
                    if fault == 'download':
                        raise RuntimeError('truncated')
                with patch.object(M, 'declared_image'), patch.object(M, 'check_context'), patch.object(M, 'snapshot', side_effect=snapshots), \
                        patch.object(M, 'listener'), patch.object(M, 'forward', return_value=process), \
                        patch.object(M, 'forwarded_port', side_effect=RuntimeError('startup') if fault == 'startup' else None,
                                     return_value=45678), patch.object(M, 'download', side_effect=download), \
                        patch.object(M.tempfile, 'mkdtemp', return_value=str(directory)), patch.object(M, 'stop') as stop:
                    if fault == 'none':
                        result = M.operate('capture')
                        self.assertEqual(result['directory'], str(directory))
                        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                        metadata = json.loads((directory / 'metadata.json').read_text())
                        self.assertLessEqual(metadata['capture_start_utc'], metadata['capture_end_utc'])
                        self.assertGreaterEqual(metadata['elapsed_seconds'], 0)
                        self.assertEqual(metadata['bytes'], len(b'\x1f\x8bfixture'))
                        for item in directory.iterdir():
                            self.assertEqual(item.stat().st_mode & 0o777, 0o600)
                    else:
                        with self.assertRaises(RuntimeError):
                            M.operate('capture')
                        self.assertFalse(directory.exists())
                    stop.assert_called_once_with(process)

    def test_http_path_redirect_bound_and_deadline(self):
        for fault in ('none', 'redirect', 'content-type', 'oversize', 'deadline', 'empty',
                      'short-length', 'truncated-gzip', 'bad-crc', 'expanded-bound', 'expiry-at-eof'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                connection = Mock()
                response = connection.getresponse.return_value
                payload = gzip.compress(b'fixture')
                def header(name, default=None):
                    if name == 'Content-Type':
                        return 'text/html' if fault == 'content-type' else 'application/octet-stream'
                    return str(len(payload) + 1) if fault == 'short-length' else None
                response.getheader.side_effect = header
                response.status = 302 if fault == 'redirect' else 200
                response.read1.side_effect = [b'', b''] if fault == 'empty' else [
                    payload[:-4] if fault == 'truncated-gzip' else
                    payload[:-8] + bytes([payload[-8] ^ 1]) + payload[-7:] if fault == 'bad-crc' else payload, b'']
                clock = ([0, 0, 46] if fault == 'deadline' else
                         [0, 0, 0, 0, 0, 0, 46] if fault == 'expiry-at-eof' else [0] * 15)
                with patch.object(M.http.client, 'HTTPConnection', return_value=connection) as constructor, \
                        patch.object(M.time, 'monotonic', side_effect=clock), \
                        patch.object(M, 'LIMIT', 2 if fault == 'oversize' else 1024), \
                        patch.object(M, 'EXPANDED_LIMIT', 2 if fault == 'expanded-bound' else 1024):
                    if fault == 'none':
                        M.download(45678, Path(directory) / 'cpu')
                    else:
                        with self.assertRaises((RuntimeError, EOFError, gzip.BadGzipFile)):
                            M.download(45678, Path(directory) / 'cpu')
                    constructor.assert_called_once_with('127.0.0.1', 45678, timeout=45)
                    connection.request.assert_called_once_with('GET', '/debug/pprof/profile?seconds=30')
                    connection.close.assert_called_once()

    def test_absolute_deadline_interrupts_blocked_headers(self):
        # getresponse never returns on its own; only the owned socket shutdown
        # releases this fake header reader. Real timer, no network or service.
        released = threading.Event()
        connection = Mock()
        connection.sock.shutdown.side_effect = lambda *_: released.set()
        def blocked_headers():
            self.assertTrue(released.wait(2), 'Outer deadline failed to interrupt headers')
            raise TimeoutError('header read interrupted')
        connection.getresponse.side_effect = blocked_headers
        timer_class = threading.Timer
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(M.http.client, 'HTTPConnection', return_value=connection), \
                patch.object(M.threading, 'Timer', side_effect=lambda seconds, callback: timer_class(0.02, callback)):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                M.download(45678, Path(directory) / 'cpu')
            self.assertLess(time.monotonic() - start, 1)
            connection.sock.shutdown.assert_called_once()
            connection.close.assert_called_once()

    def test_failed_cleanup_reports_only_owned_private_path(self):
        identity = {'pod': 'deluge-abc'}
        with tempfile.TemporaryDirectory() as parent:
            directory = Path(parent) / 'owned-capture'
            directory.mkdir()
            with patch.object(M, 'declared_image'), patch.object(M, 'check_context'), patch.object(M, 'snapshot', return_value=identity), \
                    patch.object(M, 'listener'), patch.object(M.tempfile, 'mkdtemp', return_value=str(directory)), \
                    patch.object(M, 'forward', side_effect=RuntimeError('private vendor output')), \
                    patch.object(M.shutil, 'rmtree', side_effect=PermissionError('private diagnostic')):
                with self.assertRaisesRegex(M.CleanupFailure, str(directory)) as failure:
                    M.operate('capture')
                self.assertNotIn('private diagnostic', str(failure.exception))
                self.assertNotIn('no profile retained', str(failure.exception))

    def test_cleanup_absent_root_succeeds_but_missing_child_fails(self):
        for absent_root in (True, False):
            with self.subTest(absent_root=absent_root), tempfile.TemporaryDirectory() as parent:
                directory = Path(parent) / 'owned-capture'
                directory.mkdir()
                def cleanup(path):
                    if absent_root:
                        path.rmdir()
                    raise FileNotFoundError('root or child disappeared')
                with patch.object(M, 'declared_image'), patch.object(M, 'check_context'), \
                        patch.object(M, 'snapshot', return_value={'pod': 'deluge-abc'}), \
                        patch.object(M, 'listener'), patch.object(M.tempfile, 'mkdtemp', return_value=str(directory)), \
                        patch.object(M, 'forward', side_effect=RuntimeError('original failure')), \
                        patch.object(M.shutil, 'rmtree', side_effect=cleanup):
                    if absent_root:
                        with self.assertRaisesRegex(RuntimeError, '^original failure$'):
                            M.operate('capture')
                    else:
                        with self.assertRaises(M.CleanupFailure):
                            M.operate('capture')

    def test_forward_startup_and_exact_owned_command(self):
        process = Mock()
        process.poll.return_value = None
        process.stdout.fileno.return_value = 1
        process.stderr.fileno.return_value = 2
        for line, accepted in ((b'Forwarding from 127.0.0.1:45678 -> 6060\n', True),
                               (b'Forwarding from 0.0.0.0:45678 -> 6060\n', False),
                               (b'Forwarding from 127.0.0.1:99999 -> 6060\n', False), (b'', False)):
            with patch.object(M.select, 'select', return_value=([process.stdout], [], [])), \
                    patch.object(M.os, 'read', side_effect=[line, b'']), \
                    patch.object(M.time, 'monotonic', return_value=0):
                if accepted:
                    self.assertEqual(M.forwarded_port(process), 45678)
                else:
                    with self.assertRaises(RuntimeError):
                        M.forwarded_port(process)
        with patch.object(M.subprocess, 'Popen', return_value=process) as popen:
            M.forward({'pod': 'deluge-abc'})
            self.assertEqual(popen.call_args.args[0], ['kubectl', *M.API_FLAGS, '-n', 'media', 'port-forward',
                                                      '--address=127.0.0.1', 'pod/deluge-abc', ':6060'])

    def test_stop_kills_only_owned_uncooperative_process(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('owned', 3), 0]
        M.stop(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = ProcessLookupError()
        M.stop(process)
        process.wait.assert_called_once_with(timeout=3)


if __name__ == '__main__':
    unittest.main()
