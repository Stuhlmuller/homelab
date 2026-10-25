import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const packageRoot = process.argv[2];
if (!packageRoot || !path.isAbsolute(packageRoot)) {
  throw new Error('Pass the absolute path to the installed renovate@44.167.4 package');
}
const { version } = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
assert.equal(version, '44.167.4', 'fixture must use the pinned Renovate version');

const renovateModule = async (relativePath) => import(pathToFileURL(path.join(packageRoot, 'dist', relativePath)).href);
const [
  { init: initLogger, levels, logger },
  { setGlobalLogLevelRemaps, resetGlobalLogLevelRemaps },
] = await Promise.all([
  renovateModule('logger/index.js'),
  renovateModule('logger/remap.js'),
]);

const configPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../clusters/homelab/apps/renovate/config.js');
const source = fs.readFileSync(configPath, 'utf8');
const { privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const key = privateKey.export({ type: 'pkcs8', format: 'pem' });
const context = {
  Buffer,
  module: { exports: {} },
  require(name) {
    if (name === 'node:crypto') return crypto;
    if (name === 'node:fs') return {
      readFileSync(file) {
        if (file === '/var/run/secrets/renovate/issuer-id') return 'Iv1.fixture';
        if (file === '/var/run/secrets/renovate/private-key') return key;
        throw new Error('Unexpected credential path');
      },
      writeFileSync(file, bytes, settings) {
        assert.match(file, /^\/cache\/renovate\/\.storage-probe-[0-9a-f-]+$/);
        assert.equal(bytes.length, 4096);
        assert.equal(settings.flush, true);
      },
      unlinkSync(file) { assert.match(file, /^\/cache\/renovate\/\.storage-probe-[0-9a-f-]+$/); },
    };
    throw new Error(`Unexpected config.js import: ${name}`);
  },
  async fetch(url) {
    if (url === 'https://api.github.com/orgs/Stuhlmuller/installation') {
      return { ok: true, json: async () => ({ id: 42, account: { login: 'Stuhlmuller' }, repository_selection: 'all' }) };
    }
    if (url === 'https://api.github.com/app/installations/42/access_tokens') {
      return { ok: true, json: async () => ({ token: 'ghs_fixture', expires_at: new Date(Date.now() + 3_600_000).toISOString() }) };
    }
    throw new Error(`Unexpected GitHub App API path: ${url}`);
  },
};
vm.runInNewContext(source, context, { filename: configPath });
const config = await context.module.exports();
assert.ok(Array.isArray(config.logLevelRemap), 'runner must configure targeted log remaps');
assert.deepEqual(JSON.parse(JSON.stringify(config.logLevelRemap)), [
  { matchMessage: '/^Returning cached value$/', newLogLevel: 'info' },
]);

await initLogger();
levels('stdout', 'info');
setGlobalLogLevelRemaps(config.logLevelRemap);
const output = [];
const originalWrite = process.stdout.write;
process.stdout.write = function write(chunk) {
  output.push(String(chunk));
  return true;
};
try {
  logger.debug({ packageName: 'example/widget' }, 'unrelated debug message');
  logger.trace({ namespace: 'docker-tags', key: 'fixture-key' }, 'Returning cached value');
} finally {
  process.stdout.write = originalWrite;
  resetGlobalLogLevelRemaps();
}

const records = output.join('').trim().split('\n').map((line) => JSON.parse(line));
assert.deepEqual(records.map(({ msg }) => msg), ['Returning cached value']);
assert.equal(records[0].level, 30);
assert.equal(records[0].oldLevel, 'trace');
assert.equal(records[0].namespace, 'docker-tags');
assert.equal(records[0].key, 'fixture-key', 'cache-hit metadata needs restricted logs');
console.log('Pinned Renovate cache-hit log remap passed');
