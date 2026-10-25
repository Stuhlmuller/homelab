const fs = require('node:fs');
const path = require('node:path');
const { readToken } = require('./acceptance-observer.js');
const { renovatePolicy } = require('./runner-config.js');

const privateDir = '/ledger/private';
const uidFile = '/var/run/podinfo/uid';
const readPermissions = Object.freeze({
  checks: 'read',
  contents: 'read',
  issues: 'read',
  members: 'read',
  metadata: 'read',
  pull_requests: 'read',
  statuses: 'read',
  vulnerability_alerts: 'read',
});

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
  const token = await readToken(readPermissions);
  return {
    ...renovatePolicy(token),
    baseDir: '/tmp/renovate-report/base',
    cacheDir: '/tmp/renovate-report/cache',
    repositoryCache: 'disabled',
    cachePrivatePackages: false,
    dryRun: 'full',
    reportType: 'file',
    reportPath: paths.report,
  };
}

config.podUid = podUid;
config.reportPaths = reportPaths;
config.prepare = prepare;
config.readPermissions = readPermissions;
module.exports = config;
