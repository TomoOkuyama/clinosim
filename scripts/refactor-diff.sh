#!/usr/bin/env bash
# Prove that a refactoring changes no output (Issue #3976).
#
# Usage:
#   scripts/refactor-diff.sh <base> <head>
#
# For each commit (any git revision), in a detached worktree of its own:
#   1. the forced-scenario corpus (tests/refactor_corpus/scenarios.yaml),
#      US and JP: one forced stay per path a refactoring may move;
#   2. a US and a JP cohort: seed 42, population $REFACTOR_DIFF_POPULATION
#      (default 200, at most 300), 2025-07-01 to 2026-06-30;
# each written as CIF, template narratives and FHIR R4. Then every file of
# the two output trees is compared (logs, `_generator_metadata.json` and the
# wall-clock keys of the metadata files excepted), the differences are
# printed, and the fired counters of both commits (clinosim/fired_counters.py)
# are printed side by side, so a refactoring PR can state that each moved
# path fired.
#
# The corpus definition and its runner are taken from <head> and run against
# both commits' code, so both sides generate the same scenarios. A <base>
# without fired counters prints "-" in its counter columns; a <base> that
# predates the corpus's forcing fields cannot run the corpus and fails.
#
# Exit status: 0 when the outputs are identical and every path the corpus
# expects fired on <head>; 1 when any file differs or an expected path did not
# fire; 2 on a usage or setup error.
#
# Environment:
#   REFACTOR_DIFF_WORK        work directory (default: a new temporary directory).
#                             Outputs stay there for inspection; the two
#                             worktrees are removed at exit.
#   REFACTOR_DIFF_POPULATION  cohort population (default 200, at most 300).
#   PYTHON                    interpreter (default: python3). Its environment
#                             must have clinosim's dependencies installed; the
#                             code under test comes from each worktree via
#                             PYTHONPATH.
#   CLINOSIM_JP_CLINS_PKG_DIR passed through to the JP runs; without the
#                             JP-CLINS package the JP cohort runs with
#                             --allow-legacy (the same on both commits).
set -euo pipefail

if [ "$#" -ne 2 ]; then
    sed -n '2,7p' "$0" >&2
    exit 2
fi

REPO="$(git rev-parse --show-toplevel)"
BASE_SHA="$(git -C "$REPO" rev-parse --verify "$1^{commit}")" || exit 2
HEAD_SHA="$(git -C "$REPO" rev-parse --verify "$2^{commit}")" || exit 2
POPULATION="${REFACTOR_DIFF_POPULATION:-200}"
if [ "$POPULATION" -gt 300 ]; then
    echo "REFACTOR_DIFF_POPULATION must be at most 300 (got $POPULATION)" >&2
    exit 2
fi
PY="${PYTHON:-python3}"
WORK="${REFACTOR_DIFF_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/refactor-diff.XXXXXX")}"
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
for d in "$WORK/wt-base" "$WORK/wt-head" "$WORK/out" "$WORK/counters" "$WORK/corpus"; do
    if [ -e "$d" ]; then
        echo "$d already exists: use an empty REFACTOR_DIFF_WORK" >&2
        exit 2
    fi
done

cleanup() {
    for side in base head; do
        if [ -d "$WORK/wt-$side" ]; then
            git -C "$REPO" worktree remove --force "$WORK/wt-$side" || true
        fi
    done
}
trap cleanup EXIT

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}" OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}" NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

echo "refactor-diff: base $BASE_SHA, head $HEAD_SHA, population $POPULATION, work $WORK"
git -C "$REPO" worktree add --quiet --detach "$WORK/wt-base" "$BASE_SHA"
git -C "$REPO" worktree add --quiet --detach "$WORK/wt-head" "$HEAD_SHA"
if [ ! -f "$WORK/wt-head/tests/refactor_corpus/run_corpus.py" ]; then
    echo "$HEAD_SHA has no tests/refactor_corpus/run_corpus.py" >&2
    exit 2
fi
mkdir -p "$WORK/corpus"
cp "$WORK/wt-head/tests/refactor_corpus/run_corpus.py" "$WORK/wt-head/tests/refactor_corpus/scenarios.yaml" "$WORK/corpus/"
RUNNER="$WORK/corpus/run_corpus.py"

generate() {
    local side="$1" country start_s
    local wt="$WORK/wt-$side" out="$WORK/out/$side" counters="$WORK/counters/$side"
    mkdir -p "$out" "$counters"
    for country in US JP; do
        start_s=$SECONDS
        echo "[$side] corpus $country"
        (cd "$wt" && PYTHONPATH="$wt" "$PY" "$RUNNER" corpus --country "$country" \
            --out "$out/corpus/$country" --counters "$counters/corpus_$country.json") \
            > "$WORK/$side-corpus-$country.log" 2>&1 || {
            echo "[$side] corpus $country FAILED, see $WORK/$side-corpus-$country.log" >&2
            tail -20 "$WORK/$side-corpus-$country.log" >&2
            exit 2
        }
        echo "[$side] corpus $country done in $((SECONDS - start_s)) s"
        start_s=$SECONDS
        echo "[$side] cohort $country"
        (cd "$wt" && PYTHONPATH="$wt" "$PY" "$RUNNER" cohort --counters "$counters/cohort_$country.json" -- \
            -p "$POPULATION" -s 42 --country "$country" --start 2025-07-01 --end 2026-06-30 \
            --format cif fhir-r4 --allow-legacy -o "$out/cohort/$country") \
            > "$WORK/$side-cohort-$country.log" 2>&1 || {
            echo "[$side] cohort $country FAILED, see $WORK/$side-cohort-$country.log" >&2
            tail -20 "$WORK/$side-cohort-$country.log" >&2
            exit 2
        }
        echo "[$side] cohort $country done in $((SECONDS - start_s)) s"
    done
}

generate base
generate head

status=0
echo
echo "== Output differences (base vs head)"
if "$PY" "$RUNNER" compare "$WORK/out/base" "$WORK/out/head" > "$WORK/differences.txt"; then
    echo "none: every CIF, narrative and FHIR file is identical"
else
    echo "$(wc -l < "$WORK/differences.txt" | tr -d ' ') file(s) differ (full list: $WORK/differences.txt)"
    head -50 "$WORK/differences.txt"
    status=1
fi

echo
echo "== Fired counters (head count, or base->head when they differ)"
"$PY" "$RUNNER" report "$WORK/counters/base" "$WORK/counters/head" | tee "$WORK/counters.txt"

echo
echo "== Paths the corpus expects to fire (head)"
if "$PY" "$RUNNER" check "$WORK/counters/head/corpus_US.json" "$WORK/counters/head/corpus_JP.json"; then
    echo "all fired"
else
    status=1
fi
exit "$status"
