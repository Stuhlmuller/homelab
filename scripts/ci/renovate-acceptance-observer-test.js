const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const crypto = require('node:crypto');
const observer = require('../../clusters/homelab/apps/renovate/acceptance-observer.js');

const dependency = (datasource, sourceVisibility, packageName) => ({
  repository: 'Stuhlmuller/example',
  datasource,
  sourceVisibility,
  packageName,
});

function inventory() {
  return {
    schema: 1,
    owner: 'Stuhlmuller',
    seed: 'natural-2026-10-18',
    provenance: { method: 'renovate-extract', headSha: 'a'.repeat(40) },
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
  assert.equal(observer.aggregate(missed).missedPolls, 1);

  const late = observer.selectSample(source);
  const lateItem = baseline(late, '2026-10-18T00:06:00.000Z');
  baseline(late, '2026-10-18T00:15:00.000Z', '1.1.0');
  assert.equal(lateItem.events[0].ambiguous, true);
  assert.equal(observer.aggregate(late).latePolls, 1);

  const healthy = observer.selectSample(source);
  const healthyItem = baseline(healthy, '2026-10-18T00:00:00.000Z');
  baseline(healthy, '2026-10-18T00:15:00.000Z', '1.1.0');
  assert.equal(healthyItem.events[0].ambiguous, false);
  assert.equal(observer.aggregate(healthy).missedPolls, 0);
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
    if (file === '/var/run/secrets/renovate/issuer-id') throw new Error('private failure');
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
  fs.readFileSync = (file, ...args) => file.endsWith('/issuer-id') ? '123' :
    file.endsWith('/private-key') ? privateKey : originalRead(file, ...args);
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => calls.length === 1 ?
        { id: 42, account: { login: 'Stuhlmuller' }, repository_selection: 'all' } :
        { token: 'ghs_readonly', expires_at: new Date(Date.now() + 3600_000).toISOString(),
          permissions: { contents: 'read', metadata: 'read' } },
    };
  };
  try {
    assert.equal(await observer.readToken(), 'ghs_readonly');
    assert.equal(calls[0].options.method, 'GET');
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(calls[1].url.endsWith('/access_tokens'), true);
    assert.deepEqual(JSON.parse(calls[1].options.body).permissions,
      { contents: 'read', metadata: 'read' });
  } finally {
    fs.readFileSync = originalRead;
    global.fetch = originalFetch;
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
