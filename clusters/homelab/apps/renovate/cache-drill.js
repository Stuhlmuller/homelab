const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

const missingHour = Date.parse('2099-01-01T00:00:00Z'); // Inert until reviewed UTC slots are chosen.
const corruptHour = Date.parse('2099-01-01T01:00:00Z');
const cacheDir = '/cache/renovate-drill';
const marker = '/tmp/renovate-cache-drill-mode';
const packageRoot = '/usr/local/renovate';
const namespace = 'github-releases-datasource-v2';
const key = 'https://api.github.com/:Stuhlmuller:renovate';
const repo = 'Stuhlmuller/renovate';
const badEntry = Buffer.from('not a cache entry');

function mode(now = Date.now()) {
  if (now >= missingHour && now < missingHour + 3600_000) return 'missing';
  if (now >= corruptHour && now < corruptHour + 3600_000) return 'corrupt';
  return null;
}

function prepared(now = Date.now(), markerPath = marker) {
  const selected = mode(now);
  const staged = fs.existsSync(markerPath) ? fs.readFileSync(markerPath, 'utf8').trim() : null;
  if (selected !== staged) throw new Error('Renovate cache drill slot was not prepared');
  return selected;
}

function pinnedPackage(root) {
  const packageFile = path.join(root, 'package.json');
  if (JSON.parse(fs.readFileSync(packageFile, 'utf8')).version !== '44.167.4') {
    throw new Error('Renovate cache drill image version changed');
  }
  return createRequire(packageFile)('cacache');
}

function paths(dir) {
  return {
    packageStore: path.join(dir, 'renovate', 'renovate-cache-v1'),
    repoFile: path.join(dir, 'renovate', 'repository', 'github', `${repo}.json`),
  };
}

async function prepare(options = {}) {
  const now = options.now ?? Date.now();
  const selected = mode(now);
  const dir = options.cacheDir ?? cacheDir;
  const markerPath = options.marker ?? marker;
  if (fs.existsSync(markerPath)) throw new Error('Renovate cache drill marker already exists');
  if (!selected) return null;

  const cacache = pinnedPackage(options.packageRoot ?? packageRoot);
  if (fs.readdirSync(dir).length !== 0) throw new Error('Renovate cache drill volume is not empty');
  if (selected === 'corrupt') {
    const { packageStore, repoFile } = paths(dir);
    await cacache.put(packageStore, `${namespace}-${key}`, badEntry, {
      metadata: { expiry: now + 3600_000 },
    });
    fs.mkdirSync(path.dirname(repoFile), { recursive: true });
    fs.writeFileSync(repoFile, '{broken json');
    const staged = await cacache.get(packageStore, `${namespace}-${key}`);
    if (!staged.data.equals(badEntry) || fs.readFileSync(repoFile, 'utf8') !== '{broken json') {
      throw new Error('Renovate cache drill corruption was not staged');
    }
  }
  fs.writeFileSync(markerPath, selected, { flag: 'wx' });
  return selected;
}

async function verify(options = {}) {
  const selected = fs.readFileSync(options.marker ?? marker, 'utf8').trim();
  if (selected !== 'missing' && selected !== 'corrupt') {
    throw new Error('Renovate cache drill verification has no active slot');
  }

  const root = options.packageRoot ?? packageRoot;
  const cacache = pinnedPackage(root);
  const { packageStore, repoFile } = paths(options.cacheDir ?? cacheDir);
  const raw = await cacache.get(packageStore, `${namespace}-${key}`);
  const { decodeEntry } = await import(pathToFileURL(path.join(root, 'dist/util/cache/package/codec.js')).href);
  const decoded = await decodeEntry(raw.data);
  if (decoded.value === undefined || raw.data.equals(badEntry)) {
    throw new Error('Renovate did not rebuild the public canary package entry');
  }
  if (selected === 'corrupt' && fs.readFileSync(repoFile, 'utf8') !== '{broken json') {
    throw new Error('Renovate unexpectedly rewrote the malformed repository cache in full dry-run');
  }
  if (selected === 'missing' && fs.existsSync(repoFile)) {
    throw new Error('Renovate unexpectedly wrote a repository cache in full dry-run');
  }

  return selected;
}

if (require.main === module) {
  const action = process.argv[2];
  const run = action === 'prepare' ? prepare : action === 'verify' ? verify : null;
  if (!run) throw new Error('Renovate cache drill action must be prepare or verify');
  run().then((selected) => {
    if (action === 'verify') process.stdout.write(`Renovate ${selected} cache drill rebuilt the public package entry; repository cache stayed unchanged\n`);
  }).catch((error) => {
    process.stderr.write(`Renovate cache drill failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { cacheDir, missingHour, corruptHour, mode, prepared, prepare, verify };
