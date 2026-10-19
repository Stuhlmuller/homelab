const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const inventory = require('../../clusters/homelab/apps/renovate/acceptance-inventory.js');

const repository = 'Stuhlmuller/example';
const headSha = 'a'.repeat(40);
const configHash = 'd'.repeat(128);
const dependency = { depName: 'lodash', datasource: 'npm', currentValue: '1.0.0' };
const packageFile = 'package.json';
const scan = { revision: 1, sha: headSha, configHash, packageFiles: {
  npm: [{ packageFile, deps: [dependency] }],
} };

function fixture() {
  const key = inventory.candidateKey(repository, 'main', 'npm', packageFile, 0, dependency);
  const ownerRepositories = [{ repository, baseBranch: 'main', headSha }];
  return {
    review: {
      schema: 1, owner: 'Stuhlmuller', seed: 'natural-2026-10-18',
      imageDigest: 'sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d',
      configSha256: 'b'.repeat(64),
      repositories: [{ repository, baseBranch: 'main', headSha,
        configHash, cacheHash: 'c'.repeat(128), policyEvidence: 'private://policy-review' }],
      ownerInventory: { source: 'private://independent-owner-receipt',
        verifiedAt: new Date().toISOString(), repositories: ownerRepositories,
        sha256: crypto.createHash('sha256').update(JSON.stringify(ownerRepositories)).digest('hex') },
      expectedStrata: [{ datasource: 'npm', sourceVisibility: 'public', count: 1 }],
      classifications: [{ key, decision: 'sample', sourceVisibility: 'public',
        visibilityEvidence: 'private://registry-proof', policyEvidence: 'private://policy-review',
        registryUrl: 'https://registry.npmjs.org' }],
    },
    scans: new Map([[repository, scan]]),
    datasources: new Map([['npm', { getDefaultRegistryUrls: () => ['https://registry.npmjs.org/'] }]]),
    live: [{ full_name: repository, owner: { login: 'Stuhlmuller' }, archived: false,
      default_branch: 'main', headSha }],
  };
}

test('frozen inventory derives class, canonical registry, and per-repository provenance from verified extraction', () => {
  const { review, scans, datasources, live } = fixture();
  const { inventory: result, ledger } = inventory.buildInventory(review, scans, datasources, live);
  assert.deepEqual(result.activeDatasources, ['npm']);
  assert.deepEqual(result.dependencies[0], { repository, datasource: 'npm', packageName: 'lodash',
    registryUrl: 'https://registry.npmjs.org', currentValue: '1.0.0',
    sourceVisibility: 'public', packageFile, controlledCanary: false });
  assert.deepEqual(result.provenance.repositories, [{ repository, baseBranch: 'main', headSha,
    cacheSha512: 'c'.repeat(128), configHash }]);
  assert.equal(result.provenance.sha256,
    crypto.createHash('sha256').update(JSON.stringify(result.provenance.repositories)).digest('hex'));
  assert.equal(ledger.inventorySha256,
    crypto.createHash('sha256').update(JSON.stringify(result)).digest('hex'));
});

test('missing or stale policy, source, registry, or repository proof cannot seed', () => {
  const cases = [
    (x) => { x.review.classifications = []; },
    (x) => { x.review.classifications[0].sourceVisibility = 'unknown'; },
    (x) => { x.review.classifications[0].visibilityEvidence = ''; },
    (x) => { x.review.classifications[0].policyEvidence = ''; },
    (x) => { x.review.classifications[0].registryUrl = 'https://other.example'; },
    (x) => { x.review.classifications[0].controlledCanary = true; },
    (x) => { x.review.repositories[0].headSha = 'd'.repeat(40); },
    (x) => { x.review.repositories[0].configHash = 'stale'; },
    (x) => { x.review.expectedStrata[0].count = 0; },
    (x) => { x.review.ownerInventory.source = ''; },
    (x) => { x.review.ownerInventory.verifiedAt = '2020-01-01T00:00:00.000Z'; },
    (x) => { x.live.push({ full_name: 'Stuhlmuller/omitted', owner: { login: 'Stuhlmuller' },
      archived: false, default_branch: 'main', headSha }); },
    (x) => { x.datasources.get('npm').getDefaultRegistryUrls = () => ['https://one.example', 'https://two.example']; },
  ];
  for (const mutate of cases) {
    const context = fixture();
    mutate(context);
    assert.throws(() => inventory.buildInventory(context.review, context.scans,
      context.datasources, context.live));
  }
});

test('pinned cache reader verifies Brotli payload, revision, repository, hash, and extraction SHA', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-inventory-'));
  try {
    const filename = path.join(root, `${repository}.json`);
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    const raw = JSON.stringify({ scan: { main: scan } });
    const hash = crypto.createHash('sha512').update(raw).digest('hex');
    const record = { revision: 13, repository, fingerprint: 'repo', hash,
      payload: zlib.brotliCompressSync(raw).toString('base64') };
    fs.writeFileSync(filename, JSON.stringify(record));
    assert.deepEqual(inventory.readCache(repository, 'main', hash, root), scan);
    assert.throws(() => inventory.readCache(repository, 'main', '0'.repeat(128), root));
    record.payload = zlib.brotliCompressSync('{}').toString('base64');
    fs.writeFileSync(filename, JSON.stringify(record));
    assert.throws(() => inventory.readCache(repository, 'main', hash, root));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('pinned Renovate 44.167.4 cache utilities produce a readable repository record', () => {
  // Fixture payload/hash generated by renovate@44.167.4 dist/util/compress.js and dist/util/hash.js.
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-pinned-cache-'));
  try {
    const filename = path.join(root, `${repository}.json`);
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    const fixturePath = path.join(__dirname, 'fixtures/renovate-repo-cache-v13.json');
    fs.copyFileSync(fixturePath, filename);
    const hash = JSON.parse(fs.readFileSync(fixturePath)).hash;
    assert.deepEqual(inventory.readCache(repository, 'main', hash, root).packageFiles, scan.packageFiles);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('canonical registry requires credential-free HTTPS', () => {
  assert.equal(inventory.canonicalRegistry('https://REGISTRY.example.com/packages/'),
    'https://registry.example.com/packages');
  for (const url of ['http://registry.example.com', 'https://user:pass@registry.example.com',
    'https://registry.example.com/?token=x']) {
    assert.throws(() => inventory.canonicalRegistry(url));
  }
});

test('single-file seed survives an interrupted link and refuses to replace a frozen ledger', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-ledger-'));
  const originalLink = fs.linkSync;
  try {
    fs.linkSync = () => { throw new Error('interrupted'); };
    assert.throws(() => inventory.saveLedger({ schema: 1 }, directory), /interrupted/);
    assert.deepEqual(fs.readdirSync(directory), []);
    fs.linkSync = originalLink;
    inventory.saveLedger({ schema: 1 }, directory);
    assert.equal(fs.statSync(path.join(directory, 'ledger.json')).mode & 0o077, 0);
    assert.throws(() => inventory.saveLedger({ schema: 2 }, directory), /EEXIST/);
    assert.deepEqual(fs.readdirSync(directory), ['ledger.json']);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory, 'ledger.json'))), { schema: 1 });
  } finally {
    fs.linkSync = originalLink;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
