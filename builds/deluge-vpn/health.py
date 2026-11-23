"""Monitor the two WireGuard paths and provide Deluge's loopback resolver."""

from concurrent.futures import ThreadPoolExecutor
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


PATH_MARKS = {"a": 101, "b": 102}
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


class MarkedHTTPSConnection(HTTPSConnection):
    def __init__(self, host, address, mark):
        super().__init__(host, timeout=REQUEST_TIMEOUT, context=TLS_CONTEXT)
        self.address = address
        self.mark = mark
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
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.mark)
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
                    # The request may have already closed the socket.
                    pass


def doh_query(path, resolver, query):
    host, address = resolver
    wire_query = b"\0\0" + query[2:]
    connection = MarkedHTTPSConnection(host, address, PATH_MARKS[path])
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


def probe_path(path):
    for resolver in RESOLVERS:
        answer = doh_query(path, resolver, HEALTH_QUERY)
        if answer:
            _, flags, _, answers, *_ = DNS_HEADER.unpack_from(answer)
            if not flags & 0x020F and answers:
                return True
    return False


def network_command(*arguments):
    subprocess.run([sys.executable, str(NETWORK), *arguments], check=True, timeout=PERIOD)


class PathHealth:
    def __init__(self, command=network_command, clock=time.monotonic):
        self.command = command
        self.clock = clock
        self.lock = threading.Lock()
        self.healthy = ()
        self.last_round = None
        self.streak = dict.fromkeys(PATH_MARKS, 0)
        self.transitions = dict.fromkeys(PATH_MARKS, 0)
        self.last_reachable = dict.fromkeys(PATH_MARKS, clock())
        self.dns_path = 0

    def update(self, results):
        now = self.clock()
        selected = []
        for path, reachable in results.items():
            current = path in self.healthy
            if reachable:
                self.last_reachable[path] = now
            self.streak[path] = 0 if current == reachable else self.streak[path] + 1
            if self.streak[path] >= REQUIRED_ROUNDS:
                current = reachable
                self.streak[path] = 0
            if current:
                selected.append(path)
        selected = tuple(selected)
        if selected != self.healthy:
            self.command("select", *selected)
        with self.lock:
            for path in set(self.healthy).symmetric_difference(selected):
                self.transitions[path] += 1
                logging.info("VPN path %s is %s", path, "healthy" if path in selected else "unhealthy")
            self.healthy = selected
            self.last_round = now

        for path, last_reachable in self.last_reachable.items():
            if now - last_reachable >= RENEW_AFTER:
                self.last_reachable[path] = now
                try:
                    self.command("renew", path)
                except subprocess.SubprocessError:
                    logging.warning("could not renew transit for VPN path %s", path)

    def snapshot(self):
        with self.lock:
            return self.fresh_paths(), self.transitions.copy()

    def fresh_paths(self):
        if self.last_round is not None and self.clock() - self.last_round < STALE_AFTER:
            return self.healthy
        return ()

    def resolver_paths(self):
        with self.lock:
            paths = self.fresh_paths()
            if not paths:
                return ()
            first = self.dns_path % len(paths)
            self.dns_path = (first + 1) % len(paths)
            return paths[first:] + paths[:first]


def resolve(health, query, udp):
    try:
        question_end(query)
        if DNS_HEADER.unpack_from(query)[1] & 0xF800:
            return None
    except ValueError:
        return None
    for path in health.resolver_paths():
        for resolver in RESOLVERS:
            answer = doh_query(path, resolver, query)
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
    families = {
        "deluge_vpn_path_healthy": ("gauge", {path: int(path in healthy) for path in PATH_MARKS}),
        "deluge_vpn_path_transitions_total": ("counter", transitions),
    }
    for direction, stat in (("receive", "rx_bytes"), ("transmit", "tx_bytes")):
        values = {}
        for path in PATH_MARKS:
            try:
                values[path] = int(Path(f"/sys/class/net/vpn-{path}/statistics/{stat}").read_text())
            except (OSError, ValueError):
                continue
        families[f"deluge_vpn_path_{direction}_bytes_total"] = ("counter", values)
    lines = []
    for family, (kind, values) in families.items():
        lines.append(f"# TYPE {family} {kind}")
        lines.extend(f'{family}{{path="{path}"}} {value}' for path, value in values.items())
    return "\n".join(lines) + "\n"


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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    health = PathHealth()
    network_command("select")
    with (
        UDPResolver(("127.0.0.1", 53), UDPHandler, health) as udp,
        TCPResolver(("127.0.0.1", 53), TCPHandler, health) as tcp,
        ThreadingHTTPServer(("127.0.0.1", 9999), partial(HealthHandler, health)) as status,
        ThreadPoolExecutor(max_workers=len(PATH_MARKS)) as probes,
    ):
        for listener in (udp, tcp, status):
            threading.Thread(target=listener.serve_forever, daemon=True).start()
        try:
            while not stop.is_set():
                started = time.monotonic()
                results = dict(zip(PATH_MARKS, probes.map(probe_path, PATH_MARKS)))
                health.update(results)
                stop.wait(max(0, started + PERIOD - time.monotonic()))
        finally:
            try:
                network_command("select")
            finally:
                for listener in (udp, tcp, status):
                    listener.shutdown()


if __name__ == "__main__":
    main()
