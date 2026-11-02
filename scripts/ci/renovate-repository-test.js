const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const test = require('node:test');

const config = JSON.parse(fs.readFileSync('renovate.json', 'utf8'));
const files = execFileSync('git', ['ls-files', '-z', 'IaC', '.github', 'clusters'], { encoding: 'utf8' }).split('\0');
const matchesFile = (patterns, file) => patterns.some((pattern) => new RegExp(pattern.slice(1, -1)).test(file));

test('discovers each declared HCL Helm chart once, without matching Git sources', () => {
  let charts = 0;
  for (const file of files.filter((name) => name.endsWith('.hcl'))) {
    const content = fs.readFileSync(file, 'utf8');
    const expected = [...content.matchAll(/^\s*chart\s*=\s*"([^"\s]+)"/gm)].map((match) => match[1]);
    const actual = config.customManagers.filter((manager) => matchesFile(manager.managerFilePatterns, file))
      .flatMap((manager) => manager.matchStrings.flatMap((pattern) => [...content.matchAll(new RegExp(pattern, 'g'))]));
    assert.deepEqual(actual.map((match) => match.groups.chart).sort(), expected.sort(), file);
    for (const match of actual) assert.match(match.groups.currentValue, /^v?\d/);
    charts += expected.length;
  }
  assert.ok(charts > 0, 'chart inventory must not be empty');
  assert.deepEqual(config.argocd.managerFilePatterns,
    ['/^clusters/homelab/platform/storage/nfs-subdir-external-provisioner-application\\.yaml$/']);
  const yamlCharts = files.filter((file) => file.endsWith('.yaml') && /^\s*chart:/m.test(fs.readFileSync(file, 'utf8')));
  assert.deepEqual(yamlCharts, ['clusters/homelab/platform/storage/nfs-subdir-external-provisioner-application.yaml']);
});

test('keeps Nix updates reviewed and preserves image ownership', () => {
  assert.equal(config.nix.enabled, true);
  assert.equal(config.lockFileMaintenance.enabled, true);
  const nixRule = config.packageRules.find((rule) => rule.matchManagers?.includes('nix'));
  assert.equal(nixRule.automerge, false);
  assert.equal(config.packageRules.length, 2, 'preserve existing automerge for non-Nix dependencies');
  assert.equal(config.packageRules.find((rule) => rule.matchManagers?.includes('nix')).groupName, 'Nix toolchain');
  assert.deepEqual(config.packageRules[0], {
    description: 'Image Updater exclusively owns enrolled Chainguard Harbor targets.',
    matchDatasources: ['docker'],
    matchPackageNames: ['harbor.stinkyboi.com/homelab/chainguard/python', 'harbor.stinkyboi.com/homelab/chainguard/curl'],
    enabled: false,
  });
});

test('every SHA-pinned action includes same-line version metadata', () => {
  let actions = 0;
  for (const file of files.filter((name) => name.startsWith('.github/') && /\.ya?ml$/.test(name))) {
    for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
      if (!/^\s*(?:-\s*)?uses: [^ ./]+\/[^ @]+@[a-f0-9]{40}\b/.test(line)) continue;
      assert.match(line, /#\s*v?\d[\w.-]*\s*$/, `${file}: ${line.trim()}`);
      actions += 1;
    }
  }
  assert.ok(actions > 0, 'action inventory must not be empty');
});
