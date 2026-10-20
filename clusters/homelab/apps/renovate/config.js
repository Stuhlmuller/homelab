const fs = require('node:fs');
const crypto = require('node:crypto');

const issuerPath = '/var/run/secrets/renovate/issuer-id';
const privateKeyPath = '/var/run/secrets/renovate/private-key';
const api = 'https://api.github.com';
const owner = 'Stuhlmuller';
// Temporary acceptance fault: one scheduled UTC hour, then normal PVC use resumes.
const fullCacheFaultHour = Date.parse('2026-10-20T10:00:00Z');

async function githubJson(path, authorization, method = 'GET') {
  let response;
  try {
    response = await fetch(`${api}${path}`, {
      method,
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${authorization}`,
        'User-Agent': 'homelab-renovate',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });
  } catch {
    throw new Error(`GitHub App ${method} ${path} failed`);
  }
  if (!response.ok) {
    throw new Error(`GitHub App ${method} ${path} returned HTTP ${response.status}`);
  }
  try {
    return await response.json();
  } catch {
    throw new Error(`GitHub App ${method} ${path} returned invalid JSON`);
  }
}

async function installationToken() {
  let issuer;
  let privateKey;
  try {
    issuer = fs.readFileSync(issuerPath, 'utf8').trim();
    privateKey = fs.readFileSync(privateKeyPath, 'utf8');
  } catch {
    throw new Error('Renovate GitHub App credential files are unreadable');
  }
  if (!issuer || !privateKey.trim()) {
    throw new Error('Renovate GitHub App credential files are empty');
  }

  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ iat: now - 60, exp: now + 540, iss: issuer })).toString('base64url');
  const signingInput = `${header}.${payload}`;
  let signature;
  try {
    signature = crypto.sign('RSA-SHA256', Buffer.from(signingInput), privateKey).toString('base64url');
  } catch {
    throw new Error('Renovate GitHub App private key is invalid');
  }

  const jwt = `${signingInput}.${signature}`;
  const installation = await githubJson(`/orgs/${owner}/installation`, jwt);
  if (
    !Number.isSafeInteger(installation?.id) || installation.id <= 0 ||
    installation.account?.login?.toLowerCase() !== owner.toLowerCase() ||
    installation.repository_selection !== 'all'
  ) {
    throw new Error('Renovate GitHub App installation does not cover the owner');
  }

  const result = await githubJson(`/app/installations/${installation.id}/access_tokens`, jwt, 'POST');
  const expiresAt = Date.parse(result?.expires_at);
  if (
    typeof result?.token !== 'string' || !result.token.startsWith('ghs_') ||
    !Number.isFinite(expiresAt) || expiresAt - Date.now() < 3300 * 1000
  ) {
    throw new Error('Renovate GitHub App installation token is invalid or expires too soon');
  }
  return result.token;
}

module.exports = async function config() {
  const now = Date.now();
  const faultHour = now >= fullCacheFaultHour && now < fullCacheFaultHour + 3600_000;
  const cacheDir = faultHour ? '/cache/renovate-fault' : '/cache/renovate';
  if (faultHour) {
    try {
      fs.writeFileSync(`${cacheDir}/.full-fixture`, Buffer.alloc(2 * 1024 * 1024));
      throw new Error('Renovate cache fault fixture did not reach ENOSPC');
    } catch (error) {
      if (error.code !== 'ENOSPC') throw error;
    }
  }
  const probe = `${cacheDir}/.storage-probe-${crypto.randomUUID()}`;
  try {
    fs.writeFileSync(probe, Buffer.alloc(4096), { flush: true });
    fs.unlinkSync(probe);
  } catch {
    try { fs.unlinkSync(probe); } catch {}
    throw new Error('Renovate cache volume is unavailable or full');
  }
  if (faultHour) {
    throw new Error('Renovate cache fault probe unexpectedly succeeded');
  }
  return {
    platform: 'github',
    token: await installationToken(),
    username: 'rstuhlmuller-renovate[bot]',
    gitAuthor: 'rstuhlmuller-renovate[bot] <239054205+rstuhlmuller-renovate[bot]@users.noreply.github.com>',
    globalExtends: [
      'config:best-practices',
      ':automergeAll',
      'replacements:all',
      'schedule:automergeDaily',
      'security:openssf-scorecard',
    ],
    platformCommit: 'enabled',
    rebaseWhen: 'conflicted',
    autodiscover: true,
    autodiscoverFilter: [`${owner}/*`],
    forkProcessing: 'enabled',
    onboarding: false,
    requireConfig: 'optional',
    labels: ['dependencies'],
    ignoreDeps: ['bridgecrewio/checkov-action'],
    lockFileMaintenance: { enabled: true },
    vulnerabilityAlerts: { enabled: true, labels: ['security'] },
    baseDir: '/tmp/renovate',
    cacheDir,
    repositoryCache: 'enabled',
    cachePrivatePackages: true,
    logLevelRemap: [{ matchMessage: '/^Returning cached value$/', newLogLevel: 'info' }],
    dryRun: 'full',
  };
};
