#!/usr/bin/env bash
# Runs your tests. They must pass with no network at all: we run this with
# FX_UPSTREAM_BASE pointing at a closed port.
set -euo pipefail
export FX_UPSTREAM_BASE="${FX_UPSTREAM_BASE:-http://127.0.0.1:9}"
exec python3 -m unittest discover -s tests -v
