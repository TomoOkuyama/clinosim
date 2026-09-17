# Fallback 分析と Fallback 0 目標

**User 目標 (S117 mid-verify guidance)**:
> フォールバックが発生したらログを記録し、フォールバックが発生しないように調整したい。基本的にはフォールバック0を目指す。

## Fallback taxonomy (現状 code から)

narrate 中に発生する fallback は 4 種類:

| # | fallback_reason | 発生箇所 | 発火条件 | 現状 log |
|---|---|---|---|---|
| 1 | `no_provider_configured` | `engine.py:375` | LLM provider が config 未設定 | `fallback_count` counter |
| 2 | `prompt_error:*` | `engine.py:393` | prompt render で ${var} 不足など | `fallback_count` counter |
| 3 | `provider_error:*` | `engine.py:416` | vLLM API call が network / timeout / 5xx で失敗 | `fallback_count` counter + `fallback_reason` にエラー詳細 |
| 4 | `template_seed_bundle: JSON parse failed` | `replacement_strategy.py:707` | LLM 出力が invalid JSON (bundle strategy 特有) | `_logger.warning` (INFO レベルでは出ない) |

**注意**: 上記 4 種以外に「LLM が該当 doc type の narrative section を持たない → template fallback」があるが、これは fallback ではなく **設計上の template-only routing** (triage note 等の構造化 field 系)。混同しない。

## Fallback 0 に向けた plan (次 session verify に追加)

### 追跡 (log 集約)

`run_case.sh` の narrate log から:
```
grep -c "JSON parse failed\|fallback_reason\|falling back" <narrate log>
```
+ `LLMService.metrics()` の `fallback_count` を case 前後で snapshot して delta 計算。

出力:
- `case_<id>/fallback_summary.json`: {parse_fail: N, provider_err: N, other: N, sample_fail_responses: [...]}
- `case_<id>/fallback_samples.txt`: 最初 5 件の raw LLM response を保存 (parse fail 分析用)

### 削減 (Fix C 追加)

**Fix C: vLLM structured output で JSON 出力を強制**

vLLM 0.27.1 は `guided_json` / `response_format={"type":"json_object"}` に対応。LLM の生成トークンを JSON 文法に constrain することで **`template_seed_bundle: JSON parse failed` は理論的にゼロ化**する。

- 実装: `llm_service_vllm.yaml` に `response_format: {type: json_object}` を add、または `guided_decoding_backend: xgrammar` を有効化
- 品質影響: 出力 token に構造制約が入るが、その中の文言選択は制約なし。narrative 品質不変
- 速度影響: xgrammar 使用時のオーバーヘッドは <5% 程度 (vLLM benchmark 参照)

### verify Case matrix 拡張

- **Case J** (Fix C): baseline v22 + guided JSON → fallback rate 0 の直接検証
- 全 case で fallback_summary.json を計測 → factor breakdown table に fallback rate 列追加

### analyze.py 拡張

Factor breakdown に fallback rate 列追加、fallback rate > 0 の case は WARNING mark、次の削減 iteration の候補として明示。

## 実装優先度

1. **次 session の verify に fallback logging を組み込む** (run_case.sh + analyze.py 修正、~15 min)
2. **Fix C case を verify matrix に追加** (yaml config 追加 + case 追加、~10 min)
3. **verify run 実行 → fallback rate 実測**
4. **fallback rate > 0 なら Fix C 案の恒久採用検討**

## 現在 verify 状態への反映

`run_case.sh`、`run_all_cases.sh`、`analyze.py` は fallback 追跡未実装。次 session の boot 前に:
1. `run_case.sh` に narrate log からの fallback grep + サンプル抽出を追加
2. `analyze.py` に fallback rate 集計を追加
3. `llm_service_vllm.yaml` に structured output config を用意 (別 variant で切替可能に)
