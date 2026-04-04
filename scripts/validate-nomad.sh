#!/usr/bin/env bash
set -euo pipefail

nomad fmt -check nomad/jobs >/dev/null

find nomad/jobs -name 'job.nomad.hcl' | sort | while read -r job_file; do
  nomad job validate "$job_file" >/dev/null
done
