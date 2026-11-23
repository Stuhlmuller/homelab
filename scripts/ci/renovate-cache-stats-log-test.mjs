import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const packageRoot = process.argv[2];
if (!packageRoot || !path.isAbsolute(packageRoot)) {
  throw new Error('Pass the absolute path to installed renovate@44.167.4');
}
const { version } = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
assert.equal(version, '44.167.4');

function pinnedModule(relativePath, sha256) {
  const file = path.join(packageRoot, 'dist', relativePath);
  const actual = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  assert.equal(actual, sha256, `Unexpected pinned Renovate ${relativePath}`);
  return import(pathToFileURL(file).href);
}

const [
  { init: initLogger, levels, logger, setMeta },
  { setGlobalLogLevelRemaps, resetGlobalLogLevelRemaps },
  { PackageCacheStats },
  { PackageCacheFile },
  { init: initMemoryCache, reset: resetMemoryCache },
] = await Promise.all([
  import(pathToFileURL(path.join(packageRoot, 'dist/logger/index.js')).href),
  pinnedModule('logger/remap.js', '22e121f40148ef368be7bbe14f7d06bd8e96704b5029ee743a7374de921c603e'),
  pinnedModule('util/stats.js', '033bd6709d8925a757750239e70e21bb8560480dec473aaa7466a58529d2b0f2'),
  pinnedModule('util/cache/package/impl/file.js', 'f1d34641ee8155d9a99e0aa712db1cd2964a7b4fcc9371cbd284655b8c0fc95c'),
  import(pathToFileURL(path.join(packageRoot, 'dist/util/cache/memory/index.js')).href),
]);

await initLogger();
levels('stdout', 'info');
setGlobalLogLevelRemaps([
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
initMemoryCache();
setMeta({ repository: 'fixture/repo' });
const output = [];
const cacheRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-cache-log-test-'));
const originalWrite = process.stdout.write;
process.stdout.write = function capture(chunk) {
  output.push(String(chunk));
  return true;
};
try {
  logger.debug({ namespace: 'private', key: 'private-key', url: 'https://private.invalid/' }, 'Cache miss');
  PackageCacheStats.writeGet(12);
  PackageCacheStats.writeSet(7);
  PackageCacheStats.report();
  for (const [name, meta] of [
    ['cleared', {}],
    ['stale', { repository: 'fixture/stale-repo' }],
  ]) {
    setMeta(meta);
    const cache = PackageCacheFile.create(path.join(cacheRoot, name));
    await cache.set('fixture', 'https://private.invalid/private-key', { name: 'private-package' }, 60);
    await cache.destroy();
  }
} finally {
  process.stdout.write = originalWrite;
  setMeta({});
  resetGlobalLogLevelRemaps();
  resetMemoryCache();
  fs.rmSync(cacheRoot, { recursive: true, force: true });
}

const records = output.join('').trim().split('\n').map((line) => JSON.parse(line));
assert.equal(records.length, 7);
assert.equal(records[0].msg, 'Package cache statistics');
assert.equal(records[0].level, 30);
assert.equal(records[0].oldLevel, 'debug');
assert.equal(records[0].repository, 'fixture/repo');
assert.ok(records[0].get);
assert.ok(records[0].set);
assert.equal(records[0].get.count, 1);
assert.equal(records[0].get.totalMs, 12);
assert.equal(records[0].set.count, 1);
assert.equal(records[0].set.totalMs, 7);
for (const side of ['get', 'set']) {
  assert.deepEqual(Object.keys(records[0][side]).sort(),
    ['count', 'avgMs', 'medianMs', 'maxMs', 'totalMs'].sort());
  assert.ok(Object.values(records[0][side]).every((value) => typeof value === 'number'));
}
for (const offset of [1, 4]) {
  assert.equal(records[offset].msg, 'Checking file package cache for expired items');
  assert.match(records[offset + 1].msg,
    /^Cache GC: kept [0-9]+ content entries [(][0-9]+ bytes[)], removed [0-9]+ orphaned [(][0-9]+ bytes[)] in [0-9]+(?:[.][0-9]+)?ms$/);
  assert.match(records[offset + 2].msg,
    /^Deleted [0-9]+ of [0-9]+ file cached entries in [0-9]+ms$/);
}
for (const record of records) {
  assert.equal(record.level, 30);
  assert.equal(record.oldLevel, 'debug');
  for (const field of ['namespace', 'key', 'url', 'registryUrl', 'packageName']) {
    assert.equal(Object.hasOwn(record, field), false, `${field} must not reach INFO`);
  }
}
for (const index of [1, 2, 3]) {
  assert.equal(Object.hasOwn(records[index], 'repository'), false);
}
for (const index of [4, 5, 6]) {
  assert.equal(records[index].repository, 'fixture/stale-repo');
}
assert.doesNotMatch(output.join(''), /private-key|private[.]invalid|private-package/);
console.log('Pinned Renovate restricted cache timing remap passed');
