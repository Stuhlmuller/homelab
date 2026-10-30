const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const configPath = path.resolve(__dirname, '../../clusters/homelab/apps/renovate/config.js');
const source = fs.readFileSync(configPath, 'utf8');
const appDir = path.dirname(configPath);
const cacheInitPath = path.join(appDir, 'cache-init.cjs');
const cacheInitSource = fs.readFileSync(cacheInitPath, 'utf8');
const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });

function load(options = {}) {
  const calls = [];
  const cacheWrites = [];
  const cacheUnlinks = [];
  const issuer = options.issuer ?? 'Iv1.example';
  const key = options.key ?? pem;
  const installation = options.installation ?? {
    id: 42,
    account: { login: 'Stuhlmuller' },
    repository_selection: 'all',
  };
  const result = options.result ?? {
    token: 'ghs_test-installation-token',
    expires_at: new Date(Date.now() + 3600_000).toISOString(),
  };
  const context = {
    module: { exports: {} },
    Buffer,
    require(name) {
      if (name === 'node:fs') {
        return {
          readFileSync(file) {
            if (file === '/var/run/secrets/renovate/issuer-id') return issuer;
            if (file === '/var/run/secrets/renovate/private-key') return key;
            throw new Error('unexpected credential path');
          },
          writeFileSync(file, bytes, settings) {
            assert.match(file, /^\/cache\/renovate\/\.storage-probe-[0-9a-f-]+$/);
            assert.equal(bytes.length, 4096);
            assert.equal(settings.flush, true);
            cacheWrites.push(file);
            if (options.cacheError) throw new Error('ENOSPC');
          },
          unlinkSync(file) {
            cacheUnlinks.push(file);
          },
        };
      }
      if (name === 'node:crypto') return crypto;
      throw new Error('unexpected module');
    },
    async fetch(url, request) {
      calls.push({ url, request });
      const status = options.status?.[calls.length - 1] ?? 200;
      return {
        ok: status === 200 || status === 201,
        status,
        async json() { return calls.length === 1 ? installation : result; },
      };
    },
  };
  vm.runInNewContext(source, context, { filename: configPath });
  return { config: context.module.exports, calls, cacheWrites, cacheUnlinks };
}

test('mints a signed installation token and preserves the current global policy', async () => {
  const { config, calls, cacheWrites, cacheUnlinks } = load();
  const resolved = await config();
  assert.deepEqual(cacheUnlinks, cacheWrites);
  assert.equal(cacheWrites.length, 1);
  assert.equal(resolved.token, 'ghs_test-installation-token');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'https://api.github.com/orgs/Stuhlmuller/installation');
  assert.equal(calls[1].url, 'https://api.github.com/app/installations/42/access_tokens');
  assert.equal(calls[1].request.method, 'POST');
  assert.equal(calls[0].request.headers.Authorization, calls[1].request.headers.Authorization);

  const jwt = calls[0].request.headers.Authorization.slice('Bearer '.length);
  const [header, payload, signature] = jwt.split('.');
  assert.deepEqual(JSON.parse(Buffer.from(header, 'base64url')), { alg: 'RS256', typ: 'JWT' });
  const claims = JSON.parse(Buffer.from(payload, 'base64url'));
  assert.equal(claims.iss, 'Iv1.example');
  assert.ok(claims.exp - claims.iat <= 600);
  assert.ok(crypto.verify('RSA-SHA256', Buffer.from(`${header}.${payload}`), publicKey, Buffer.from(signature, 'base64url')));

  assert.equal(resolved.platform, 'github');
  assert.equal(resolved.username, 'rstuhlmuller-renovate[bot]');
  assert.equal(resolved.gitAuthor, 'rstuhlmuller-renovate[bot] <239054205+rstuhlmuller-renovate[bot]@users.noreply.github.com>');
  assert.equal(resolved.autodiscover, true);
  assert.deepEqual(Array.from(resolved.autodiscoverFilter), ['Stuhlmuller/*']);
  assert.equal(resolved.forkProcessing, 'enabled');
  assert.equal(resolved.onboarding, false);
  assert.equal(resolved.requireConfig, 'optional');
  assert.equal(resolved.platformCommit, 'enabled');
  assert.deepEqual(Array.from(resolved.globalExtends), [
    'config:best-practices', ':automergeAll', 'replacements:all',
    'schedule:automergeDaily', 'security:openssf-scorecard',
  ]);
  assert.equal(resolved.dryRun, 'full');
  assert.equal(resolved.cacheDir, '/cache/renovate');
  assert.equal(resolved.baseDir, '/tmp/renovate');
  assert.equal(resolved.repositoryCache, 'enabled');
  assert.equal(resolved.cachePrivatePackages, true);
});

test('fails closed for missing credentials and invalid signing keys', async () => {
  for (const options of [{ issuer: '' }, { key: '' }, { key: 'not a private key' }]) {
    const { config, calls } = load(options);
    await assert.rejects(config(), /credential files are empty|private key is invalid/);
    assert.equal(calls.length, 0);
  }
});

test('fails before GitHub access when the cache volume is full or unwritable', async () => {
  const options = { cacheError: true };
  const { config, calls, cacheWrites, cacheUnlinks } = load(options);
  await assert.rejects(config(), /cache volume is unavailable or full/);
  assert.equal(calls.length, 0);
  assert.deepEqual(cacheUnlinks, cacheWrites);

  options.cacheError = false;
  const recovered = load(options);
  const laterRun = await recovered.config();
  assert.equal(laterRun.cacheDir, '/cache/renovate');
  assert.equal(recovered.calls.length, 2, 'a later run may mint a token after storage recovers');
  assert.deepEqual(recovered.cacheUnlinks, recovered.cacheWrites);
});

test('refuses an inaccessible or selected-repository installation', async () => {
  const inaccessible = load({ status: [404] });
  await assert.rejects(inaccessible.config(), /returned HTTP 404/);
  assert.equal(inaccessible.calls.length, 1);

  const selected = load({ installation: {
    id: 42,
    account: { login: 'Stuhlmuller' },
    repository_selection: 'selected',
  } });
  await assert.rejects(selected.config(), /does not cover the owner/);
  assert.equal(selected.calls.length, 1);
});

test('refuses invalid or nearly expired installation tokens', async () => {
  for (const result of [
    { token: 'bad-token', expires_at: new Date(Date.now() + 3600_000).toISOString() },
    { token: 'ghs_short', expires_at: new Date(Date.now() + 3000_000).toISOString() },
    { token: 'ghs_missing-expiration' },
    { token: 'ghs_invalid-expiration', expires_at: 'invalid' },
  ]) {
    const { config, calls } = load({ result });
    await assert.rejects(config(), /installation token is invalid or expires too soon/);
    assert.equal(calls.length, 2);
  }
});

test('promotes only pinned cache timing messages during full dry run', async () => {
  const { config } = load();
  const resolved = await config();
  assert.equal(resolved.dryRun, 'full');
  assert.deepEqual(JSON.parse(JSON.stringify(resolved.logLevelRemap)), [
    { matchMessage: '/^Package cache statistics$/', newLogLevel: 'info' },
    { matchMessage: '/^Checking file package cache for expired items$/', newLogLevel: 'info' },
    {
      matchMessage: '/^Cache GC: kept [0-9]+ content entries [(][0-9]+ bytes[)], ' +
        'removed [0-9]+ orphaned [(][0-9]+ bytes[)] in [0-9]+(?:[.][0-9]+)?ms$/',
      newLogLevel: 'info',
    },
    {
      matchMessage: '/^Deleted [0-9]+ of [0-9]+ file cached entries in [0-9]+ms$/',
      newLogLevel: 'info',
    },
  ]);
  const cronjob = fs.readFileSync(path.resolve(__dirname, '../../clusters/homelab/apps/renovate/cronjob.yaml'), 'utf8');
  assert.deepEqual([...cronjob.matchAll(/^\s+image: (\S+)$/gm)].map((match) => match[1]), [
    'harbor.stinkyboi.com/mirror/ghcr.io/renovatebot/renovate:44.167.4@sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d',
    'harbor.stinkyboi.com/mirror/ghcr.io/renovatebot/renovate:44.167.4@sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d',
  ]);
  assert.match(cronjob, /^  suspend: false$/m);
  assert.match(cronjob, /^  schedule: "0 \* \* \* \*"$/m);
  assert.match(cronjob, /^  concurrencyPolicy: Forbid$/m);
});

test('keeps Renovate cache refresh defaults and mounts credentials outside the PVC', async () => {
  const { config } = load();
  const resolved = await config();
  for (const key of ['cacheTtlOverride', 'cacheHardTtlMinutes', 'httpCacheTtlDays']) {
    assert.equal(Object.hasOwn(resolved, key), false, `${key} must use the Renovate default`);
  }
  assert.equal(resolved.repositoryCache, 'enabled');
  assert.equal(resolved.cachePrivatePackages, true);
  assert.equal(resolved.cacheDir, '/cache/renovate');
  assert.equal(resolved.baseDir, '/tmp/renovate');

  const cronjob = fs.readFileSync(path.resolve(__dirname, '../../clusters/homelab/apps/renovate/cronjob.yaml'), 'utf8');
  assert.match(cronjob, /- name: cache\n\s+mountPath: \/cache\/renovate\n/);
  assert.match(cronjob, /- name: cache\n\s+persistentVolumeClaim:\n\s+claimName: renovate-cache-local\n/);
  assert.match(cronjob, /- name: github-app\n\s+mountPath: \/var\/run\/secrets\/renovate\n\s+readOnly: true\n/);
  assert.match(cronjob, /- name: github-app\n\s+secret:\n\s+secretName: renovate\n/);
});

test('binds a retained dedicated local cache on the selected node and retains the old NFS claim', () => {
  const platformDir = path.resolve(appDir, '../../platform/storage');
  const platform = fs.readFileSync(path.join(platformDir, 'renovate-cache-local.yaml'), 'utf8');
  const claim = fs.readFileSync(path.join(appDir, 'local-cache-pvc.yaml'), 'utf8');
  const cronjob = fs.readFileSync(path.join(appDir, 'cronjob.yaml'), 'utf8');
  const [storageClass, volume] = platform.split('\n---\n');
  assert.match(storageClass, /kind: StorageClass\nmetadata:\n  name: renovate-cache-local\n/);
  assert.match(storageClass, /^provisioner: kubernetes.io\/no-provisioner$/m);
  assert.match(storageClass, /^reclaimPolicy: Retain$/m);
  assert.match(storageClass, /^volumeBindingMode: Immediate$/m);
  assert.match(volume, /kind: PersistentVolume\nmetadata:\n  name: renovate-cache-local\n/);
  assert.match(volume, /claimRef:\n    name: renovate-cache-local\n    namespace: automation\n/);
  assert.match(volume, /hostPath:\n    path: \/var\/lib\/renovate-cache\n    type: DirectoryOrCreate\n/);
  assert.match(volume, /nodeAffinity:\n    required:\n      nodeSelectorTerms:\n        - matchExpressions:\n            - key: kubernetes.io\/hostname\n              operator: In\n              values:\n                - acer\n/);
  assert.match(volume, /^  persistentVolumeReclaimPolicy: Retain$/m);
  for (const source of [volume, claim]) {
    assert.match(source, /argocd.argoproj.io\/sync-options: Prune=false,Delete=false\n/);
    assert.match(source, /^  storageClassName: renovate-cache-local$/m);
    assert.match(source, /^  volumeMode: Filesystem$/m);
    assert.match(source, /accessModes:\n    - ReadWriteOnce\n/);
    assert.match(source, /storage: 20Gi\n/);
  }
  assert.match(claim, /metadata:\n  name: renovate-cache-local\n  namespace: automation\n/);
  assert.match(claim, /^  volumeName: renovate-cache-local$/m);
  assert.match(cronjob, /nodeSelector:\n            kubernetes.io\/hostname: acer\n/);
  assert.match(fs.readFileSync(path.join(platformDir, 'kustomization.yaml'), 'utf8'), /^  - renovate-cache-local.yaml$/m);
  const app = fs.readFileSync(path.join(appDir, 'kustomization.yaml'), 'utf8');
  assert.match(app, /^  - local-cache-pvc.yaml$/m);
  assert.match(app, /^  - pvc.yaml$/m);
  assert.match(app, /- name: renovate-cache-init\n    files:\n      - cache-init.cjs\n/);
  const oldClaim = fs.readFileSync(path.join(appDir, 'pvc.yaml'), 'utf8');
  assert.match(oldClaim, /name: renovate-cache\n/);
  assert.match(oldClaim, /argocd.argoproj.io\/sync-options: Prune=false\n/);
  assert.match(oldClaim, /storageClassName: nfs-default\n/);
});

test('limits root ownership initialization to the cache and nonsecret script mounts', () => {
  const cronjob = fs.readFileSync(path.join(appDir, 'cronjob.yaml'), 'utf8');
  const init = cronjob.match(/          initContainers:\n([\s\S]*?)          containers:\n/)[1];
  const main = cronjob.match(/          containers:\n([\s\S]*?)          volumes:\n/)[1];
  assert.match(init, /command: \[node, \/etc\/renovate-cache-init\/cache-init.cjs\]\n/);
  for (const setting of ['runAsUser: 0', 'runAsGroup: 0', 'runAsNonRoot: false',
    'allowPrivilegeEscalation: false', 'readOnlyRootFilesystem: true']) {
    assert.ok(init.includes(`${setting}\n`), setting);
  }
  assert.match(init, /capabilities:\n                  drop:\n                    - ALL\n                  add:\n                    - CHOWN\n                    - FOWNER\n/);
  assert.match(init, /requests:\n                  cpu: 10m\n                  memory: 16Mi\n                  ephemeral-storage: 1Mi\n/);
  assert.match(init, /limits:\n                  cpu: 100m\n                  memory: 64Mi\n                  ephemeral-storage: 16Mi\n/);
  assert.deepEqual([...init.matchAll(/- name: (\S+)/g)].map((match) => match[1]),
    ['prepare-local-cache', 'cache', 'cache-init']);
  assert.match(init, /- name: cache-init\n                  mountPath: \/etc\/renovate-cache-init\n                  readOnly: true\n/);
  assert.doesNotMatch(init, /\b(?:env|envFrom|secret|secretRef|secretKeyRef|projected|hostPath):/);
  assert.match(cronjob, /automountServiceAccountToken: false\n/);
  assert.match(cronjob, /securityContext:\n            runAsUser: 12021\n            runAsGroup: 0\n            runAsNonRoot: true\n/);
  assert.doesNotMatch(main, /runAsUser: 0|runAsNonRoot: false|\badd:/);
  assert.match(main, /requests:\n                  cpu: 250m\n                  memory: 512Mi\n                  ephemeral-storage: 1Gi\n/);
  assert.match(main, /limits:\n                  cpu: "2"\n                  memory: 4Gi\n                  ephemeral-storage: 8Gi\n/);
  assert.match(cronjob, /activeDeadlineSeconds: 2400\n/);
  assert.match(cronjob, /backoffLimit: 0\n/);
  assert.match(cronjob, /- name: cache-init\n              configMap:\n                name: renovate-cache-init\n                defaultMode: 0444\n/);
});

function cacheFixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-cache-init-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const root = path.join(directory, 'cache');
  fs.mkdirSync(root, { mode: 0o755 });
  // Ownership is simulated because local tests do not run as root. All actual
  // filesystem operations must target only the mount root, never its contents.
  const owner = { uid: 0, gid: 0 };
  const changes = [];
  const rootOnly = (target) => {
    assert.equal(target, '/cache/renovate');
    return root;
  };
  const io = {
    lstatSync(target) { return Object.assign(fs.lstatSync(rootOnly(target)), owner); },
    chownSync(target, uid, gid) {
      rootOnly(target);
      changes.push('chown');
      Object.assign(owner, { uid, gid });
    },
    chmodSync(target, mode) {
      fs.chmodSync(rootOnly(target), mode);
      changes.push('chmod');
    },
  };
  function run(overrides = {}) {
    vm.runInNewContext(cacheInitSource, {
      require(name) {
        assert.equal(name, 'node:fs', 'initialization needs no credential, network or process modules');
        return { ...io, ...overrides };
      },
    }, { filename: cacheInitPath });
  }
  return { root, owner, changes, run };
}

test('initializes a fresh cache and repeats without metadata writes', (t) => {
  const { root, owner, changes, run } = cacheFixture(t);
  run();
  assert.deepEqual(owner, { uid: 12021, gid: 12021 });
  assert.equal(fs.statSync(root).mode & 0o7777, 0o700);
  assert.deepEqual(changes, ['chown', 'chmod']);
  changes.length = 0;
  run();
  assert.deepEqual(changes, []);
  assert.deepEqual(fs.readdirSync(root), []);
});

test('accepts warm cache data without traversing, replacing or changing it', (t) => {
  const { root, changes, run } = cacheFixture(t);
  const entries = ['repository', 'package', 'containerbase'];
  for (const entry of entries) {
    fs.mkdirSync(path.join(root, entry), { mode: 0o750 });
    fs.writeFileSync(path.join(root, entry, 'warm-entry'), `persistent ${entry} data`, { mode: 0o640 });
  }
  fs.symlinkSync('package/warm-entry', path.join(root, 'warm-link'));
  function snapshot() {
    return [...entries, ...entries.map((entry) => `${entry}/warm-entry`), 'warm-link'].map((entry) => {
      const file = path.join(root, entry);
      const stat = fs.lstatSync(file);
      return { entry, mode: stat.mode, uid: stat.uid, gid: stat.gid, inode: stat.ino, mtime: stat.mtimeMs,
        bytes: stat.isFile() ? fs.readFileSync(file, 'utf8') : undefined,
        link: stat.isSymbolicLink() ? fs.readlinkSync(file) : undefined };
    });
  }
  const before = snapshot();
  run();
  assert.deepEqual(snapshot(), before);
  changes.length = 0;
  run();
  assert.deepEqual(snapshot(), before);
  assert.deepEqual(changes, []);
});

test('fails closed on a non-directory root or failed ownership and permission changes', (t) => {
  const { changes, run } = cacheFixture(t);
  for (const type of ['file', 'symlink']) {
    assert.throws(() => run({ lstatSync() {
      return { isDirectory: () => false, isSymbolicLink: () => type === 'symlink' };
    } }), /cache mount must be a directory/);
  }
  assert.deepEqual(changes, []);
  assert.throws(() => run({ chownSync() { throw new Error('EPERM'); } }), /EPERM/);
  assert.throws(() => run({ chmodSync() { throw new Error('EROFS'); } }), /EROFS/);
  assert.throws(() => run({ chmodSync() {} }), /ownership or permissions are incorrect/);
});
