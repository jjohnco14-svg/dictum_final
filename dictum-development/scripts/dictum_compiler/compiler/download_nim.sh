#!/usr/bin/env bash
# Fetches and vendors the Nim compiler for the `--backend nim` target.
# Normally you never need to run this yourself -- `dictumc_cli.py FILE.dict
# --backend nim --run` does this automatically on first use. This script
# exists for pre-warming a machine/CI image, or checking the install
# without compiling anything.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/dictumc_cli.py" --install-nim
