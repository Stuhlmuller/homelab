const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const observer = require('../../clusters/homelab/apps/renovate/acceptance-observer.js');
const proof = require('../../clusters/homelab/apps/renovate/acceptance-pr-proof.js');
const reviewer = require('../../clusters/homelab/apps/renovate/acceptance-source-review.js');

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const uid = '12345678-1234-1234-1234-123456789abc';
const repository = 'Stuhlmuller/example';
const startedAt = '2026-10-19T00:20:00.000Z';
const completedAt = '2026-10-19T00:22:00.000Z';
const item = { repository, datasource: 'npm', packageName: 'fixture-package',
  packageFile: 'package.json', sourceVisibility: 'public',
  registryUrl: 'https://registry.npmjs.org', currentValue: '1.0.0' };
const event = { version: '1.1.0', lastAbsent: '2026-10-19T00:00:00.000Z',
  firstPresent: '2026-10-19T00:15:00.000Z', ambiguous: false };
const branch = { branchName: 'renovate/fixture-package-1.x', prNo: 42,
  result: 'done', upgrades: [{ datasource: 'npm', depName: 'fixture-package',
    packageFile: 'package.json', newVersion: '1.1.0' }] };
const pull = { number: 42, changed_files: 1, state: 'open', merged: false,
  closed_at: null, merged_at: null, created_at: '2026-10-19T00:21:00.000Z',
  user: { login: 'rstuhlmuller-renovate[bot]' },
  base: { ref: 'main', repo: { full_name: repository } },
  head: { ref: branch.branchName, sha: 'a'.repeat(40),
    repo: { full_name: repository } } };
const files = [{ filename: 'package.json',
  patch: '@@ -1 +1 @@\n-"fixture-package":"1.0.0"\n+"fixture-package":"1.1.0"' }];

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-source-review-'));
  const reports = path.join(directory, 'reports');
  const evidence = path.join(directory, 'evidence');
  fs.mkdirSync(reports, { mode: 0o700 });
  fs.mkdirSync(evidence, { mode: 0o700 });
  const provenance = [{ repository, baseBranch: 'main', headSha: 'a'.repeat(40),
    cacheSha512: 'b'.repeat(128), configHash: 'c'.repeat(128) }];
  const inventory = { schema: 1, owner: 'Stuhlmuller', seed: 'reviewed-seed-2026',
    windowStart: '2026-10-17T00:00:00.000Z',
    windowEnd: '2026-10-24T00:00:00.000Z',
    provenance: { method: 'renovate-extract', repositories: provenance,
      sha256: sha256(JSON.stringify(provenance)) },
    activeDatasources: ['npm'], dependencies: [item] };
  const ledger = observer.selectSample(inventory);
  ledger.inventory = inventory;
  ledger.sample[0].events.push(event);
  const review = { schema: 1, configSha256: 'd'.repeat(64),
    windowStart: inventory.windowStart, windowEnd: inventory.windowEnd };
  ledger.reviewSha256 = sha256(JSON.stringify(review));
  fs.writeFileSync(path.join(directory, 'ledger.json'), JSON.stringify(ledger), { mode: 0o600 });
  fs.writeFileSync(path.join(directory, 'review.json'), JSON.stringify(review), { mode: 0o600 });
  const report = { problems: [], repositories: { [repository]: { branches: [branch] } } };
  const reportBytes = Buffer.from(JSON.stringify(report));
  const reportReceipt = { schema: 1, podUid: uid,
    image: 'harbor.stinkyboi.com/mirror/ghcr.io/renovatebot/renovate:44.167.4@sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d',
    policySha256: review.configSha256, startedAt, completedAt,
    report: { file: `${uid}.json`, sha256: sha256(reportBytes), bytes: reportBytes.length,
      modifiedAt: completedAt } };
  fs.writeFileSync(path.join(reports, `${uid}.json`), reportBytes, { mode: 0o600 });
  fs.writeFileSync(path.join(reports, `${uid}.receipt.json`), JSON.stringify(reportReceipt), { mode: 0o600 });
  const sampled = ledger.sample[0];
  const match = proof.candidate(sampled, event, [{ receipt: reportReceipt, report }]);
  const snapshot = { before: proof.pullSnapshot(pull), after: proof.pullSnapshot(pull), files };
  const proposal = proof.proposalProof(sampled, event, match, snapshot.after,
    snapshot.files, '2026-10-19T00:30:00.000Z', 'main', snapshot);
  function save(kind, claim, material) {
    const name = `${kind}-${crypto.randomUUID()}.json`;
    const envelope = { schema: 1, key: sampled.key, version: event.version,
      kind, claim, material };
    const bytes = Buffer.from(JSON.stringify(envelope));
    fs.writeFileSync(path.join(evidence, name), bytes, { mode: 0o600 });
    return { ...claim, source: `evidence/${name}`, sha256: sha256(bytes) };
  }
  const eligibility = save('eligibility',
    { status: 'eligible', verifiedAt: completedAt },
    { provenance: 'renovate-full-dry-run-v1', repository,
      packageFile: item.packageFile, reportPodUid: uid,
      reportSha256: reportReceipt.report.sha256, reportCompletedAt: completedAt,
      branches: [branch] });
  const outcome = save('outcome', proposal.claim, proposal.material);
  const outcomes = { schema: 1, inventorySha256: ledger.inventorySha256,
    receipts: [{ key: sampled.key, version: event.version, eligibility, outcome }] };
  fs.writeFileSync(path.join(directory, 'outcomes.json'), JSON.stringify(outcomes), { mode: 0o600 });
  return { directory, ledger, outcomes, reportReceipt, report, review };
}

test('replays a sealed report and exact GitHub snapshot without leaking source names', () => {
  const data = fixture();
  try {
    const result = reviewer.sourceReview(data.directory);
    assert.equal(result.sourceLinks, 2);
    assert.equal(result.manualReviewItems, 0);
    assert.equal(result.humanReviewRequired, true);
    assert.equal(result.status, 'inconclusive'); // Seven healthy days are not in this fixture.
    assert.doesNotMatch(JSON.stringify(result), /Stuhlmuller\/example|fixture-package|1\.1\.0/);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('changed policy hash, report branch, or PR head fails closed', () => {
  const data = fixture();
  try {
    const receiptPath = path.join(data.directory, 'reports', `${uid}.receipt.json`);
    const original = fs.readFileSync(receiptPath);
    fs.writeFileSync(receiptPath, JSON.stringify({ ...data.reportReceipt,
      policySha256: 'e'.repeat(64) }));
    assert.throws(() => reviewer.sourceReview(data.directory), /policy-changed/);
    fs.writeFileSync(receiptPath, original);
    const outcome = data.outcomes.receipts[0].outcome;
    const source = path.join(data.directory, outcome.source);
    const envelope = JSON.parse(fs.readFileSync(source));
    envelope.material.github.after.head.sha = 'f'.repeat(40);
    const bytes = Buffer.from(JSON.stringify(envelope));
    fs.writeFileSync(source, bytes);
    data.outcomes.receipts[0].outcome.sha256 = sha256(bytes);
    fs.writeFileSync(path.join(data.directory, 'outcomes.json'), JSON.stringify(data.outcomes));
    assert.throws(() => reviewer.sourceReview(data.directory), /proposal-snapshot-invalid/);
    const altered = { problems: [], repositories: { [repository]: { branches: [{
      ...branch, result: 'not-scheduled', prNo: null }] } } };
    const reportBytes = Buffer.from(JSON.stringify(altered));
    fs.writeFileSync(path.join(data.directory, 'reports', `${uid}.json`), reportBytes);
    fs.writeFileSync(receiptPath, JSON.stringify({ ...data.reportReceipt,
      report: { ...data.reportReceipt.report, bytes: reportBytes.length,
        sha256: sha256(reportBytes) } }));
    assert.throws(() => reviewer.sourceReview(data.directory), /report-link-mismatch/);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('source replay rejects a review window different from the frozen ledger', () => {
  const data = fixture();
  try {
    const reviewPath = path.join(data.directory, 'review.json');
    const ledgerPath = path.join(data.directory, 'ledger.json');
    const review = JSON.parse(fs.readFileSync(reviewPath));
    const ledger = JSON.parse(fs.readFileSync(ledgerPath));
    review.windowStart = '2026-10-17T01:00:00.000Z';
    review.windowEnd = '2026-10-24T01:00:00.000Z';
    ledger.reviewSha256 = sha256(JSON.stringify(review));
    fs.writeFileSync(reviewPath, JSON.stringify(review));
    fs.writeFileSync(ledgerPath, JSON.stringify(ledger));
    assert.throws(() => reviewer.sourceReview(data.directory), /policy-review-invalid/);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('review Job is dormant, private, and credential-free', () => {
  const root = path.resolve(__dirname, '../../clusters/homelab/apps/renovate');
  const job = fs.readFileSync(path.join(root, 'acceptance-source-review-job.yaml'), 'utf8');
  const policy = fs.readFileSync(path.join(root, 'acceptance-source-review-networkpolicy.yaml'), 'utf8');
  const kust = fs.readFileSync(path.join(root, 'kustomization.yaml'), 'utf8');
  assert.match(job, /^  suspend: true$/m);
  assert.match(job, /automountServiceAccountToken: false/);
  assert.match(job, /claimName: renovate-acceptance-ledger/);
  assert.match(job, /readOnly: true/);
  assert.doesNotMatch(job, /secretName:|claimName: renovate-cache/);
  assert.doesNotMatch(kust, /- acceptance-source-review-job.yaml/);
  assert.match(kust, /- acceptance-source-review-networkpolicy.yaml/);
  assert.doesNotMatch(job, /^kind: NetworkPolicy$/m);
  assert.match(policy, /app\.kubernetes\.io\/component: acceptance-source-review/);
  assert.match(policy, /policyTypes: \[Ingress, Egress\]/);
  assert.match(policy, /^  ingress: \[\]$/m);
  assert.match(policy, /^  egress: \[\]$/m);
  assert.match(kust, /- acceptance-source-review.js/);
});
