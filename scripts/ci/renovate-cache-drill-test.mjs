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
const require = createRequire(import.meta.url);
const drill = require('../../clusters/homelab/apps/renovate/cache-drill.js');
const renovateModule = (relativePath) => import(pathToFileURL(path.join(packageRoot, 'dist', relativePath)).href);
const [{ PackageCacheFile }, { RepoCacheLocal }, { GlobalConfig }, { init: initLogger, levels }, repositoryCache] = await Promise.all([
  renovateModule('util/cache/package/impl/file.js'),
  renovateModule('util/cache/repository/impl/local.js'),
  renovateModule('config/global.js'),
  renovateModule('logger/index.js'),
  renovateModule('util/cache/repository/index.js'),
]);
await initLogger();
levels('stdout', 'error');

const { missingHour, corruptHour } = drill;
const namespace = 'github-releases-datasource-v2';
const key = 'https://api.github.com/:Stuhlmuller:renovate';

test('only two committed UTC hours select the scratch cache', () => {
  assert.ok(Number.isFinite(missingHour));
  assert.ok(Number.isFinite(corruptHour));
  assert.ok(corruptHour >= missingHour + 3600_000);
  assert.equal(drill.mode(missingHour - 1), null);
  assert.equal(drill.mode(missingHour), 'missing');
  assert.equal(drill.mode(missingHour + 3600_000 - 1), 'missing');
  assert.equal(drill.mode(corruptHour), 'corrupt');
  assert.equal(drill.mode(corruptHour + 3600_000 - 1), 'corrupt');
  assert.equal(drill.mode(corruptHour + 3600_000), null);
});

for (const [selected, now] of [['missing', missingHour], ['corrupt', corruptHour]]) {
  test(`pinned Renovate rebuilds the ${selected} package cache and skips repo save in full dry-run`, async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'renovate-cache-drill-'));
    const cacheDir = path.join(root, 'cache');
    const marker = path.join(root, 'marker');
    await fs.mkdir(cacheDir);
    const options = { now, cacheDir, marker, packageRoot };
    try {
      assert.equal(await drill.prepare(options), selected);
      assert.equal(drill.prepared(now, marker), selected);
      await assert.rejects(drill.verify(options));

      GlobalConfig.set({ platform: 'github', cacheDir, dryRun: 'full' });
      const packageCache = PackageCacheFile.create(cacheDir);
      const repoCache = new RepoCacheLocal('Stuhlmuller/renovate', 'fixture-fingerprint');
      assert.equal(await packageCache.get(namespace, key), undefined);
      await repoCache.load();
      assert.deepEqual(repoCache.getData(), {});
      await packageCache.set(namespace, key, { versions: ['v0.0.2'] }, 60);
      repoCache.getData().fixture = 'rebuilt';
      repositoryCache.setCache(repoCache);
      await repositoryCache.saveCache();
      const repoFile = path.join(cacheDir, 'renovate', 'repository', 'github', 'Stuhlmuller', 'renovate.json');
      if (selected === 'corrupt') {
        assert.equal(await fs.readFile(repoFile, 'utf8'), '{broken json');
      } else {
        await assert.rejects(fs.stat(repoFile), { code: 'ENOENT' });
      }

      assert.equal(await drill.verify(options), selected);
      assert.equal(await drill.verify({ ...options, now: corruptHour + 3600_000 }), selected);
      assert.throws(() => drill.prepared(corruptHour + 3600_000, marker), /slot was not prepared/);
      await fs.mkdir(path.dirname(repoFile), { recursive: true });
      await fs.writeFile(repoFile, '{}');
      await assert.rejects(drill.verify(options), /Renovate unexpectedly (rewrote|wrote)/);
    } finally {
      repositoryCache.resetCache();
      GlobalConfig.reset();
      await fs.rm(root, { recursive: true, force: true });
    }
  });
}

test('unprepared or invalid staging stops before a scan can start', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'renovate-cache-drill-invalid-'));
  const cacheDir = path.join(root, 'cache');
  const marker = path.join(root, 'marker');
  await fs.mkdir(cacheDir);
  try {
    assert.throws(() => drill.prepared(missingHour, marker), /slot was not prepared/);
    await assert.rejects(drill.prepare({ now: corruptHour, cacheDir, marker, packageRoot: root }), /ENOENT/);
    assert.equal(await fs.readdir(cacheDir).then((items) => items.length), 0);
    assert.equal(await fs.stat(marker).then(() => true, () => false), false);
    assert.equal(await drill.prepare({ now: missingHour - 1, cacheDir, marker, packageRoot }), null);
    assert.equal(await fs.readdir(cacheDir).then((items) => items.length), 0);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
