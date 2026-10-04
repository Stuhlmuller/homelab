#!/usr/bin/env python3
"""Real loopback TLS primitives and offline rendered identity checks, not proxy/server acceptance."""
import argparse
import copy
import importlib.util
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tls_render', ROOT / 'scripts/harbor-tls-render.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NAMES = ('harbor.stinkyboi.com', 'harbor-frontend.harbor.svc.cluster.local', 'harbor-core', 'harbor-portal')
CHART = None
HELM = 'helm'


class HandshakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.cert = Path(cls.tmp.name) / 'cert.pem'
        cls.key = Path(cls.tmp.name) / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(cls.key), '-out', str(cls.cert), '-days', '1',
                        '-subj', '/CN=synthetic-only', '-addext',
                        'subjectAltName=' + ','.join('DNS:' + name for name in NAMES)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def connect(self, name, *, trust=True, plaintext=False):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(3)
        address = listener.getsockname()
        received = []

        def serve():
            try:
                raw, _ = listener.accept()
                with raw:
                    raw.settimeout(3)
                    if plaintext:
                        raw.recv(4096)
                        raw.sendall(b'HTTP/1.1 200 OK\r\n\r\n')
                    else:
                        try:
                            with context.wrap_socket(raw, server_side=True) as conn:
                                received.append(conn.recv(32))
                        except (ssl.SSLError, OSError):
                            pass
            finally:
                listener.close()

        worker = threading.Thread(target=serve)
        worker.start()
        client = ssl.create_default_context(cafile=str(self.cert) if trust else None)
        client.minimum_version = ssl.TLSVersion.TLSv1_2
        succeeds = trust and name in NAMES and not plaintext
        try:
            if succeeds:
                with socket.create_connection(address, timeout=3) as raw, \
                        client.wrap_socket(raw, server_hostname=name) as conn:
                    conn.sendall(b'synthetic-auth')
            else:
                with self.assertRaises(ssl.SSLError), socket.create_connection(address, timeout=3) as raw, \
                        client.wrap_socket(raw, server_hostname=name) as conn:
                    conn.sendall(b'synthetic-auth')
        finally:
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(received, [b'synthetic-auth'] if succeeds else [])

    def test_each_hop_matching_identity(self):
        for name in NAMES:
            with self.subTest(hop=name):
                self.connect(name)

    def test_each_hop_untrusted_ca(self):
        for name in NAMES:
            with self.subTest(hop=name):
                self.connect(name, trust=False)

    def test_each_hop_wrong_san(self):
        for name in NAMES:
            with self.subTest(hop=name):
                self.connect('wrong.' + name)

    def test_each_hop_plaintext_has_no_fallback(self):
        for name in NAMES:
            with self.subTest(hop=name):
                self.connect(name, plaintext=True)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = m.render(CHART, HELM)

    def test_actual_render(self):
        m.check(self.resources)

    def test_disabled_verification_rejected(self):
        resources = copy.deepcopy(self.resources)
        cm = m.one(resources, 'ConfigMap', 'harbor-nginx')
        cm['data']['nginx.conf'] = cm['data']['nginx.conf'].replace('proxy_ssl_verify on;', 'proxy_ssl_verify off;')
        with self.assertRaises(ValueError):
            m.check(resources)

    def test_missing_trust_mount_rejected(self):
        resources = copy.deepcopy(self.resources)
        pod = m.one(resources, 'Deployment', 'harbor-nginx')['spec']['template']['spec']
        pod['containers'][0]['volumeMounts'].pop()
        with self.assertRaises(ValueError):
            m.check(resources)

    def test_plaintext_service_rejected(self):
        resources = copy.deepcopy(self.resources)
        m.one(resources, 'Service', 'harbor')['spec']['ports'].append({'port': 80, 'targetPort': 8080})
        with self.assertRaises(ValueError):
            m.check(resources)

    def test_gateway_identity_and_certificate_contract(self):
        dr = m.one(self.resources, 'DestinationRule', 'harbor-verified-frontend')
        tls = dr['spec']['trafficPolicy']['portLevelSettings'][0]['tls']
        self.assertEqual(tls, {'mode': 'SIMPLE', 'credentialName': 'harbor-frontend-trust',
                              'sni': NAMES[1], 'subjectAltNames': [NAMES[1]], 'insecureSkipVerify': False})
        cert = m.one(self.resources, 'Certificate', 'harbor-frontend-tls')
        self.assertIn(NAMES[1], cert['spec']['dnsNames'])
        self.assertEqual(m.one(self.resources, 'VirtualService', 'harbor-octelium')['spec']['http'][0]
                         ['route'][0]['destination']['port']['number'], 443)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--chart', type=Path, required=True)
    parser.add_argument('--helm', default='helm')
    args, remaining = parser.parse_known_args()
    CHART, HELM = args.chart, args.helm
    unittest.main(argv=['harbor-tls-test'] + remaining)
