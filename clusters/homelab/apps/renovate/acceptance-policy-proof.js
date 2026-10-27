const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const observer = require('./acceptance-observer.js');
const inventory = require('./acceptance-inventory.js');

const owner = 'Stuhlmuller';
const privateDir = '/ledger/private';
const podUidFile = '/var/run/podinfo/uid';
const planUnavailable = Symbol('github-private-protection-plan-unavailable');
const planMessage = 'Upgrade to GitHub Pro or make this repository public to enable this feature.';
const entitlementRoutes = Object.freeze({
  rules: {
    route: /^\/repos\/Stuhlmuller\/[A-Za-z0-9_.-]+\/rules\/branches\/[^/?]+\?per_page=100$/,
    documentation: 'https://docs.github.com/rest/repos/rules#get-rules-for-a-branch',
  },
  classic: {
    route: /^\/repos\/Stuhlmuller\/[A-Za-z0-9_.-]+\/branches\/[^/?]+\/protection$/,
    documentation: 'https://docs.github.com/rest/branches/branch-protection#get-branch-protection',
  },
});
// Pinned Renovate 44.167.4 getConfigFileNames('github') order.
const configFiles = Object.freeze([
  'renovate.json', 'renovate.jsonc', 'renovate.json5',
  '.github/renovate.json', '.github/renovate.jsonc', '.github/renovate.json5',
  '.renovaterc', '.renovaterc.json', '.renovaterc.jsonc', '.renovaterc.json5',
  'package.json',
]);
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');

async function github(token, route, allow404 = false, entitlement = null) {
  let response;
  try {
    response = await fetch(`https://api.github.com${route}`, {
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'User-Agent': 'homelab-renovate-acceptance-policy',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new Error('github-policy-read-failed');
  }
  const serverTime = Date.parse(response.headers.get('date'));
  if (!Number.isFinite(serverTime) || Math.abs(serverTime - Date.now()) > 60000) {
    throw new Error('github-clock-unverified');
  }
  if (allow404 && response.status === 404) return null;
  if (response.status === 403 && entitlement) {
    const expected = entitlementRoutes[entitlement];
    if (!expected?.route.test(route)) throw new Error('github-policy-read-failed');
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > 4096) throw new Error('github-policy-read-failed');
    let error;
    try {
      const body = await response.text();
      if (Buffer.byteLength(body) > 4096) throw new Error('oversized');
      error = JSON.parse(body);
    } catch {
      throw new Error('github-policy-read-failed');
    }
    if (error?.message === planMessage && error.status === '403' &&
        error.documentation_url === expected.documentation) return planUnavailable;
  }
  if (!response.ok) throw new Error('github-policy-read-failed');
  if (response.headers.get('link')?.includes('rel="next"')) {
    throw new Error('github-policy-response-paginated');
  }
  const length = Number(response.headers.get('content-length'));
  if (Number.isFinite(length) && length > 4 * 1024 * 1024) {
    throw new Error('github-policy-response-too-large');
  }
  const body = await response.text();
  if (Buffer.byteLength(body) > 4 * 1024 * 1024) throw new Error('github-policy-response-too-large');
  try { return JSON.parse(body); } catch { throw new Error('github-policy-json-invalid'); }
}

function configBytes(file) {
  if (file?.type !== 'file' || file.encoding !== 'base64' ||
      !Number.isSafeInteger(file.size) || file.size <= 0 || file.size > 1024 * 1024 ||
      typeof file.content !== 'string') throw new Error('invalid-repository-config');
  const encoded = file.content.replace(/\s/g, '');
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw new Error('invalid-repository-config');
  }
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.length !== file.size || bytes.toString('base64') !== encoded) {
    throw new Error('invalid-repository-config');
  }
  return bytes;
}

async function snapshotRepository(repository, get) {
  if (!new RegExp(`^${owner}/[A-Za-z0-9_.-]+$`).test(repository?.full_name) ||
      repository.private !== true || repository.archived ||
      typeof repository.default_branch !== 'string' || !repository.default_branch ||
      !/^[a-f0-9]{40}$/.test(repository.headSha || '')) {
    throw new Error('invalid-private-repository');
  }
  const route = `/repos/${repository.full_name}`;
  const branch = encodeURIComponent(repository.default_branch);
  const rules = await get(`${route}/rules/branches/${branch}?per_page=100`, false, 'rules');
  const classic = await get(`${route}/branches/${branch}/protection`, true, 'classic');
  const unavailable = rules === planUnavailable || classic === planUnavailable;
  if (unavailable && (rules !== planUnavailable || classic !== planUnavailable)) {
    throw new Error('inconsistent-policy-entitlement');
  }
  if (!unavailable) {
    if (!Array.isArray(rules) || rules.length >= 100 || rules.some((rule) =>
      !rule || typeof rule.type !== 'string' || !rule.type)) throw new Error('invalid-branch-rules');
    if (classic !== null && (!classic || typeof classic !== 'object' || Array.isArray(classic))) {
      throw new Error('invalid-classic-protection');
    }
  }
  const found = [];
  for (const file of configFiles) {
    const content = await get(`${route}/contents/${file}?ref=${repository.headSha}`, true);
    if (content === null) continue;
    const bytes = configBytes(content);
    if (file === 'package.json') {
      let pkg;
      try { pkg = JSON.parse(bytes); } catch { throw new Error('invalid-package-config'); }
      if (!pkg || typeof pkg !== 'object' || Array.isArray(pkg)) {
        throw new Error('invalid-package-config');
      }
      if (!Object.hasOwn(pkg, 'renovate')) continue;
      if (!pkg.renovate || typeof pkg.renovate !== 'object' || Array.isArray(pkg.renovate)) {
        throw new Error('invalid-package-config');
      }
    }
    found.push({ path: file, sha256: sha256(bytes), bytes: bytes.length });
  }
  const finalBranch = await get(`${route}/branches/${branch}`);
  if (finalBranch?.commit?.sha !== repository.headSha) throw new Error('policy-branch-changed');
  if (typeof finalBranch.protected !== 'boolean') throw new Error('invalid-policy-branch');
  if (unavailable && finalBranch.protected) throw new Error('policy-branch-protected');
  const finalRepository = await get(route);
  if (finalRepository?.private !== true || finalRepository.archived ||
      finalRepository.default_branch !== repository.default_branch) {
    throw new Error('policy-repository-changed');
  }
  return {
    repository: repository.full_name,
    branch: repository.default_branch,
    headSha: repository.headSha,
    defaultBranchProtected: finalBranch.protected,
    rules: unavailable ? { available: false, reason: 'private-plan-entitlement',
      storedConfiguration: 'unverified' } : {
      available: true, sha256: sha256(JSON.stringify(rules)), count: rules.length,
      types: [...new Set(rules.map((rule) => rule.type))].sort() },
    classic: unavailable ? { available: false, reason: 'private-plan-entitlement',
      storedConfiguration: 'unverified' } : classic === null ? { available: true, present: false } : {
      available: true,
      present: true, sha256: sha256(JSON.stringify(classic)),
      strictStatusChecks: classic.required_status_checks?.strict ?? null,
      requiredApprovals: classic.required_pull_request_reviews?.required_approving_review_count ?? null,
      enforceAdmins: classic.enforce_admins?.enabled ?? null,
    },
    config: { free: found.length === 0, selected: found[0]?.path ?? null,
      files: found, multiple: found.length > 1 },
    rulesetBypassActors: 'unknown-read-only',
    effectiveBranchProtection: unavailable ? 'inactive-under-current-plan' :
      finalBranch.protected ? 'active-needs-private-review' : 'not-active-on-default-branch',
    effectiveAutoMerge: 'requires-private-review',
  };
}

function seal(receipt, uid, directory = privateDir) {
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(uid)) {
    throw new Error('invalid-pod-uid');
  }
  const parent = fs.lstatSync(directory);
  if (!parent.isDirectory() || parent.uid !== process.getuid() || (parent.mode & 0o077)) {
    throw new Error('invalid-private-directory');
  }
  const folder = path.join(directory, 'policy');
  fs.mkdirSync(folder, { mode: 0o700, recursive: true });
  const metadata = fs.lstatSync(folder);
  if (!metadata.isDirectory() || metadata.uid !== process.getuid() || (metadata.mode & 0o077)) {
    throw new Error('invalid-policy-directory');
  }
  const bytes = Buffer.from(`${JSON.stringify(receipt)}\n`);
  if (bytes.length > 256 * 1024) throw new Error('policy-receipt-too-large');
  const target = path.join(folder, `${uid}.json`);
  const temporary = `${target}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, bytes, { flag: 'wx', mode: 0o600, flush: true });
    fs.linkSync(temporary, target);
  } finally {
    try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return sha256(bytes);
}

function privateRepositories(repositories) {
  const eligible = repositories.filter((entry) =>
    entry.owner?.login?.toLowerCase() === owner.toLowerCase() && !entry.archived);
  if (eligible.some((entry) => typeof entry.private !== 'boolean')) {
    throw new Error('repository-visibility-missing');
  }
  const privateRepos = eligible.filter((entry) => entry.private);
  if (!privateRepos.length) throw new Error('private-repository-coverage-empty');
  return { eligible: eligible.length, private: privateRepos };
}

async function run() {
  process.umask(0o077);
  const uid = fs.readFileSync(podUidFile, 'utf8').trim();
  const config = fs.readFileSync('/usr/src/app/config.js');
  if (!config.length || config.length > 1024 * 1024) throw new Error('invalid-global-config');
  if (require('./config.js').renovatePolicy('redacted').configFileNames !== undefined) {
    throw new Error('custom-repository-config-paths-unreviewed');
  }
  const token = await observer.readToken({ administration: 'read', contents: 'read', metadata: 'read' });
  const repositories = await inventory.githubRepositories(token);
  const owned = privateRepositories(repositories);
  const startedAt = new Date().toISOString();
  const snapshots = [];
  for (const repository of owned.private) {
    snapshots.push(await snapshotRepository(repository, (route, allow404, entitlement) =>
      github(token, route, allow404, entitlement)));
  }
  const receipt = { schema: 1, podUid: uid, owner, startedAt,
    completedAt: new Date().toISOString(), appVisibleRepositories: repositories.length,
    eligibleOwnerRepositories: owned.eligible, privateRepositories: snapshots.length,
    globalConfigSha256: sha256(config),
    ownerCoverage: 'requires-independent-owner-inventory',
    effectiveAutoMerge: 'requires-private-review', repositories: snapshots };
  seal(receipt, uid);
  console.log(JSON.stringify({ mode: 'private-policy-proof',
    repositories: snapshots.length, configFree: snapshots.filter((entry) => entry.config.free).length,
    planUnavailable: snapshots.filter((entry) => !entry.rules.available).length,
    classicProtectedWhenReadable: snapshots.filter((entry) => entry.classic.present === true).length }));
}

if (require.main === module) run().catch(() => {
  console.error(JSON.stringify({ mode: 'private-policy-proof', error: 'verification-failed' }));
  process.exitCode = 1;
});

module.exports = { configFiles, planUnavailable, github, configBytes, snapshotRepository, seal,
  privateRepositories, run };
