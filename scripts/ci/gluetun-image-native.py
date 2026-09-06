#!/usr/bin/env python3
"""Compare immutable Gluetun images in owned, internal Docker fixtures; no real VPN."""
import argparse
import base64
import gzip
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import select
import signal
import shutil
import subprocess
import tempfile
import time
import uuid

DOCKER_CONFIG = None
STAGE = 'preflight'
LABEL = 'homelab.gluetun-native-fixture'
PEER_ADDRESS = '198.18.0.2'
IMAGE_PATTERN = r'sha256:[0-9a-f]{64}'
FIXTURES = Path(__file__).with_name('gluetun-image-fixtures')
NATIVE_INPUTS = Path(__file__).resolve().parents[2] / 'images/gluetun/native-inputs.json'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def run(args, timeout=20, check=True, limit=2 * 1024 * 1024, env=None, include_stderr=False):
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    streams = [process.stdout, process.stderr]
    output = bytearray()
    errors = bytearray()
    size = 0
    deadline = time.monotonic() + timeout
    try:
        while streams:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'Fixture command timed out')
            ready, _, _ = select.select(streams, [], [], remaining)
            for stream in ready:
                data = os.read(stream.fileno(), 65536)
                if not data:
                    streams.remove(stream)
                    continue
                size += len(data)
                require(size <= limit, 'Fixture command exceeded output bound')
                if stream is process.stdout:
                    output.extend(data)
                elif include_stderr:
                    errors.extend(data)
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        require(not check or code == 0, 'Fixture command failed; vendor output withheld')
        return code, bytes(output + errors)
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # The owned command may exit between poll and kill.
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def docker(*args, **kwargs):
    require(DOCKER_CONFIG is not None, 'Private Docker configuration is required')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('DOCKER_', 'BUILDX_', 'BUILDKIT_'))}
    operation = args[0]
    if operation == 'logs':
        kwargs['include_stderr'] = True
    if operation == 'exec':
        operation += ':' + Path(args[2]).name
    require(re.fullmatch(r'[a-zA-Z0-9_.:-]+', operation), 'Invalid diagnostic operation')
    try:
        return run(['docker', '--config', str(DOCKER_CONFIG), '--host', 'unix:///var/run/docker.sock', *args],
                   env=environment, **kwargs)
    except RuntimeError as error:
        raise RuntimeError(STAGE + ' [' + operation + ']: ' + str(error)) from None


def image_contract(image):
    require(re.fullmatch(IMAGE_PATTERN, image), 'Images must be immutable local sha256 IDs')
    _, raw = docker('image', 'inspect', '--format', '[{{json .Id}},{{json .Os}},{{json .Architecture}}]', image)
    require(json.loads(raw) == [image, 'linux', 'amd64'], 'Image ID/platform mismatch')


class Owned:
    def __init__(self):
        self.nonce = uuid.uuid4().hex
        self.network = None
        self.containers = []

    def network_create(self):
        name = 'gluetun-fixture-' + self.nonce
        # Record intent before create so an uncertain response is reconciled.
        self.network = name
        docker('network', 'create', '--internal', '--label', LABEL + '=' + self.nonce, name)
        self.network_check()
        return name

    def network_check(self):
        _, raw = docker('network', 'inspect', '--format',
                        '[{{json .Name}},{{json .Labels}},{{json .Internal}}]', self.network)
        name, labels, internal = json.loads(raw)
        require(name == self.network and labels.get(LABEL) == self.nonce and internal is True,
                'Owned network identity changed')

    def inspect(self, record):
        _, raw = docker('container', 'inspect', '--format',
                        '[{{json .Id}},{{json .Name}},{{json .Config.Labels}},{{json .Image}},{{json .State}}]',
                        record['id'] or record['name'])
        identity, name, labels, image, state = json.loads(raw)
        require(re.fullmatch(r'[0-9a-f]{64}', identity) and name == '/' + record['name'] and
                labels.get(LABEL) == self.nonce and image == record['image'] and
                (record['id'] is None or record['id'] == identity), 'Owned container identity changed')
        record['id'] = identity
        return state

    def create(self, image, *options, command):
        record = {'name': 'gluetun-fixture-' + uuid.uuid4().hex, 'id': None, 'image': image}
        self.containers.append(record)
        _, raw = docker('create', '--pull=never', '--name', record['name'], '--label', LABEL + '=' + self.nonce,
                        '--network', self.network, '--memory', '256m', '--cpus', '1', '--pids-limit', '128',
                        '--security-opt', 'no-new-privileges:true', '--entrypoint', '/bin/sh',
                        *options, image, *command)
        identity = raw.decode().strip()
        require(re.fullmatch(r'[0-9a-f]{64}', identity), 'Create did not return a container ID')
        record['id'] = identity
        self.inspect(record)
        docker('start', identity)
        return record

    def execute(self, record, *args, **kwargs):
        require(self.inspect(record)['Running'], 'Fixture container stopped unexpectedly')
        return docker('exec', record['id'], *args, **kwargs)

    def cleanup(self):
        failures = []
        for record in reversed(self.containers):
            try:
                # Listing proves absence even when create failed before returning ID.
                _, found = docker('container', 'ls', '-aq', '--no-trunc', '--filter',
                                  'name=^/' + record['name'] + '$')
                if not found.strip():
                    continue
                require(len(found.splitlines()) == 1, 'Ambiguous cleanup identity')
                self.inspect(record)
                docker('rm', '--force', '--volumes', record['id'])
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
                failures.append('container')
        if self.network:
            try:
                _, found = docker('network', 'ls', '-q', '--filter', 'name=^' + self.network + '$')
                if found.strip():
                    self.network_check()
                    # Docker refuses removal with foreign attached containers.
                    docker('network', 'rm', self.network)
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
                failures.append('network')
        require(not failures, 'Owned fixture cleanup failed; inspect fixture-labeled Docker resources')


def wait_until(predicate, message, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise RuntimeError(message)


def settings(directory, enabled, invalid=None):
    directory.mkdir(mode=0o700)
    config = json.loads((FIXTURES / 'settings.json').read_text())
    config['pprof_enabled'] = 'on' if enabled else 'off'
    if invalid in ('provider', 'type'):
        config['vpn_service_provider' if invalid == 'provider' else 'vpn_type'] = 'invalid-fixture'
    for name, value in config.items():
        (directory / name).write_text(value + '\n')
    # No real credentials: fresh ephemeral WireGuard material, never printed.
    key = base64.b64encode(os.urandom(32)).decode()
    preshared = base64.b64encode(os.urandom(32)).decode()
    profile = '[Interface]\nPrivateKey = ' + key + '\nAddress = 10.99.0.2/32\n[Peer]\nPresharedKey = ' + preshared + '\n'
    (directory / 'wg0.conf').write_text(profile)
    (directory / 'mode').write_text('invalid' if invalid == 'key' else 'valid')
    for path in directory.iterdir():
        path.chmod(0o600)


def check_listener(owned, target, enabled):
    _, raw = owned.execute(target, 'cat', '/proc/net/tcp', '/proc/net/tcp6')
    listeners = []
    for line in raw.decode().splitlines():
        columns = line.split()
        if columns and columns[0] != 'sl' and columns[3] == '0A' and columns[1].endswith(':17AC'):
            listeners.append(columns[1])
    require(listeners == (['0100007F:17AC'] if enabled else []), 'pprof binding mismatch')


def case(owned, image, peer_ip, enabled, directory, invalid=None):
    global STAGE
    STAGE = directory.name + '/' + (invalid or ('pprof-on' if enabled else 'pprof-off'))
    print(json.dumps({'stage': STAGE}), flush=True)
    config = directory / (invalid if invalid else 'on' if enabled else 'off')
    settings(config, enabled, invalid)
    target = owned.create(image, '--cap-add', 'NET_ADMIN', '--device', '/dev/net/tun',
                         '--mount', f'type=bind,src={FIXTURES},dst=/fixture,readonly',
                         '--mount', f'type=bind,src={config},dst=/settings,readonly',
                         command=['/fixture/target.sh', peer_ip])
    # Fresh connection before Gluetun establishes a routed positive control.
    wait_until(lambda: owned.execute(target, 'test', '-e', '/tmp/before-ready', check=False)[0] == 0,
               'Target routing setup failed')
    code, body = owned.execute(target, 'wget', '-q', '-T', '2', '-O', '-', 'http://' + PEER_ADDRESS + ':8080/marker')
    require(code == 0 and body == b'fixture-ok\n', 'Off-subnet positive control failed')
    owned.execute(target, 'touch', '/tmp/start-gluetun')
    if invalid:
        wait_until(lambda: not owned.inspect(target)['Running'], 'Invalid file configuration did not stop startup')
        require(owned.inspect(target)['ExitCode'] != 0, 'Invalid file configuration accepted')
        _, logs = docker('logs', target['id'])
        expected = {'key': b'private key is not valid', 'provider': b'VPN provider name is not valid',
                    'type': b'VPN type is not valid'}[invalid]
        require(expected in logs, 'Expected invalid file-setting rejection not observed')
        return
    def health_listening():
        _, sockets = owned.execute(target, 'cat', '/proc/net/tcp')
        return any(len(fields) > 3 and fields[1] == '0100007F:270F' and fields[3] == '0A'
                   for fields in (line.split() for line in sockets.decode().splitlines()))
    wait_until(health_listening, 'Health listener did not start')
    _, logs = docker('logs', target['id'])
    require(b'v3.41.3' in logs and b'wireguard' in logs.lower() and b'airvpn' in logs.lower(),
            'Expected version/provider/type startup evidence missing')
    check_listener(owned, target, enabled)
    # Same-subnet LAN remains allowed by Gluetun; off-subnet connection must be new.
    code, body = owned.execute(target, 'wget', '-q', '-T', '2', '-O', '-', 'http://' + peer_ip + ':8080/marker')
    require(code == 0 and body == b'fixture-ok\n', 'Expected fixture LAN access was blocked')
    _, route = owned.execute(target, 'ip', 'route', 'get', PEER_ADDRESS)
    route_words = route.decode().split()
    require(route_words[:5] == [PEER_ADDRESS, 'via', peer_ip, 'dev', 'eth0'],
            'Post-start off-subnet route changed')
    require(owned.execute(target, 'wget', '-q', '-T', '2', '-O', '/dev/null',
                          'http://' + PEER_ADDRESS + ':8080/marker', check=False, timeout=5)[0] != 0,
            'Firewall leaked a fresh off-subnet connection without a VPN')
    # A narrow allow on this owned namespace must restore the same fresh connection.
    # This proves firewall causality instead of mistaking a broken route for isolation.
    allow = ['-o', 'eth0', '-d', PEER_ADDRESS + '/32', '-p', 'tcp', '--dport', '8080', '-j', 'ACCEPT']
    try:
        owned.execute(target, 'iptables', '-I', 'OUTPUT', '1', *allow)
        code, body = owned.execute(target, 'wget', '-q', '-T', '2', '-O', '-',
                                   'http://' + PEER_ADDRESS + ':8080/marker', timeout=5)
        require(code == 0 and body == b'fixture-ok\n', 'Firewall allow positive control failed')
    finally:
        # If insertion had an uncertain result, -C distinguishes absent from present.
        present = owned.execute(target, 'iptables', '-C', 'OUTPUT', *allow, check=False)[0]
        require(present in (0, 1), 'Could not verify temporary firewall rule cleanup')
        if present == 0:
            owned.execute(target, 'iptables', '-D', 'OUTPUT', *allow)
    _, policies = owned.execute(target, 'iptables', '-S')
    require(all(b'-P ' + chain + b' DROP' in policies for chain in (b'INPUT', b'FORWARD', b'OUTPUT')),
            'VPN firewall default DROP policies missing')
    require(owned.execute(target, '/gluetun-entrypoint', 'healthcheck', check=False, timeout=15)[0] != 0,
            'Synthetic disconnected VPN incorrectly reported healthy')
    if enabled:
        owned.execute(target, 'sh', '-ec', 'umask 077; wget -q -T 5 -O /tmp/cpu.pprof '
                      '"http://127.0.0.1:6060/debug/pprof/profile?seconds=1"', timeout=10)
        private_profile = directory / 'cpu.pprof'
        docker('cp', target['id'] + ':/tmp/cpu.pprof', str(private_profile))
        private_profile.chmod(0o600)
        require(0 < private_profile.stat().st_size <= 1024 * 1024, 'Profile size bound failed')
        with gzip.open(private_profile, 'rb') as profile:
            require(0 < len(profile.read(4 * 1024 * 1024 + 1)) <= 4 * 1024 * 1024, 'Invalid bounded CPU profile')
        private_profile.unlink()
    else:
        require(owned.execute(target, 'wget', '-q', '-T', '1', '-O', '/dev/null',
                              'http://127.0.0.1:6060/debug/pprof/profile?seconds=1', check=False)[0] != 0,
                'Disabled pprof remained accessible')
    require(owned.inspect(target)['Running'], 'Target exited during compatibility test')



def openvpn_pair(owned, image, family, directory, expected_version=None, expected_ssl=None):
    """Fresh bidirectional HTTP over encrypted static-key TUN, never a provider VPN."""
    global STAGE
    STAGE = directory.name + '/openvpn-' + family + '/create-and-version'
    print(json.dumps({'stage': STAGE}), flush=True)
    folder = directory / ('openvpn-' + family)
    folder.mkdir(mode=0o700)
    key_hex = os.urandom(256).hex()
    key = '-----BEGIN OpenVPN Static key V1-----\n' + '\n'.join(
        key_hex[index:index + 32] for index in range(0, len(key_hex), 32))
    key += '\n-----END OpenVPN Static key V1-----\n'
    binary = '/usr/sbin/openvpn' + family
    peers = []
    for index in range(2):
        config = folder / str(index)
        config.mkdir(mode=0o700)
        (config / 'static.key').write_text(key)
        (config / 'static.key').chmod(0o600)
        target = owned.create(image, '--cap-add', 'NET_ADMIN', '--device', '/dev/net/tun',
                              '--mount', f'type=bind,src={FIXTURES},dst=/fixture,readonly',
                              '--mount', f'type=bind,src={config},dst=/settings,readonly',
                              command=['/fixture/openvpn.sh', binary])
        _, version = owned.execute(target, binary, '--version')
        require(re.search(rb'^OpenVPN ' + re.escape(family.encode()) + rb'\.\d+', version),
                'OpenVPN binary family mismatch')
        if expected_version:
            require(version.startswith(('OpenVPN ' + expected_version + ' ').encode()),
                    'Candidate OpenVPN version mismatch')
        require(b'library versions: OpenSSL ' in version, 'OpenVPN runtime OpenSSL evidence missing')
        if expected_ssl:
            require(('library versions: OpenSSL ' + expected_ssl + ' ').encode() in version,
                    'Candidate linked OpenSSL version mismatch')
        _, linked = owned.execute(target, 'ldd', binary)
        require(b'libssl.so.3' in linked and b'libcrypto.so.3' in linked and b'not found' not in linked,
                'OpenVPN shared crypto libraries missing')
        _, raw = docker('inspect', '--format',
                        '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', target['id'])
        address = raw.decode().strip()
        require(ipaddress.ip_address(address).version == 4, 'OpenVPN peer IPv4 missing')
        peers.append((target, config, address))
    subnet = '10.88.' + ('25' if family == '2.5' else '26')
    for index, (_, config, address) in enumerate(peers):
        other = 1 - index
        text = ('dev tun0\nproto udp4\nport 1194\nlocal ' + address + '\nremote ' + peers[other][2] +
                ' 1194\nifconfig ' + subnet + '.' + str(index + 1) + ' ' + subnet + '.' + str(other + 1) +
                '\nsecret /settings/static.key\ncipher AES-256-CBC\nauth SHA256\nverb 4\nping 1\nping-restart 10\n')
        # Publishing complete config by rename avoids a reader observing partial bytes.
        temporary = config / 'pending.conf'
        temporary.write_text(text)
        temporary.chmod(0o600)
        temporary.rename(config / 'openvpn.conf')
    for index, (target, _, _) in enumerate(peers):
        STAGE = directory.name + '/openvpn-' + family + '/traffic-' + str(index)
        print(json.dumps({'stage': STAGE}), flush=True)
        destination = subnet + '.' + str(2 - index)
        def transferred():
            code, body = owned.execute(target, 'timeout', '2', 'wget', '-q', '-T', '1', '-O', '-',
                                       'http://' + destination + ':8080/marker', check=False, timeout=5)
            return code == 0 and body == b'fixture-ok\n'
        wait_until(transferred, 'Encrypted OpenVPN TUN traffic failed')
        _, route = owned.execute(target, 'ip', 'route', 'get', destination)
        require(b'dev tun0' in route, 'OpenVPN traffic did not route through TUN')
        def initialized():
            _, logs = docker('logs', target['id'])
            return (b'Initialization Sequence Completed' in logs and
                    b"Cipher 'AES-256-CBC' initialized" in logs)
        # Docker log delivery can lag traffic; preserve both exact markers with a deadline.
        wait_until(initialized, 'OpenVPN encrypted initialization evidence missing', seconds=10)
    # Stop one peer and require a fresh connection to fail: bridge HTTP cannot satisfy this test.
    STAGE = directory.name + '/openvpn-' + family + '/stop-negative-control'
    print(json.dumps({'stage': STAGE}), flush=True)
    docker('stop', '--time', '2', peers[1][0]['id'], timeout=10)
    require(owned.execute(peers[0][0], 'timeout', '2', 'wget', '-q', '-T', '1', '-O', '/dev/null',
                          'http://' + subnet + '.2:8080/marker', check=False, timeout=5)[0] != 0,
            'OpenVPN disconnected negative control unexpectedly succeeded')


def main():
    global DOCKER_CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--docker-config', type=Path)
    args = parser.parse_args()
    temporary = None
    try:
        if args.docker_config is None:
            temporary = tempfile.TemporaryDirectory(prefix='gluetun-docker-config-')
            config = Path(temporary.name)
            (config / 'config.json').write_text('{"auths":{}}\n')
            (config / 'config.json').chmod(0o600)
        else:
            config = args.docker_config
        require(not config.is_symlink() and config.is_dir() and
                sorted(path.name for path in config.iterdir()) == ['config.json'],
                'Docker configuration must contain only empty auths')
        path = config / 'config.json'
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 128 and
                json.loads(path.read_text()) == {'auths': {}}, 'Docker configuration is not empty')
        DOCKER_CONFIG = config.resolve()
        suite(args)
    finally:
        DOCKER_CONFIG = None
        if temporary is not None:
            temporary.cleanup()


def suite(args):
    require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64'),
            'Native Linux amd64 runner required')
    _, raw = docker('info', '--format', '[{{json .OSType}},{{json .Architecture}}]')
    require(json.loads(raw) in (['linux', 'x86_64'], ['linux', 'amd64']), 'Native Linux amd64 Docker required')
    require(args.baseline != args.candidate, 'Baseline and candidate must be distinct image IDs')
    for image in (args.baseline, args.candidate):
        image_contract(image)
    native_inputs = json.loads(NATIVE_INPUTS.read_text())
    require(native_inputs['platform'] == 'linux/amd64', 'Native inputs platform mismatch')
    ssl_package = native_inputs['runtime_packages']['libssl3']
    require(ssl_package == native_inputs['runtime_packages']['libcrypto3'], 'Crypto package versions differ')
    ssl_version = ssl_package.split('-r')[0]
    require(re.fullmatch(r'3\.\d+\.\d+', ssl_version), 'Invalid expected OpenSSL version')
    for family in ('2.5', '2.6'):
        entry = native_inputs['openvpn'][family]
        require(entry['binary'] == '/usr/sbin/openvpn' + family and
                re.fullmatch(re.escape(family) + r'\.\d+', entry['version']), 'Invalid OpenVPN contract')
    owned = Owned()
    def interrupted(signum, frame):
        raise RuntimeError('Native fixture interrupted')
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix='gluetun-native-'))
    try:
        owned.network_create()
        peer = owned.create(args.baseline, '--cap-add', 'NET_ADMIN',
                            '--mount', f'type=bind,src={FIXTURES},dst=/fixture,readonly',
                            command=['/fixture/peer.sh'])
        _, raw = docker('inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', peer['id'])
        peer_ip = raw.decode().strip()
        require(ipaddress.ip_address(peer_ip).version == 4, 'Peer IPv4 address missing')
        wait_until(lambda: owned.execute(peer, 'wget', '-q', '-T', '1', '-O', '-',
                   'http://127.0.0.1:8080/marker', check=False) == (0, b'fixture-ok\n'),
                   'Synthetic peer did not start')
        for label, image in (('baseline', args.baseline), ('candidate', args.candidate)):
            target = owned.create(image, command=['-c', 'exec /gluetun-entrypoint unknown-fixture-command'])
            wait_until(lambda: not owned.inspect(target)['Running'], 'Unknown CLI command did not exit')
            require(owned.inspect(target)['ExitCode'] != 0, 'Unknown CLI command accepted')
            _, cli_logs = docker('logs', target['id'])
            require(b'command is unknown' in cli_logs, 'Expected CLI rejection was not observed')
            print(json.dumps({'image': label, 'case': 'cli-rejection', 'passed': True}), flush=True)
            folder = directory / label
            folder.mkdir(mode=0o700)
            for family in ('2.5', '2.6'):
                openvpn_pair(owned, image, family, folder,
                             native_inputs['openvpn'][family]['version'] if label == 'candidate' else None,
                             ssl_version if label == 'candidate' else None)
                print(json.dumps({'image': label, 'case': 'openvpn-' + family + '-encrypted-tun',
                                  'passed': True, 'provider_vpn_proven': False}), flush=True)
            for enabled, invalid in ((True, 'provider'), (True, 'type'), (True, 'key'), (True, None), (False, None)):
                case(owned, image, peer_ip, enabled, folder, invalid)
                print(json.dumps({'image': label, 'case': 'invalid-' + invalid if invalid else 'pprof-on' if enabled else 'pprof-off',
                                  'passed': True, 'real_vpn_proven': False}), flush=True)
    finally:
        try:
            try:
                owned.cleanup()
            finally:
                shutil.rmtree(directory)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        # RuntimeError messages originate only from fixed fixture diagnostics.
        raise SystemExit('Gluetun native compatibility failed: ' + str(error)) from None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('Gluetun native compatibility failed; vendor output withheld') from None
