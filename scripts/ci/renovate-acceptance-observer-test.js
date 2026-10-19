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
  const at = ['2026-10-18T00:00:00.000Z', '2026-10-18T00:15:00.000Z', '2026-10-18T00:30:00.000Z'];
  const result = (versions) => new Map([[item.key, { releases: versions.map((version) => ({ version })) }]]);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0']), at[0]).failed, 2);
  assert.equal(observer.recordPoll(ledger, new Map(), at[1]).failed, 3);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0', '1.1.0']), at[2]).events, 1);
  assert.deepEqual(item.events, [{ version: '1.1.0', lastAbsent: at[0], firstPresent: at[2] }]);
  assert.equal(observer.aggregate(ledger).bracketedEvents, 1);
  const absent = '2026-10-18T00:45:00.000Z';
  const present = '2026-10-18T01:00:00.000Z';
  observer.recordPoll(ledger, result(['1.0.0']), absent);
  assert.equal(observer.recordPoll(ledger, result(['1.0.0', '1.1.0']), present).events, 1);
  assert.deepEqual(item.events[1], { version: '1.1.0', lastAbsent: absent, firstPresent: present });
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
