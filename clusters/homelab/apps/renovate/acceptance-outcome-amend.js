// Adds reviewed non-eligible classifications after all acceptance writers drain.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const observer = require('./acceptance-observer.js');

const ledgerDir = '/ledger/private';
const reviewSource = '/review/review.json';
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const validTime = (value) => typeof value === 'string' &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;
const exactKeys = (value, keys) => value && typeof value === 'object' &&
  !Array.isArray(value) && isDeepStrictEqual(Object.keys(value).sort(), [...keys].sort());

function privateBytes(file, limit) {
  const metadata = fs.lstatSync(file);
  if (!metadata.isFile() || metadata.nlink !== 1 || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077) || !metadata.size || metadata.size > limit) {
    throw new Error('invalid-private-file');
  }
  return fs.readFileSync(file);
}

function evidence(directory, entry, kind, claim, material) {
  const bytes = Buffer.from(`${JSON.stringify({ schema: 1, key: entry.key,
    version: entry.version, kind, claim, material })}\n`);
  const hash = sha256(bytes);
  const source = `evidence/${kind}-${hash}.json`;
  return { file: path.join(directory, source), bytes,
    value: { ...claim, source, sha256: hash },
    id: JSON.stringify([entry.key, entry.version, kind, source, hash]) };
}

function reviewedSource(source) {
  if (!exactKeys(source, ['ref', 'observedAt', 'sha256', 'record']) ||
      typeof source.ref !== 'string' || !/^private:\/\/[A-Za-z0-9][^\s]{0,199}$/.test(source.ref) ||
      !validTime(source.observedAt) || Date.parse(source.observedAt) > Date.now() ||
      !source.record || typeof source.record !== 'object' || Array.isArray(source.record) ||
      !Object.keys(source.record).length ||
      Buffer.byteLength(JSON.stringify(source.record)) > 32768 ||
      source.sha256 !== sha256(JSON.stringify(source.record))) {
    throw new Error('invalid-reviewed-source');
  }
  return source;
}

function buildReceipt(entry, event, ledger, review, directory) {
  const status = entry?.eligibility?.status;
  if (!exactKeys(entry, status === 'excluded-outage' ?
    ['key', 'version', 'lastAbsent', 'firstPresent', 'eligibility', 'exclusion', 'source'] :
    ['key', 'version', 'lastAbsent', 'firstPresent', 'eligibility', 'source']) ||
      entry.lastAbsent !== event.lastAbsent || entry.firstPresent !== event.firstPresent ||
      typeof entry.key !== 'string' || typeof entry.version !== 'string' ||
      !entry.version || !validTime(entry.eligibility?.verifiedAt) ||
      Date.parse(entry.eligibility.verifiedAt) > Date.now() ||
      !['policy-ineligible', 'excluded-outage'].includes(status) ||
      !exactKeys(entry.eligibility, status === 'policy-ineligible' ?
        ['status', 'verifiedAt', 'reason'] : ['status', 'verifiedAt'])) {
    throw new Error('invalid-classification');
  }
  const source = reviewedSource(entry.source);
  if (Date.parse(source.observedAt) > Date.parse(entry.eligibility.verifiedAt)) {
    throw new Error('invalid-reviewed-source');
  }
  const material = { provenance: 'owner-reviewed-private-source-v1',
    inventorySha256: ledger.inventorySha256, reviewSha256: ledger.reviewSha256,
    configSha256: review.configSha256, key: entry.key, version: entry.version,
    lastAbsent: event.lastAbsent, firstPresent: event.firstPresent, source };
  const eligibility = { status: entry.eligibility.status,
    verifiedAt: entry.eligibility.verifiedAt };
  if (eligibility.status === 'policy-ineligible') {
    if (typeof entry.eligibility.reason !== 'string' ||
        !entry.eligibility.reason.trim() || entry.eligibility.reason.length > 512) {
      throw new Error('invalid-classification');
    }
    eligibility.reason = entry.eligibility.reason;
  } else if (!exactKeys(entry.exclusion,
    ['reason', 'startAt', 'endAt', 'affectedAt', 'impact', 'verifiedAt'])) {
    throw new Error('invalid-classification');
  }
  const files = [evidence(directory, entry, 'eligibility', eligibility, material)];
  const receipt = { key: entry.key, version: entry.version,
    eligibility: files[0].value };
  if (eligibility.status === 'excluded-outage') {
    const { reason, startAt, endAt, affectedAt, impact, verifiedAt } = entry.exclusion;
    if (!['source-outage', 'github-outage', 'maintenance'].includes(reason) ||
        ![startAt, endAt, affectedAt, verifiedAt].every(validTime) ||
        Date.parse(verifiedAt) > Date.now() ||
        Date.parse(source.observedAt) > Date.parse(verifiedAt) ||
        typeof impact !== 'string' || !impact.trim() || impact.length > 512) {
      throw new Error('invalid-exclusion');
    }
    files.push(evidence(directory, entry, 'exclusion',
      { reason, startAt, endAt, affectedAt, impact, verifiedAt }, material));
    receipt.exclusion = files[1].value;
  }
  return { receipt, files };
}

function amend(directory = ledgerDir, inputFile = reviewSource, checkOnly = false) {
  observer.privateDirectory(false, directory);
  const ledger = JSON.parse(privateBytes(path.join(directory, 'ledger.json'), 128 * 1024 * 1024));
  observer.verifyFrozenSample(ledger);
  const review = JSON.parse(privateBytes(path.join(directory, 'review.json'), 900 * 1024));
  if (ledger.reviewSha256 !== sha256(JSON.stringify(review)) ||
      !/^[a-f0-9]{64}$/.test(review.configSha256 || '') ||
      review.windowStart !== ledger.windowStart || review.windowEnd !== ledger.windowEnd) {
    throw new Error('invalid-frozen-review');
  }
  // Kubernetes Secret projection uses symlinks and group-readable files.
  const inputMetadata = fs.statSync(inputFile);
  if (!fs.realpathSync(inputFile).startsWith(`${fs.realpathSync(path.dirname(inputFile))}${path.sep}`) ||
      !inputMetadata.isFile() || (inputMetadata.mode & 0o007) ||
      !inputMetadata.size || inputMetadata.size > 900 * 1024) throw new Error('invalid-review-input');
  const input = JSON.parse(fs.readFileSync(inputFile));
  if (!exactKeys(input, ['schema', 'owner', 'inventorySha256', 'reviewSha256',
    'configSha256', 'windowStart', 'windowEnd', 'classifications']) ||
      input.schema !== 1 || input.owner !== 'Stuhlmuller' ||
      input.inventorySha256 !== ledger.inventorySha256 ||
      input.reviewSha256 !== ledger.reviewSha256 ||
      input.configSha256 !== review.configSha256 ||
      input.windowStart !== ledger.windowStart || input.windowEnd !== ledger.windowEnd ||
      !Array.isArray(input.classifications) || !input.classifications.length ||
      input.classifications.length > 500) throw new Error('invalid-review-input');

  const outcomesPath = path.join(directory, 'outcomes.json');
  let original = null;
  try { original = privateBytes(outcomesPath, 128 * 1024 * 1024); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const outcomes = original ? JSON.parse(original) :
    { schema: 1, inventorySha256: ledger.inventorySha256, receipts: [] };
  const existingEvidence = observer.verifyPrivateEvidence(outcomes, directory);
  for (const receipt of outcomes.receipts) {
    for (const kind of ['eligibility', 'outcome', 'exclusion']) {
      const value = receipt[kind];
      if (!value || (kind === 'eligibility' && value.status === 'unknown')) continue;
      if (!existingEvidence.has(JSON.stringify([receipt.key, receipt.version, kind,
        value.source, value.sha256]))) throw new Error('invalid-existing-evidence');
    }
  }
  observer.aggregateReport(ledger, outcomes, existingEvidence);
  const byEvent = new Map(outcomes.receipts.map((receipt) =>
    [JSON.stringify([receipt.key, receipt.version]), receipt]));
  const events = new Map();
  for (const item of ledger.sample) {
    for (const event of item.events) {
      const id = JSON.stringify([item.key, event.version]);
      if (events.has(id)) throw new Error('duplicate-ledger-event');
      events.set(id, event);
    }
  }
  const { start, end } = observer.windowBounds(ledger);
  const files = new Map();
  const verified = new Set(existingEvidence);
  const seen = new Set();
  let applied = 0;
  let unchanged = 0;
  for (const entry of input.classifications) {
    const id = JSON.stringify([entry?.key, entry?.version]);
    if (seen.has(id)) throw new Error('duplicate-classification');
    seen.add(id);
    const event = events.get(id);
    if (!event || Date.parse(event.lastAbsent) < start ||
        Date.parse(event.firstPresent) > end) throw new Error('unknown-or-boundary-event');
    const candidate = buildReceipt(entry, event, ledger, review, directory);
    for (const file of candidate.files) {
      if (files.has(file.file) && !files.get(file.file).equals(file.bytes)) {
        throw new Error('evidence-collision');
      }
      files.set(file.file, file.bytes);
      verified.add(file.id);
    }
    const classification = observer.classifyReceipt(candidate.receipt, event, verified);
    if (classification.kind !== entry.eligibility.status || classification.incomplete) {
      throw new Error('invalid-classification-evidence');
    }
    const current = byEvent.get(id);
    if (current && isDeepStrictEqual(current, candidate.receipt)) {
      unchanged++;
      continue;
    }
    if (current && !isDeepStrictEqual(current,
      { key: entry.key, version: entry.version, eligibility: { status: 'unknown' } })) {
      throw new Error('classification-conflict');
    }
    if (current) {
      const index = outcomes.receipts.indexOf(current);
      outcomes.receipts[index] = candidate.receipt;
    } else outcomes.receipts.push(candidate.receipt);
    byEvent.set(id, candidate.receipt);
    applied++;
  }
  observer.aggregateReport(ledger, outcomes, verified);
  const output = `${JSON.stringify(outcomes)}\n`;
  if (Buffer.byteLength(output) > 128 * 1024 * 1024) throw new Error('outcomes-too-large');

  const evidenceDir = path.join(directory, 'evidence');
  let metadata;
  try { metadata = fs.lstatSync(evidenceDir); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (metadata && (!metadata.isDirectory() || metadata.uid !== process.getuid() ||
      (metadata.mode & 0o077))) throw new Error('invalid-evidence-directory');
  for (const [file, bytes] of files) {
    try {
      const current = privateBytes(file, 900 * 1024);
      if (!current.equals(bytes)) throw new Error('evidence-conflict');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  if (checkOnly) return { mode: 'outcome-amend-check', valid: true,
    prospective: applied, unchanged };
  if (!applied) return { mode: 'outcome-amend', applied, unchanged };
  if (!metadata) fs.mkdirSync(evidenceDir, { mode: 0o700 });
  for (const [file, bytes] of files) {
    if (fs.existsSync(file)) continue;
    const temporaryEvidence = `${file}.${crypto.randomUUID()}.tmp`;
    try {
      fs.writeFileSync(temporaryEvidence, bytes,
        { flag: 'wx', mode: 0o600, flush: true });
      if (fs.existsSync(file)) throw new Error('evidence-raced');
      fs.renameSync(temporaryEvidence, file);
    } finally {
      if (fs.existsSync(temporaryEvidence)) fs.unlinkSync(temporaryEvidence);
    }
  }
  const temporary = `${outcomesPath}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, output,
      { flag: 'wx', mode: 0o600, flush: true });
    let latest = null;
    try { latest = privateBytes(outcomesPath, 128 * 1024 * 1024); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if ((original === null) !== (latest === null) ||
        (original && !original.equals(latest))) throw new Error('outcomes-changed');
    fs.renameSync(temporary, outcomesPath);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  const persisted = JSON.parse(privateBytes(outcomesPath, 128 * 1024 * 1024));
  observer.aggregateReport(ledger, persisted, observer.verifyPrivateEvidence(persisted, directory));
  return { mode: 'outcome-amend', applied, unchanged };
}

if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    if (args.length > 1 || (args.length === 1 && args[0] !== '--check-only')) {
      throw new Error('invalid-mode');
    }
    console.log(JSON.stringify(amend(ledgerDir, reviewSource, args.length === 1)));
  } catch {
    console.error(JSON.stringify({ mode: 'outcome-amend', error: 'private-review-failed' }));
    process.exitCode = 1;
  }
}

module.exports = { amend, buildReceipt, reviewedSource };
