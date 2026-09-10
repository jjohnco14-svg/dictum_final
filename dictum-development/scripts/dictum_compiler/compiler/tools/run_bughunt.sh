#!/bin/bash
# run_bughunt.sh — single-command Kaggle entry point for tools/bughunter.dict
#
# Usage:
#   ./run_bughunt.sh --hours 8
#   ./run_bughunt.sh --hours 8 --outdir /kaggle/working/bughunt_results
#
# What it does, in order:
#   1. Installs Nim if it's not already on PATH (apt-get; Kaggle images are
#      Debian/Ubuntu-based, same as this tool was built/tested against).
#   2. Compiles tools/bughunter.dict once (fails loudly if this doesn't work
#      — no point starting an 8-hour run on a binary that isn't there).
#   3. Writes the requested duration (in seconds) to the config file
#      bughunter.dict reads at startup — no recompilation needed to change
#      the duration.
#   4. Runs the compiled bughunter, which tests all 3 backends (c/cpp/nim)
#      per mutation for the FULL requested duration (not split 3 ways).
#   5. On exit (normal or Ctrl-C), copies summary.txt and the findings/
#      directory (only interesting cases — crashes/internal errors, never
#      the routine clean_reject/compiled_ok bulk) to --outdir.
#
# summary.txt is overwritten periodically DURING the run (every mutation
# round), not just at the end — so even if the process is killed mid-run
# (e.g. a Kaggle session time limit), --outdir will contain the latest
# checkpoint, not nothing.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPILER_SRC="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOURS="8"
OUTDIR="/kaggle/working/bughunt_results"
if [[ -d /kaggle/working ]]; then
    WORKDIR="/kaggle/working/dictum_bughunt"
else
    WORKDIR="${HOME}/dictum_bughunt_workdir"
    OUTDIR="${WORKDIR}/results"
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hours)   HOURS="$2"; shift 2 ;;
        --outdir)  OUTDIR="$2"; shift 2 ;;
        --workdir) WORKDIR="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

DURATION_SECONDS=$(python3 -c "print(int(float('${HOURS}') * 3600))")
echo "=== run_bughunt.sh: ${HOURS}h (${DURATION_SECONDS}s) requested, results -> ${OUTDIR} ==="

# Kaggle datasets mount read-only under /kaggle/input/... -- compiling and
# writing findings/summary.txt directly next to this script would fail
# there. Copy the whole compiler tree to a writable working directory
# first, so this script behaves identically whether launched from a
# read-only dataset mount or an already-writable directory.
echo "--- staging a writable copy at ${WORKDIR} ---"
mkdir -p "${WORKDIR}"
cp -r "${COMPILER_SRC}" "${WORKDIR}/compiler"
cd "${WORKDIR}/compiler/tools"
SCRIPT_DIR="$(pwd)"

echo "--- checking for build tools (gcc/g++) ---"
if ! command -v gcc >/dev/null 2>&1 || ! command -v g++ >/dev/null 2>&1; then
    echo "gcc/g++ not found, installing (apt-get) ..."
    apt-get update -qq && apt-get install -y build-essential
fi

echo "--- checking for Nim ---"
if ! command -v nim >/dev/null 2>&1; then
    echo "nim not found, trying apt-get ..."
    apt-get update -qq && apt-get install -y nim 2>&1 | tail -5
fi
if ! command -v nim >/dev/null 2>&1; then
    echo "apt-get didn't provide nim (not in this image's repos, e.g. Kaggle) -- "
    echo "trying the official choosenim installer instead ..."
    curl -sSf https://nim-lang.org/choosenim/init.sh | sh -s -- -y 2>&1 | tail -20
    export PATH="${HOME}/.nimble/bin:${PATH}"
fi
if command -v nim >/dev/null 2>&1; then
    echo "nim available: $(nim --version | head -1)"
else
    echo "WARNING: nim still not available after both install attempts."
    echo "This is handled gracefully, not fatal -- bughunter's own startup"
    echo "smoke test will detect this and automatically disable Nim-backend"
    echo "testing for this run, while c and cpp still get a full, honest"
    echo "campaign. See the 'SMOKE TEST -- c:_ cpp:_ nim:_' line in the output."
fi

echo "--- compiling bughunter.dict ---"
cd "${SCRIPT_DIR}"
rm -f bughunter
python3 ../dictumc_cli.py bughunter.dict --backend c --output bughunter --compile
if [[ ! -x ./bughunter ]]; then
    echo "FATAL: bughunter failed to compile, see output above" >&2
    exit 1
fi

echo "${DURATION_SECONDS}" > /tmp/bughunt_duration_seconds.txt
rm -rf findings summary.txt
mkdir -p findings "${OUTDIR}"

# Copy whatever exists to OUTDIR whether we exit normally or get killed
# (Ctrl-C, Kaggle session limit, etc.) -- this is what makes summary.txt's
# periodic overwriting actually useful instead of losing everything on
# an interrupted run.
finish() {
    echo "--- copying results to ${OUTDIR} ---"
    cp -f summary.txt "${OUTDIR}/" 2>/dev/null
    mkdir -p "${OUTDIR}/findings"
    cp -f findings/*.dict "${OUTDIR}/findings/" 2>/dev/null
    echo "--- final summary ---"
    cat "${OUTDIR}/summary.txt" 2>/dev/null
}
trap finish EXIT

echo "--- running for ${HOURS}h across c/cpp/nim per mutation ---"
./bughunter
