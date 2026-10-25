const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const reportConfig = require('./config.js');
const { renovateRoot } = require('./acceptance-observer.js');

const maxEvidenceBytes = 128 * 1024 * 1024;

function privateFile(file, allowEmpty = false) {
  const metadata = fs.lstatSync(file);
  if (!metadata.isFile() || (metadata.mode & 0o077) || metadata.uid !== process.getuid() ||
      (!allowEmpty && metadata.size <= 0) || metadata.size > maxEvidenceBytes) {
    throw new Error('invalid-report-file');
  }
  return { metadata, bytes: fs.readFileSync(file) };
}

function seal(paths, uid, startedAt, completedAt,
  policyPath = path.join(__dirname, 'runner-config.js')) {
  const report = privateFile(paths.report);
  const log = privateFile(paths.log, true);
  let parsed;
  try { parsed = JSON.parse(report.bytes); } catch { throw new Error('invalid-report-json'); }
  if (!parsed || !Array.isArray(parsed.problems) || parsed.problems.length ||
      !parsed.repositories || typeof parsed.repositories !== 'object' ||
      Array.isArray(parsed.repositories) || !Object.keys(parsed.repositories).length) {
    throw new Error('invalid-report-shape');
  }
  let packageFiles = 0;
  let dependencies = 0;
  let branches = 0;
  for (const repository of Object.values(parsed.repositories)) {
    if (!repository || !Array.isArray(repository.problems) || repository.problems.length ||
        !repository.packageFiles || typeof repository.packageFiles !== 'object' ||
        Array.isArray(repository.packageFiles) || !Array.isArray(repository.branches)) {
      throw new Error('invalid-report-shape');
    }
    for (const files of Object.values(repository.packageFiles)) {
      if (!Array.isArray(files)) throw new Error('invalid-report-shape');
      for (const file of files) {
        if (typeof file?.packageFile !== 'string' || !Array.isArray(file.deps)) {
          throw new Error('invalid-report-shape');
        }
        packageFiles++;
        dependencies += file.deps.length;
      }
    }
    branches += repository.branches.length;
  }
  if (!dependencies) throw new Error('empty-report-inventory');
  const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
  const receipt = {
    schema: 1,
    podUid: uid,
    image: 'harbor.stinkyboi.com/mirror/ghcr.io/renovatebot/renovate:44.167.4@sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d',
    policySha256: sha256(fs.readFileSync(policyPath)),
    startedAt,
    completedAt,
    report: {
      file: path.basename(paths.report),
      sha256: sha256(report.bytes),
      bytes: report.metadata.size,
      modifiedAt: report.metadata.mtime.toISOString(),
    },
    log: { file: path.basename(paths.log), sha256: sha256(log.bytes), bytes: log.metadata.size },
    repositories: Object.keys(parsed.repositories).length,
    packageFiles,
    dependencies,
    branches,
  };
  const temporary = `${paths.receipt}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, `${JSON.stringify(receipt)}\n`, { flag: 'wx', mode: 0o600, flush: true });
    fs.linkSync(temporary, paths.receipt); // Exclusive creation; never replace a prior receipt.
  } finally {
    try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return { repositories: receipt.repositories, packageFiles, dependencies, branches };
}

function copyBoundedReport(source, destination) {
  const report = privateFile(source);
  const temporary = `${destination}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, report.bytes, { flag: 'wx', mode: 0o600, flush: true });
    fs.linkSync(temporary, destination); // Publish only a complete, bounded report.
  } finally {
    try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}

function runBounded(script, logFd, limit = maxEvidenceBytes, cwd = '/usr/src/app') {
  if (!Number.isSafeInteger(limit) || limit <= 0) throw new Error('invalid-report-limit');
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script], {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let written = 0;
    let failure;
    function stop(message) {
      if (failure) return;
      failure = new Error(message);
      child.kill('SIGKILL');
      child.stdout.destroy();
      child.stderr.destroy();
    }
    function write(chunk) {
      if (failure) return;
      const allowed = Math.min(chunk.length, limit - written);
      try {
        let offset = 0;
        while (offset < allowed) {
          const count = fs.writeSync(logFd, chunk, offset, allowed - offset);
          if (count <= 0) throw new Error('short-write');
          offset += count;
          written += count;
        }
      } catch {
        stop('report-log-write-failed');
        return;
      }
      if (allowed < chunk.length) stop('report-log-too-large');
    }
    child.stdout.on('data', write);
    child.stderr.on('data', write);
    child.stdout.on('error', () => stop('report-log-stream-failed'));
    child.stderr.on('error', () => stop('report-log-stream-failed'));
    child.once('error', reject);
    child.once('close', (code, signal) => {
      if (failure) reject(failure);
      else resolve({ code, signal });
    });
  });
}

async function run() {
  process.umask(0o077);
  const uid = reportConfig.podUid();
  const paths = reportConfig.reportPaths(uid);
  reportConfig.prepare(paths);
  const startedAt = new Date().toISOString();
  const logFd = fs.openSync(paths.log, 'wx', 0o600);
  let result;
  try {
    const script = path.join(renovateRoot(), 'dist/renovate.js');
    result = await runBounded(script, logFd);
  } finally {
    fs.closeSync(logFd);
  }
  if (result.code !== 0 || result.signal) throw new Error('renovate-report-run-failed');
  copyBoundedReport(reportConfig.reportScratchPath(uid), paths.report);
  const counts = seal(paths, uid, startedAt, new Date().toISOString());
  console.log(JSON.stringify({ status: 'report-sealed', ...counts }));
}

if (require.main === module) {
  run().catch((error) => {
    console.error(`acceptance-report: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { privateFile, copyBoundedReport, runBounded, seal, run };
