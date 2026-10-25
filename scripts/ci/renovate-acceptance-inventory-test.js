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
      windowStart: '2026-10-17T00:00:00.000Z',
      windowEnd: '2026-10-24T00:00:00.000Z',
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
  assert.equal(ledger.windowStart, review.windowStart);
  assert.equal(ledger.windowEnd, review.windowEnd);
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

test('excluded extraction rows cannot erase an active datasource or visibility stratum', () => {
  function addExcluded(context, manager, fileName, dep, visibility) {
    const extracted = structuredClone(context.scans.get(repository));
    extracted.packageFiles[manager] ||= [];
    extracted.packageFiles[manager].push({ packageFile: fileName, deps: [dep] });
    context.scans.set(repository, extracted);
    context.review.classifications.push({
      key: inventory.candidateKey(repository, 'main', manager, fileName, 0, dep),
      decision: 'exclude', reason: 'reviewed-policy-exclusion',
      sourceVisibility: visibility, visibilityEvidence: 'private://registry-proof',
      policyEvidence: 'private://policy-review',
    });
  }

  const justified = fixture();
  addExcluded(justified, 'npm', 'other.json',
    { depName: 'other-package', datasource: 'npm' }, 'public');
  justified.review.expectedStrata[0].count = 2;
  const { inventory: frozen } = inventory.buildInventory(justified.review,
    justified.scans, justified.datasources, justified.live);
  assert.deepEqual(frozen.activeDatasources, ['npm']);
  assert.equal(frozen.dependencies.length, 1);

  const missingVisibility = fixture();
  addExcluded(missingVisibility, 'npm', 'private.json',
    { depName: '@example/private', datasource: 'npm' }, 'private');
  missingVisibility.review.expectedStrata = [
    { datasource: 'npm', sourceVisibility: 'private', count: 1 },
    { datasource: 'npm', sourceVisibility: 'public', count: 1 },
  ];
  assert.throws(() => inventory.buildInventory(missingVisibility.review,
    missingVisibility.scans, missingVisibility.datasources, missingVisibility.live),
  /missing-source-stratum/);

  const missingClass = fixture();
  const release = { depName: 'example/tool', datasource: 'github-releases' };
  addExcluded(missingClass, 'github', 'deps.yml', release, 'private');
  missingClass.datasources.set('github-releases',
    { getDefaultRegistryUrls: () => ['https://api.github.com/'] });
  missingClass.review.expectedStrata = [
    { datasource: 'github-releases', sourceVisibility: 'private', count: 1 },
    { datasource: 'npm', sourceVisibility: 'public', count: 1 },
  ];
  assert.throws(() => inventory.buildInventory(missingClass.review,
    missingClass.scans, missingClass.datasources, missingClass.live),
  /missing-source-stratum/);
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
    (x) => { delete x.review.windowStart; },
    (x) => { x.review.windowEnd = '2026-10-24T01:00:00.000Z'; },
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

test('projected private review is copied once to the protected ledger', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-review-'));
  try {
    const projection = path.join(root, 'projection');
    const ledger = path.join(root, 'ledger');
    fs.mkdirSync(path.join(projection, '..data'), { recursive: true });
    const source = path.join(projection, '..data', 'review.json');
    fs.writeFileSync(source, JSON.stringify({ schema: 1, owner: 'Stuhlmuller' }), { mode: 0o440 });
    fs.symlinkSync('..data/review.json', path.join(projection, 'review.json'));
    const projected = inventory.readReview(path.join(projection, 'review.json'));
    assert.equal(projected.review.schema, 1);
    inventory.materializeReview(projected.bytes, ledger);
    const frozen = path.join(ledger, 'review.json');
    assert.equal(fs.statSync(frozen).mode & 0o077, 0);
    inventory.materializeReview(projected.bytes, ledger);
    fs.rmSync(source);
    fs.writeFileSync(source, JSON.stringify({ schema: 1, owner: 'other' }), { mode: 0o440 });
    assert.throws(() => inventory.materializeReview(
      inventory.readReview(path.join(projection, 'review.json')).bytes, ledger),
      /review-already-frozen/);
    fs.chmodSync(source, 0o644);
    assert.throws(() => inventory.readReview(path.join(projection, 'review.json')),
      /invalid-review-source/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
