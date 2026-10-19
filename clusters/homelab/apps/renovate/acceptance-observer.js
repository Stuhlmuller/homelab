const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');

const owner = 'Stuhlmuller';
const ledgerDir = '/ledger/private';
const inventoryPath = path.join(ledgerDir, 'inventory.json');
const ledgerPath = path.join(ledgerDir, 'ledger.json');
const sampleSize = 5;

function digest(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function sampleKey(item) {
  return [item.repository, item.datasource, item.packageName, item.registryUrl || '',
    item.currentValue || '', item.sourceVisibility].join('\0');
}

function selectSample(inventory) {
  if (inventory.schema !== 1 || inventory.owner !== owner ||
      !/^[a-zA-Z0-9_-]{8,64}$/.test(inventory.seed) ||
      !Array.isArray(inventory.activeDatasources) || !inventory.activeDatasources.length ||
      !Array.isArray(inventory.dependencies) || !inventory.dependencies.length ||
      inventory.provenance?.method !== 'renovate-extract' ||
      !/^[a-f0-9]{40}$/.test(inventory.provenance.headSha)) {
    throw new Error('invalid-inventory');
  }
  const classes = new Set(inventory.activeDatasources);
  if (classes.size !== inventory.activeDatasources.length ||
      [...classes].some((name) => !/^[a-z0-9-]+$/.test(name))) {
    throw new Error('invalid-classes');
  }
  const strata = new Map();
  const keys = new Set();
  for (const item of inventory.dependencies) {
    if (item.controlledCanary === true ||
        item.packageFile === 'scripts/fixtures/renovate-cache-canary.txt' ||
        (item.datasource === 'github-releases' && item.packageName?.toLowerCase() === 'stuhlmuller/renovate')) continue;
    if (typeof item.repository !== 'string' || !item.repository.startsWith(`${owner}/`) ||
        !classes.has(item.datasource) || !item.packageName ||
        !['public', 'private'].includes(item.sourceVisibility) ||
        (item.registryUrl && !/^https:\/\//.test(item.registryUrl)) ||
        (item.currentValue && typeof item.currentValue !== 'string')) {
      throw new Error('invalid-dependency');
    }
    const key = sampleKey(item);
    if (keys.has(key)) continue;
    keys.add(key);
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
      events: [],
    });
  }
  if ([...classes].some((name) => ![...strata.keys()].some((key) => key.startsWith(`${name}:`)))) {
    throw new Error('missing-datasource-class');
  }
  const sample = [...strata.values()].flatMap((items) => items
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

function recordPoll(ledger, results, at) {
  let healthy = 0;
  let failed = 0;
  let events = 0;
  for (const item of ledger.sample) {
    const result = results.get(item.key);
    if (!result || !Array.isArray(result.releases) || !result.releases.length ||
        result.releases.some((release) => typeof release.version !== 'string')) {
      failed++;
      continue;
    }
    healthy++;
    const seen = new Set(item.seen);
    const versions = new Map(result.releases.map((release) => [digest(release.version), release.version]));
    if (item.lastHealthyAt) {
      for (const [hash, version] of versions) {
        if (!seen.has(hash)) {
          item.events.push({ version, lastAbsent: item.lastHealthyAt, firstPresent: at });
          events++;
        }
      }
    }
    item.seen = [...versions.keys()];
    item.lastHealthyAt = at;
  }
  ledger.polls.push({ at, healthy, failed, events });
  return { healthy, failed, events };
}

function aggregate(ledger) {
  const strata = { public: 0, private: 0 };
  for (const item of ledger.sample) strata[item.sourceVisibility]++;
  return {
    classes: new Set(ledger.sample.map((item) => item.datasource)).size,
    sample: ledger.sample.length,
    strata,
    polls: ledger.polls.length,
    failedSources: ledger.polls.reduce((sum, poll) => sum + poll.failed, 0),
    bracketedEvents: ledger.sample.reduce((sum, item) => sum + item.events.length, 0),
  };
}

function privateDirectory() {
  fs.mkdirSync(ledgerDir, { recursive: true, mode: 0o700 });
  if ((fs.statSync(ledgerDir).mode & 0o077) !== 0) throw new Error('ledger-permissions');
}

function saveLedger(ledger, create = false) {
  const target = create ? ledgerPath : `${ledgerPath}.new`;
  fs.writeFileSync(target, `${JSON.stringify(ledger)}\n`, { flag: create ? 'wx' : 'w', mode: 0o600 });
  if (!create) fs.renameSync(target, ledgerPath);
}

async function readToken() {
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
  const permissions = { contents: 'read', metadata: 'read' };
  const result = await github(`/app/installations/${installation.id}/access_tokens`, jwt, 'POST', { permissions });
  if (typeof result.token !== 'string' || !result.token.startsWith('ghs_') ||
      Date.parse(result.expires_at) - Date.now() < 10 * 60 * 1000 ||
      !result.permissions || Object.values(result.permissions).some((value) => value !== 'read')) {
    throw new Error('read-token-invalid');
  }
  return result.token;
}

function renovateRoot() {
  for (const candidate of ['/usr/src/app/node_modules/renovate', '/usr/local/lib/node_modules/renovate']) {
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
      try {
        // Call the datasource directly: Renovate's package-cache wrapper is never invoked.
        const registryUrl = item.registryUrl || datasource.getDefaultRegistryUrls(item.packageName)?.[0];
        const result = await datasource.getReleases({
          datasource: item.datasource,
          packageName: item.packageName,
          registryUrl,
          currentValue: item.currentValue || undefined,
        });
        results.set(item.key, result);
      } catch {
        results.set(item.key, null);
      }
    }
  } finally {
    process.stdout.write = stdout;
    process.stderr.write = stderr;
  }
  const counts = recordPoll(ledger, results, new Date().toISOString());
  saveLedger(ledger);
  console.log(JSON.stringify({ mode: 'poll', ...counts }));
  if (counts.failed) process.exitCode = 1;
}

async function main() {
  privateDirectory();
  const mode = process.argv[2];
  if (mode === 'seed') {
    const inventory = JSON.parse(fs.readFileSync(inventoryPath, 'utf8'));
    const ledger = selectSample(inventory);
    saveLedger(ledger, true);
    console.log(JSON.stringify({ mode, ...aggregate(ledger) }));
  } else if (mode === 'poll') {
    const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
    await poll(ledger);
  } else if (mode === 'report') {
    console.log(JSON.stringify({ mode, ...aggregate(JSON.parse(fs.readFileSync(ledgerPath, 'utf8'))) }));
  } else {
    throw new Error('invalid-mode');
  }
}

if (require.main === module) {
  main().catch((error) => {
    // Error details may contain private package names, URLs, or credentials.
    console.error(JSON.stringify({ mode: process.argv[2] || 'unknown', error: error.message.startsWith('invalid-') ? 'invalid-input' : 'observer-failed' }));
    process.exitCode = 1;
  });
}

module.exports = { selectSample, recordPoll, aggregate, readToken, datasourceApi };
