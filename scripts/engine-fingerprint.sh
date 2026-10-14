#!/usr/bin/env bash
# Cohort output fingerprint for engine-refactor validation
# (META #1596). Produces a stable SHA256-per-file listing for a short
# US + JP p=500 cohort pair so a refactor branch can diff against a
# baseline captured on master.
#
# Usage:
#   scripts/engine-fingerprint.sh <label>
#
#     <label>  arbitrary tag (e.g. "master" or "step1"). Output is
#              written under $OUT_ROOT/<label>/.
#
# Env overrides:
#   OUT_ROOT   fingerprint workspace (default: /tmp/engine-fingerprint)
#   KEEP       1 = keep generated cohorts (default); 0 = delete after
#              fingerprinting to save disk.
#
# The fingerprint listing is written to $OUT_ROOT/<label>/FINGERPRINT.txt
# as `<sha256>  <relative path>` lines sorted by path, plus a trailing
# `TOTAL <sha256-of-all-lines>` summary. A refactor is byte-identical
# iff the TOTAL hashes match.
set -euo pipefail

LABEL="${1:-}"
if [ -z "$LABEL" ]; then
    echo "usage: $0 <label>" >&2
    exit 2
fi

OUT_ROOT="${OUT_ROOT:-/tmp/engine-fingerprint}"
KEEP="${KEEP:-1}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LABEL_DIR="$OUT_ROOT/$LABEL"
rm -rf "$LABEL_DIR"
mkdir -p "$LABEL_DIR"

# Fixed configurations. Short time window keeps the run under a few
# minutes while still exercising aging + monthly events across a year
# boundary. Seeds chosen deterministic / arbitrary.
configs=(
    "us_s42:US:42:2025-01-01:2025-04-30"
    "jp_s17:JP:17:2025-01-01:2025-04-30"
)

for cfg in "${configs[@]}"; do
    IFS=':' read -r name country seed start end <<<"$cfg"
    out="$LABEL_DIR/$name"
    mkdir -p "$out"
    echo "[$LABEL/$name] generating cohort (country=$country seed=$seed $start..$end) ..." >&2
    extra_flags=""
    if [ "$country" = "JP" ]; then
        # JP-CLINS package is optional for engine-refactor byte-identity
        # testing; --allow-legacy is accepted here because the fingerprint
        # measures determinism, not JP eCS compliance.
        extra_flags="--allow-legacy"
    fi
    PYTHONPATH="$REPO_ROOT" python3 -m clinosim.simulator.cli generate \
        -o "$out" -p 500 -s "$seed" \
        --country "$country" \
        --start "$start" --end "$end" \
        --format cif fhir-r4 \
        $extra_flags \
        > "$out/.generate.log" 2>&1 || {
            echo "[$LABEL/$name] FAILED — see $out/.generate.log" >&2
            tail -40 "$out/.generate.log" >&2 || true
            exit 1
        }
done

cd "$LABEL_DIR"
# Fingerprint every regular output file. Exclude metadata and logs
# that carry wall-clock timestamps / git commit hash (which are
# correct to vary across runs; they are not simulation content).
# Everything else — CIF ndjson, FHIR ndjson, cache_manifest — is
# content-deterministic for a fixed (seed, country, config).
find . -type f \
    ! -name ".generate.log" \
    ! -name "simulator.log" \
    ! -name "_generator_metadata.json" \
    ! -name "manifest.json" \
    ! -path "*/cif/metadata.json" \
    ! -path "*/log/*" \
    | sort > FILES.txt

# shasum is available on macOS and Linux (coreutils ships sha256sum,
# BSD ships shasum). Prefer shasum for cross-platform.
if command -v shasum >/dev/null 2>&1; then
    HASHER="shasum -a 256"
else
    HASHER="sha256sum"
fi

while read -r f; do
    $HASHER "$f"
done < FILES.txt > FINGERPRINT.txt

TOTAL=$($HASHER FINGERPRINT.txt | awk '{print $1}')
echo "TOTAL  $TOTAL" >> FINGERPRINT.txt

echo "---- $LABEL fingerprint ----"
tail -5 FINGERPRINT.txt
echo "TOTAL  $TOTAL"

if [ "$KEEP" = "0" ]; then
    find . -mindepth 1 -maxdepth 1 ! -name 'FINGERPRINT.txt' ! -name 'FILES.txt' -exec rm -rf {} +
fi
