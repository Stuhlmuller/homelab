#!/usr/bin/env python3
"""Ensure the public transport gate rejects false health responses."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "transport", Path(__file__).resolve().parents[1] / "octelium-tunnel-check.py"
)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class TransportCheck(unittest.TestCase):
    def check_response(self, headers, body=b"", result="200 2", code=0, native=False):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            def run(command, **_kwargs):
                if command[0] == "dig":
                    return subprocess.CompletedProcess(command, 0, "203.0.113.1\n")
                (directory / "headers").write_bytes(headers)
                (directory / "body").write_bytes(body)
                return subprocess.CompletedProcess(command, code, result)

            with patch.object(transport.subprocess, "run", side_effect=run):
                return transport.probe("octelium-api.example.test", directory, port=18443 if native else None)

    def test_browser_trailer(self):
        headers = b"content-type: application/grpc-web+proto\r\n"
        trailer = b"grpc-status: 16\r\n"
        frame = b"\x80" + len(trailer).to_bytes(4, "big") + trailer
        self.assertTrue(self.check_response(headers, frame))
        for bad in (b"grpc-status: 16\r\n", frame[:-1], frame + b"extra", frame.replace(b"16", b"12")):
            self.assertFalse(self.check_response(headers, bad))
        self.assertFalse(self.check_response(headers, frame, result="502 2"))
        self.assertFalse(self.check_response(headers, frame, code=60))

    def test_native_tls_and_protocol(self):
        headers = b"content-type: application/grpc\r\ngrpc-status: 16\r\n"
        self.assertTrue(self.check_response(headers, native=True))
        self.assertFalse(self.check_response(headers, native=True, code=60))
        self.assertFalse(self.check_response(headers, native=True, result="200 1.1"))
        self.assertFalse(self.check_response(headers.replace(b"grpc-status", b"x-grpc-status"), native=True))
        self.assertFalse(self.check_response(headers.replace(b"16", b"0"), native=True))
        self.assertFalse(self.check_response(b"content-type: text/html\r\n", native=True))


if __name__ == "__main__":
    unittest.main()
