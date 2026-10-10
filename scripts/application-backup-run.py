#!/usr/bin/env python3
"""Hourly candidate runner; reads only completed local logical backups."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('application_backup', ROOT / 'scripts/application-backup.py')
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


def main():
    os.umask(0o077)
    config = json.loads((ROOT / 'recovery/application-backups/schedule.json').read_text())
    failed = False
    for app, source_root in config['source_roots'].items():
        success, stamp = False, 0
        try:
            workspace = APP.OFFSITE.backup.private_directory(Path(config['workspace']) / app)
            # Reserve room for preparation + verification + remote check copies.
            if shutil.disk_usage(workspace).free < 20 * 1024**3:
                raise ValueError('insufficient private scratch capacity')
            candidates = sorted(p for p in Path(source_root).iterdir()
                                if re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', p.name) and p.is_dir() and not p.is_symlink())
            if not candidates:
                raise ValueError('no completed source')
            source = candidates[-1]  # Never fall back from a bad/stale newest set.
            prepared = APP.prepare(source, workspace, app)
            aws = APP.OFFSITE.AWS(Path(config['aws_cli']), config['profile'], APP.target())
            APP.publish(prepared, workspace, aws)
            identifier = APP.completed(aws, app)[-1]
            APP.fresh(identifier[:16])
            APP.retrieve(app, identifier, workspace, aws)
            APP.fresh(identifier[:16])
            success, stamp = True, APP.captured(identifier[:16])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            failed = True
            print(f'{app}: backup check failed; inspect private workspace', file=sys.stderr)
        finally:
            APP.metrics(Path(config['metrics_directory']) / f'{app}.prom', app, success, stamp)
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
