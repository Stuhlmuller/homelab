import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

const packageRoot = process.argv[2];
if (!packageRoot || !path.isAbsolute(packageRoot)) {
  throw new Error('Pass the absolute path to the installed renovate@44.167.4 package');
}
const { version } = JSON.parse(await fs.readFile(path.join(packageRoot, 'package.json'), 'utf8'));
assert.equal(version, '44.167.4', 'fixture must use the pinned Renovate version');

const renovateModule = (relativePath) => import(pathToFileURL(path.join(packageRoot, 'dist', relativePath)).href);
const requireRenovate = createRequire(path.join(packageRoot, 'package.json'));
const [{ PackageCacheFile }, { RepoCacheLocal }, { GlobalConfig }, { init: initLogger, levels }] = await Promise.all([
  renovateModule('util/cache/package/impl/file.js'),
  renovateModule('util/cache/repository/impl/local.js'),
  renovateModule('config/global.js'),
  renovateModule('logger/index.js'),
]);
const cacache = requireRenovate('cacache');
await initLogger();
levels('stdout', 'error');

test('pinned Renovate rebuilds missing and malformed package cache entries', async () => {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'renovate-cache-recovery-'));
  try {
    const cache = PackageCacheFile.create(cacheDir);
    assert.equal(await cache.get('fixture', 'missing'), undefined);
    await cache.set('fixture', 'missing', { versions: ['1.0.0'] }, 60);
    const laterRun = PackageCacheFile.create(cacheDir);
    assert.deepEqual(await laterRun.get('fixture', 'missing'), { versions: ['1.0.0'] });

    await cacache.put(cache.cacheFileName, 'fixture-corrupt', Buffer.from('not a cache entry'), {
      metadata: { expiry: Date.now() + 60_000 },
    });
    assert.equal(await laterRun.get('fixture', 'corrupt'), undefined);
    await laterRun.set('fixture', 'corrupt', { versions: ['2.0.0'] }, 60);
    assert.deepEqual(await PackageCacheFile.create(cacheDir).get('fixture', 'corrupt'), { versions: ['2.0.0'] });
  } finally {
    await fs.rm(cacheDir, { recursive: true, force: true });
  }
});

test('pinned Renovate replaces a malformed repository cache on the next save', async () => {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'renovate-repo-recovery-'));
  try {
    GlobalConfig.set({ platform: 'github', cacheDir });
    const cache = new RepoCacheLocal('Stuhlmuller/cache-fixture', 'fixture-fingerprint');
    const file = path.join(cacheDir, cache.getCacheFileName());
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, '{broken json');
    await cache.load();
    assert.deepEqual(cache.getData(), {});
    cache.getData().fixture = 'rebuilt';
    await cache.save();

    const nextRun = new RepoCacheLocal('Stuhlmuller/cache-fixture', 'fixture-fingerprint');
    await nextRun.load();
    assert.deepEqual(nextRun.getData(), { fixture: 'rebuilt' });
  } finally {
    GlobalConfig.reset();
    await fs.rm(cacheDir, { recursive: true, force: true });
  }
});
