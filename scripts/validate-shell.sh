#!/usr/bin/env bash
set -euo pipefail

find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
