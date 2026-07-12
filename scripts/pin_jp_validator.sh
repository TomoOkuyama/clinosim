#!/usr/bin/env bash
#
# pin_jp_validator.sh — JP FHIR Validator の SHA256 pin bootstrap
# (P2-13 PR3 sub-PR-C 高度化, session 48)
#
# 用途:
#   `.github/jp-validator-pins.env` の *_SHA256 欄が空のとき、
#   実バイナリを fetch → sha256 計算 → 該当行に in-place 書き込み。
#
# 使い方:
#   bash scripts/pin_jp_validator.sh
#
#   Environment overrides:
#     PIN_FILE=<path>   default = .github/jp-validator-pins.env
#     DRY_RUN=1         書き込みせず新値を printf のみ
#
# 更新ワークフロー:
#   1. `.github/jp-validator-pins.env` の VALIDATOR_VERSION を最新化
#   2. VALIDATOR_SHA256 を空に
#   3. `bash scripts/pin_jp_validator.sh` を実行
#   4. `git diff .github/jp-validator-pins.env` で差分確認 → commit
set -euo pipefail

PIN_FILE="${PIN_FILE:-.github/jp-validator-pins.env}"
DRY_RUN="${DRY_RUN:-0}"

if [ ! -f "$PIN_FILE" ]; then
    echo "pin_jp_validator.sh: pin file が見つかりません: $PIN_FILE" >&2
    exit 2
fi

# shellcheck source=/dev/null
set -a; source "$PIN_FILE"; set +a

TMP=$(mktemp -d -t clinosim-pin.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

_calc_sha256() {
    local url="$1"; local dest="$2"
    echo "  fetching $url"
    curl -sSL --fail -o "$dest" "$url" || {
        echo "  ERROR: download failed"
        return 1
    }
    shasum -a 256 "$dest" | awk '{print $1}'
}

_update_pin() {
    local key="$1"; local val="$2"
    if [ "$DRY_RUN" = "1" ]; then
        echo "  (dry-run) $key=$val"
        return 0
    fi
    # sed で該当行を置換(POSIX 互換の in-place: BSD/GNU 両対応で -i '' 使う)
    if [[ "$OSTYPE" == darwin* ]]; then
        sed -i '' -E "s|^${key}=.*$|${key}=${val}|" "$PIN_FILE"
    else
        sed -i -E "s|^${key}=.*$|${key}=${val}|" "$PIN_FILE"
    fi
    echo "  wrote $key=$val"
}

echo "== validator_cli.jar pin =="
if [ -z "${VALIDATOR_VERSION:-}" ]; then
    echo "  ERROR: VALIDATOR_VERSION not set in pin file" >&2
    exit 2
fi
url="https://github.com/hapifhir/org.hl7.fhir.core/releases/download/${VALIDATOR_VERSION}/validator_cli.jar"
sha=$(_calc_sha256 "$url" "$TMP/validator_cli.jar")
if [ -n "${VALIDATOR_SHA256:-}" ] && [ "$VALIDATOR_SHA256" != "$sha" ]; then
    echo "  ⚠ pin ずれ: 現行=$VALIDATOR_SHA256  実測=$sha"
fi
_update_pin "VALIDATOR_SHA256" "$sha"

echo ""
echo "== JP IG package pins =="
for prefix in JP_CORE JP_CLINS JP_ECHECKUP; do
    url_var="${prefix}_PACKAGE_URL"
    sha_var="${prefix}_PACKAGE_SHA256"
    url="${!url_var:-}"
    if [ -z "$url" ]; then
        echo "  skip: ${prefix}_PACKAGE_URL 未設定"
        continue
    fi
    label=$(echo "$prefix" | tr '[:upper:]' '[:lower:]')
    sha=$(_calc_sha256 "$url" "$TMP/${label}.tgz") || continue
    _update_pin "$sha_var" "$sha"
done

echo ""
echo "pin_jp_validator.sh: 完了。差分を確認して commit してください。"
if [ "$DRY_RUN" = "0" ]; then
    git diff --stat "$PIN_FILE" 2>/dev/null || true
fi
