import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const app = path.join(root, 'clusters/homelab/apps/renovate');
const manifest = fs.readFileSync(path.join(app, 'cache-corruption-drill.yaml'), 'utf8');
const marker = '  inject.js: |\n';
assert.equal(manifest.split(marker).length, 2, 'one fixed injector script');
const block = manifest.split(marker)[1].split('\n---\n')[0];
const lines = block.split('\n');
assert(lines.every((line) => !line || line.startsWith('    ')));
const source = lines.map((line) => line ? line.slice(4) : '').join('\n');
const scriptDir = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-cache-drill-script-'));
const scriptPath = path.join(scriptDir, 'inject.js');
fs.writeFileSync(scriptPath, source);
const script = createRequire(import.meta.url)(scriptPath);
fs.rmSync(scriptDir, { recursive: true, force: true });
const { CACHE, KEY, verifyMount, verifyCapacity, inject } = script;

const now = 1_000_000;
const hour = 60 * 60 * 1000;
const validMount = '125 96 0:45 / /cache/renovate rw,relatime - ' +
  'nfs 10.1.0.2:/renovate-cache rw,vers=3\n';
const validDf = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n' +
  '10.1.0.2:/renovate-cache 20971520 1024 20970496 1% /cache/renovate\n';

function store(info = { key: KEY, metadata: { expiry: now + 3 * hour } }) {
  const calls = [];
  return {
    calls,
    info: async (key) => { calls.push(['info', key]); return info; },
    put: async (key, data, options) => {
      calls.push(['put', key, data, options]);
    },
  };
}

test('staged Job is isolated from credentials and live Kustomization', () => {
  assert.equal((manifest.match(/^kind: ConfigMap$/gm) ?? []).length, 1);
  assert.equal((manifest.match(/^kind: Job$/gm) ?? []).length, 1);
  assert.equal((manifest.match(/^kind: NetworkPolicy$/gm) ?? []).length, 1);
  assert.match(manifest, /  suspend: true/);
  assert.match(manifest, /automountServiceAccountToken: false/);
  assert.match(manifest, /policyTypes: \[Ingress, Egress\]/);
  assert.match(manifest, /claimName: renovate-cache-dedicated/);
  assert.match(manifest, /mountPath: \/cache\/renovate/);
  assert.doesNotMatch(manifest, /github-app|secretName:|serviceAccountName:/);
  assert.doesNotMatch(
    fs.readFileSync(path.join(app, 'kustomization.yaml'), 'utf8'),
    /cache-corruption-drill\.yaml/,
  );
  const image = manifest.match(/^\s+image: (\S+)$/m)?.[1];
  assert(image?.includes('renovate:44.167.4@sha256:'));
  assert.match(
    fs.readFileSync(path.join(app, 'cronjob.yaml'), 'utf8'),
    new RegExp(`image: ${image.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
  );
  assert.equal(CACHE, '/cache/renovate/renovate/renovate-cache-v1');
  assert.match(source, /createRequire\('\/usr\/local\/renovate\/package\.json'\)/);
  assert.equal(
    KEY,
    'github-tags-datasource-v2-' +
      'https://api.github.com/:chainguard-actions:actions-checkout',
  );
});

test('mount and capacity guards reject shared, wrong, or ambiguous volumes', () => {
  assert.doesNotThrow(() => verifyMount(validMount));
  assert.doesNotThrow(() => verifyCapacity(validDf));
  for (const mount of [
    validMount.replace('/renovate-cache', '/homelab'),
    validMount.replace(' - nfs ', ' - nfs4 '),
    validMount.replace('rw,relatime', 'ro,relatime'),
    validMount.replace('/cache/renovate', '/other'),
    validMount + validMount,
  ]) {
    assert.throws(() => verifyMount(mount));
  }
  for (const size of ['1048576', '26214400', 'unknown']) {
    assert.throws(() => verifyCapacity(validDf.replace('20971520', size)));
  }
});

test('only an existing warm public key can be overwritten', async () => {
  const valid = store();
  await inject(valid, validMount, validDf, now);
  assert.equal(valid.calls.length, 2);
  assert.deepEqual(valid.calls[0], ['info', KEY]);
  const [operation, key, data, options] = valid.calls[1];
  assert.equal(operation, 'put');
  assert.equal(key, KEY);
  assert.equal(data.toString(), 'not a cache entry');
  assert(data.length < 32);
  assert(options.metadata.expiry > now + 2 * hour);

  for (const info of [null, { key: 'other', metadata: { expiry: now + 3 * hour } },
    { key: KEY, metadata: { expiry: now + hour } }]) {
    const denied = store(info);
    await assert.rejects(inject(denied, validMount, validDf, now));
    assert.deepEqual(denied.calls.map(([op]) => op), ['info']);
  }
  const wrongMount = store();
  await assert.rejects(inject(wrongMount, validMount.replace('/renovate-cache', '/homelab'), validDf, now));
  assert.equal(wrongMount.calls.length, 0);
});

const packageRoot = process.argv[2];
if (packageRoot) {
  test('pinned cacache 20.0.4 replaces only the public entry with native expiry', async () => {
    assert(path.isAbsolute(packageRoot));
    const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
    assert.equal(packageJson.version, '44.167.4');
    const cacache = createRequire(path.join(packageRoot, 'package.json'))('cacache');
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-cache-corruption-'));
    try {
      const current = Date.now();
      await cacache.put(cacheDir, KEY, Buffer.from('public fixture'), {
        metadata: { expiry: current + 3 * hour },
      });
      const actual = {
        info: (key) => cacache.get.info(cacheDir, key),
        put: (key, data, options) => cacache.put(cacheDir, key, data, options),
      };
      await inject(actual, validMount, validDf, current);
      const entry = await cacache.get(cacheDir, KEY);
      assert.equal(entry.data.toString(), 'not a cache entry');
      assert(entry.metadata.expiry > current + 2 * hour);
      assert.equal((await cacache.ls(cacheDir))[KEY].key, KEY);
    } finally {
      fs.rmSync(cacheDir, { recursive: true, force: true });
    }
  });
}
