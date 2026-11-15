#!/usr/bin/env bash
# Runs the pinned, tested Chert CLI without a global install.
set -euo pipefail
exec npx -y -p @trychert/facetime@0.1.0-beta.21 chert "$@"
