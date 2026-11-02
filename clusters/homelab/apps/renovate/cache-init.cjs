'use strict';

const fs = require('node:fs');
const root = '/cache/renovate';
const uid = 12021;
const gid = 12021;
const mode = 0o700;

const before = fs.lstatSync(root);
if (!before.isDirectory() || before.isSymbolicLink()) {
  throw new Error('Renovate cache mount must be a directory');
}

// Only the mount root needs initialization. Never traverse or replace warm data.
if (before.uid !== uid || before.gid !== gid) fs.chownSync(root, uid, gid);
if ((before.mode & 0o7777) !== mode) fs.chmodSync(root, mode);

const after = fs.lstatSync(root);
if (after.uid !== uid || after.gid !== gid || (after.mode & 0o7777) !== mode) {
  throw new Error('Renovate cache mount ownership or permissions are incorrect');
}
