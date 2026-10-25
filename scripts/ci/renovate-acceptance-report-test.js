const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../clusters/homelab/apps/renovate');
const runner = require(path.join(root, 'acceptance-report-runner.js'));
const uid = '12345678-1234-1234-1234-123456789abc';

function reportConfig(realStorage = false, dryRun = 'full') {
  const source = fs.readFileSync(path.join(root, 'acceptance-report-config.js'), 'utf8');
  const fileSystem = {
    readFileSync(file) {
      if (file === '/var/run/podinfo/uid') return `${uid}\n`;
      if (realStorage) return fs.readFileSync(file);
      throw new Error(`unexpected read: ${file}`);
    },
    mkdirSync(...args) { if (realStorage) return fs.mkdirSync(...args); },
    lstatSync(file) {
      if (realStorage) return fs.lstatSync(file);
      if (file === '/ledger/private' || file === '/ledger/private/reports') {
        return { isDirectory: () => true, mode: 0o40700, uid: process.getuid() };
      }
      const error = new Error('missing');
      error.code = 'ENOENT';
      throw error;
    },
  };
  const module = { exports: {} };
  const context = {
    module,
    process,
    require(name) {
      if (name === 'node:fs') return fileSystem;
      if (name === 'node:path') return path;
      if (name === './runner-config.js') return async () => ({
        token: 'ghs_writer', cacheDir: '/cache/renovate', repositoryCache: 'enabled',
        cachePrivatePackages: true, ...(dryRun === null ? {} : { dryRun }),
      });
      throw new Error(`unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(source, context);
  return { config: module.exports };
}

test('one primary scan reports to a per-Pod path without changing its token, cache, or write mode', async () => {
  const { config } = reportConfig();
  const value = await config();
  assert.equal(value.token, 'ghs_writer');
  assert.equal(value.reportType, 'file');
  assert.equal(value.reportPath, `/report-output/${uid}.json`);
  assert.equal(value.cacheDir, '/cache/renovate');
  assert.equal(value.repositoryCache, 'enabled');
  assert.equal(value.cachePrivatePackages, true);
  assert.equal(value.dryRun, 'full');
  const writeEnabled = await reportConfig(false, null).config();
  assert.equal(writeEnabled.dryRun, undefined);
  assert.equal(writeEnabled.token, 'ghs_writer');
  assert.equal(writeEnabled.cacheDir, '/cache/renovate');
  assert.throws(() => config.reportPaths('../escape'), /invalid-pod-uid/);
  assert.throws(() => config.reportScratchPath('../escape'), /invalid-pod-uid/);
  const kustomization = fs.readFileSync(path.join(root, 'kustomization.yaml'), 'utf8');
  const cron = fs.readFileSync(path.join(root, 'cronjob.yaml'), 'utf8');
  const patch = fs.readFileSync(path.join(root, 'acceptance-primary-report-patch.yaml'), 'utf8');
  assert.equal((kustomization.match(/- cronjob\.yaml/g) || []).length, 1);
  assert.doesNotMatch(kustomization, /acceptance-primary-report-patch/);
  assert.match(cron, /^  schedule: "0 \* \* \* \*"$/m);
  assert.match(cron, /secretName: renovate\n/);
  assert.match(cron, /claimName: renovate-cache\n/);
  assert.match(patch, /acceptance-report-runner\.js/);
  assert.match(patch, /claimName: renovate-acceptance-ledger/);
  assert.match(patch, /medium: Memory\n\s+sizeLimit: 128Mi/);
  assert.doesNotMatch(patch, /secretName: renovate-acceptance|schedule:/);
  assert.equal(fs.existsSync(path.join(root, 'acceptance-report-cronjob.yaml')), false);
  assert.equal(fs.existsSync(path.join(root, 'acceptance-report-job.yaml')), false);
});

test('a pinned-shape report is sealed once with private files and matching hashes', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-report-'));
  try {
    const { config } = reportConfig(true);
    const paths = config.reportPaths(uid, directory);
    config.prepare(paths);
    // Produced by pinned Renovate 44.167.4 reporting.js from synthetic extraction and branch cache.
    const bytes = fs.readFileSync(path.join(__dirname, 'fixtures/renovate-report-44.167.4.json'));
    const report = JSON.parse(bytes);
    assert.deepEqual(report.repositories['example/fixture'].branches.map(({ result }) => result),
      ['not-scheduled', 'needs-pr-approval', 'done']);
    assert.equal(report.repositories['example/fixture'].branches[2].prNo, 42);
    assert.equal(Object.hasOwn(report, 'timestamp'), false, 'the receipt supplies the scan time');
    const scratch = path.join(directory, 'scratch.json');
    fs.writeFileSync(scratch, bytes, { mode: 0o600 });
    runner.copyBoundedReport(scratch, paths.report);
    fs.writeFileSync(paths.log, 'private diagnostic\n', { mode: 0o600 });
    const counts = runner.seal(paths, uid, '2026-10-19T00:00:00.000Z', '2026-10-19T00:01:00.000Z', path.join(root, 'config.js'));
    assert.deepEqual(counts, { repositories: 1, packageFiles: 1, dependencies: 1, branches: 3 });
    const receipt = JSON.parse(fs.readFileSync(paths.receipt, 'utf8'));
    const manifest = fs.readFileSync(path.join(root, 'cronjob.yaml'), 'utf8');
    assert.equal(receipt.image, manifest.match(/^\s+image: (\S+)$/m)?.[1]);
    assert.equal(receipt.report.sha256, crypto.createHash('sha256').update(bytes).digest('hex'));
    assert.equal(receipt.policySha256, crypto.createHash('sha256').update(
      fs.readFileSync(path.join(root, 'config.js'))).digest('hex'));
    assert.equal(receipt.podUid, uid);
    assert.equal(receipt.report.file, `${uid}.json`);
    assert.equal(fs.statSync(paths.receipt).mode & 0o077, 0);
    assert.doesNotMatch(JSON.stringify(receipt), /example\/repo|private diagnostic/);
    assert.throws(() => runner.seal(paths, uid, '2026-10-19T00:00:00.000Z', '2026-10-19T00:01:00.000Z', path.join(root, 'config.js')), /EEXIST/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('report copy refuses oversized input before publishing on the ledger', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-report-cap-'));
  try {
    const source = path.join(directory, 'oversized.json');
    const destination = path.join(directory, 'report.json');
    const descriptor = fs.openSync(source, 'wx', 0o600);
    fs.ftruncateSync(descriptor, 128 * 1024 * 1024 + 1);
    fs.closeSync(descriptor);
    assert.throws(() => runner.copyBoundedReport(source, destination), /invalid-report-file/);
    assert.equal(fs.existsSync(destination), false);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('runner streams a bounded log without forwarding child output to Pod logs', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-report-stream-'));
  try {
    const script = path.join(directory, 'fixture.js');
    const log = path.join(directory, 'fixture.log');
    fs.writeFileSync(script, 'process.stdout.write("normal-out"); process.stderr.write("normal-err");\n');
    let descriptor = fs.openSync(log, 'wx', 0o600);
    try {
      assert.deepEqual(await runner.runBounded(script, descriptor, 1024, directory),
        { code: 0, signal: null });
    } finally {
      fs.closeSync(descriptor);
    }
    assert.equal(fs.readFileSync(log, 'utf8'), 'normal-outnormal-err');
    fs.writeFileSync(script, 'process.stdout.write("x".repeat(4096));\n');
    descriptor = fs.openSync(path.join(directory, 'overflow.log'), 'wx', 0o600);
    try {
      await assert.rejects(runner.runBounded(script, descriptor, 1024, directory),
        /report-log-too-large/);
    } finally {
      fs.closeSync(descriptor);
    }
    assert.ok(fs.statSync(path.join(directory, 'overflow.log')).size <= 1024);
    assert.equal(fs.existsSync(path.join(directory, 'fixture.receipt.json')), false);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('missing or malformed report cannot create a success receipt', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'renovate-report-bad-'));
  try {
    const { config } = reportConfig(true);
    const paths = config.reportPaths(uid, directory);
    config.prepare(paths);
    fs.writeFileSync(paths.log, '', { mode: 0o600 });
    assert.throws(() => runner.seal(paths, uid, '2026-10-19T00:00:00Z', '2026-10-19T00:01:00Z', path.join(root, 'config.js')), /ENOENT/);
    fs.writeFileSync(paths.report, '{"problems":[],"repositories":{"repo":{}}}', { mode: 0o600 });
    assert.throws(() => runner.seal(paths, uid, '2026-10-19T00:00:00Z', '2026-10-19T00:01:00Z', path.join(root, 'config.js')), /invalid-report-shape/);
    assert.equal(fs.existsSync(paths.receipt), false);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
