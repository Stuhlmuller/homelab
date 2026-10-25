const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const proof = require('../../clusters/homelab/apps/renovate/acceptance-policy-proof.js');
const headSha = 'a'.repeat(40);
const repository = { full_name: 'Stuhlmuller/private-fixture', private: true,
  archived: false, default_branch: 'main', headSha };
const base = `/repos/${repository.full_name}`;
const content = (text) => ({ type: 'file', encoding: 'base64',
  size: Buffer.byteLength(text), content: Buffer.from(text).toString('base64') });

function fixture(found = {}) {
  const routes = new Map([
    [`${base}/rules/branches/main`, []],
    [`${base}/branches/main/protection`, null],
    [`${base}/branches/main`, { commit: { sha: headSha } }],
    [base, { private: true, archived: false, default_branch: 'main' }],
    ...Object.entries(found).map(([name, value]) =>
      [`${base}/contents/${name}?ref=${headSha}`, content(value)]),
  ]);
  return (route, allow404 = false) => {
    if (routes.has(route)) return routes.get(route);
    if (allow404) return null;
    throw new Error('missing-fixture-route');
  };
}

test('pinned GitHub config paths capture a config-free repository', async () => {
  assert.deepEqual(proof.configFiles, [
    'renovate.json', 'renovate.jsonc', 'renovate.json5',
    '.github/renovate.json', '.github/renovate.jsonc', '.github/renovate.json5',
    '.renovaterc', '.renovaterc.json', '.renovaterc.jsonc', '.renovaterc.json5',
    'package.json',
  ]);
  const snapshot = await proof.snapshotRepository(repository, fixture({
    'package.json': '{"name":"fixture"}',
  }));
  assert.equal(snapshot.config.free, true);
  assert.equal(snapshot.config.selected, null);
  assert.equal(snapshot.classic.present, false);
  assert.equal(snapshot.rulesetBypassActors, 'unknown-read-only');
  assert.equal(snapshot.effectiveAutoMerge, 'requires-private-review');
});

test('override, shadowed config, rules, and classic protection stay private evidence', async () => {
  const get = fixture({
    'renovate.json': '{"automerge":false}',
    '.github/renovate.json': '{"extends":["config:recommended"]}',
    'package.json': '{"name":"fixture","renovate":{"schedule":["at any time"]}}',
  });
  const snapshot = await proof.snapshotRepository(repository, (route, allow404) => {
    if (route === `${base}/rules/branches/main`) return [{ type: 'required_status_checks' }];
    if (route === `${base}/branches/main/protection`) return {
      required_status_checks: { strict: true },
      required_pull_request_reviews: { required_approving_review_count: 2 },
      enforce_admins: { enabled: true },
    };
    return get(route, allow404);
  });
  assert.equal(snapshot.config.free, false);
  assert.equal(snapshot.config.selected, 'renovate.json');
  assert.equal(snapshot.config.files.length, 3);
  assert.equal(snapshot.config.multiple, true);
  assert.equal(snapshot.rules.count, 1);
  assert.deepEqual(snapshot.rules.types, ['required_status_checks']);
  assert.equal(snapshot.classic.requiredApprovals, 2);
  assert.equal(snapshot.classic.strictStatusChecks, true);
  assert.equal(snapshot.classic.enforceAdmins, true);
  assert.match(snapshot.config.files[0].sha256, /^[a-f0-9]{64}$/);
  assert.equal(JSON.stringify(snapshot).includes('automerge'), false);
});

test('403, malformed config, and changing default branch fail closed', async () => {
  await assert.rejects(proof.snapshotRepository(repository, (route, allow404) => {
    if (route === `${base}/rules/branches/main`) throw new Error('github-policy-read-failed');
    return fixture()(route, allow404);
  }), /github-policy-read-failed/);
  await assert.rejects(proof.snapshotRepository(repository, fixture({
    'package.json': '{invalid',
  })), /invalid-package-config/);
  await assert.rejects(proof.snapshotRepository(repository, (route, allow404) => {
    if (route === `${base}/branches/main`) return { commit: { sha: 'b'.repeat(40) } };
    return fixture()(route, allow404);
  }), /policy-branch-changed/);
  await assert.rejects(proof.snapshotRepository(repository, (route, allow404) => {
    if (route === base) return { private: true, archived: false, default_branch: 'next' };
    return fixture()(route, allow404);
  }), /policy-repository-changed/);
  assert.throws(() => proof.configBytes({ type: 'file', encoding: 'base64',
    size: 2, content: 'not-base64' }), /invalid-repository-config/);
});

test('GitHub 200 succeeds, 404 is optional only, and 403 always fails', async () => {
  const prior = global.fetch;
  global.fetch = async () => ({ status: 200, ok: true,
    headers: { get: (name) => name === 'date' ? new Date().toUTCString() : null },
    text: async () => '[]' });
  try {
    assert.deepEqual(await proof.github('fixture-token', '/rules'), []);
    global.fetch = async () => ({ status: 404, ok: false,
      headers: { get: (name) => name === 'date' ? new Date().toUTCString() : null } });
    assert.equal(await proof.github('fixture-token', '/missing', true), null);
    await assert.rejects(proof.github('fixture-token', '/missing'), /github-policy-read-failed/);
    global.fetch = async () => ({ status: 403, ok: false,
      headers: { get: (name) => name === 'date' ? new Date().toUTCString() : null } });
    await assert.rejects(proof.github('fixture-token', '/private', true), /github-policy-read-failed/);
  } finally {
    global.fetch = prior;
  }
});

test('private inventory rejects missing visibility instead of hiding a coverage gap', () => {
  const owned = proof.privateRepositories([repository, {
    full_name: 'Stuhlmuller/public-fixture', owner: { login: 'Stuhlmuller' },
    private: false, archived: false,
  }].map((entry) => ({ owner: { login: 'Stuhlmuller' }, ...entry })));
  assert.equal(owned.eligible, 2);
  assert.equal(owned.private.length, 1);
  assert.throws(() => proof.privateRepositories([{
    full_name: 'Stuhlmuller/unknown-fixture', owner: { login: 'Stuhlmuller' },
    archived: false,
  }]), /repository-visibility-missing/);
  assert.throws(() => proof.privateRepositories([{
    full_name: 'Stuhlmuller/public-fixture', owner: { login: 'Stuhlmuller' },
    private: false, archived: false,
  }]), /private-repository-coverage-empty/);
});

test('receipt is private, atomic, immutable, and never a public log', () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-policy-proof-'));
  const privateDir = path.join(rootDir, 'private');
  const uid = '12345678-1234-1234-1234-123456789abc';
  try {
    fs.mkdirSync(privateDir, { mode: 0o700 });
    const digest = proof.seal({ schema: 1, repositories: [{ repository: repository.full_name }] },
      uid, privateDir);
    const file = path.join(privateDir, 'policy', `${uid}.json`);
    assert.match(digest, /^[a-f0-9]{64}$/);
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    assert.equal(fs.statSync(path.dirname(file)).mode & 0o777, 0o700);
    assert.throws(() => proof.seal({ schema: 1 }, uid, privateDir), /EEXIST/);
    fs.chmodSync(privateDir, 0o755);
    assert.throws(() => proof.seal({ schema: 1 }, '12345678-1234-1234-1234-123456789abd',
      privateDir), /invalid-private-directory/);
  } finally {
    fs.rmSync(rootDir, { recursive: true, force: true });
  }
});

test('staged Job uses only the dedicated App and ledger', () => {
  const manifest = fs.readFileSync(path.join(root,
    'clusters/homelab/apps/renovate/acceptance-policy-proof-job.yaml'), 'utf8');
  const kustomization = fs.readFileSync(path.join(root,
    'clusters/homelab/apps/renovate/kustomization.yaml'), 'utf8');
  assert.match(manifest, /suspend: true/);
  assert.match(manifest, /automountServiceAccountToken: false/);
  assert.match(manifest, /secretName: renovate-acceptance\n/);
  assert.doesNotMatch(manifest, /secretName: renovate\n/);
  assert.match(manifest, /claimName: renovate-acceptance-ledger/);
  assert.doesNotMatch(kustomization, /  - acceptance-policy-proof-job.yaml/);
  assert.match(kustomization, /      - acceptance-policy-proof.js/);
});
