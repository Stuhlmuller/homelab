const fs = require('node:fs');
const path = require('node:path');
const runnerConfig = require('./runner-config.js');

const privateDir = '/ledger/private';
const scratchDir = '/report-output';
const uidFile = '/var/run/podinfo/uid';

function podUid() {
  const uid = fs.readFileSync(uidFile, 'utf8').trim();
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(uid)) {
    throw new Error('invalid-pod-uid');
  }
  return uid;
}

function reportPaths(uid, directory = privateDir) {
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(uid)) {
    throw new Error('invalid-pod-uid');
  }
  const reports = path.join(directory, 'reports');
  return {
    directory,
    reports,
    report: path.join(reports, `${uid}.json`),
    log: path.join(reports, `${uid}.log`),
    receipt: path.join(reports, `${uid}.receipt.json`),
  };
}

function reportScratchPath(uid) {
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(uid)) {
    throw new Error('invalid-pod-uid');
  }
  return path.join(scratchDir, `${uid}.json`);
}

function prepare(paths) {
  for (const directory of [paths.directory, paths.reports]) {
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const metadata = fs.lstatSync(directory);
    if (!metadata.isDirectory() || (metadata.mode & 0o077) ||
        metadata.uid !== process.getuid()) throw new Error('report-directory-permissions');
  }
  for (const file of [paths.report, paths.receipt]) {
    try {
      fs.lstatSync(file);
      throw new Error('report-run-already-exists');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

async function config() {
  const paths = reportPaths(podUid());
  prepare(paths);
  return {
    ...await runnerConfig(),
    reportType: 'file',
    // The 128 MiB memory-backed volume hard-limits the raw report before it
    // can be copied to the private ledger and sealed by the wrapper.
    reportPath: reportScratchPath(podUid()),
  };
}

config.podUid = podUid;
config.reportPaths = reportPaths;
config.reportScratchPath = reportScratchPath;
config.prepare = prepare;
module.exports = config;
