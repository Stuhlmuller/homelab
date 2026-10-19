import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const packageRoot = process.argv[2];
if (!packageRoot || !path.isAbsolute(packageRoot)) {
  throw new Error('Pass the absolute path to the installed renovate@44.167.4 package');
}
if (!RegExp.escape) {
  throw new Error('Renovate 44.167.4 requires Node.js 24.11 or newer');
}
const { version } = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
assert.equal(version, '44.167.4', 'fixture must use the pinned Renovate version');

const renovateModule = async (relativePath) => import(pathToFileURL(path.join(packageRoot, 'dist', relativePath)).href);
const [
  { setPlatformApi, platform },
  { platformScmImpls },
  { autodiscoverRepositories },
  { getRepoConfig },
  { GlobalConfig },
  { resolveConfigPresets },
  { mergeChildConfig },
  { getConfig: getDefaults },
  { resetCache },
] = await Promise.all([
  renovateModule('modules/platform/index.js'),
  renovateModule('modules/platform/scm.js'),
  renovateModule('workers/global/autodiscover.js'),
  renovateModule('workers/repository/init/config.js'),
  renovateModule('config/global.js'),
  renovateModule('config/presets/index.js'),
  renovateModule('config/utils.js'),
  renovateModule('config/defaults.js'),
  renovateModule('util/cache/repository/index.js'),
]);

const configPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../clusters/homelab/apps/renovate/config.js');
const source = fs.readFileSync(configPath, 'utf8');
const { privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const key = privateKey.export({ type: 'pkcs8', format: 'pem' });

async function configuredRunner() {
  const requests = [];
  const logs = [];
  const context = {
    Buffer,
    module: { exports: {} },
    console: {
      log: (...args) => logs.push(args),
      warn: (...args) => logs.push(args),
      error: (...args) => logs.push(args),
    },
    require(name) {
      if (name === 'node:crypto') return crypto;
      if (name === 'node:fs') return {
        readFileSync(file) {
          if (file === '/var/run/secrets/renovate/issuer-id') return 'Iv1.fixture';
          if (file === '/var/run/secrets/renovate/private-key') return key;
          throw new Error('Unexpected credential path');
        },
        writeFileSync(file, bytes, settings) {
          assert.match(file, /^\/cache\/renovate\/\.storage-probe-[0-9a-f-]+$/);
          assert.equal(bytes.length, 4096);
          assert.equal(settings.flush, true);
        },
        unlinkSync(file) { assert.match(file, /^\/cache\/renovate\/\.storage-probe-[0-9a-f-]+$/); },
      };
      throw new Error(`Unexpected config.js import: ${name}`);
    },
    async fetch(url, request) {
      requests.push({ url, request });
      if (url === 'https://api.github.com/orgs/Stuhlmuller/installation') {
        return { ok: true, json: async () => ({ id: 42, account: { login: 'Stuhlmuller' }, repository_selection: 'all' }) };
      }
      if (url === 'https://api.github.com/app/installations/42/access_tokens') {
        return { ok: true, json: async () => ({ token: 'ghs_fixture', expires_at: new Date(Date.now() + 3_600_000).toISOString() }) };
      }
      throw new Error(`Unexpected GitHub App API path: ${url}`);
    },
  };
  vm.runInNewContext(source, context, { filename: configPath });
  const config = await context.module.exports();
  assert.equal(requests.length, 2);
  assert.equal(logs.length, 0, 'config.js must not log credentials or tokens');
  return config;
}

test('pinned Renovate discovers and resolves A, then config-free B, then only A', async () => {
  const runnerConfig = await configuredRunner();
  const { config: globalPolicy } = await resolveConfigPresets({ extends: runnerConfig.globalExtends });
  const { globalExtends: _globalExtends, ...fileConfig } = runnerConfig;
  const config = mergeChildConfig(getDefaults(), mergeChildConfig(globalPolicy, fileConfig));

  let fileChecks = 0;
  platformScmImpls.set('github', class {
    async getFileList() {
      fileChecks += 1;
      return []; // B has no repository configuration file.
    }
  });
  setPlatformApi('github');

  let inventory = [];
  const apiRequests = [];
  const server = http.createServer((request, response) => {
    apiRequests.push({ method: request.method, path: request.url });
    response.setHeader('Content-Type', 'application/json');
    if (request.method === 'HEAD' && request.url === '/') {
      response.writeHead(200);
      response.end();
    } else if (request.method === 'GET' && request.url === '/installation/repositories?per_page=100') {
      response.end(JSON.stringify({ total_count: inventory.length, repositories: inventory }));
    } else {
      response.writeHead(404);
      response.end('{}');
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const endpoint = `http://127.0.0.1:${server.address().port}/`;

  try {
    await platform.initPlatform({ endpoint, token: runnerConfig.token, username: runnerConfig.username, gitAuthor: runnerConfig.gitAuthor });
    const seen = [];
    const a = { full_name: 'Stuhlmuller/A', archived: false };
    const b = { full_name: 'Stuhlmuller/B', archived: false };
    const ignored = [
      { full_name: 'Other/repo', archived: false },
      { full_name: 'Stuhlmuller/archived', archived: true },
    ];
    for (const owned of [[a], [a, b], [a]]) {
      inventory = [...owned, ...ignored];
      const cycle = await autodiscoverRepositories({ ...config });
      seen.push(cycle.repositories);
      for (const repository of cycle.repositories) {
        resetCache();
        const repositoryConfig = GlobalConfig.set(config);
        const resolved = await getRepoConfig({ ...repositoryConfig, repository, defaultBranch: 'main', endpoint });
        assert.equal(resolved.repoIsOnboarded, true, `${repository} must skip onboarding`);
        assert.equal(resolved.renovateJsonPresent, true, `${repository} must finish config resolution`);
        assert.equal(resolved.automerge, true, `${repository} must inherit the current policy`);
        assert.deepEqual(resolved.labels, ['dependencies']);
      }
    }
    assert.deepEqual(seen, [
      ['Stuhlmuller/A'],
      ['Stuhlmuller/A', 'Stuhlmuller/B'],
      ['Stuhlmuller/A'],
    ]);
    assert.ok(fileChecks > 0, 'Renovate must check for a repository config file');
    assert.deepEqual(apiRequests.map(({ method, path: requestPath }) => `${method} ${requestPath}`), [
      'HEAD /',
      'GET /installation/repositories?per_page=100',
      'GET /installation/repositories?per_page=100',
      'GET /installation/repositories?per_page=100',
    ]);
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
