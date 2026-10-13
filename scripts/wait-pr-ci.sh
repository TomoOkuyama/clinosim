#!/usr/bin/env bash
# wait-pr-ci.sh — reliable PR CI wait gate before `gh pr merge`.
#
# Polls `gh pr view <PR> --json statusCheckRollup` until every required check
# reaches COMPLETED, then exits 0 only when no non-informational check ended
# in a FAILURE / CANCELLED / TIMED_OUT / ACTION_REQUIRED state.
#
# Why this exists:
#   `gh pr checks <N> --watch --fail-fast` has been observed to return exit 0
#   on PRs whose required checks eventually ended in FAILURE (clinosim
#   master-CI breakage, 2026-10-11, 4 consecutive PRs). The exact root cause
#   (gh CLI race, polling-interval miss, or gate not actually invoked) was
#   never pinned down. This wrapper does its own deterministic polling so the
#   outcome does not depend on gh CLI's streaming behaviour.
#
# Usage:
#   scripts/wait-pr-ci.sh <pr-number>
#     [--poll-seconds N]     (default: 20)
#     [--timeout-seconds N]  (default: 1800 = 30 min)
#     [--exclude-pattern RE] (default: '(?i)informational')
#
# Exit codes:
#   0   — all required checks terminal + SUCCESS/SKIPPED/NEUTRAL
#   1   — at least one required check ended in a non-success state
#   2   — usage error
#   124 — timeout
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <pr-number> [--poll-seconds N] [--timeout-seconds N] [--exclude-pattern RE]" >&2
  exit 2
fi

PR="$1"
shift
POLL=20
TIMEOUT=1800
EXCLUDE='(?i)informational'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --poll-seconds)    POLL="$2";    shift 2 ;;
    --timeout-seconds) TIMEOUT="$2"; shift 2 ;;
    --exclude-pattern) EXCLUDE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! [[ "$PR" =~ ^[0-9]+$ ]]; then
  echo "pr-number must be numeric, got: $PR" >&2
  exit 2
fi

start=$(date +%s)

while :; do
  now=$(date +%s)
  elapsed=$((now - start))
  if (( elapsed > TIMEOUT )); then
    echo "wait-pr-ci: timeout after ${TIMEOUT}s — PR #$PR still has non-terminal checks" >&2
    gh pr view "$PR" --json statusCheckRollup \
      --jq '.statusCheckRollup | map(select(.status != "COMPLETED") | .name)' >&2
    exit 124
  fi

  rollup=$(gh pr view "$PR" --json statusCheckRollup --jq '.statusCheckRollup')

  pending_count=$(printf '%s' "$rollup" | jq --arg ex "$EXCLUDE" \
    '[.[] | select((.name // "") | test($ex) | not) | select(.status != "COMPLETED")] | length')

  if [[ "$pending_count" != "0" ]]; then
    pending_names=$(printf '%s' "$rollup" | jq -r --arg ex "$EXCLUDE" \
      '[.[] | select((.name // "") | test($ex) | not) | select(.status != "COMPLETED") | .name] | join(", ")')
    echo "wait-pr-ci: PR #$PR pending=$pending_count ($pending_names) elapsed=${elapsed}s" >&2
    sleep "$POLL"
    continue
  fi

  failed=$(printf '%s' "$rollup" | jq -c --arg ex "$EXCLUDE" \
    '[.[]
      | select((.name // "") | test($ex) | not)
      | select(.status == "COMPLETED")
      | select((.conclusion // "") as $c
          | ($c != "SUCCESS") and ($c != "SKIPPED") and ($c != "NEUTRAL"))
      | {name, conclusion}]')

  if [[ "$failed" == "[]" ]]; then
    echo "wait-pr-ci: PR #$PR — all required checks SUCCESS (elapsed ${elapsed}s)"
    exit 0
  fi

  echo "wait-pr-ci: PR #$PR — required checks did not pass:" >&2
  printf '%s' "$failed" | jq -r '.[] | "  \(.conclusion)\t\(.name)"' >&2
  exit 1
done
