const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { isDeepStrictEqual } = require('node:util');

const owner = 'Stuhlmuller';
const ledgerDir = '/ledger/private';
const ledgerPath = path.join(ledgerDir, 'ledger.json');
const outcomesPath = path.join(ledgerDir, 'outcomes.json');
const sampleSize = 5;

function digest(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function sampleKey(item) {
  return [item.repository, item.datasource, item.packageName, item.registryUrl || '',
    item.currentValue || '', item.sourceVisibility].join('\0');
}

function sourceKey(item) {
  if (typeof item.registryUrl !== 'string' || !item.registryUrl) throw new Error('invalid-registry');
  let url;
  try { url = new URL(item.registryUrl); } catch { throw new Error('invalid-registry'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('invalid-registry');
  }
  const registry = `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
  const packageName = ['github-releases', 'github-tags'].includes(item.datasource) ?
    item.packageName.toLowerCase() : item.packageName;
  return [item.datasource, packageName, registry].join('\0');
}

function selectSample(inventory) {
  if (inventory.schema !== 1 || inventory.owner !== owner ||
      !/^[a-zA-Z0-9_-]{8,64}$/.test(inventory.seed) ||
      !Array.isArray(inventory.activeDatasources) || !inventory.activeDatasources.length ||
      !Array.isArray(inventory.dependencies) || !inventory.dependencies.length ||
      inventory.provenance?.method !== 'renovate-extract' ||
      !Array.isArray(inventory.provenance.repositories) || !inventory.provenance.repositories.length ||
      inventory.provenance.sha256 !== digest(JSON.stringify(inventory.provenance.repositories))) {
    throw new Error('invalid-inventory');
  }
  const heads = new Set();
  for (const entry of inventory.provenance.repositories) {
    if (typeof entry.repository !== 'string' || !entry.repository.startsWith(`${owner}/`) ||
        heads.has(entry.repository) || typeof entry.baseBranch !== 'string' || !entry.baseBranch ||
        !/^[a-f0-9]{40}$/.test(entry.headSha) ||
        !/^[a-f0-9]{128}$/.test(entry.cacheSha512) ||
        !/^[a-f0-9]{128}$/.test(entry.configHash)) throw new Error('invalid-inventory-head');
    heads.add(entry.repository);
  }
  const classes = new Set(inventory.activeDatasources);
  if (classes.size !== inventory.activeDatasources.length ||
      [...classes].some((name) => !/^[a-z0-9-]+$/.test(name))) {
    throw new Error('invalid-classes');
  }
  const strata = new Map();
  const sources = new Map();
  for (const item of inventory.dependencies) {
    if (item.controlledCanary === true ||
        item.packageFile === 'scripts/fixtures/renovate-cache-canary.txt' ||
        (item.datasource === 'github-releases' && item.packageName?.toLowerCase() === 'stuhlmuller/renovate')) continue;
    if (typeof item.repository !== 'string' || !item.repository.startsWith(`${owner}/`) ||
        !heads.has(item.repository) ||
        !classes.has(item.datasource) || typeof item.packageName !== 'string' || !item.packageName ||
        !['public', 'private'].includes(item.sourceVisibility) ||
        (item.currentValue && typeof item.currentValue !== 'string')) {
      throw new Error('invalid-dependency');
    }
    const key = sampleKey(item);
    const source = sourceKey(item);
    const rank = digest(`${inventory.seed}\0${key}`);
    const prior = sources.get(source);
    if (prior && prior.item.sourceVisibility !== item.sourceVisibility) {
      throw new Error('ambiguous-source-visibility');
    }
    if (!prior || rank < prior.rank) sources.set(source, { item, key, rank });
  }
  for (const { item, key } of sources.values()) {
    const stratum = `${item.datasource}:${item.sourceVisibility}`;
    if (!strata.has(stratum)) strata.set(stratum, []);
    strata.get(stratum).push({
      repository: item.repository,
      datasource: item.datasource,
      packageName: item.packageName,
      registryUrl: item.registryUrl || null,
      currentValue: item.currentValue || null,
      sourceVisibility: item.sourceVisibility,
      key: digest(key),
      seen: [],
      lastHealthyAt: null,
      lastHealthySlot: null,
      lastHealthyLate: false,
      failures: [],
      events: [],
    });
  }
  if ([...classes].some((name) => ![...strata.keys()].some((key) => key.startsWith(`${name}:`)))) {
    throw new Error('missing-datasource-class');
  }
  const sample = [...strata].sort(([left], [right]) => left.localeCompare(right)).flatMap(([, items]) => items
    .sort((a, b) => digest(`${inventory.seed}\0${a.key}`).localeCompare(digest(`${inventory.seed}\0${b.key}`)))
    .slice(0, sampleSize));
  return {
    schema: 1,
    seed: inventory.seed,
    inventorySha256: digest(JSON.stringify(inventory)),
    selectedAt: new Date().toISOString(),
    sample,
    polls: [],
  };
}

function recordPoll(ledger, results, at, startedAt = at) {
  const started = Date.parse(startedAt);
  if (!Number.isFinite(started) || !Number.isFinite(Date.parse(at))) throw new Error('invalid-poll-time');
  const slotAt = new Date(Math.floor(started / 900000) * 900000).toISOString();
  const late = started - Date.parse(slotAt) > 300000;
  let healthy = 0;
  let failed = 0;
  let events = 0;
  for (const item of ledger.sample) {
    const observation = results.get(item.key);
    const result = observation?.response;
    const startedAt = observation?.startedAt;
    const finishedAt = observation?.finishedAt;
    if (!result || !Array.isArray(result.releases) ||
        result.releases.some((release) => typeof release.version !== 'string') ||
        !startedAt || !finishedAt || !Number.isFinite(Date.parse(startedAt)) ||
        !Number.isFinite(Date.parse(finishedAt)) || startedAt > finishedAt) {
      failed++;
      const failureAt = Number.isFinite(Date.parse(finishedAt)) ? finishedAt : at;
      item.failures.push({ at: failureAt,
        status: observation?.status || (observation ? 'invalid-response' : 'missing-observation') });
      continue;
    }
    healthy++;
    const seen = new Set(item.seen);
    const versions = new Map(result.releases.map((release) => [digest(release.version), release.version]));
    if (item.lastHealthyAt) {
      for (const [hash, version] of versions) {
        if (!seen.has(hash)) {
          const previousSlot = Date.parse(item.lastHealthySlot);
          const ambiguous = item.failures.some((failure) =>
            failure.at > item.lastHealthyAt && failure.at <= finishedAt) ||
            !Number.isFinite(previousSlot) || Date.parse(slotAt) - previousSlot !== 900000 ||
            item.lastHealthyLate || late;
          item.events.push({ version, lastAbsent: item.lastHealthyAt, firstPresent: finishedAt, ambiguous });
          events++;
        }
      }
    }
    for (const hash of versions.keys()) seen.add(hash);
    item.seen = [...seen];
    // The request start is a conservative lower bound for a later unseen release.
    item.lastHealthyAt = startedAt;
    item.lastHealthySlot = slotAt;
    item.lastHealthyLate = late;
  }
  ledger.polls.push({ at, startedAt, slotAt, late, healthy, failed, events });
  return { healthy, failed, events };
}

function aggregate(ledger) {
  const strata = { public: 0, private: 0 };
  for (const item of ledger.sample) strata[item.sourceVisibility]++;
  let missedPolls = 0;
  for (let index = 1; index < ledger.polls.length; index++) {
    const gap = Date.parse(ledger.polls[index].slotAt) - Date.parse(ledger.polls[index - 1].slotAt);
    if (gap > 900000) missedPolls += gap / 900000 - 1;
  }
  return {
    classes: new Set(ledger.sample.map((item) => item.datasource)).size,
    sample: ledger.sample.length,
    strata,
    polls: ledger.polls.length,
    missedPolls,
    latePolls: ledger.polls.filter((poll) => poll.late).length,
    failedSources: ledger.polls.reduce((sum, poll) => sum + poll.failed, 0),
    bracketedEvents: ledger.sample.reduce((sum, item) => sum + item.events.length, 0),
    ambiguousEvents: ledger.sample.reduce((sum, item) =>
      sum + item.events.filter((event) => event.ambiguous).length, 0),
  };
}

function verifyFrozenSample(ledger) {
  if (!ledger?.inventory || !Array.isArray(ledger.sample) || !Array.isArray(ledger.polls) ||
      ledger.inventorySha256 !== digest(JSON.stringify(ledger.inventory))) {
    throw new Error('invalid-ledger');
  }
  const fields = ['repository', 'datasource', 'packageName', 'registryUrl',
    'currentValue', 'sourceVisibility', 'key'];
  const identities = (items) => items.map((item) => fields.map((field) => item?.[field]));
  if (!isDeepStrictEqual(identities(ledger.sample), identities(selectSample(ledger.inventory).sample))) {
    throw new Error('sample-changed');
  }
}

function validTime(value) {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function evidenceId(receipt, kind, value) {
  return JSON.stringify([receipt.key, receipt.version, kind, value.source, value.sha256]);
}

function evidenceShape(value) {
  return typeof value?.source === 'string' &&
    /^evidence\/[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.json$/.test(value.source) &&
    /^[a-f0-9]{64}$/.test(value.sha256) && validTime(value.verifiedAt);
}

function hasEvidenceFields(value, evidence, receipt, kind) {
  return evidenceShape(value) && evidence.has(evidenceId(receipt, kind, value));
}

function verifyPrivateEvidence(outcomes, directory = ledgerDir) {
  const verified = new Set();
  if (!outcomes) return verified;
  const evidenceDirectory = path.join(directory, 'evidence');
  let metadata;
  try {
    metadata = fs.lstatSync(evidenceDirectory);
  } catch (error) {
    if (error.code === 'ENOENT') return verified;
    throw error;
  }
  if (!metadata.isDirectory() || (metadata.mode & 0o077)) throw new Error('invalid-evidence-permissions');
  for (const receipt of outcomes.receipts || []) {
    for (const kind of ['eligibility', 'outcome', 'exclusion']) {
      const value = receipt?.[kind];
      if (!evidenceShape(value)) continue;
      const file = path.join(directory, value.source);
      try {
        metadata = fs.lstatSync(file);
      } catch (error) {
        if (error.code === 'ENOENT') continue;
        throw error;
      }
      if (!metadata.isFile() || (metadata.mode & 0o077)) throw new Error('invalid-evidence-permissions');
      const bytes = fs.readFileSync(file);
      if (digest(bytes) !== value.sha256) continue;
      let proof;
      try { proof = JSON.parse(bytes.toString('utf8')); } catch { continue; }
      const { source, sha256, ...claim } = value;
      if (proof?.schema === 1 && proof.key === receipt.key && proof.version === receipt.version &&
          proof.kind === kind && isDeepStrictEqual(proof.claim, claim) &&
          proof.material && typeof proof.material === 'object' &&
          Object.keys(proof.material).length) verified.add(evidenceId(receipt, kind, value));
    }
  }
  return verified;
}

function classifyReceipt(receipt, event, evidence) {
  const eligibility = receipt?.eligibility;
  if (!eligibility || eligibility.status === 'unknown') return { kind: 'unknown' };
  if (!hasEvidenceFields(eligibility, evidence, receipt, 'eligibility')) return { kind: 'unknown', incomplete: true };
  if (eligibility.status === 'policy-ineligible') {
    return typeof eligibility.reason === 'string' && eligibility.reason.trim()
      ? { kind: 'policy-ineligible' } : { kind: 'unknown', incomplete: true };
  }
  if (eligibility.status === 'excluded-outage') {
    const interval = receipt.exclusion;
    const start = Date.parse(interval?.startAt);
    const end = Date.parse(interval?.endAt);
    const lastAbsent = Date.parse(event.lastAbsent);
    const affectedAt = Date.parse(interval?.affectedAt);
    if (!['source-outage', 'github-outage', 'maintenance'].includes(interval?.reason) ||
        !hasEvidenceFields(interval, evidence, receipt, 'exclusion') || !validTime(interval.startAt) || !validTime(interval.endAt) ||
        !validTime(interval.affectedAt) || typeof interval.impact !== 'string' ||
        !interval.impact.trim() ||
        !(start < end && affectedAt >= start && affectedAt < end &&
          affectedAt >= lastAbsent && affectedAt <= lastAbsent + 4 * 3600000 &&
          Date.parse(interval.verifiedAt) >= end)) return { kind: 'unknown', incomplete: true };
    return { kind: 'excluded-outage' };
  }
  if (eligibility.status !== 'eligible') throw new Error('invalid-outcomes');
  const outcome = receipt.outcome;
  if (!outcome) return { kind: 'eligible', missing: true };
  const at = Date.parse(outcome.at);
  if (!['proposal', 'deferral'].includes(outcome.kind) || !validTime(outcome.at) ||
      !hasEvidenceFields(outcome, evidence, receipt, 'outcome') || at < Date.parse(event.lastAbsent) ||
      Date.parse(outcome.verifiedAt) < at ||
      (outcome.kind === 'deferral' &&
        (typeof outcome.reason !== 'string' || !outcome.reason.trim()))) {
    return { kind: 'eligible', missing: true, incomplete: true };
  }
  return { kind: 'eligible', at };
}

function aggregateReport(ledger, outcomes, evidence = new Set()) {
  const receipts = outcomes || { schema: 1, inventorySha256: ledger.inventorySha256, receipts: [] };
  if (receipts.schema !== 1 || receipts.inventorySha256 !== ledger.inventorySha256 ||
      !Array.isArray(receipts.receipts)) throw new Error('invalid-outcomes');
  const events = new Map();
  const releases = new Map();
  for (const item of ledger.sample) {
    for (const event of item.events) {
      if (typeof item.key !== 'string' || typeof event.version !== 'string' ||
          !validTime(event.lastAbsent) || !validTime(event.firstPresent) ||
          Date.parse(event.lastAbsent) >= Date.parse(event.firstPresent)) throw new Error('invalid-ledger');
      const id = JSON.stringify([item.key, event.version]);
      if (events.has(id)) throw new Error('invalid-ledger');
      events.set(id, event);
      const release = JSON.stringify([sourceKey(item), event.version]);
      if (!releases.has(release)) releases.set(release, []);
      releases.get(release).push({ item, event, id });
    }
  }
  const byEvent = new Map();
  for (const receipt of receipts.receipts) {
    const id = JSON.stringify([receipt?.key, receipt?.version]);
    if (!events.has(id) || byEvent.has(id)) throw new Error('invalid-outcomes');
    byEvent.set(id, receipt);
  }
  const counts = {
    naturalEvents: releases.size,
    eligibleEvents: 0,
    onTime: 0,
    late: 0,
    missingOutcomes: 0,
    policyIneligible: 0,
    excludedIntervals: 0,
    unknownEvents: 0,
    incompleteEvidence: 0,
    ambiguousEvents: 0,
  };
  for (const members of releases.values()) {
    const classifications = members.map(({ id, event }) => classifyReceipt(byEvent.get(id), event, evidence));
    const lastAbsent = Math.min(...members.map(({ event }) => Date.parse(event.lastAbsent)));
    if (members.some(({ event }) => event.ambiguous) ||
        new Set(members.map(({ item }) => item.sourceVisibility)).size !== 1 ||
        Math.max(...members.map(({ event }) => Date.parse(event.lastAbsent))) >=
          Math.min(...members.map(({ event }) => Date.parse(event.firstPresent)))) {
      counts.ambiguousEvents++;
    }
    if (classifications.some(({ incomplete }) => incomplete)) counts.incompleteEvidence++;
    if (classifications.some(({ kind }) => kind === 'unknown')) counts.unknownEvents++;
    const eligible = classifications.filter(({ kind }) => kind === 'eligible');
    if (eligible.length) {
      counts.eligibleEvents++;
      if (eligible.some(({ missing }) => missing) || classifications.some(({ kind }) => kind === 'unknown')) {
        counts.missingOutcomes++;
      } else if (Math.max(...eligible.map(({ at }) => at)) - lastAbsent <= 4 * 3600000) {
        counts.onTime++;
      } else counts.late++;
    } else if (classifications.every(({ kind }) => kind === 'policy-ineligible')) {
      counts.policyIneligible++;
    } else if (classifications.some(({ kind }) => kind === 'excluded-outage') &&
        !classifications.some(({ kind }) => kind === 'unknown')) {
      counts.excludedIntervals++;
    }
  }
  let status = 'review-required';
  if (counts.eligibleEvents < 10 || counts.ambiguousEvents || counts.unknownEvents ||
      counts.incompleteEvidence) status = 'inconclusive';
  else if (counts.onTime * 100 < counts.eligibleEvents * 95) status = 'criteria-not-met';
  return {
    mode: 'report',
    ...aggregate(ledger),
    ...counts,
    onTimePercent: counts.eligibleEvents ? Math.floor(counts.onTime / counts.eligibleEvents * 10000) / 100 : null,
    status,
  };
}

function readPrivateOutcomes() {
  let metadata;
  try {
    metadata = fs.lstatSync(outcomesPath);
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  if (!metadata.isFile() || (metadata.mode & 0o077)) throw new Error('invalid-outcomes-permissions');
  return JSON.parse(fs.readFileSync(outcomesPath, 'utf8'));
}

function privateDirectory() {
  fs.mkdirSync(ledgerDir, { recursive: true, mode: 0o700 });
  if ((fs.statSync(ledgerDir).mode & 0o077) !== 0) throw new Error('ledger-permissions');
}

function saveLedger(ledger) {
  const target = `${ledgerPath}.new`;
  fs.writeFileSync(target, `${JSON.stringify(ledger)}\n`, { flag: 'w', mode: 0o600 });
  fs.renameSync(target, ledgerPath);
}

async function readToken(permissions = { contents: 'read', metadata: 'read' }) {
  if (!permissions || !Object.keys(permissions).length ||
      Object.values(permissions).some((value) => value !== 'read')) {
    throw new Error('read-token-permissions');
  }
  let issuer;
  let privateKey;
  try {
    issuer = fs.readFileSync('/var/run/secrets/renovate/issuer-id', 'utf8').trim();
    privateKey = fs.readFileSync('/var/run/secrets/renovate/private-key', 'utf8');
  } catch {
    throw new Error('app-credential-unreadable');
  }
  if (!issuer || !privateKey.trim()) throw new Error('app-credential-empty');
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ iat: now - 60, exp: now + 540, iss: issuer })).toString('base64url');
  const input = `${header}.${payload}`;
  let jwt;
  try {
    jwt = `${input}.${crypto.sign('RSA-SHA256', Buffer.from(input), privateKey).toString('base64url')}`;
  } catch {
    throw new Error('app-credential-invalid');
  }
  async function github(route, token, method = 'GET', body) {
    const response = await fetch(`https://api.github.com${route}`, {
      method,
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'User-Agent': 'homelab-renovate-acceptance-observer',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: body && JSON.stringify(body),
    });
    if (!response.ok) throw new Error('github-read-failed');
    return response.json();
  }
  const installation = await github(`/orgs/${owner}/installation`, jwt);
  if (!Number.isSafeInteger(installation.id) || installation.account?.login?.toLowerCase() !== owner.toLowerCase() ||
      installation.repository_selection !== 'all') throw new Error('installation-coverage');
  const result = await github(`/app/installations/${installation.id}/access_tokens`, jwt, 'POST', { permissions });
  if (typeof result.token !== 'string' || !result.token.startsWith('ghs_') ||
      Date.parse(result.expires_at) - Date.now() < 10 * 60 * 1000 ||
      !result.permissions || Object.values(result.permissions).some((value) => value !== 'read') ||
      Object.keys(permissions).some((key) => result.permissions[key] !== 'read')) {
    throw new Error('read-token-invalid');
  }
  return result.token;
}

function renovateRoot() {
  for (const candidate of ['/usr/local/renovate', '/usr/src/app/node_modules/renovate',
    '/usr/local/lib/node_modules/renovate']) {
    if (fs.existsSync(path.join(candidate, 'dist/modules/datasource/api.js'))) return fs.realpathSync(candidate);
  }
  for (const directory of (process.env.PATH || '').split(path.delimiter)) {
    try {
      let current = path.dirname(fs.realpathSync(path.join(directory, 'renovate')));
      while (current !== path.dirname(current)) {
        const manifest = path.join(current, 'package.json');
        if (fs.existsSync(manifest) && JSON.parse(fs.readFileSync(manifest, 'utf8')).name === 'renovate' &&
            fs.existsSync(path.join(current, 'dist/modules/datasource/api.js'))) return current;
        current = path.dirname(current);
      }
    } catch { /* Try the next executable directory. */ }
  }
  throw new Error('renovate-package-unavailable');
}

async function datasourceApi(token) {
  const root = renovateRoot();
  const imported = async (relative) => import(pathToFileURL(path.join(root, 'dist', relative)).href);
  const [{ default: datasources }, { GlobalConfig }, hostRules, logger] = await Promise.all([
    imported('modules/datasource/api.js'),
    imported('config/global.js'),
    imported('util/host-rules.js'),
    imported('logger/index.js'),
  ]);
  await logger.init();
  logger.levels('stdout', 'fatal');
  GlobalConfig.set({ platform: 'github', cacheDir: '/tmp/renovate-observer', cachePrivatePackages: false });
  hostRules.add({ matchHost: 'api.github.com', token });
  hostRules.add({ matchHost: 'github.com', token });
  return datasources;
}

async function poll(ledger) {
  const cycleStartedAt = new Date().toISOString();
  const results = new Map();
  const stdout = process.stdout.write;
  const stderr = process.stderr.write;
  process.stdout.write = () => true;
  process.stderr.write = () => true;
  try {
    const datasources = await datasourceApi(await readToken());
    for (const item of ledger.sample) {
      const datasource = datasources.get(item.datasource);
      if (!datasource) throw new Error('unsupported-datasource');
      const startedAt = new Date().toISOString();
      try {
        // Call the datasource directly: Renovate's package-cache wrapper is never invoked.
        const registryUrl = item.registryUrl || datasource.getDefaultRegistryUrls(item.packageName)?.[0];
        const result = await datasource.getReleases({
          datasource: item.datasource,
          packageName: item.packageName,
          registryUrl,
          currentValue: item.currentValue || undefined,
        });
        results.set(item.key, { response: result, startedAt, finishedAt: new Date().toISOString() });
      } catch {
        results.set(item.key, { response: null, startedAt, finishedAt: new Date().toISOString(), status: 'request-error' });
      }
    }
  } catch {
    results.clear();
    const finishedAt = new Date().toISOString();
    for (const item of ledger.sample) {
      results.set(item.key, { response: null, startedAt: cycleStartedAt,
        finishedAt, status: 'global-error' });
    }
  } finally {
    process.stdout.write = stdout;
    process.stderr.write = stderr;
  }
  const counts = recordPoll(ledger, results, new Date().toISOString(), cycleStartedAt);
  saveLedger(ledger);
  console.log(JSON.stringify({ mode: 'poll', ...counts }));
  if (counts.failed) process.exitCode = 1;
}

async function main() {
  const mode = process.argv[2];
  if (mode !== 'poll' && mode !== 'report') throw new Error('invalid-mode');
  privateDirectory();
  const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
  verifyFrozenSample(ledger);
  if (mode === 'poll') {
    await poll(ledger);
  } else {
    const outcomes = readPrivateOutcomes();
    console.log(JSON.stringify(aggregateReport(ledger, outcomes, verifyPrivateEvidence(outcomes))));
  }
}

if (require.main === module) {
  main().catch((error) => {
    // Error details may contain private package names, URLs, or credentials.
    console.error(JSON.stringify({ mode: process.argv[2] || 'unknown', error: error.message.startsWith('invalid-') ? 'invalid-input' : 'observer-failed' }));
    process.exitCode = 1;
  });
}

module.exports = { selectSample, recordPoll, aggregate, aggregateReport, verifyFrozenSample,
  readPrivateOutcomes,
  verifyPrivateEvidence,
  readToken, renovateRoot, datasourceApi, poll };
