const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const crypto = require('node:crypto');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const observer = require('../../clusters/homelab/apps/renovate/acceptance-observer.js');

const proof = (name) => ({ source: `evidence/${name}.json`, sha256: 'a'.repeat(64) });
const dependency = (datasource, sourceVisibility, packageName) => ({
  repository: 'Stuhlmuller/example',
  datasource,
  sourceVisibility,
  packageName,
  packageFile: 'package.json',
  registryUrl: datasource === 'npm' ? 'https://registry.example.com' : 'https://api.github.com',
});

function inventory() {
  const repositories = [{ repository: 'Stuhlmuller/example', baseBranch: 'main',
    headSha: 'a'.repeat(40), cacheSha512: 'b'.repeat(128), configHash: 'c'.repeat(128) }];
  return {
    schema: 1,
    owner: 'Stuhlmuller',
    seed: 'natural-2026-10-18',
    windowStart: '2026-10-17T00:00:00.000Z',
    windowEnd: '2026-10-24T00:00:00.000Z',
    provenance: { method: 'renovate-extract', repositories,
      sha256: crypto.createHash('sha256').update(JSON.stringify(repositories)).digest('hex') },
    activeDatasources: ['npm', 'github-releases'],
    dependencies: [
      dependency('npm', 'public', 'lodash'),
      dependency('npm', 'private', '@example/private'),
      dependency('github-releases', 'public', 'example/tool'),
      { ...dependency('github-releases', 'public', 'Stuhlmuller/renovate'),
        packageFile: 'scripts/fixtures/renovate-cache-canary.txt' },
    ],
  };
}

function fixtureReport(ledger, receipts) {
  // Unit fixtures mark source references present; the file-verification test covers real proof checks.
  const evidence = new Set();
  for (const receipt of receipts.receipts) {
    for (const kind of ['eligibility', 'outcome', 'exclusion']) {
      const field = receipt[kind];
      if (field) evidence.add(JSON.stringify([
        receipt.key, receipt.version, kind, field.source, field.sha256]));
    }
  }
  return observer.aggregateReport(ledger, receipts, evidence);
}

function completeWindow(ledger) {
  const start = Date.parse(ledger.windowStart);
  for (let index = 0; index <= 7 * 24 * 4; index++) {
    const slotAt = new Date(start + index * 900000).toISOString();
    ledger.polls.push({ at: slotAt, startedAt: slotAt, slotAt, late: false,
      healthy: ledger.sample.length, failed: 0, events: 0 });
  }
}

function observedReleases() {
  const ledger = observer.selectSample(inventory());
  completeWindow(ledger);
  const receipts = { schema: 1, inventorySha256: ledger.inventorySha256, receipts: [] };
  const start = Date.parse('2026-10-18T00:00:00.000Z');
  for (let index = 0; index < 10; index++) {
    const item = ledger.sample[index % ledger.sample.length];
    const absent = start + index * 3600_000;
    const version = `private-version-${index}`;
    item.events.push({ version, lastAbsent: new Date(absent).toISOString(),
      firstPresent: new Date(absent + 15 * 60_000).toISOString(), ambiguous: false });
    receipts.receipts.push({
      key: item.key,
      version,
      eligibility: { status: 'eligible', ...proof(`policy-${index}`),
        verifiedAt: new Date(absent + 6 * 3600_000).toISOString() },
      outcome: { kind: 'proposal', at: new Date(absent + 3 * 3600_000).toISOString(),
        ...proof(`proposal-${index}`), verifiedAt: new Date(absent + 6 * 3600_000).toISOString() },
    });
  }
  return { ledger, receipts };
}

test('CLI rejects the legacy bare-inventory seed mode', () => {
  const script = path.resolve(__dirname, '../../clusters/homelab/apps/renovate/acceptance-observer.js');
  const result = spawnSync(process.execPath, [script, 'seed'], { encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.deepEqual(JSON.parse(result.stderr.trim()), { mode: 'seed', error: 'invalid-input' });
});

test('sample freezes every class and source visibility, excluding the controlled canary', () => {
  const source = inventory();
  const first = observer.selectSample(source);
  const second = observer.selectSample(source);
  assert.deepEqual(first.sample, second.sample);
  assert.equal(first.sample.length, 3);
  assert.deepEqual(observer.aggregate(first).strata, { public: 2, private: 1 });
  const aggregate = JSON.stringify(observer.aggregate(first));
  for (const privateValue of [source.seed, 'Stuhlmuller/example', '@example/private']) {
    assert.equal(aggregate.includes(privateValue), false);
  }
  assert.equal(first.sample.some((item) => item.packageName === 'Stuhlmuller/renovate'), false);
  source.dependencies.splice(2, 1);
  assert.throws(() => observer.selectSample(source), /missing-datasource-class/);
});

test('poll and report reject a changed frozen sample while allowing observations', () => {
  const source = inventory();
  const ledger = observer.selectSample(source);
  ledger.inventory = source;
  assert.doesNotThrow(() => observer.verifyFrozenSample(ledger));
  ledger.sample[0].seen.push('observed-version-hash');
  assert.doesNotThrow(() => observer.verifyFrozenSample(ledger));
  ledger.sample.pop();
  assert.throws(() => observer.verifyFrozenSample(ledger), /sample-changed/);
  ledger.sample = observer.selectSample(source).sample;
  source.dependencies.pop();
  assert.throws(() => observer.verifyFrozenSample(ledger), /invalid-ledger/);
});

test('seed deduplicates one upstream source across repositories before freezing', () => {
  const source = inventory();
  source.activeDatasources = ['npm'];
  source.provenance.repositories = [
    { repository: 'Stuhlmuller/one', baseBranch: 'main', headSha: '1'.repeat(40),
      cacheSha512: 'a'.repeat(128), configHash: 'b'.repeat(128) },
    { repository: 'Stuhlmuller/three', baseBranch: 'main', headSha: '3'.repeat(40),
      cacheSha512: 'c'.repeat(128), configHash: 'd'.repeat(128) },
    { repository: 'Stuhlmuller/two', baseBranch: 'main', headSha: '2'.repeat(40),
      cacheSha512: 'e'.repeat(128), configHash: 'f'.repeat(128) },
  ];
  source.provenance.sha256 = crypto.createHash('sha256').update(
    JSON.stringify(source.provenance.repositories)).digest('hex');
  source.dependencies = [
    { ...dependency('npm', 'public', 'shared-package'), repository: 'Stuhlmuller/one',
      registryUrl: 'https://REGISTRY.example.com/packages/' },
    { ...dependency('npm', 'public', 'shared-package'), repository: 'Stuhlmuller/two',
      registryUrl: 'https://registry.example.com/packages' },
    { ...dependency('npm', 'private', 'shared-package'), repository: 'Stuhlmuller/three',
      registryUrl: 'https://private-registry.example.com/packages' },
  ];
  const first = observer.selectSample(source).sample;
  const reverse = observer.selectSample({ ...source, dependencies: [...source.dependencies].reverse() }).sample;
  assert.equal(first.length, 2);
  assert.deepEqual(first, reverse);
  assert.deepEqual(observer.aggregate({ ...observer.selectSample(source), sample: first }).strata,
    { public: 1, private: 1 });
  source.dependencies[2].registryUrl = 'https://registry.example.com/packages';
  assert.throws(() => observer.selectSample(source), /ambiguous-source-visibility/);
  delete source.dependencies[2].registryUrl;
  assert.throws(() => observer.selectSample(source), /invalid-registry/);
});

test('GitHub repository case variants are one upstream source', () => {
  const source = inventory();
  source.dependencies.push(dependency('github-releases', 'public', 'EXAMPLE/TOOL'));
  const sample = observer.selectSample(source).sample;
  assert.equal(sample.length, 3);
  assert.equal(sample.filter((item) => item.datasource === 'github-releases').length, 1);
});

test('report counts one independent release and requires every sampled consumer outcome', () => {
  const { ledger, receipts } = observedReleases();
  const first = ledger.sample.find((item) => item.datasource === 'github-releases');
  const duplicate = { ...first, repository: 'Stuhlmuller/second', key: 'second-consumer',
    packageName: first.packageName.toUpperCase(),
    events: first.events.map((event) => ({ ...event })) };
  ledger.sample.push(duplicate);
  for (const receipt of receipts.receipts.filter((entry) => entry.key === first.key)) {
    receipts.receipts.push({ ...receipt, key: duplicate.key });
  }
  const complete = fixtureReport(ledger, receipts);
  assert.equal(complete.bracketedEvents, 10 + first.events.length);
  assert.equal(complete.naturalEvents, 10);
  assert.equal(complete.eligibleEvents, 10);
  assert.equal(complete.onTime, 10);
  const duplicated = receipts.receipts.find((receipt) => receipt.key === duplicate.key);
  delete duplicated.outcome;
  const missing = fixtureReport(ledger, receipts);
  assert.equal(missing.naturalEvents, 10);
  assert.equal(missing.missingOutcomes, 1);
  assert.equal(missing.onTime, 9);
  assert.equal(missing.status, 'inconclusive');
  duplicated.outcome = receipts.receipts.find((receipt) => receipt.key === first.key &&
    receipt.version === duplicated.version).outcome;
  duplicated.outcome = { ...duplicated.outcome, at: new Date(
    Date.parse(first.events[0].lastAbsent) + 5 * 3600_000).toISOString() };
  const slowest = fixtureReport(ledger, receipts);
  assert.equal(slowest.late, 1);
  assert.equal(slowest.onTime, 9);
  duplicated.outcome = receipts.receipts.find((receipt) => receipt.key === first.key &&
    receipt.version === duplicated.version).outcome;
  duplicate.events[0].lastAbsent = new Date(
    Date.parse(first.events[0].firstPresent) + 60_000).toISOString();
  duplicate.events[0].firstPresent = new Date(
    Date.parse(first.events[0].firstPresent) + 120_000).toISOString();
  assert.equal(fixtureReport(ledger, receipts).status, 'inconclusive');
});

test('offline report joins exact private receipts and counts missing outcomes in the denominator', () => {
  const { ledger, receipts } = observedReleases();
  const complete = fixtureReport(ledger, receipts);
  assert.equal(complete.status, 'review-required');
  assert.equal(complete.naturalEvents, 10);
  assert.equal(complete.eligibleEvents, 10);
  assert.equal(complete.onTime, 10);
  assert.equal(complete.onTimePercent, 100);
  assert.equal(complete.window.complete, true);
  for (const privateValue of ['private-version-0', 'evidence/proposal-0.json',
    'Stuhlmuller/example', '@example/private']) {
    assert.equal(JSON.stringify(complete).includes(privateValue), false);
  }
  delete receipts.receipts[0].outcome;
  receipts.receipts[1].outcome.at = new Date(
    Date.parse(ledger.sample[1].events.find((event) => event.version === 'private-version-1').lastAbsent) +
    5 * 3600_000).toISOString();
  const incomplete = fixtureReport(ledger, receipts);
  assert.equal(incomplete.eligibleEvents, 10);
  assert.equal(incomplete.missingOutcomes, 1);
  assert.equal(incomplete.late, 1);
  assert.equal(incomplete.onTime, 8);
  assert.equal(incomplete.onTimePercent, 80);
  assert.equal(incomplete.status, 'inconclusive');
});

test('the frozen seven-day window excludes earlier and eighth-day observations', () => {
  const { ledger, receipts } = observedReleases();
  const outsidePoll = (slotAt) => ({ slotAt, startedAt: slotAt, at: slotAt,
    late: false, healthy: ledger.sample.length - 1, failed: 1, events: 1 });
  ledger.polls.unshift(outsidePoll('2026-10-16T23:45:00.000Z'));
  ledger.polls.push(outsidePoll('2026-10-24T00:15:00.000Z'));
  ledger.sample[0].events.push(
    { version: 'pre-window', lastAbsent: '2026-10-16T23:00:00.000Z',
      firstPresent: '2026-10-16T23:15:00.000Z', ambiguous: false },
    { version: 'eighth-day', lastAbsent: '2026-10-24T01:00:00.000Z',
      firstPresent: '2026-10-24T01:15:00.000Z', ambiguous: false });
  for (const version of ['pre-window', 'eighth-day']) {
    receipts.receipts.push({ ...receipts.receipts[0], key: ledger.sample[0].key, version });
  }
  const report = fixtureReport(ledger, receipts);
  assert.equal(report.status, 'review-required');
  assert.equal(report.naturalEvents, 10);
  assert.equal(report.eligibleEvents, 10);
  assert.equal(report.onTime, 10);
  assert.equal(report.polls, 673);
  assert.equal(report.failedSources, 0);
  assert.equal(report.bracketedEvents, 10);
  assert.equal(report.outsideEvents, 2);
  assert.equal(report.window.plannedHourlySlots, 168);
  assert.equal(report.window.requiredSlots, 673);
  assert.equal(report.window.complete, true);

  ledger.sample[0].events.push({ version: 'boundary-unknown',
    lastAbsent: '2026-10-16T23:45:00.000Z',
    firstPresent: '2026-10-17T00:01:00.000Z', ambiguous: false });
  const boundary = fixtureReport(ledger, receipts);
  assert.equal(boundary.boundaryEvents, 1);
  assert.equal(boundary.eligibleEvents, 10);
  assert.equal(boundary.status, 'inconclusive');
});

test('the first in-window poll establishes a fresh baseline after pre-window polls', () => {
  const ledger = observer.selectSample(inventory());
  const item = ledger.sample[0];
  const poll = (at, version) => observer.recordPoll(ledger,
    new Map([[item.key, { response: { releases: [{ version }] },
      startedAt: at, finishedAt: new Date(Date.parse(at) + 60_000).toISOString() }]]),
    new Date(Date.parse(at) + 60_000).toISOString(), at);
  poll('2026-10-16T23:45:00.000Z', '1.0.0');
  poll(ledger.windowStart, '1.1.0');
  assert.equal(item.events.length, 0);
  poll('2026-10-17T00:15:00.000Z', '1.2.0');
  assert.deepEqual(item.events.map(({ version }) => version), ['1.2.0']);
});

test('missing or mismatched frozen boundaries cannot produce a final report', () => {
  const { ledger, receipts } = observedReleases();
  ledger.inventory = inventory();
  delete ledger.windowStart;
  assert.throws(() => fixtureReport(ledger, receipts), /invalid-window/);
  ledger.windowStart = '2026-10-17T01:00:00.000Z';
  ledger.windowEnd = '2026-10-24T01:00:00.000Z';
  assert.throws(() => fixtureReport(ledger, receipts), /window-mismatch/);
  ledger.windowStart = ledger.inventory.windowStart;
  ledger.windowEnd = ledger.inventory.windowEnd;
  ledger.polls[0].slotAt = '2026-10-17T00:15:00.000Z';
  assert.throws(() => fixtureReport(ledger, receipts), /invalid-ledger-poll/);
});

test('a node-loss gap or unhealthy source cannot silently complete the seven-day window', () => {
  const { ledger, receipts } = observedReleases();
  assert.equal(fixtureReport(ledger, receipts).status, 'review-required');
  ledger.polls.splice(300, 1);
  const lostNode = fixtureReport(ledger, receipts);
  assert.equal(lostNode.window.complete, false);
  assert.equal(lostNode.status, 'inconclusive');
  ledger.polls = [];
  completeWindow(ledger);
  ledger.polls[300].failed = 1;
  ledger.polls[300].healthy--;
  assert.equal(fixtureReport(ledger, receipts).window.complete, false);
  const extraStart = Date.parse(ledger.polls.at(-1).slotAt) + 900000;
  for (let index = 0; index <= 7 * 24 * 4; index++) {
    const slotAt = new Date(extraStart + index * 900000).toISOString();
    ledger.polls.push({ at: slotAt, startedAt: slotAt, slotAt, late: false,
      healthy: ledger.sample.length, failed: 0, events: 0 });
  }
  assert.equal(fixtureReport(ledger, receipts).window.complete, false,
    'an earlier failed slot requires a reviewed ledger reset');
});

test('report stays inconclusive for low sample, ambiguity, unknown, or incomplete evidence', () => {
  const { ledger, receipts } = observedReleases();
  ledger.sample[0].events[0].ambiguous = true;
  assert.equal(fixtureReport(ledger, receipts).status, 'inconclusive');
  ledger.sample[0].events[0].ambiguous = false;
  receipts.receipts[0].eligibility.status = 'unknown';
  assert.equal(fixtureReport(ledger, receipts).unknownEvents, 1);
  assert.equal(fixtureReport(ledger, receipts).status, 'inconclusive');
  receipts.receipts[0].eligibility.status = 'eligible';
  delete receipts.receipts[0].outcome.source;
  assert.equal(fixtureReport(ledger, receipts).incompleteEvidence, 1);
  assert.equal(fixtureReport(ledger, receipts).status, 'inconclusive');
  receipts.receipts[0].outcome.source = 'evidence/proposal-0.json';
  const removed = ledger.sample[0].events.shift();
  receipts.receipts = receipts.receipts.filter((receipt) => receipt.version !== removed.version);
  assert.equal(fixtureReport(ledger, receipts).eligibleEvents, 9);
  assert.equal(fixtureReport(ledger, receipts).status, 'inconclusive');
});

test('integer threshold and floored display stay below 95 percent when unmet', () => {
  const ledger = observer.selectSample(inventory());
  completeWindow(ledger);
  const item = ledger.sample[0];
  const lastAbsent = '2026-10-18T00:00:00.000Z';
  const firstPresent = '2026-10-18T00:15:00.000Z';
  const eligibility = { status: 'eligible', ...proof('policy-bulk'),
    verifiedAt: '2026-10-18T06:00:00.000Z' };
  const onTime = { kind: 'proposal', at: '2026-10-18T03:00:00.000Z',
    ...proof('proposal-bulk'), verifiedAt: '2026-10-18T06:00:00.000Z' };
  const late = { ...onTime, at: '2026-10-18T05:00:00.000Z' };
  const receipts = { schema: 1, inventorySha256: ledger.inventorySha256, receipts: [] };
  for (let index = 0; index < 20000; index++) {
    const version = `synthetic-${index}`;
    item.events.push({ version, lastAbsent, firstPresent, ambiguous: false });
    receipts.receipts.push({ key: item.key, version, eligibility,
      outcome: index < 18999 ? onTime : late });
  }
  const below = fixtureReport(ledger, receipts);
  assert.equal(below.onTime, 18999);
  assert.equal(below.onTimePercent, 94.99);
  assert.equal(below.status, 'criteria-not-met');
  receipts.receipts[18999].outcome = onTime;
  assert.equal(fixtureReport(ledger, receipts).status, 'review-required');
});

test('report separates policy exclusion from reviewed outage interval and rejects unmatched receipts', () => {
  const { ledger, receipts } = observedReleases();
  const first = receipts.receipts[0];
  first.eligibility = { status: 'policy-ineligible', reason: 'private policy receipt',
    ...proof('policy-ineligible'), verifiedAt: first.outcome.verifiedAt };
  delete first.outcome;
  const second = receipts.receipts[1];
  const absent = ledger.sample[1].events.find((event) => event.version === second.version).lastAbsent;
  second.eligibility.status = 'excluded-outage';
  second.exclusion = { reason: 'source-outage', startAt: absent,
    endAt: new Date(Date.parse(absent) + 3600_000).toISOString(),
    ...proof('outage'),
    verifiedAt: new Date(Date.parse(absent) + 2 * 3600_000).toISOString() };
  delete second.outcome;
  const unrelated = fixtureReport(ledger, receipts);
  assert.equal(unrelated.excludedIntervals, 0);
  assert.equal(unrelated.incompleteEvidence, 1);
  second.exclusion.affectedAt = new Date(Date.parse(absent) + 30 * 60_000).toISOString();
  second.exclusion.impact = 'scheduled source lookup failed';
  const report = fixtureReport(ledger, receipts);
  assert.equal(report.policyIneligible, 1);
  assert.equal(report.excludedIntervals, 1);
  assert.equal(report.eligibleEvents, 8);
  assert.equal(report.status, 'inconclusive');
  second.exclusion.affectedAt = new Date(Date.parse(absent) + 2 * 3600_000).toISOString();
  assert.equal(fixtureReport(ledger, receipts).excludedIntervals, 0);
  second.exclusion.affectedAt = new Date(Date.parse(absent) + 30 * 60_000).toISOString();
  second.exclusion.impact = '';
  assert.equal(fixtureReport(ledger, receipts).excludedIntervals, 0);
  second.exclusion.impact = 'scheduled source lookup failed';
  receipts.receipts.push({ ...receipts.receipts[2], key: 'unknown-private-key' });
  assert.throws(() => fixtureReport(ledger, receipts), /invalid-outcomes/);
  receipts.receipts.pop();
  receipts.receipts[2].version = 'unknown-private-version';
  assert.throws(() => fixtureReport(ledger, receipts), /invalid-outcomes/);
});

test('report refuses a readable-by-others private outcomes file', () => {
  const originalLstat = fs.lstatSync;
  const originalRead = fs.readFileSync;
  fs.lstatSync = () => ({ isFile: () => true, mode: 0o100644 });
  fs.readFileSync = () => { throw new Error('private receipt should not be read'); };
  try {
    assert.throws(() => observer.readPrivateOutcomes(), /invalid-outcomes-permissions/);
  } finally {
    fs.lstatSync = originalLstat;
    fs.readFileSync = originalRead;
  }
});

test('private evidence must be exact, private, and bound to the receipt claim', () => {
  const { ledger, receipts } = observedReleases();
  assert.equal(observer.aggregateReport(ledger, receipts).status, 'inconclusive');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-evidence-'));
  const directory = path.join(temporary, 'evidence');
  fs.mkdirSync(directory, { mode: 0o700 });
  try {
    const receipt = receipts.receipts[0];
    for (const kind of ['eligibility', 'outcome']) {
      const field = receipt[kind];
      const { source, sha256, ...claim } = field;
      const bytes = Buffer.from(JSON.stringify({ schema: 1, key: receipt.key,
        version: receipt.version, kind, claim, material: { reviewedSource: 'private source' } }));
      field.sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
      fs.writeFileSync(path.join(temporary, source), bytes, { mode: 0o600 });
    }
    const evidence = observer.verifyPrivateEvidence(receipts, temporary);
    assert.equal(evidence.size, 2);
    const report = observer.aggregateReport(ledger, receipts, evidence);
    assert.equal(report.incompleteEvidence, 9);
    assert.equal(report.status, 'inconclusive');
    fs.appendFileSync(path.join(temporary, receipt.outcome.source), '\n');
    const changed = observer.aggregateReport(ledger, receipts,
      observer.verifyPrivateEvidence(receipts, temporary));
    assert.equal(changed.incompleteEvidence, 10);
    fs.chmodSync(path.join(temporary, receipt.eligibility.source), 0o644);
    assert.throws(() => observer.verifyPrivateEvidence(receipts, temporary),
      /invalid-evidence-permissions/);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('only healthy upstream polls advance last-absent brackets', () => {
  const ledger = observer.selectSample(inventory());
  const item = ledger.sample[0];
  const baselineStart = '2026-10-18T00:00:00.000Z';
  const baselineEnd = '2026-10-18T00:02:00.000Z';
  const failedAt = '2026-10-18T00:15:00.000Z';
  const firstStart = '2026-10-18T00:30:00.000Z';
  const firstEnd = '2026-10-18T00:32:00.000Z';
  const result = (versions, startedAt, finishedAt = startedAt) =>
    new Map([[item.key, { response: { releases: versions.map((version) => ({ version })) },
      startedAt, finishedAt }]]);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0'], baselineStart, baselineEnd), baselineEnd).failed, 2);
  assert.equal(observer.recordPoll(ledger, new Map(), failedAt).failed, 3);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0', '1.1.0'], firstStart, firstEnd), firstEnd).events, 1);
  assert.deepEqual(item.failures, [{ at: failedAt, status: 'missing-observation' }]);
  assert.deepEqual(item.events, [{ version: '1.1.0', lastAbsent: baselineStart,
    firstPresent: firstEnd, ambiguous: true }]);
  assert.equal(observer.aggregate(ledger).bracketedEvents, 1);
  assert.equal(observer.aggregate(ledger).ambiguousEvents, 1);
  const absent = '2026-10-18T00:45:00.000Z';
  const present = '2026-10-18T01:00:00.000Z';
  observer.recordPoll(ledger, result(['1.0.0'], absent), absent);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0', '1.1.0'], present), present).events, 0);
  assert.equal(item.events.length, 1);
});

test('a healthy empty release list establishes the first last-absent bound', () => {
  const ledger = observer.selectSample(inventory());
  const item = ledger.sample[0];
  const absent = '2026-10-18T00:00:00.000Z';
  const present = '2026-10-18T00:15:00.000Z';
  const result = (versions, at) => new Map([[item.key, {
    response: { releases: versions.map((version) => ({ version })) },
    startedAt: at, finishedAt: new Date(Date.parse(at) + 60_000).toISOString(),
  }]]);
  assert.equal(observer.recordPoll(ledger, result([], absent), absent).healthy, 1);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0'], present), present).events, 1);
  assert.deepEqual(item.events, [{ version: '1.0.0', lastAbsent: absent,
    firstPresent: '2026-10-18T00:16:00.000Z', ambiguous: false }]);
});

test('missed and late observer slots make release timing ambiguous', () => {
  const source = inventory();
  const baseline = (ledger, cycle, version = '1.0.0') => {
    const item = ledger.sample[0];
    const finished = new Date(Date.parse(cycle) + 60_000).toISOString();
    observer.recordPoll(ledger, new Map([[item.key, {
      response: { releases: [{ version }] }, startedAt: cycle, finishedAt: finished,
    }]]), finished, cycle);
    return item;
  };
  const missed = observer.selectSample(source);
  const missedItem = baseline(missed, '2026-10-18T00:00:00.000Z');
  baseline(missed, '2026-10-18T00:30:00.000Z', '1.1.0');
  assert.equal(missedItem.events[0].ambiguous, true);
  assert.equal(observer.aggregate(missed).missedPolls, 671);

  const late = observer.selectSample(source);
  const lateItem = baseline(late, '2026-10-18T00:06:00.000Z');
  baseline(late, '2026-10-18T00:15:00.000Z', '1.1.0');
  assert.equal(lateItem.events[0].ambiguous, true);
  assert.equal(observer.aggregate(late).latePolls, 1);

  const healthy = observer.selectSample(source);
  const healthyItem = baseline(healthy, '2026-10-18T00:00:00.000Z');
  baseline(healthy, '2026-10-18T00:15:00.000Z', '1.1.0');
  assert.equal(healthyItem.events[0].ambiguous, false);
  assert.equal(observer.aggregate(healthy).missedPolls, 671);
});

test('global poll failure persists private failed observations and exits nonzero', async () => {
  const ledger = observer.selectSample(inventory());
  const originalRead = fs.readFileSync;
  const originalWrite = fs.writeFileSync;
  const originalRename = fs.renameSync;
  const originalLog = console.log;
  const originalExitCode = process.exitCode;
  const writes = [];
  const logs = [];
  fs.readFileSync = (file, ...args) => {
    if (file === '/var/run/secrets/renovate-acceptance/issuer-id') throw new Error('private failure');
    return originalRead(file, ...args);
  };
  fs.writeFileSync = (file, data) => writes.push({ file, data });
  fs.renameSync = (source, target) => writes.push({ source, target });
  console.log = (line) => logs.push(line);
  try {
    await observer.poll(ledger);
    assert.equal(ledger.polls[0].failed, ledger.sample.length);
    assert.equal(ledger.polls[0].healthy, 0);
    assert.equal(ledger.sample.every((item) => item.failures[0].status === 'global-error'), true);
    assert.equal(writes.length, 2);
    assert.equal(process.exitCode, 1);
    assert.match(JSON.parse(logs.at(-1)).ledgerSha256, /^[0-9a-f]{64}$/);
    assert.equal(JSON.stringify(logs).includes('private failure'), false);
    assert.equal(JSON.stringify(logs).includes('@example/private'), false);
  } finally {
    fs.readFileSync = originalRead;
    fs.writeFileSync = originalWrite;
    fs.renameSync = originalRename;
    console.log = originalLog;
    process.exitCode = originalExitCode;
  }
});

test('observer requests only read-scoped GitHub App permissions', async () => {
  const { privateKey } = crypto.generateKeyPairSync('rsa', {
    modulusLength: 2048,
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    publicKeyEncoding: { type: 'spki', format: 'pem' },
  });
  const originalRead = fs.readFileSync;
  const originalFetch = global.fetch;
  const calls = [];
  const reads = [];
  let installationContents = 'read';
  fs.readFileSync = (file, ...args) => {
    reads.push(file);
    return file.endsWith('/issuer-id') ? '123' :
      file.endsWith('/private-key') ? privateKey : originalRead(file, ...args);
  };
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => url.endsWith('/installation') ?
        { id: 42, account: { login: 'Stuhlmuller' }, repository_selection: 'all',
          permissions: { contents: installationContents, metadata: 'read', pull_requests: 'read' } } :
        { token: 'ghs_readonly', expires_at: new Date(Date.now() + 3600_000).toISOString(),
          permissions: JSON.parse(calls.at(-1).options.body).permissions },
    };
  };
  try {
    assert.equal(await observer.readToken(), 'ghs_readonly');
    assert.equal(calls[0].options.method, 'GET');
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(calls[1].url.endsWith('/access_tokens'), true);
    assert.deepEqual(JSON.parse(calls[1].options.body).permissions,
      { contents: 'read', metadata: 'read' });
    const expanded = { contents: 'read', metadata: 'read', pull_requests: 'read' };
    assert.equal(await observer.readToken(expanded), 'ghs_readonly');
    assert.deepEqual(JSON.parse(calls[3].options.body).permissions, expanded);
    assert.deepEqual(new Set(reads), new Set([
      '/var/run/secrets/renovate-acceptance/issuer-id',
      '/var/run/secrets/renovate-acceptance/private-key',
    ]));
    installationContents = 'write';
    await assert.rejects(observer.readToken(), /installation-not-read-only/);
    await assert.rejects(observer.readToken({ contents: 'write' }), /read-token-permissions/);
  } finally {
    fs.readFileSync = originalRead;
    global.fetch = originalFetch;
  }
});

test('private acceptance data binds only to initialized acer-local storage', () => {
  const root = path.resolve(__dirname, '../../clusters/homelab/apps/renovate');
  const platform = path.resolve(__dirname, '../../clusters/homelab/platform/storage');
  const storage = fs.readFileSync(path.join(root, 'acceptance-ledger-pvc.yaml'), 'utf8');
  const platformStorage = fs.readFileSync(path.join(platform,
    'renovate-acceptance-ledger-platform.yaml'), 'utf8');
  const platformKustomization = fs.readFileSync(path.join(platform, 'kustomization.yaml'), 'utf8');
  const initializer = fs.readFileSync(path.join(root, 'acceptance-ledger-init-job.yaml'), 'utf8');
  const runner = fs.readFileSync(path.join(root, 'cronjob.yaml'), 'utf8');
  const kustomization = fs.readFileSync(path.join(root, 'kustomization.yaml'), 'utf8');
  assert.match(storage, /storageClassName: renovate-acceptance-ledger-local/);
  assert.match(storage, /^kind: PersistentVolumeClaim$/m);
  assert.doesNotMatch(storage, /^kind: (StorageClass|PersistentVolume)$/m);
  assert.match(platformStorage, /^kind: StorageClass$/m);
  assert.match(platformStorage, /^kind: PersistentVolume$/m);
  assert.doesNotMatch(platformStorage, /^kind: PersistentVolumeClaim$/m);
  assert.match(platformStorage, /path: \/var\/lib\/renovate-acceptance-ledger/);
  assert.match(platformStorage, /values:\s*\n\s*- acer/);
  assert.doesNotMatch(storage, /nfs-default/);
  assert.doesNotMatch(kustomization, /- acceptance-ledger-pvc.yaml/);
  assert.match(platformKustomization, /- renovate-acceptance-ledger-platform.yaml/);
  assert.match(initializer, /^  suspend: true$/m);
  assert.match(initializer, /chown 12021:12021 \/ledger/);
  assert.match(initializer, /chmod 0700 \/ledger/);
  assert.doesNotMatch(kustomization, /- acceptance-ledger-init-job.yaml/);
  for (const filename of ['acceptance-inventory-job.yaml', 'acceptance-observer-cronjob.yaml',
    'acceptance-pr-proof-job.yaml', 'acceptance-pr-proof-cronjob.yaml']) {
    const manifest = fs.readFileSync(path.join(root, filename), 'utf8');
    assert.match(manifest, /kubernetes.io\/hostname: acer/, filename);
    assert.match(manifest, /claimName: renovate-acceptance-ledger/, filename);
    if (filename !== 'acceptance-inventory-job.yaml') {
      assert.doesNotMatch(manifest, /claimName: renovate-cache/, filename);
    } else {
      const inventoryClaim = manifest.match(/claimName: (renovate-cache(?:-dedicated)?)\n\s+readOnly: true/)?.[1];
      const runnerClaim = runner.match(/claimName: (renovate-cache(?:-dedicated)?)/)?.[1];
      assert.equal(inventoryClaim, 'renovate-cache-dedicated');
      if (inventoryClaim !== runnerClaim) {
        assert.match(manifest, /^  suspend: true$/m);
        assert.doesNotMatch(kustomization, /- acceptance-inventory-job.yaml/);
      }
    }
  }
});

test('pinned Renovate image package path resolves without its shell wrapper', () => {
  const originalExists = fs.existsSync;
  const originalRealpath = fs.realpathSync;
  const imagePackage = '/usr/local/renovate';
  fs.existsSync = (file) => file === `${imagePackage}/dist/modules/datasource/api.js`;
  fs.realpathSync = (file) => file === imagePackage ? imagePackage : originalRealpath(file);
  try {
    assert.equal(observer.renovateRoot(), imagePackage);
  } finally {
    fs.existsSync = originalExists;
    fs.realpathSync = originalRealpath;
  }
});
