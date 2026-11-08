# 縦断属性カタログ

臨床属性ごとに 1 yaml。各ファイルは共通 frontmatter (`attribute_id`, `pattern`, `depends_on`, `clinical_scope`) とパターン固有の本体を持つ。スキーマの詳細は設計書 `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` を参照。

`clinosim/modules/longitudinal/loader.py` が本ディレクトリ配下の `*.yaml` をすべて再帰的に (`rglob`) ロードする。現在の内容 (64 ファイル。パターン内訳: `ar1` 4 / `markov` 19 / `event` 41):

- `hba1c_trajectory.yaml` — E11 / E10 成人の AR(1) HbA1c 潜在値
- `labs/` (1) — LDL 推移
- `vitals/` (1) — 収縮期血圧推移
- `anthropometry/` (1) — BMI の drift
- `stage/` (19) — Markov ステージ遷移 (CKD、COPD、心不全、虚血性心疾患、心房細動、認知症、パーキンソン病、多発性硬化症、肝線維化 / アルコール性肝疾患、脳卒中後遺症、がんステージ)
- `event/` (35) — イベント発火属性: 慢性疾患の発症 (`*_onset.yaml`) と糖尿病合併症の発症 (腎症 / 神経障害 / 網膜症)
- `med/` (6) — 治療強化 (糖尿病: インスリン / SGLT2 阻害薬、高血圧: 第 3 / 第 4 剤、脂質: エゼチミブ。高強度スタチン切替は rate 0 で廃止、スタチンの増量は実測 LDL に基づき `simulator/statin_monitoring.py` が行う)
