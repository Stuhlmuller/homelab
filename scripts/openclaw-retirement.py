#!/usr/bin/env python3
"""Run the GitOps-mounted legacy retirement helper locally for inventory or review."""

import runpy
from pathlib import Path


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] /
                       'clusters/homelab/apps/openclaw/retirement/retirement.py'), run_name='__main__')
