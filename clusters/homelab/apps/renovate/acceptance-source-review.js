// Replays private SC-002 source links after all acceptance writers are drained.
// A passing replay is still subject to independent human source/policy review.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const observer = require('./acceptance-observer.js');
const proof = require('./acceptance-pr-proof.js');

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');

function privateBytes(file, limit = 16 * 1024 * 1024) {
  const metadata = fs.lstatSync(file);
  if (!metadata.isFile() || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077) || metadata.size > limit) throw new Error('private-file-invalid');
  return fs.readFileSync(file);
}

function evidence(directory, receipt, kind, value, verified) {
  if (!value || typeof value.source !== 'string' ||
      !/^evidence\/[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.json$/.test(value.source) ||
      !/^[a-f0-9]{64}$/.test(value.sha256 || '') ||
      !verified.has(JSON.stringify([receipt.key, receipt.version, kind,
        value.source, value.sha256]))) throw new Error('unverified-evidence');
  const bytes = privateBytes(path.join(directory, value.source));
  if (sha256(bytes) !== value.sha256) throw new Error('unverified-evidence');
  const envelope = JSON.parse(bytes);
  return envelope.material;
}

function sourceReview(directory = '/ledger/private') {
  const root = fs.lstatSync(directory);
  if (!root.isDirectory() || root.uid !== process.getuid() ||
      (root.mode & 0o077)) throw new Error('private-directory-invalid');
  const ledger = JSON.parse(privateBytes(path.join(directory, 'ledger.json')));
  observer.verifyFrozenSample(ledger);
  const reviewBytes = privateBytes(path.join(directory, 'review.json'));
  const review = JSON.parse(reviewBytes);
  if (ledger.reviewSha256 !== sha256(JSON.stringify(review)) ||
      !/^[a-f0-9]{64}$/.test(review.configSha256 || '') ||
      review.windowStart !== ledger.windowStart || review.windowEnd !== ledger.windowEnd) {
    throw new Error('policy-review-invalid');
  }
  const outcomes = JSON.parse(privateBytes(path.join(directory, 'outcomes.json')));
  const verified = observer.verifyPrivateEvidence(outcomes, directory);
  const aggregate = observer.aggregateReport(ledger, outcomes, verified);
  const byEvent = new Map();
  for (const item of ledger.sample) {
    for (const event of item.events) byEvent.set(JSON.stringify([item.key, event.version]),
      { item, event });
  }
  const tasks = new Map();
  let manual = 0;
  let sourceLinks = 0;
  for (const receipt of outcomes.receipts) {
    const entry = byEvent.get(JSON.stringify([receipt.key, receipt.version]));
    if (!entry) throw new Error('unknown-event');
    const { item, event } = entry;
    if (receipt.eligibility?.status !== 'eligible') {
      manual++;
      continue;
    }
    for (const kind of ['eligibility', 'outcome']) {
      const value = receipt[kind];
      if (!value) throw new Error('missing-source-link');
      const material = evidence(directory, receipt, kind, value, verified);
      const uid = material?.reportPodUid;
      if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(uid || '') ||
          !/^[a-f0-9]{64}$/.test(material.reportSha256 || '')) {
        throw new Error('invalid-report-link');
      }
      if (!tasks.has(uid)) tasks.set(uid, []);
      tasks.get(uid).push({ item, event, kind, value, material });
      sourceLinks++;
    }
  }
  for (const { receipt: reportReceipt, report } of proof.verifiedReports(
    directory, null, new Set(tasks.keys()))) {
    const linked = tasks.get(reportReceipt.podUid);
    if (!linked) continue;
    if (reportReceipt.policySha256 !== review.configSha256) {
      throw new Error('policy-changed');
    }
    for (const { item, event, kind, value, material } of linked) {
      if (material.reportSha256 !== reportReceipt.report.sha256 ||
          material.reportCompletedAt && material.reportCompletedAt !== reportReceipt.completedAt) {
        throw new Error('report-link-mismatch');
      }
      const decision = proof.reportDecision(item, event, [{ receipt: reportReceipt, report }]);
      if (kind === 'eligibility') {
        if (value.status !== 'eligible' || !decision ||
            !isDeepStrictEqual(material.branches, decision.branches)) {
          throw new Error('eligibility-source-mismatch');
        }
      } else if (value.kind === 'deferral') {
        if (!decision?.deferral || decision.deferral.reason !== value.reason ||
            value.at !== reportReceipt.completedAt ||
            !isDeepStrictEqual(material.branches, decision.deferral.branches)) {
          throw new Error('deferral-source-mismatch');
        }
      } else if (value.kind === 'proposal') {
        const snapshot = material.github;
        if (!snapshot || !proof.samePullSnapshot(snapshot.before, snapshot.after) ||
            !Array.isArray(snapshot.files) ||
            Buffer.byteLength(JSON.stringify(snapshot)) > 8 * 1024 * 1024) {
          throw new Error('proposal-snapshot-invalid');
        }
        const candidate = proof.candidate(item, event, [{ receipt: reportReceipt, report }]);
        const baseBranch = ledger.inventory.provenance.repositories.find((source) =>
          source.repository === item.repository)?.baseBranch;
        const replay = proof.proposalProof(item, event, candidate, snapshot.after,
          snapshot.files, material.observedAt, baseBranch, snapshot);
        const { source, sha256: hash, ...claim } = value;
        if (!replay || !isDeepStrictEqual(replay.claim, claim) ||
            !isDeepStrictEqual(replay.material, material)) {
          throw new Error('proposal-source-mismatch');
        }
      } else throw new Error('unknown-outcome-kind');
    }
    tasks.delete(reportReceipt.podUid);
  }
  if (tasks.size) throw new Error('missing-raw-report');
  return { mode: 'source-review', status: aggregate.status,
    sourceLinks, manualReviewItems: manual, eligibleEvents: aggregate.eligibleEvents,
    onTime: aggregate.onTime, late: aggregate.late,
    humanReviewRequired: true };
}

if (require.main === module) {
  try { console.log(JSON.stringify(sourceReview())); } catch {
    console.error(JSON.stringify({ mode: 'source-review', status: 'inconclusive',
      error: 'private-source-verification-failed' }));
    process.exitCode = 1;
  }
}

module.exports = { privateBytes, evidence, sourceReview };
