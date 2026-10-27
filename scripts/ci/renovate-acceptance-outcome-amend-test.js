const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const observer = require('../../clusters/homelab/apps/renovate/acceptance-observer.js');
const amend = require('../../clusters/homelab/apps/renovate/acceptance-outcome-amend.js');

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const event = { version: '1.1.0', lastAbsent: '2026-10-19T00:00:00.000Z',
  firstPresent: '2026-10-19T00:15:00.000Z', ambiguous: false };

function fixture(status = 'policy-ineligible') {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-outcome-amend-'));
  const item = { repository: 'Stuhlmuller/example', datasource: 'npm',
    packageName: 'fixture-package', packageFile: 'package.json',
    sourceVisibility: 'public', registryUrl: 'https://registry.npmjs.org',
    currentValue: '1.0.0' };
  const provenance = [{ repository: item.repository, baseBranch: 'main',
    headSha: 'a'.repeat(40), cacheSha512: 'b'.repeat(128), configHash: 'c'.repeat(128) }];
  const inventory = { schema: 1, owner: 'Stuhlmuller', seed: 'reviewed-seed-2026',
    windowStart: '2026-10-17T00:00:00.000Z', windowEnd: '2026-10-24T00:00:00.000Z',
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
  const record = { privatePolicyOrIncident: 'reviewed fixture source' };
  const source = { ref: 'private://acceptance/fixture', observedAt: '2026-10-19T01:10:00.000Z',
    sha256: sha256(JSON.stringify(record)), record };
  const classification = { key: ledger.sample[0].key, version: event.version,
    lastAbsent: event.lastAbsent, firstPresent: event.firstPresent,
    eligibility: { status, verifiedAt: '2026-10-19T01:10:00.000Z' }, source };
  if (status === 'policy-ineligible') classification.eligibility.reason = 'reviewed policy';
  else classification.exclusion = { reason: 'source-outage',
    startAt: '2026-10-19T00:30:00.000Z', endAt: '2026-10-19T01:00:00.000Z',
    affectedAt: '2026-10-19T00:45:00.000Z', impact: 'scheduled lookup unavailable',
    verifiedAt: '2026-10-19T01:10:00.000Z' };
  const input = { schema: 1, owner: 'Stuhlmuller',
    inventorySha256: ledger.inventorySha256, reviewSha256: ledger.reviewSha256,
    configSha256: review.configSha256,
    windowStart: ledger.windowStart, windowEnd: ledger.windowEnd,
    classifications: [classification] };
  const inputFile = path.join(directory, 'input.json');
  fs.writeFileSync(inputFile, JSON.stringify(input), { mode: 0o600 });
  return { directory, ledger, review, input, inputFile };
}

function run(data) {
  fs.writeFileSync(data.inputFile, JSON.stringify(data.input));
  return amend.amend(data.directory, data.inputFile);
}

test('read-only preflight checks exact input without creating outcomes or evidence', () => {
  const data = fixture('excluded-outage');
  try {
    const before = fs.readdirSync(data.directory).sort();
    const ledger = fs.readFileSync(path.join(data.directory, 'ledger.json'));
    assert.deepEqual(amend.amend(data.directory, data.inputFile, true),
      { mode: 'outcome-amend-check', valid: true, prospective: 1, unchanged: 0 });
    assert.deepEqual(fs.readdirSync(data.directory).sort(), before);
    assert.deepEqual(fs.readFileSync(path.join(data.directory, 'ledger.json')), ledger);
    data.input.classifications[0].firstPresent = '2026-10-19T01:00:00.000Z';
    fs.writeFileSync(data.inputFile, JSON.stringify(data.input));
    assert.throws(() => amend.amend(data.directory, data.inputFile, true),
      /invalid-classification/);
    assert.deepEqual(fs.readdirSync(data.directory).sort(), before);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

for (const status of ['policy-ineligible', 'excluded-outage']) {
  test(`writes bounded ${status} evidence and replays exact input without another write`, () => {
    const data = fixture(status);
    try {
      assert.deepEqual(run(data), { mode: 'outcome-amend', applied: 1, unchanged: 0 });
      const outcomesPath = path.join(data.directory, 'outcomes.json');
      const first = fs.readFileSync(outcomesPath);
      const outcomes = JSON.parse(first);
      const receipt = outcomes.receipts[0];
      const verified = observer.verifyPrivateEvidence(outcomes, data.directory);
      assert.equal(verified.size, status === 'excluded-outage' ? 2 : 1);
      assert.equal(observer.classifyReceipt(receipt, event, verified).kind, status);
      for (const value of [receipt.eligibility, receipt.exclusion].filter(Boolean)) {
        const file = path.join(data.directory, value.source);
        assert.equal(fs.statSync(file).mode & 0o077, 0);
        const material = JSON.parse(fs.readFileSync(file)).material;
        assert.equal(material.inventorySha256, data.ledger.inventorySha256);
        assert.equal(material.reviewSha256, data.ledger.reviewSha256);
        assert.equal(material.configSha256, data.review.configSha256);
        assert.equal(material.lastAbsent, event.lastAbsent);
        assert.equal(material.firstPresent, event.firstPresent);
      }
      assert.deepEqual(run(data), { mode: 'outcome-amend', applied: 0, unchanged: 1 });
      assert.deepEqual(fs.readFileSync(outcomesPath), first);
    } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
  });
}

test('replaces only a bare unknown placeholder and refuses existing eligible evidence', () => {
  const data = fixture();
  try {
    const outcomesPath = path.join(data.directory, 'outcomes.json');
    const unknown = { schema: 1, inventorySha256: data.ledger.inventorySha256,
      receipts: [{ key: data.input.classifications[0].key, version: event.version,
        eligibility: { status: 'unknown' } }] };
    fs.writeFileSync(outcomesPath, JSON.stringify(unknown), { mode: 0o600 });
    assert.equal(run(data).applied, 1);
    const after = fs.readFileSync(outcomesPath);
    data.input.classifications[0].eligibility.reason = 'changed policy';
    assert.throws(() => run(data), /classification-conflict/);
    assert.deepEqual(fs.readFileSync(outcomesPath), after);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('rejects unknown events, duplicate entries and unbound source material', () => {
  const data = fixture();
  try {
    data.input.classifications[0].version = '9.9.9';
    assert.throws(() => run(data), /unknown-or-boundary-event/);
    data.input.classifications[0].version = event.version;
    data.input.classifications[0].lastAbsent = '2026-10-18T00:00:00.000Z';
    assert.throws(() => run(data), /invalid-classification/);
    data.input.classifications[0].lastAbsent = event.lastAbsent;
    data.input.classifications.push(structuredClone(data.input.classifications[0]));
    assert.throws(() => run(data), /duplicate-classification/);
    data.input.classifications.pop();
    data.input.classifications[0].source.sha256 = 'f'.repeat(64);
    assert.throws(() => run(data), /invalid-reviewed-source/);
    data.input.classifications[0].source.sha256 = sha256(JSON.stringify(
      data.input.classifications[0].source.record));
    data.input.classifications[0].source.observedAt = '2026-10-19T02:00:00.000Z';
    assert.throws(() => run(data), /invalid-reviewed-source/);
    data.input.classifications[0].source.observedAt = '2026-10-19T01:10:00';
    assert.throws(() => run(data), /invalid-reviewed-source/);
    assert.equal(fs.existsSync(path.join(data.directory, 'outcomes.json')), false);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('rejects invalid outage interval and relaxed private file permissions', () => {
  const data = fixture('excluded-outage');
  try {
    data.input.classifications[0].exclusion.affectedAt = '2026-10-19T05:00:00.000Z';
    assert.throws(() => run(data), /invalid-classification-evidence/);
    data.input.classifications[0].exclusion.affectedAt = '2026-10-19T00:45:00';
    assert.throws(() => run(data), /invalid-exclusion/);
    data.input.classifications[0].exclusion.affectedAt = '2026-10-19T00:45:00.000Z';
    fs.chmodSync(data.inputFile, 0o644);
    assert.throws(() => run(data), /invalid-review-input/);
    fs.chmodSync(data.inputFile, 0o600);
    fs.chmodSync(path.join(data.directory, 'review.json'), 0o644);
    assert.throws(() => run(data), /invalid-private-file/);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('refuses to carry an existing receipt with missing private evidence', () => {
  const data = fixture();
  try {
    run(data);
    const outcomes = JSON.parse(fs.readFileSync(path.join(data.directory, 'outcomes.json')));
    fs.unlinkSync(path.join(data.directory, outcomes.receipts[0].eligibility.source));
    assert.throws(() => run(data), /invalid-existing-evidence/);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('preserves an eligible receipt and refuses a manual classification over it', () => {
  const data = fixture();
  try {
    const folder = path.join(data.directory, 'evidence');
    fs.mkdirSync(folder, { mode: 0o700 });
    const entry = data.input.classifications[0];
    const claim = { status: 'eligible', verifiedAt: entry.eligibility.verifiedAt };
    const bytes = Buffer.from(JSON.stringify({ schema: 1, key: entry.key,
      version: entry.version, kind: 'eligibility', claim, material: { source: 'fixture' } }));
    fs.writeFileSync(path.join(folder, 'eligibility-fixture.json'), bytes, { mode: 0o600 });
    const outcomes = { schema: 1, inventorySha256: data.ledger.inventorySha256,
      receipts: [{ key: entry.key, version: entry.version,
        eligibility: { ...claim, source: 'evidence/eligibility-fixture.json',
          sha256: sha256(bytes) } }] };
    const target = path.join(data.directory, 'outcomes.json');
    fs.writeFileSync(target, JSON.stringify(outcomes), { mode: 0o600 });
    const before = fs.readFileSync(target);
    assert.throws(() => run(data), /classification-conflict/);
    assert.deepEqual(fs.readFileSync(target), before);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('resumes after evidence write before outcomes rename', () => {
  const data = fixture('excluded-outage');
  try {
    const folder = path.join(data.directory, 'evidence');
    fs.mkdirSync(folder, { mode: 0o700 });
    const candidate = amend.buildReceipt(data.input.classifications[0], event,
      data.ledger, data.review, data.directory);
    fs.writeFileSync(candidate.files[0].file, candidate.files[0].bytes,
      { mode: 0o600 });
    assert.equal(run(data).applied, 1);
    assert.equal(run(data).unchanged, 1);
    assert.equal(observer.verifyPrivateEvidence(JSON.parse(fs.readFileSync(
      path.join(data.directory, 'outcomes.json'))), data.directory).size, 2);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('a crashed partial temporary evidence write replays; a corrupt final file fails closed', () => {
  const data = fixture();
  try {
    fs.mkdirSync(path.join(data.directory, 'evidence'), { mode: 0o700 });
    const candidate = amend.buildReceipt(data.input.classifications[0], event,
      data.ledger, data.review, data.directory);
    const file = candidate.files[0];
    fs.writeFileSync(`${file.file}.aborted.tmp`, file.bytes.subarray(0, 12), { mode: 0o600 });
    assert.equal(run(data).applied, 1);
    assert.deepEqual(fs.readFileSync(file.file), file.bytes);
    fs.unlinkSync(path.join(data.directory, 'outcomes.json'));
    fs.writeFileSync(file.file, file.bytes.subarray(0, 12));
    assert.throws(() => run(data), /evidence-conflict/);
    assert.equal(fs.existsSync(path.join(data.directory, 'outcomes.json')), false);
  } finally { fs.rmSync(data.directory, { recursive: true, force: true }); }
});

test('rejects extra fields, wrong review hash and a Secret symlink escaping its mount', () => {
  const data = fixture();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-review-outside-'));
  try {
    data.input.classifications[0].unreviewed = true;
    assert.throws(() => run(data), /invalid-classification/);
    delete data.input.classifications[0].unreviewed;
    data.input.reviewSha256 = 'f'.repeat(64);
    assert.throws(() => run(data), /invalid-review-input/);
    data.input.reviewSha256 = data.ledger.reviewSha256;
    const external = path.join(outside, 'review.json');
    fs.writeFileSync(external, JSON.stringify(data.input), { mode: 0o600 });
    const link = path.join(data.directory, 'linked.json');
    fs.symlinkSync(external, link);
    assert.throws(() => amend.amend(data.directory, link), /invalid-review-input/);
  } finally {
    fs.rmSync(data.directory, { recursive: true, force: true });
    fs.rmSync(outside, { recursive: true, force: true });
  }
});

test('staged Jobs remain suspended and credential-free; policy is only desired state', () => {
  const root = path.resolve(__dirname, '../../clusters/homelab/apps/renovate');
  const job = fs.readFileSync(path.join(root, 'acceptance-outcome-amend-job.yaml'), 'utf8');
  const preflight = fs.readFileSync(path.join(root,
    'acceptance-outcome-preflight-job.yaml'), 'utf8');
  const policy = fs.readFileSync(path.join(root, 'acceptance-outcome-amend-networkpolicy.yaml'), 'utf8');
  const kust = fs.readFileSync(path.join(root, 'kustomization.yaml'), 'utf8');
  for (const manifest of [job, preflight]) {
    assert.match(manifest, /^  suspend: true$/m);
    assert.match(manifest, /automountServiceAccountToken: false/);
    assert.match(manifest, /secretName: renovate-acceptance-outcome-review/);
    assert.match(manifest, /claimName: renovate-acceptance-ledger/);
    assert.doesNotMatch(manifest,
      /secretName: renovate-acceptance\s*$|claimName: renovate-cache/m);
    assert.match(manifest, /app\.kubernetes\.io\/component: acceptance-outcome-amend/);
  }
  assert.match(preflight, /--check-only/);
  assert.match(preflight, /mountPath: \/ledger\n\s+readOnly: true/);
  assert.match(preflight,
    /persistentVolumeClaim:\n\s+claimName: renovate-acceptance-ledger\n\s+readOnly: true/);
  assert.doesNotMatch(preflight, /fsGroup:/);
  assert.doesNotMatch(kust, /- acceptance-outcome-amend-job.yaml/);
  assert.doesNotMatch(kust, /- acceptance-outcome-preflight-job.yaml/);
  assert.match(kust, /- acceptance-outcome-amend-networkpolicy.yaml/);
  assert.match(kust, /- acceptance-outcome-amend.js/);
  assert.match(policy, /app\.kubernetes\.io\/component: acceptance-outcome-amend/);
  assert.match(policy, /policyTypes: \[Ingress, Egress\]/);
  assert.match(policy, /^  egress: \[\]$/m);
});
