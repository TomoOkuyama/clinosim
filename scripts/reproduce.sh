#!/usr/bin/env bash
#
# reproduce.sh — verify clinosim's determinism contract.
#
# clinosim guarantees: for a given (seed, config, country, start, end,
# population) tuple, output NDJSON + CIF JSON is byte-identical within
# a MINOR release line. This script exercises that guarantee end-to-end
# on both US and JP locales:
#
#   1. Run `clinosim simulate --format fhir` twice per locale into two
#      isolated temp directories.
#   2. Hash every *.ndjson and CIF *.json in each output with sha256sum
#      (or `shasum -a 256` on macOS where the GNU tool is absent).
#   3. Diff the two hash lists per locale. Any difference is a
#      determinism regression — exit 1 with the offending files listed.
#   4. `fhir_r4/manifest.json` is excluded from the hash set: it carries
#      a `transactionTime` wall-clock field that is expected to differ
#      between runs. Every other file must match byte-for-byte.
#
# Runs on both locales in sequence (US first, then JP).
#
# Environment overrides (defaults chosen for ~30 s per locale on
# GitHub-hosted `ubuntu-latest`):
#
#   CLINOSIM_REPRO_COUNTRIES     # space-separated, default: "US JP"
#   CLINOSIM_REPRO_POPULATION    # default: 50
#   CLINOSIM_REPRO_SEED          # default: 42
#   CLINOSIM_REPRO_START         # default: 2026-01-01
#   CLINOSIM_REPRO_END           # default: 2026-03-31
#   CLINOSIM_REPRO_KEEP_OUTPUT   # keep temp dirs on success (any non-empty value)
#
# Exit codes:
#   0 — all runs byte-identical (excluding manifest.json)
#   1 — a determinism regression was detected; see stdout diff
#   2 — the script itself broke (dependency missing, generate crashed, etc.)

set -euo pipefail

# --------------------------------------------------------------------------- #
# Config

COUNTRIES=(${CLINOSIM_REPRO_COUNTRIES:-US JP})
POPULATION="${CLINOSIM_REPRO_POPULATION:-50}"
SEED="${CLINOSIM_REPRO_SEED:-42}"
START="${CLINOSIM_REPRO_START:-2026-01-01}"
END="${CLINOSIM_REPRO_END:-2026-03-31}"

# --------------------------------------------------------------------------- #
# Portable sha256sum (GNU coreutils on Linux/CI; macOS ships shasum instead)

if command -v sha256sum >/dev/null 2>&1; then
    SHA_CMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    # `shasum -a 256` emits `<hash>  <path>` — same shape as GNU sha256sum.
    SHA_CMD="shasum -a 256"
else
    echo "reproduce.sh: neither sha256sum nor shasum is available" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# Sanity: clinosim must be on PATH.

if ! command -v clinosim >/dev/null 2>&1; then
    echo "reproduce.sh: clinosim CLI not on PATH — did you run 'pip install -e .'?" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# Work in a temp root that's cleaned up on exit (unless KEEP is set).

REPO_TMP=$(mktemp -d -t clinosim-reproduce.XXXXXX)
cleanup() {
    if [ -z "${CLINOSIM_REPRO_KEEP_OUTPUT:-}" ]; then
        rm -rf "$REPO_TMP"
    else
        echo "reproduce.sh: keeping $REPO_TMP (CLINOSIM_REPRO_KEEP_OUTPUT set)"
    fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Hash every output file that we require to be byte-identical.
#
# Included:  *.ndjson, cif/**/*.json, narratives/**/*.json (structural output)
# Excluded (wall-clock metadata, expected to differ between runs):
#   fhir_r4/manifest.json                       (FHIR Bulk transactionTime)
#   cif/metadata.json                           (CIF generation_timestamp)
#   cif/narratives/*/manifest.json              (narrative-pass generated_at)
#
# `find | sort` keeps the ordering deterministic across the two runs, and the
# `sed` strips the run-specific temp-dir prefix so the two hash lists compare.

hash_output_dir() {
    local root="$1"
    local out="$2"
    (
        cd "$root"
        find . -type f \( -name "*.ndjson" -o -name "*.json" \) \
            ! -name "manifest.json" \
            ! -path "./cif/metadata.json" \
            | LC_ALL=C sort
    ) | while read -r rel; do
        $SHA_CMD "$root/$rel" | awk -v r="$root/" '{ sub(r, "", $2); print }'
    done > "$out"
}

# --------------------------------------------------------------------------- #
# Main loop: for each locale, run twice + compare.

fail=0
for country in "${COUNTRIES[@]}"; do
    echo
    echo "== Locale: $country =="
    dir1="$REPO_TMP/${country}-run1"
    dir2="$REPO_TMP/${country}-run2"

    for target in "$dir1" "$dir2"; do
        echo "-- generating into $target"
        clinosim simulate \
            --country "$country" \
            --population "$POPULATION" \
            --seed "$SEED" \
            --start "$START" \
            --end "$END" \
            --output "$target" \
            --format fhir \
            > "$target.log" 2>&1 || {
                echo "reproduce.sh: clinosim simulate failed for $country; see $target.log" >&2
                exit 2
            }
    done

    hash1="$REPO_TMP/${country}-run1.sha256"
    hash2="$REPO_TMP/${country}-run2.sha256"
    hash_output_dir "$dir1" "$hash1"
    hash_output_dir "$dir2" "$hash2"

    n_files=$(wc -l < "$hash1" | tr -d ' ')
    echo "-- hashing complete: $n_files file(s) per run"

    if diff -u "$hash1" "$hash2" > "$REPO_TMP/${country}.diff"; then
        echo "-- OK: $country output byte-identical across two runs"
    else
        echo "-- FAIL: $country determinism regression"
        echo
        cat "$REPO_TMP/${country}.diff"
        fail=1
    fi
done

echo
if [ "$fail" -eq 0 ]; then
    echo "reproduce.sh: PASS — byte-identical output across ${#COUNTRIES[@]} locale(s) (seed=$SEED, pop=$POPULATION)"
    exit 0
else
    echo "reproduce.sh: FAIL — determinism regression detected; see diff(s) above" >&2
    exit 1
fi
