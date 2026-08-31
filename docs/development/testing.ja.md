<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# テスト

```bash
source .venv/bin/activate

# 全テスト (unit ~1 min, integration ~30 min, e2e ~8 min)
pytest -x

# カテゴリ別
pytest -m unit                   # 単体テスト (~3900 test 関数、パラメタライズ含み 5100+ ケース)
pytest -m integration            # cross-module (reproduce.sh gate 含む)
pytest -m e2e                    # E2E + golden テスト

# カバレッジ
pytest --cov=clinosim
```

### 再現性

clinosim は所与の `(seed, config, country, start, end, population)`
タプルに対して **byte-identical 出力** を MINOR release line 内で
保証します — 壁時計メタデータ (`fhir_r4/manifest.json` /
`cif/metadata.json` / narrative-pass `manifest.json`) は差分あり想定、
それ以外は完全一致でなければなりません。

いつでも検証:

```bash
bash scripts/reproduce.sh
```

スクリプトは locale ごと (デフォルト US + JP) に
`clinosim simulate --format fhir` を 2 つの分離した temp ディレクト
リへ 2 回実行、各 NDJSON + CIF JSON を sha256 化し、hash リストを
diff します。exit 0 = byte-identical、exit 1 = 決定性回帰 (該当
ファイル名が diff に出力)。環境変数 `CLINOSIM_REPRO_COUNTRIES` /
`CLINOSIM_REPRO_POPULATION` / `CLINOSIM_REPRO_SEED` /
`CLINOSIM_REPRO_START` / `CLINOSIM_REPRO_END` でデフォルトを上書き
可能。

CI の `reproducibility` job が全 push + PR で実行するので、回帰が
コードのランド前に merge gate を trip します。

---
