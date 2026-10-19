const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const observer = require('./acceptance-observer.js');

const owner = 'Stuhlmuller';
const privateDir = '/ledger/private';
const cacheDir = '/cache/renovate/renovate/repository/github';
const imageDigest = 'sha256:82f2a1375a48339c02f9a74b14f8468386c5c5e88ff10aa1674aae31df52969d';

function digest(value, algorithm = 'sha256') {
  return crypto.createHash(algorithm).update(value).digest('hex');
}

function canonicalRegistry(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('invalid-registry');
  }
  return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
}

function candidateKey(repository, baseBranch, manager, packageFile, index, dependency) {
  return digest(JSON.stringify([repository, baseBranch, manager, packageFile, index, dependency]));
}

function readCache(repository, baseBranch, expectedHash, root = cacheDir) {
  if (!new RegExp(`^${owner}/[A-Za-z0-9_.-]+$`).test(repository)) throw new Error('invalid-repository');
  const filename = path.join(root, `${repository}.json`);
  if (!fs.lstatSync(filename).isFile() || fs.statSync(filename).size > 100 * 1024 * 1024) {
    throw new Error('invalid-cache-file');
  }
  const record = JSON.parse(fs.readFileSync(filename, 'utf8'));
  if (record.revision !== 13 || record.repository !== repository ||
      !/^[a-f0-9]{128}$/.test(record.hash) || record.hash !== expectedHash ||
      typeof record.fingerprint !== 'string' || !record.fingerprint ||
      typeof record.payload !== 'string') throw new Error('invalid-cache-record');
  const raw = zlib.brotliDecompressSync(Buffer.from(record.payload, 'base64'),
    { maxOutputLength: 100 * 1024 * 1024 }).toString('utf8');
  if (digest(raw, 'sha512') !== record.hash) throw new Error('invalid-cache-hash');
  const scan = JSON.parse(raw).scan?.[baseBranch];
  if (scan?.revision !== 1 || !/^[a-f0-9]{40}$/.test(scan.sha) ||
      !/^[a-f0-9]{128}$/.test(scan.configHash) ||
      !scan.packageFiles || typeof scan.packageFiles !== 'object' ||
      Array.isArray(scan.packageFiles)) throw new Error('invalid-cache-extraction');
  return scan;
}

async function githubRepositories(token) {
  const repositories = [];
  const headers = {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'User-Agent': 'homelab-renovate-acceptance-inventory',
    'X-GitHub-Api-Version': '2022-11-28',
  };
  for (let page = 1; page <= 20; page++) {
    const response = await fetch(`https://api.github.com/installation/repositories?per_page=100&page=${page}`, {
      headers,
    });
    if (!response.ok) throw new Error('github-read-failed');
    const body = await response.json();
    if (!Array.isArray(body.repositories) || !Number.isSafeInteger(body.total_count)) {
      throw new Error('github-inventory-invalid');
    }
    repositories.push(...body.repositories);
    if (repositories.length === body.total_count) {
      for (const repository of repositories) {
        if (repository.owner?.login?.toLowerCase() !== owner.toLowerCase() || repository.archived) continue;
        const branch = await fetch(`https://api.github.com/repos/${repository.full_name}/branches/${encodeURIComponent(repository.default_branch)}`, {
          headers,
        });
        if (!branch.ok) throw new Error('github-branch-read-failed');
        repository.headSha = (await branch.json()).commit?.sha;
      }
      return repositories;
    }
    if (repositories.length > body.total_count || body.repositories.length !== 100) {
      throw new Error('github-inventory-incomplete');
    }
  }
  throw new Error('github-inventory-incomplete');
}

function buildInventory(review, scans, datasources, liveRepositories) {
  if (review?.schema !== 1 || review.owner !== owner ||
      !/^[A-Za-z0-9_-]{8,64}$/.test(review.seed) ||
      review.imageDigest !== imageDigest ||
      !/^[a-f0-9]{64}$/.test(review.configSha256) ||
      !Array.isArray(review.repositories) || !review.repositories.length ||
      !Array.isArray(review.classifications) || !review.classifications.length ||
      !Array.isArray(review.expectedStrata) || !review.expectedStrata.length ||
      !Array.isArray(review.ownerInventory?.repositories) ||
      typeof review.ownerInventory.source !== 'string' ||
      !review.ownerInventory.source.startsWith('private://') ||
      review.ownerInventory.sha256 !== digest(JSON.stringify(review.ownerInventory.repositories)) ||
      !Number.isFinite(Date.parse(review.ownerInventory.verifiedAt)) ||
      Date.now() - Date.parse(review.ownerInventory.verifiedAt) > 3600000 ||
      Date.parse(review.ownerInventory.verifiedAt) > Date.now()) {
    throw new Error('invalid-review');
  }
  const ownerVector = review.repositories.map(({ repository, baseBranch, headSha }) =>
    ({ repository, baseBranch, headSha })).sort((left, right) =>
    left.repository < right.repository ? -1 : left.repository > right.repository ? 1 : 0);
  if (JSON.stringify(ownerVector) !== JSON.stringify(review.ownerInventory.repositories)) {
    throw new Error('owner-inventory-parity');
  }
  const expected = new Map(review.repositories.map((entry) => [entry.repository, entry]));
  const live = liveRepositories.filter((entry) => entry.owner?.login?.toLowerCase() === owner.toLowerCase() &&
    !entry.archived);
  if (expected.size !== review.repositories.length || expected.size !== live.length ||
      live.some((entry) => !expected.has(entry.full_name))) throw new Error('repository-parity');
  const decisions = new Map(review.classifications.map((entry) => [entry.key, entry]));
  if (decisions.size !== review.classifications.length) throw new Error('duplicate-classification');
  const dependencies = [];
  const provenance = [];
  for (const [repository, entry] of [...expected].sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0)) {
    const liveRepo = live.find((item) => item.full_name === repository);
    const scan = scans.get(repository);
    if (!scan || entry.baseBranch !== liveRepo.default_branch ||
        entry.headSha !== liveRepo.headSha || scan.sha !== entry.headSha ||
        scan.configHash !== entry.configHash ||
        !/^[a-f0-9]{40}$/.test(entry.headSha) ||
        !/^[a-f0-9]{128}$/.test(entry.cacheHash) ||
        !/^[a-f0-9]{128}$/.test(entry.configHash) ||
        typeof entry.policyEvidence !== 'string' || !entry.policyEvidence.startsWith('private://')) {
      throw new Error('extraction-parity');
    }
    provenance.push({ repository, baseBranch: entry.baseBranch, headSha: entry.headSha,
      cacheSha512: entry.cacheHash, configHash: entry.configHash });
    for (const [manager, files] of Object.entries(scan.packageFiles)) {
      if (!Array.isArray(files)) throw new Error('invalid-package-files');
      for (const file of files) {
        if (typeof file.packageFile !== 'string' || !Array.isArray(file.deps)) {
          throw new Error('invalid-package-file');
        }
        for (const [index, dependency] of file.deps.entries()) {
          const key = candidateKey(repository, entry.baseBranch, manager, file.packageFile, index, dependency);
          const decision = decisions.get(key);
          if (!decision || !['sample', 'exclude'].includes(decision.decision) ||
              typeof decision.policyEvidence !== 'string' ||
              !decision.policyEvidence.startsWith('private://')) throw new Error('unreviewed-dependency');
          decisions.delete(key);
          if (decision.decision === 'exclude') {
            if (typeof decision.reason !== 'string' || !decision.reason) throw new Error('invalid-exclusion');
            continue;
          }
          const datasource = dependency.datasource || file.datasource;
          const packageName = dependency.packageName || dependency.depName;
          if (typeof datasource !== 'string' || !datasources.has(datasource) ||
              typeof packageName !== 'string' || !packageName ||
              !['public', 'private'].includes(decision.sourceVisibility) ||
              typeof decision.visibilityEvidence !== 'string' ||
              !decision.visibilityEvidence.startsWith('private://')) throw new Error('invalid-source');
          const urls = dependency.registryUrls ?? file.registryUrls ??
            datasources.get(datasource).getDefaultRegistryUrls(packageName);
          if (!Array.isArray(urls) || urls.length !== 1 || typeof urls[0] !== 'string') {
            throw new Error('ambiguous-registry');
          }
          const registryUrl = canonicalRegistry(urls[0]);
          if (decision.registryUrl !== registryUrl) throw new Error('registry-parity');
          const controlledCanary = file.packageFile === 'scripts/fixtures/renovate-cache-canary.txt' ||
            (datasource === 'github-releases' && packageName.toLowerCase() === 'stuhlmuller/renovate');
          if (decision.controlledCanary === true && !controlledCanary) {
            throw new Error('invalid-canary');
          }
          dependencies.push({ repository, datasource, packageName, registryUrl,
            currentValue: typeof dependency.currentValue === 'string' ? dependency.currentValue : undefined,
            sourceVisibility: decision.sourceVisibility, packageFile: file.packageFile,
            controlledCanary });
        }
      }
    }
  }
  if (decisions.size || !dependencies.length) throw new Error('inventory-incomplete');
  const classes = [...new Set(dependencies.filter((item) => !item.controlledCanary)
    .map((item) => item.datasource))].sort();
  const strata = new Map();
  for (const item of dependencies.filter((candidate) => !candidate.controlledCanary)) {
    const key = `${item.datasource}:${item.sourceVisibility}`;
    strata.set(key, (strata.get(key) || 0) + 1);
  }
  const expectedStrata = [...strata].sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, count]) => ({ datasource: key.split(':')[0], sourceVisibility: key.split(':')[1], count }));
  if (JSON.stringify(expectedStrata) !== JSON.stringify(review.expectedStrata)) {
    throw new Error('stratum-parity');
  }
  const inventory = { schema: 1, owner, seed: review.seed,
    provenance: { method: 'renovate-extract', repositories: provenance,
      sha256: digest(JSON.stringify(provenance)) },
    activeDatasources: classes, dependencies };
  return { inventory, ledger: observer.selectSample(inventory) };
}

function saveLedger(ledger, directory = privateDir) {
  const target = path.join(directory, 'ledger.json');
  const temporary = `${target}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, `${JSON.stringify(ledger)}\n`, { flag: 'wx', mode: 0o600 });
    fs.linkSync(temporary, target);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

async function main() {
  const directory = fs.lstatSync(privateDir);
  if (!directory.isDirectory() || (directory.mode & 0o077)) {
    throw new Error('invalid-ledger-permissions');
  }
  const reviewPath = path.join(privateDir, 'review.json');
  const metadata = fs.lstatSync(reviewPath);
  if (!metadata.isFile() || (metadata.mode & 0o077)) throw new Error('invalid-review-permissions');
  const review = JSON.parse(fs.readFileSync(reviewPath, 'utf8'));
  const ledgerPath = path.join(privateDir, 'ledger.json');
  if (fs.existsSync(ledgerPath)) {
    const existing = fs.lstatSync(ledgerPath);
    if (!existing.isFile() || (existing.mode & 0o077)) throw new Error('invalid-ledger-permissions');
    const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
    if (ledger.reviewSha256 !== digest(JSON.stringify(review)) ||
        ledger.inventorySha256 !== digest(JSON.stringify(ledger.inventory))) {
      throw new Error('sample-already-frozen');
    }
    console.log(JSON.stringify({ mode: 'inventory-seed', status: 'already-frozen',
      repositories: ledger.inventory.provenance.repositories.length,
      classes: ledger.inventory.activeDatasources.length,
      candidates: ledger.inventory.dependencies.length, selected: ledger.sample.length }));
    return;
  }
  if (digest(fs.readFileSync('/usr/src/app/config.js')) !== review.configSha256) {
    throw new Error('config-parity');
  }
  const token = await observer.readToken();
  const [datasources, live] = await Promise.all([
    observer.datasourceApi(token), githubRepositories(token),
  ]);
  const scans = new Map();
  for (const entry of review.repositories || []) {
    scans.set(entry.repository, readCache(entry.repository, entry.baseBranch, entry.cacheHash));
  }
  const { inventory, ledger } = buildInventory(review, scans, datasources, live);
  ledger.inventory = inventory;
  ledger.reviewSha256 = digest(JSON.stringify(review));
  saveLedger(ledger);
  console.log(JSON.stringify({ mode: 'inventory-seed', repositories: review.repositories.length,
    classes: inventory.activeDatasources.length, candidates: inventory.dependencies.length,
    selected: ledger.sample.length }));
}

if (require.main === module) main().catch(() => {
  console.error(JSON.stringify({ mode: 'inventory-seed', error: 'verification-failed' }));
  process.exitCode = 1;
});

module.exports = { candidateKey, canonicalRegistry, readCache, buildInventory, saveLedger };
