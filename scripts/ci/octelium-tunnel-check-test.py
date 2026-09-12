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
    @staticmethod
    def response(fields, trailers=b""):
        return b"HTTP/2 200\r\n" + fields + b"\r\n" + trailers

    @staticmethod
    def frame(fields=b"grpc-status: 16\r\n"):
        return b"\x80" + len(fields).to_bytes(4, "big") + fields

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
        headers = self.response(b"content-type: application/grpc-web+proto\r\n")
        trailer = b"grpc-status: 16\r\n"
        frame = b"\x80" + len(trailer).to_bytes(4, "big") + trailer
        self.assertTrue(self.check_response(headers, frame))
        for bad in (b"grpc-status: 16\r\n", frame[:-1], frame + b"extra", frame.replace(b"16", b"12")):
            self.assertFalse(self.check_response(headers, bad))
        self.assertFalse(self.check_response(headers, frame, result="502 2"))
        self.assertFalse(self.check_response(headers, frame, code=60))

    def test_native_tls_and_protocol(self):
        headers = self.response(b"content-type: application/grpc\r\ngrpc-status: 16\r\n")
        self.assertTrue(self.check_response(headers, native=True))
        self.assertFalse(self.check_response(headers, native=True, code=60))
        self.assertFalse(self.check_response(headers, native=True, result="200 1.1"))
        self.assertFalse(self.check_response(headers.replace(b"grpc-status", b"x-grpc-status"), native=True))
        self.assertFalse(self.check_response(headers.replace(b"16", b"0"), native=True))
        self.assertFalse(self.check_response(b"content-type: text/html\r\n", native=True))

    def test_browser_trailers_only_headers(self):
        headers = self.response(b"content-type: application/grpc-web+proto\r\ngrpc-status: 16\r\n")
        self.assertTrue(self.check_response(headers))
        for bad in (headers.replace(b"16", b"0"),
                    headers.replace(b"grpc-status", b"x-grpc-status"),
                    b"content-type: text/html\r\ngrpc-status: 16\r\n"):
            self.assertFalse(self.check_response(bad))
        self.assertFalse(self.check_response(headers, b"partial"))
        self.assertFalse(self.check_response(headers, result="502 2"))
        self.assertFalse(self.check_response(headers, result="200 1.1"))
        self.assertFalse(self.check_response(headers, code=60))

    def test_content_type_requires_one_actual_exact_field(self):
        for native, media in ((False, b"application/grpc-web+proto"), (True, b"application/grpc")):
            for field in (b"x-content-type: " + media, b"content-type: " + media + b"junk",
                          b"content-type: " + media + b"\v", b"content-type: " + media + b"\f",
                          b"content-type: text/html", b"content-type: " + media + b", text/html",
                          b"content-type: " + media + b"\r\nContent-Type: " + media,
                          b"content-type: " + media + b"\r\ncontent-type: text/html"):
                with self.subTest(native=native, field=field):
                    headers = self.response(field + b"\r\ngrpc-status: 16\r\n")
                    self.assertFalse(self.check_response(headers, native=native))
            headers = self.response(b"Content-Type:\t" + media + b"; charset=utf-8\r\nGrpc-Status:\t16\r\n")
            self.assertTrue(self.check_response(headers, native=native))
        native_proto = self.response(b"content-type: application/grpc+proto\r\ngrpc-status: 16\r\n")
        self.assertTrue(self.check_response(native_proto, native=True))

    def test_earlier_responses_cannot_supply_final_status_or_content_type(self):
        for native, media in ((False, b"application/grpc-web+proto"), (True, b"application/grpc")):
            for status in (b"HTTP/2 103", b"HTTP/1.1 200 Connection established"):
                with self.subTest(native=native, status=status):
                    earlier = status + b"\r\ncontent-type: " + media + b"\r\ngrpc-status: 16\r\n\r\n"
                    final = self.response(b"content-type: " + media + b"\r\n")
                    self.assertFalse(self.check_response(earlier + final, native=native))
                    self.assertFalse(self.check_response(earlier + self.response(b"grpc-status: 16\r\n"), native=native))
                    for value in (b"0", b"16"):
                        final = self.response(b"content-type: " + media + b"\r\ngrpc-status: " + value + b"\r\n")
                        self.assertEqual(self.check_response(earlier + final, native=native), value == b"16")

    def test_native_http_trailers_belong_to_final_response(self):
        earlier = b"HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 103\r\ngrpc-status: 0\r\n\r\n"
        final = self.response(b"content-type: application/grpc\r\n", b"grpc-status: 16\r\n")
        self.assertTrue(self.check_response(earlier + final, native=True))
        self.assertTrue(self.check_response(final, b"\0\0\0\0\0", native=True))
        self.assertFalse(self.check_response(final.replace(b"16", b"0"), native=True))
        missing_type = self.response(b"server: fixture\r\n", b"content-type: application/grpc\r\ngrpc-status: 16\r\n")
        self.assertFalse(self.check_response(missing_type, native=True))
        duplicate_type = self.response(b"content-type: application/grpc\r\n", b"content-type: application/grpc\r\ngrpc-status: 16\r\n")
        self.assertFalse(self.check_response(duplicate_type, native=True))

    def test_missing_incorrect_and_duplicate_status_fail_in_each_location(self):
        for fields in (b"", b"grpc-status: 0\r\n", b"x-grpc-status: 16\r\n",
                       b"grpc-status: 16\r\ngrpc-status: 16\r\n",
                       b"grpc-status: 16\r\nGrpc-Status: 0\r\n",
                       b"grpc-status: 16, 0\r\n", b" grpc-status: 16\r\n"):
            with self.subTest(fields=fields):
                browser = self.response(b"content-type: application/grpc-web+proto\r\n")
                self.assertFalse(self.check_response(browser, self.frame(fields)))
                self.assertFalse(self.check_response(self.response(b"content-type: application/grpc-web+proto\r\n" + fields)))
                native = self.response(b"content-type: application/grpc\r\n", fields)
                self.assertFalse(self.check_response(native, native=True))

    def test_nonempty_bodies_cannot_reuse_header_status(self):
        browser = self.response(b"content-type: application/grpc-web+proto\r\ngrpc-status: 16\r\n")
        self.assertFalse(self.check_response(browser, self.frame()))
        self.assertFalse(self.check_response(browser, b"partial"))
        native = self.response(b"content-type: application/grpc\r\ngrpc-status: 16\r\n")
        self.assertFalse(self.check_response(native, b"\0\0\0\0\0", native=True))
        duplicate = self.response(b"content-type: application/grpc\r\ngrpc-status: 16\r\n", b"grpc-status: 16\r\n")
        self.assertFalse(self.check_response(duplicate, native=True))

    def test_browser_body_trailer_is_independent_of_earlier_responses(self):
        earlier = b"HTTP/2 103\r\ncontent-type: text/html\r\ngrpc-status: 0\r\n\r\n"
        final = self.response(b"content-type: application/grpc-web+proto\r\n")
        self.assertTrue(self.check_response(earlier + final, self.frame()))
        self.assertFalse(self.check_response(final + b"grpc-status: 16\r\n", self.frame()))
        self.assertFalse(self.check_response(final + b"grpc-status: 16\r\n"))

    def test_dump_must_include_a_matching_final_http_status_line(self):
        fields = b"content-type: application/grpc-web+proto\r\ngrpc-status: 16\r\n"
        for headers in (fields, b"HTTP/2 502\r\n" + fields + b"\r\n",
                        b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n"):
            self.assertFalse(self.check_response(headers))


if __name__ == "__main__":
    unittest.main()
