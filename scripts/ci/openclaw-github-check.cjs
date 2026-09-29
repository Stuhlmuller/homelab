#!/usr/bin/env node
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { run } = require('../../clusters/homelab/apps/openclaw/assistant/gh');

(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'github-check-'));
  try {
    const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
    const keyPath = path.join(directory, 'key.pem');
    fs.writeFileSync(keyPath, privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 });
    const env = { GITHUB_APP_ID: '123', GITHUB_APP_INSTALLATION_ID: '456',
      GITHUB_APP_PRIVATE_KEY_PATH: keyPath, GH_TOKEN: 'must-not-win', GH_DEBUG: 'api' };
    let calls = 0;
    const directories = [];
    const request = async (url, options) => {
      calls++;
      assert.equal(url, 'https://api.github.com/app/installations/456/access_tokens');
      const parts = options.headers.Authorization.slice(7).split('.');
      assert(crypto.verify('RSA-SHA256', Buffer.from(parts.slice(0, 2).join('.')),
        publicKey, Buffer.from(parts[2], 'base64url')));
      assert.equal(JSON.parse(Buffer.from(parts[1], 'base64url')).iss, '123');
      const scope = JSON.parse(options.body);
      assert.deepEqual(scope.repositories, ['homelab']);
      assert.equal(scope.permissions.contents, 'write');
      assert.equal(scope.permissions.administration, undefined);
      return { ok: true, json: async () => ({ token: 'fixture' }) };
    };
    const spawn = (binary, args, options) => {
      assert.equal(binary, '/toolbox/profile/bin/gh');
      assert.deepEqual(args, ['api', 'repos/Stuhlmuller/homelab']);
      assert.equal(options.env.GH_TOKEN, undefined);
      assert.equal(options.env.GH_DEBUG, undefined);
      const config = path.join(options.env.GH_CONFIG_DIR, 'hosts.yml');
      assert.equal(fs.statSync(config).mode & 0o777, 0o600);
      assert.equal(fs.statSync(options.env.GH_CONFIG_DIR).mode & 0o777, 0o700);
      assert.equal(JSON.parse(fs.readFileSync(config))['github.com'].oauth_token, 'fixture');
      directories.push(options.env.GH_CONFIG_DIR);
      return { status: 7 };
    };
    for (let i = 0; i < 2; i++) {
      assert.equal(await run(['api', 'repos/Stuhlmuller/homelab'], env, request, spawn), 7);
    }
    assert.equal(calls, 2); // Every invocation renews; an expired token cannot be reused.
    assert.notEqual(directories[0], directories[1]);
    assert(directories.every(dir => !fs.existsSync(dir)));
    await assert.rejects(run([], { ...env, GITHUB_APP_ID: 'REPLACE_ME' }, request, spawn), /IDs/);
    await assert.rejects(run([], env, async () => ({ ok: false, status: 403 }), spawn), /HTTP 403/);
    assert.equal(calls, 2);
    let failedDirectory;
    await assert.rejects(run([], env, request, (_binary, _args, options) => {
      failedDirectory = options.env.GH_CONFIG_DIR;
      return { error: new Error('fixture launch failure') };
    }), /Could not start/);
    assert(!fs.existsSync(failedDirectory));
    console.log('OpenClaw GitHub authentication checks passed');
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
