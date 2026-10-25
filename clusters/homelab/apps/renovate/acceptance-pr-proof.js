const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const observer = require('./acceptance-observer.js');

const privateDir = '/ledger/private';
const bot = 'rstuhlmuller-renovate[bot]';
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const validTime = (value) => typeof value === 'string' && Number.isFinite(Date.parse(value));

function privateFile(file, limit = 128 * 1024 * 1024) {
  const metadata = fs.lstatSync(file);
  if (!metadata.isFile() || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077) || metadata.size > limit) throw new Error('invalid-private-file');
  return fs.readFileSync(file);
}

function* verifiedReports(directory = privateDir, since = null) {
  const folder = path.join(directory, 'reports');
  const metadata = fs.lstatSync(folder);
  if (!metadata.isDirectory() || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077)) throw new Error('invalid-report-directory');
  let totalBytes = 0;
  const names = fs.readdirSync(folder).filter((name) =>
    /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.receipt\.json$/.test(name));
  if (names.length > 192) throw new Error('report-set-too-large');
  for (const name of names) {
      const uid = name.slice(0, 36);
      const receiptBytes = privateFile(path.join(folder, name), 8192);
      const receipt = JSON.parse(receiptBytes);
      if (receipt.schema !== 1 || receipt.podUid !== uid ||
          receipt.image !== 'harbor.stinkyboi.com/mirror/ghcr.io/renovatebot/renovate:44.167.4@sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d' ||
          !validTime(receipt.startedAt) || !validTime(receipt.completedAt) ||
          Date.parse(receipt.startedAt) > Date.parse(receipt.completedAt) ||
          Date.parse(receipt.completedAt) > Date.now()) throw new Error('invalid-report-receipt');
      if (since && Date.parse(receipt.completedAt) < Date.parse(since)) continue;
      const reportBytes = privateFile(path.join(folder, `${uid}.json`));
      totalBytes += reportBytes.length;
      if (totalBytes > 192 * 128 * 1024 * 1024) throw new Error('report-set-too-large');
      if (receipt.report?.file !== `${uid}.json` || receipt.report.bytes !== reportBytes.length ||
          receipt.report.sha256 !== sha256(reportBytes) ||
          !validTime(receipt.report.modifiedAt)) throw new Error('invalid-report-receipt');
      const report = JSON.parse(reportBytes);
      if (!report || !Array.isArray(report.problems) || report.problems.length || !report.repositories ||
          typeof report.repositories !== 'object' || Array.isArray(report.repositories)) {
        throw new Error('invalid-report');
      }
      yield { receipt, report };
  }
}

function candidate(item, event, reports) {
  const numbers = new Map();
  for (const { receipt, report } of reports) {
    if (Date.parse(receipt.completedAt) < Date.parse(event.lastAbsent)) continue;
    const repository = Object.entries(report.repositories).find(([name]) =>
      name.toLowerCase() === item.repository.toLowerCase())?.[1];
    for (const branch of repository?.branches || []) {
      if (!Number.isSafeInteger(branch.prNo) || branch.prNo <= 0 ||
          !Array.isArray(branch.upgrades)) continue;
      if (branch.upgrades.some((upgrade) => upgrade.datasource === item.datasource &&
          (upgrade.packageName || upgrade.depName) === item.packageName &&
          upgrade.packageFile === item.packageFile && upgrade.newVersion === event.version)) {
        const prior = numbers.get(branch.prNo);
        if (!prior || Date.parse(receipt.completedAt) < Date.parse(prior.receipt.completedAt)) {
          numbers.set(branch.prNo, { number: branch.prNo, receipt, branch });
        }
      }
    }
  }
  return numbers.size === 1 ? [...numbers.values()][0] : null;
}

function matchingBranches(item, event, report) {
  const repository = Object.entries(report.repositories).find(([name]) =>
    name.toLowerCase() === item.repository.toLowerCase())?.[1];
  return (repository?.branches || []).filter((branch) => Array.isArray(branch.upgrades) &&
    branch.upgrades.some((upgrade) => upgrade.datasource === item.datasource &&
      (upgrade.packageName || upgrade.depName) === item.packageName &&
      upgrade.packageFile === item.packageFile && upgrade.newVersion === event.version));
}

function reportDecision(item, event, reports) {
  const eligibleResults = new Set(['not-scheduled', 'needs-pr-approval', 'done',
    'pr-created', 'pr-edited', 'already-existed', 'pending', 'update-not-scheduled']);
  let eligibility = null;
  let deferral = null;
  for (const { receipt, report } of [...reports].sort((a, b) =>
    Date.parse(a.receipt.completedAt) - Date.parse(b.receipt.completedAt))) {
    if (Date.parse(receipt.completedAt) < Date.parse(event.lastAbsent)) continue;
    const branches = matchingBranches(item, event, report).filter((branch) =>
      eligibleResults.has(branch.result));
    if (!branches.length) continue;
    if (!eligibility) eligibility = { receipt, branches };
    const branch = branches.length === 1 ? branches[0] : null;
    const reason = branch && !branch.prNo &&
      ((branch.result === 'not-scheduled' && !branch.prBlockedBy && 'schedule') ||
        (branch.result === 'needs-pr-approval' && branch.prBlockedBy === 'NeedsApproval' &&
          'pull-request-approval'));
    if (reason) {
      deferral = { receipt, branches, reason };
      break;
    }
  }
  return eligibility ? { ...eligibility, deferral } : null;
}

function proposalProof(item, event, match, pull, files, observedAt, baseBranch) {
  if (!match || typeof event.version !== 'string' || !event.version ||
      event.version.length > 256 || /[\r\n]/.test(event.version) ||
      !validTime(observedAt) || Date.parse(observedAt) < Date.parse(event.firstPresent) ||
      !Array.isArray(files) || !Number.isSafeInteger(pull?.changed_files) ||
      pull.changed_files !== files.length || pull.number !== match.number ||
      pull.state !== 'open' || pull.closed_at != null || pull.merged_at != null ||
      pull.user?.login !== bot || pull.base?.repo?.full_name !== item.repository ||
      pull.head?.repo?.full_name !== item.repository ||
      pull.head?.ref !== match.branch.branchName || pull.base?.ref !== baseBranch ||
      !/^[a-f0-9]{40}$/.test(pull.head?.sha || '') ||
      !validTime(pull.created_at) || Date.parse(pull.created_at) > Date.parse(observedAt)) return null;
  const escaped = event.version.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const version = new RegExp(`(?:^|[^A-Za-z0-9._-])${escaped}(?:$|[^A-Za-z0-9._-])`);
  const escapedPackage = item.packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const packageName = new RegExp(`(?:^|[^A-Za-z0-9_/@.-])${escapedPackage}(?:$|[^A-Za-z0-9_/@.-])`);
  const file = files.find((entry) => entry?.filename === item.packageFile &&
    typeof entry.patch === 'string' && entry.patch.split('\n').some((line) =>
      line.startsWith('+') && !line.startsWith('+++') &&
      packageName.test(line.slice(1)) && version.test(line.slice(1))));
  if (!file) return null;
  return {
    claim: { kind: 'proposal', at: observedAt, verifiedAt: observedAt },
    material: { provenance: 'github-pr-file-snapshot-v1', repository: item.repository,
      pullNumber: pull.number, createdAt: pull.created_at, observedAt,
      branchName: match.branch.branchName, headSha: pull.head.sha,
      reportPodUid: match.receipt.podUid,
      reportSha256: match.receipt.report.sha256, packageFile: item.packageFile,
      patch: file.patch },
  };
}

async function github(token, route) {
  const response = await fetch(`https://api.github.com${route}`, {
    headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`,
      'User-Agent': 'homelab-renovate-acceptance-proof',
      'X-GitHub-Api-Version': '2022-11-28' },
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error('github-read-failed');
  const serverTime = Date.parse(response.headers.get('date'));
  if (!Number.isFinite(serverTime) || Math.abs(serverTime - Date.now()) > 60000) {
    throw new Error('github-clock-unverified');
  }
  return response.json();
}

async function pullFiles(token, repository, number, count) {
  if (count < 1 || count > 1000) return null;
  const files = [];
  for (let page = 1; files.length < count; page++) {
    const part = await github(token,
      `/repos/${repository}/pulls/${number}/files?per_page=100&page=${page}`);
    if (!Array.isArray(part) || !part.length || files.length + part.length > count) return null;
    files.push(...part);
  }
  return files;
}

async function collect(directory = privateDir) {
  const metadata = fs.lstatSync(directory);
  if (!metadata.isDirectory() || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077)) throw new Error('invalid-private-directory');
  const ledger = JSON.parse(privateFile(path.join(directory, 'ledger.json')));
  observer.verifyFrozenSample(ledger);
  const outcomesPath = path.join(directory, 'outcomes.json');
  const outcomes = fs.existsSync(outcomesPath) ? JSON.parse(privateFile(outcomesPath)) :
    { schema: 1, inventorySha256: ledger.inventorySha256, receipts: [] };
  observer.aggregateReport(ledger, outcomes);
  const byEvent = new Map(outcomes.receipts.map((entry) =>
    [JSON.stringify([entry.key, entry.version]), entry]));
  const pending = ledger.sample.flatMap((item) => item.events.filter((event) => {
    const entry = byEvent.get(JSON.stringify([item.key, event.version]));
    return entry?.eligibility?.status !== 'eligible' || !entry.outcome;
  }).map((event) => ({ item, event })));
  if (!pending.length) {
    console.log(JSON.stringify({ mode: 'proposal-proof', candidates: 0, proven: 0,
      eligible: 0, deferred: 0, unknown: 0 }));
    return;
  }
  const since = pending.length ? new Date(Math.min(...pending.map(({ event }) =>
    Date.parse(event.lastAbsent)))).toISOString() : null;
  const reports = [];
  for (const { receipt, report } of verifiedReports(directory, since)) {
    const repositories = new Map();
    for (const { item, event } of pending) {
      for (const branch of matchingBranches(item, event, report)) {
        if (!repositories.has(item.repository)) repositories.set(item.repository, new Set());
        repositories.get(item.repository).add(branch);
      }
    }
    if (repositories.size) reports.push({ receipt, report: { repositories: Object.fromEntries(
      [...repositories].map(([name, branches]) => [name, { branches: [...branches] }])) } });
  }
  const work = [];
  const decisions = [];
  for (const item of ledger.sample) {
    const baseBranch = ledger.inventory.provenance.repositories.find((entry) =>
      entry.repository === item.repository)?.baseBranch;
    if (!baseBranch) throw new Error('invalid-inventory');
    for (const event of item.events) {
      const id = JSON.stringify([item.key, event.version]);
      const existing = byEvent.get(id);
      if (existing?.eligibility?.status === 'eligible' && existing.outcome) continue;
      const decision = reportDecision(item, event, reports);
      if (decision && (existing?.eligibility?.status !== 'eligible' ||
          (decision.deferral && !existing?.outcome))) {
        decisions.push({ item, event, id, decision });
      }
      if (existing?.outcome || decision?.deferral) continue;
      const match = candidate(item, event, reports);
      if (match) work.push({ item, event, id, match, baseBranch });
    }
  }
  const token = work.length ? await observer.readToken({ contents: 'read', metadata: 'read', pull_requests: 'read' }) : null;
  const folder = path.join(directory, 'evidence');
  fs.mkdirSync(folder, { recursive: true, mode: 0o700 });
  const folderMetadata = fs.lstatSync(folder);
  if (!folderMetadata.isDirectory() || folderMetadata.uid !== process.getuid() ||
      (folderMetadata.mode & 0o077)) throw new Error('invalid-evidence-directory');
  const verified = [];
  for (const { item, event, id, match, baseBranch } of work) {
    const repository = item.repository;
    if (!/^Stuhlmuller\/[A-Za-z0-9_.-]+$/.test(repository)) throw new Error('invalid-repository');
    const pull = await github(token, `/repos/${repository}/pulls/${match.number}`);
    const files = await pullFiles(token, repository, match.number, pull.changed_files);
    // The upper bound allows for the maximum accepted difference from GitHub's Date header.
    const result = proposalProof(item, event, match, pull,
      files, new Date(Date.now() + 60000).toISOString(), baseBranch);
    if (!result) continue;
    verified.push({ item, event, id, result });
  }
  function saveEvidence(item, event, kind, claim, material) {
    const source = `evidence/${kind}-${crypto.randomUUID()}.json`;
    const envelope = { schema: 1, key: item.key, version: event.version, kind, claim, material };
    const bytes = Buffer.from(`${JSON.stringify(envelope)}\n`);
    fs.writeFileSync(path.join(directory, source), bytes, { flag: 'wx', mode: 0o600, flush: true });
    return { ...claim, source, sha256: sha256(bytes) };
  }
  function outcomeReceipt(item, event, id) {
    let entry = byEvent.get(id);
    if (!entry) {
      entry = { key: item.key, version: event.version, eligibility: { status: 'unknown' } };
      outcomes.receipts.push(entry);
      byEvent.set(id, entry);
    }
    return entry;
  }
  let eligibility = 0;
  let deferred = 0;
  for (const { item, event, id, decision } of decisions) {
    const entry = outcomeReceipt(item, event, id);
    const { receipt, branches, deferral } = decision;
    const verifiedAt = new Date().toISOString();
    const reportMaterial = (source, matched) => ({ provenance: 'renovate-full-dry-run-v1',
      repository: item.repository, packageFile: item.packageFile, reportPodUid: source.podUid,
      reportSha256: source.report.sha256, reportCompletedAt: source.completedAt,
      branches: matched });
    if (entry.eligibility.status !== 'eligible') {
      entry.eligibility = saveEvidence(item, event, 'eligibility',
        { status: 'eligible', verifiedAt }, reportMaterial(receipt, branches));
      eligibility++;
    }
    if (deferral && !entry.outcome) {
      entry.outcome = saveEvidence(item, event, 'outcome',
        { kind: 'deferral', reason: deferral.reason, at: deferral.receipt.completedAt,
          verifiedAt }, reportMaterial(deferral.receipt, deferral.branches));
      deferred++;
    }
  }
  for (const { item, event, id, result } of verified) {
    const entry = outcomeReceipt(item, event, id);
    entry.outcome = saveEvidence(item, event, 'outcome', result.claim, result.material);
  }
  if (eligibility || deferred || verified.length) {
    const temporary = `${outcomesPath}.${crypto.randomUUID()}.tmp`;
    try {
      fs.writeFileSync(temporary, `${JSON.stringify(outcomes)}\n`, { flag: 'wx', mode: 0o600, flush: true });
      fs.renameSync(temporary, outcomesPath);
    } finally {
      if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    }
  }
  console.log(JSON.stringify({ mode: 'proposal-proof', candidates: work.length, proven: verified.length,
    eligible: eligibility, deferred, unknown: work.length - verified.length }));
}

if (require.main === module) collect().catch(() => {
  console.error(JSON.stringify({ mode: 'proposal-proof', error: 'verification-failed' }));
  process.exitCode = 1;
});

module.exports = { privateFile, verifiedReports, candidate, reportDecision, proposalProof, pullFiles, collect };
