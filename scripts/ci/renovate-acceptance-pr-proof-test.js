const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const proof = require('../../clusters/homelab/apps/renovate/acceptance-pr-proof.js');
const observer = require('../../clusters/homelab/apps/renovate/acceptance-observer.js');

const uid = '12345678-1234-1234-1234-123456789abc';
const repository = 'Stuhlmuller/example';
const item = { repository, datasource: 'npm', packageName: 'fixture-package',
  packageFile: 'package.json' };
const event = { version: '1.1.0', lastAbsent: '2026-10-19T00:00:00.000Z',
  firstPresent: '2026-10-19T00:15:00.000Z' };
const receipt = { schema: 1, podUid: uid, image: 'renovate:44.167.4',
  startedAt: '2026-10-19T00:20:00.000Z', completedAt: '2026-10-19T00:22:00.000Z' };
const branch = { branchName: 'renovate/fixture-package-1.x', prNo: 42,
  upgrades: [{ datasource: 'npm', depName: 'fixture-package',
  packageFile: 'package.json', newVersion: '1.1.0' }] };
const report = { problems: [], repositories: { [repository]: { branches: [branch] } } };
const pull = { number: 42, changed_files: 1,
  created_at: '2026-10-19T00:21:00.000Z', user: { login: 'rstuhlmuller-renovate[bot]' },
  base: { ref: 'main', repo: { full_name: repository } },
  head: { ref: branch.branchName, sha: 'a'.repeat(40), repo: { full_name: repository } } };
const files = [{ filename: 'package.json', patch: '@@ -1 +1 @@\n-"fixture-package":"1.0.0"\n+"fixture-package":"1.1.0"' }];
const observedAt = '2026-10-19T00:30:00.000Z';

test('only one exact pinned-report PR candidate can bind a sampled version', () => {
  const reports = [{ receipt, report }];
  assert.equal(proof.candidate(item, event, reports).number, 42);
  assert.equal(proof.candidate({ ...item, packageFile: 'other.json' }, event, reports), null);
  assert.equal(proof.candidate(item, { ...event, version: '1.2.0' }, reports), null);
  assert.equal(proof.candidate(item, event, [{ receipt: { ...receipt,
    completedAt: '2026-10-18T23:59:00.000Z' }, report }]), null);
  assert.equal(proof.candidate(item, event, [...reports, { receipt,
    report: { problems: [], repositories: { [repository]: { branches: [{ ...branch, prNo: 43 }] } } } }]), null);
});

test('GitHub PR patch proves an exact version only at the read time upper bound', () => {
  const match = proof.candidate(item, event, [{ receipt: { ...receipt,
    report: { sha256: 'b'.repeat(64) } }, report }]);
  const result = proof.proposalProof(item, event, match, pull, files, observedAt, 'main');
  assert.equal(result.claim.at, observedAt);
  assert.equal(result.material.createdAt, pull.created_at);
  assert.equal(result.material.reportSha256, 'b'.repeat(64));
  assert.equal(proof.proposalProof(item, event, match, pull, files,
    '2026-10-19T04:01:00.000Z', 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, pull,
    [{ filename: 'package.json', patch: '+"fixture-package":"11.1.0"' }], observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, pull,
    [{ filename: 'lock.json', patch: files[0].patch }], observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, pull,
    [{ filename: 'package.json', patch: '+"unrelated-package":"1.1.0"' }], observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, pull,
    [{ filename: 'package.json', patch: '+"somefixture-package":"1.1.0"' }], observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, { ...pull,
    user: { login: 'unrelated' } }, files, observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, { ...pull,
    changed_files: 2 }, files, observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, { ...pull,
    base: { ref: 'other', repo: { full_name: repository } } }, files, observedAt, 'main'), null);
  assert.equal(proof.proposalProof(item, event, match, { ...pull,
    head: { ...pull.head, ref: 'unrelated' } }, files, observedAt, 'main'), null);
});

test('report reader requires private exact bytes and pinned image receipt', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-pr-proof-'));
  try {
    const folder = path.join(directory, 'reports');
    fs.mkdirSync(folder, { mode: 0o700 });
    const bytes = Buffer.from(JSON.stringify(report));
    const fullReceipt = { ...receipt, report: { file: `${uid}.json`, bytes: bytes.length,
      sha256: crypto.createHash('sha256').update(bytes).digest('hex') } };
    const reportPath = path.join(folder, `${uid}.json`);
    const receiptPath = path.join(folder, `${uid}.receipt.json`);
    fs.writeFileSync(reportPath, bytes, { mode: 0o600 });
    fs.writeFileSync(receiptPath, JSON.stringify(fullReceipt), { mode: 0o600 });
    assert.equal(proof.verifiedReports(directory).length, 1);
    fs.writeFileSync(reportPath, '{}');
    assert.throws(() => proof.verifiedReports(directory), /invalid-report-receipt/);
    fs.writeFileSync(reportPath, bytes);
    fs.chmodSync(receiptPath, 0o644);
    assert.throws(() => proof.verifiedReports(directory), /invalid-private-file/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('PR proof Job stays suspended and omitted with no runner cache or Kubernetes token', () => {
  const root = path.resolve(__dirname, '../../clusters/homelab/apps/renovate');
  const manifest = fs.readFileSync(path.join(root, 'acceptance-pr-proof-job.yaml'), 'utf8');
  const kustomization = fs.readFileSync(path.join(root, 'kustomization.yaml'), 'utf8');
  assert.match(manifest, /^  suspend: true$/m);
  assert.match(manifest, /automountServiceAccountToken: false/);
  assert.doesNotMatch(manifest, /claimName: renovate-cache/);
  assert.doesNotMatch(kustomization, /- acceptance-pr-proof-job.yaml/);
  assert.match(kustomization, /- acceptance-pr-proof.js/);
});

test('GitHub response needs a current server clock before a timing receipt', async () => {
  const oldFetch = global.fetch;
  try {
    global.fetch = async () => ({ ok: true,
      headers: { get: () => 'Mon, 01 Jan 2024 00:00:00 GMT' },
      json: async () => files });
    await assert.rejects(proof.pullFiles('ghs_test', repository, 42, 1),
      /github-clock-unverified/);
  } finally {
    global.fetch = oldFetch;
  }
});

test('collector writes private version-bound proof and logs aggregate counts only', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-proof-collect-'));
  const oldToken = observer.readToken;
  const oldFetch = global.fetch;
  const oldLog = console.log;
  const output = [];
  try {
    const now = Date.now();
    const iso = (offset) => new Date(now + offset * 60_000).toISOString();
    const provenance = [{ repository, baseBranch: 'main', headSha: 'a'.repeat(40),
      cacheSha512: 'b'.repeat(128), configHash: 'c'.repeat(128) }];
    const inventory = { schema: 1, owner: 'Stuhlmuller', seed: 'reviewed-seed-2026',
      provenance: { method: 'renovate-extract', repositories: provenance,
        sha256: crypto.createHash('sha256').update(JSON.stringify(provenance)).digest('hex') },
      activeDatasources: ['npm'], dependencies: [{ ...item, sourceVisibility: 'public',
        registryUrl: 'https://registry.npmjs.org', currentValue: '1.0.0' }] };
    const ledger = observer.selectSample(inventory);
    ledger.inventory = inventory;
    ledger.sample[0].events.push({ version: event.version, lastAbsent: iso(-30),
      firstPresent: iso(-15), ambiguous: false });
    fs.writeFileSync(path.join(directory, 'ledger.json'), JSON.stringify(ledger), { mode: 0o600 });
    const folder = path.join(directory, 'reports');
    fs.mkdirSync(folder, { mode: 0o700 });
    const reportBytes = Buffer.from(JSON.stringify(report));
    const reportReceipt = { ...receipt, startedAt: iso(-12), completedAt: iso(-10),
      report: { file: `${uid}.json`, bytes: reportBytes.length,
        sha256: crypto.createHash('sha256').update(reportBytes).digest('hex') } };
    fs.writeFileSync(path.join(folder, `${uid}.json`), reportBytes, { mode: 0o600 });
    fs.writeFileSync(path.join(folder, `${uid}.receipt.json`), JSON.stringify(reportReceipt), { mode: 0o600 });
    observer.readToken = async (permissions) => {
      assert.deepEqual(permissions, { contents: 'read', metadata: 'read', pull_requests: 'read' });
      return 'ghs_test';
    };
    global.fetch = async (url) => ({ ok: true,
      headers: { get: () => new Date().toUTCString() }, json: async () =>
      url.includes('/files?') ? files : { ...pull, created_at: iso(-8) } });
    console.log = (line) => output.push(line);
    await proof.collect(directory);
    const outcomes = JSON.parse(fs.readFileSync(path.join(directory, 'outcomes.json')));
    assert.equal(outcomes.receipts.length, 1);
    assert.equal(outcomes.receipts[0].outcome.kind, 'proposal');
    assert.equal(fs.statSync(path.join(directory, 'outcomes.json')).mode & 0o077, 0);
    assert.equal(observer.verifyPrivateEvidence(outcomes, directory).size, 1);
    assert.deepEqual(JSON.parse(output[0]), { mode: 'proposal-proof', candidates: 1, proven: 1,
      unknown: 0 });
    assert.equal(output.join('').includes(repository), false);
    assert.equal(output.join('').includes(event.version), false);
    await proof.collect(directory);
    assert.deepEqual(JSON.parse(output[1]), { mode: 'proposal-proof', candidates: 0, proven: 0,
      unknown: 0 });
  } finally {
    observer.readToken = oldToken;
    global.fetch = oldFetch;
    console.log = oldLog;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
