"""Monitor the WireGuard transit tunnel and provide Deluge's loopback resolver."""

from functools import partial
from http.client import HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import logging
import signal
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.request


RESOLVERS = (("cloudflare-dns.com", "1.1.1.1"), ("dns.google", "8.8.8.8"))
PERIOD = 3
REQUIRED_ROUNDS = 3
STALE_AFTER = 10
RENEW_AFTER = 30
REQUEST_TIMEOUT = 1
MAX_WIRE_MESSAGE = 65535
DNS_HEADER = struct.Struct("!6H")
TLS_CONTEXT = ssl.create_default_context()
NETWORK = Path(__file__).with_name("network.py")
HEALTH_QUERY = DNS_HEADER.pack(0, 0x0100, 1, 0, 0, 0) + b"\x07example\x03com\0\0\x01\0\x01"


def question_end(message):
    if len(message) < DNS_HEADER.size or DNS_HEADER.unpack_from(message)[2] != 1:
        raise ValueError("expected one DNS question")
    offset = DNS_HEADER.size
    while offset < len(message) and offset < DNS_HEADER.size + 255:
        length = message[offset]
        offset += 1
        if length == 0 and offset + 4 <= len(message):
            return offset + 4
        if not 1 <= length <= 63:
            break
        offset += length
    raise ValueError("invalid DNS question")


def local_response(query, flags):
    identifier, request_flags, *_ = DNS_HEADER.unpack_from(query)
    return DNS_HEADER.pack(identifier, flags | (request_flags & 0x0110), 1, 0, 0, 0) + query[12:question_end(query)]


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=REQUEST_TIMEOUT, context=TLS_CONTEXT)
        self.address = address
        self.deadline_socket = None
        self.socket_lock = threading.Lock()
        self.expired = False

    def connect(self):
        # The numeric address bootstraps without DNS. TLS still authenticates the hostname.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            with self.socket_lock:
                if self.expired:
                    raise TimeoutError
                self.deadline_socket = raw
            raw.settimeout(self.timeout)
            raw.connect((self.address, self.port))
            with self.socket_lock:
                if self.expired:
                    raise TimeoutError
                self.sock = TLS_CONTEXT.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
                self.deadline_socket = self.sock
            self.sock.do_handshake()

    def abort(self):
        # A socket timeout by itself would reset on every HTTPS response read.
        with self.socket_lock:
            self.expired = True
            if self.deadline_socket is not None:
                try:
                    self.deadline_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def doh_query(resolver, query):
    host, address = resolver
    wire_query = b"\0\0" + query[2:]
    connection = PinnedHTTPSConnection(host, address)
    deadline = threading.Timer(REQUEST_TIMEOUT, connection.abort)
    deadline.daemon = True
    deadline.start()
    try:
        connection.request("POST", "/dns-query", body=wire_query, headers={
            "Accept": "application/dns-message",
            "Content-Type": "application/dns-message",
        })
        with connection.getresponse() as response:
            if response.status != 200 or response.headers.get_content_type() != "application/dns-message":
                return None
            answer = response.read(MAX_WIRE_MESSAGE + 1)
        if connection.expired or len(answer) > MAX_WIRE_MESSAGE:
            return None
        end = question_end(answer)
        identifier, flags, *_ = DNS_HEADER.unpack_from(answer)
        if identifier != 0 or not flags & 0x8000 or answer[12:end].lower() != query[12:question_end(query)].lower():
            return None
        return query[:2] + answer[2:]
    except (OSError, HTTPException, ValueError):
        return None
    finally:
        deadline.cancel()
        connection.close()


def probe_tunnel():
    for resolver in RESOLVERS:
        answer = doh_query(resolver, HEALTH_QUERY)
        if answer:
            _, flags, _, answers, *_ = DNS_HEADER.unpack_from(answer)
            if not flags & 0x020F and answers:
                return True
    return False


def network_command(*arguments):
    subprocess.run([sys.executable, str(NETWORK), *arguments], check=True, timeout=PERIOD)


class TunnelHealth:
    def __init__(self, command=network_command, clock=time.monotonic):
        self.command = command
        self.clock = clock
        self.lock = threading.Lock()
        self.healthy = False
        self.last_round = None
        self.last_reachable = clock()
        self.streak = 0
        self.transitions = 0

    def update(self, reachable):
        now = self.clock()
        if reachable:
            self.last_reachable = now
        with self.lock:
            self.streak = 0 if self.healthy == reachable else self.streak + 1
            if self.streak >= REQUIRED_ROUNDS:
                self.healthy = reachable
                self.streak = 0
                self.transitions += 1
                logging.info("VPN transit is %s", "healthy" if reachable else "unhealthy")
            self.last_round = now

        if now - self.last_reachable >= RENEW_AFTER:
            self.last_reachable = now
            try:
                self.command("renew")
            except subprocess.SubprocessError:
                logging.warning("Could not renew VPN transit")

    def snapshot(self):
        with self.lock:
            fresh = self.last_round is not None and self.clock() - self.last_round < STALE_AFTER
            return self.healthy and fresh, self.transitions


def resolve(health, query, udp):
    try:
        question_end(query)
        if DNS_HEADER.unpack_from(query)[1] & 0xF800:
            return None
    except ValueError:
        return None
    if health.snapshot()[0]:
        for resolver in RESOLVERS:
            answer = doh_query(resolver, query)
            if answer is None or (DNS_HEADER.unpack_from(answer)[1] & 0x000F) in (2, 5):
                continue
            if udp and len(answer) > 512:
                return local_response(query, 0x8280)
            return answer
    return local_response(query, 0x8082)


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        query, transport = self.request
        answer = resolve(self.server.health, query, udp=True)
        if answer is not None:
            transport.sendto(answer, self.client_address)


class TCPHandler(socketserver.StreamRequestHandler):
    timeout = REQUEST_TIMEOUT

    def handle(self):
        # DNS clients may reuse a TCP connection when resolving multiple names.
        try:
            while len(header := self.rfile.read(2)) == 2:
                size = int.from_bytes(header, "big")
                query = self.rfile.read(size)
                if len(query) != size:
                    break
                answer = resolve(self.server.health, query, udp=False)
                if answer is None:
                    break
                self.wfile.write(len(answer).to_bytes(2, "big") + answer)
        except (TimeoutError, ConnectionError):
            return


class BoundedDNSRequests(socketserver.ThreadingMixIn):
    daemon_threads = True
    allow_reuse_address = True
    max_packet_size = MAX_WIRE_MESSAGE

    def __init__(self, address, handler, health):
        self.health = health
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class TCPResolver(BoundedDNSRequests, socketserver.TCPServer):
    pass


class UDPResolver(BoundedDNSRequests, socketserver.UDPServer):
    pass


def metrics(healthy, transitions):
    values = {
        "deluge_vpn_transit_healthy": ("gauge", int(healthy)),
        "deluge_vpn_transit_transitions_total": ("counter", transitions),
    }
    for direction, stat in (("receive", "rx_bytes"), ("transmit", "tx_bytes")):
        try:
            value = int(Path(f"/sys/class/net/transit/statistics/{stat}").read_text())
        except (OSError, ValueError):
            continue
        values[f"deluge_vpn_transit_{direction}_bytes_total"] = ("counter", value)
    return "".join(f"# TYPE {name} {kind}\n{name} {value}\n" for name, (kind, value) in values.items())


class HealthHandler(BaseHTTPRequestHandler):
    def __init__(self, health, *args):
        self.health = health
        super().__init__(*args)

    def do_GET(self):
        healthy, transitions = self.health.snapshot()
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(metrics(healthy, transitions).encode())
        elif self.path == "/":
            self.send_response(200 if healthy else 503)
            self.end_headers()
        else:
            self.send_error(404)

    def log_message(self, *_args):
        pass


def main():
    if sys.argv[1:] == ["check"]:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9999/", timeout=0.7) as response:
                return 0 if response.status == 200 else 1
        except OSError:
            return 1
    if sys.argv[1:]:
        raise SystemExit("Expected no arguments or check")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    health = TunnelHealth()
    with (
        UDPResolver(("127.0.0.1", 53), UDPHandler, health) as udp,
        TCPResolver(("127.0.0.1", 53), TCPHandler, health) as tcp,
        ThreadingHTTPServer(("127.0.0.1", 9999), partial(HealthHandler, health)) as status,
    ):
        for listener in (udp, tcp, status):
            threading.Thread(target=listener.serve_forever, daemon=True).start()
        try:
            while not stop.is_set():
                started = time.monotonic()
                health.update(probe_tunnel())
                stop.wait(max(0, started + PERIOD - time.monotonic()))
        finally:
            for listener in (udp, tcp, status):
                listener.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
