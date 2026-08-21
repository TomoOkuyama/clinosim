# ドキュメント + コード品質ポリシー

**Status**: Active
**適用対象**: 本リポジトリへの変更を提出する全 contributor (人間および
自動化 agent) の全 pull request。
**強制**: reviewer が PR review でコンプライアンスを check、一部
ルール (§6 の dead-code baseline、§7 の signed-off commits) は CI で
強制。

本ドキュメントは、このプロジェクトでドキュメントがどう書かれ、ソース
コード品質がどう維持されるかの single source of truth。
[`AGENTS.md`](../../AGENTS.md) (自動 agent 向け)、
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) (人間 contributor 向け)、
トップレベル READMEs から参照される。

ポリシーは
[`docs/superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md`](../superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md)
で設計された campaign の一部として批准。

---

## 目次

1. [ドキュメント言語](#1-ドキュメント言語)
2. [文書間リンク (言語一貫性)](#2-文書間リンク-言語一貫性)
3. [self-contained OSS 品質](#3-self-contained-oss-品質)
4. [ソースコードコメント言語](#4-ソースコードコメント言語)
5. [定数と設定](#5-定数と設定)
6. [Dead-code 衛生](#6-dead-code-衛生)
7. [Contributing ワークフロー](#7-contributing-ワークフロー)
8. [ポリシー変更方法](#8-ポリシー変更方法)

---

## 1. ドキュメント言語

プロジェクトドキュメントの全パートは英語または日本語のいずれか、
ファイル言語はファイル名接尾辞で識別。

| ファイル位置 | 言語 | 必須 |
|---|---|---|
| Root `README.md` | 英語 | Yes |
| Root `README.ja.md` | 日本語 | Yes |
| 各パッケージ/モジュールディレクトリ `README.md` | 英語 | Yes |
| 各パッケージ/モジュールディレクトリ `README.ja.md` | 日本語 | Yes |
| `docs/**/*.md` (canonical 英語文書) | 英語 | Yes |
| `docs/**/*.ja.md` (日本語 mirror 文書) | 日本語 | 英語文書が user-facing または contributor-facing (純粋な内部設計ノートではない) の場合 |

**ファイル名規約**: デフォルト (接尾辞なし) は常に英語。日本語版は
`<name>.ja.md` 接尾辞 — 例: `README.ja.md`、`installation.ja.md`。
他の言語混合接尾辞規約は導入しない。

**規則**: 新規 user-facing または contributor-facing ドキュメントを
英語で追加するときは、同ディレクトリに `.ja.md` 接尾辞で日本語版
を追加。英語版更新時は同 PR で日本語版も更新 (または follow-up
Issue を起票し PR description に link)。

---

## 2. 文書間リンク (言語一貫性)

- **英語** 文書内のリンクは **英語** 文書を指す。
- **日本語** 文書内のリンクは **日本語** 文書を指す。
- ターゲット文書が片方言語のみに存在するとき、リンクは他言語を指し
  ても良いが、リンクテキストに言語マーカーを含める (例: 日本語
  文書内で `[foo (英語)](foo.md)`)。翻訳追加の follow-up Issue を
  起票。
- 外部リンク (GitHub Issues、上流 spec、RFC) は任意言語で、マーカー
  不要。

---

## 3. self-contained OSS 品質

全 READMEs、ドキュメントファイル、Issue body はリポジトリ / 履歴の
事前 context なしの初 contributor に理解可能でなければならない。

**リポジトリコミット文書または Issue body で禁止**:

- Session または conversation 識別子 (`session-NN`、"last session"、
  "previous session" 等)。
- Insider 代名詞 ("you and I"、"as we discussed"、"私"、"あなた")。
- ローカル / gitignored ファイルへの参照 (例: `.resume-prompt.md`、
  個人ノート、scratchpad ファイル)。
- 定義への link なしの unexplained プロジェクト内部 jargon。
- 絶対日付なしの相対時間表現 ("yesterday"、"recently" → `YYYY-MM-DD`
  を使用)。

**各 README で必須**:

- Purpose 文 — このモジュールが何をするか、一文で。
- Scope boundaries — 何をしないか; 他モジュールが代わりに何をするか。
- Public API surface — 何を export するか; caller が何を import すべ
  きか。
- Dependencies — 他のどのモジュール / 外部システムを使うか。
- Constants and configuration — [§5](#5-定数と設定) 参照。
- Testing pointer — モジュールのテスト実行方法。
- Ownership / area lead — 単一 owner がなければ `maintainers@` で
  可。

新規モジュール README は
[`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md)
の boilerplate から開始。

---

## 4. ソースコードコメント言語

**デフォルト: 英語**。全コメント (line comment、docstring、TODO/FIXME
マーカー、block comment) は英語。以下の明示的許可カテゴリに該当する
場合のみ日本語コメント許可。

**日本語コメント許可カテゴリ**:

1. **JP-Core / JP-CLINS プロファイル不変条件。** 日本の医療プロファ
   イル制約 (例: "JP eCS requires
   `MedicationRequest.status='completed'`") を文書化するコメントで、
   周囲の変数 / 要素名が日本語 spec 語彙 (`検体検査`、`処方せん`、
   `救急` 等) 由来なら、日本 locale contributor が spec テキストを
   相互参照できるよう日本語許可。
2. **JLAC10 / JJ1017 / MEDIS コードシステム固有事項。** 日本の
   コードシステムエントリ (5 軸 JLAC10、JJ1017 procedure code、
   MEDIS drug master、YJ code、HOT code) を引用または説明するコメント
   は元の日本語テキストを含めてよい。
3. **日本の権威ソースからの逐語引用** (厚生労働省通知、JAHIS
   technical report、jpfhir.jp implementation guide)。ソースを日本語
   で引用し、英語のみの読者が navigate できるよう英語 1 行 gloss を
   追加。

**他の全コメントは英語必須**、以下を含む:

- Simulator core (`clinosim/simulator/`)
- Audit / eval / benchmark ハーネス
- 非 JP モジュールのビジネスロジック
- Test ファイル
- CLI help 文字列 (翻訳には gettext スタイル locale ファイルを使用)

spec テキストを引用せず単に "Japanese output" や "JP handling" と
述べるコメントは日本語例外 **に該当しない** — 英語で書く。

---

## 5. 定数と設定

患者 state / 臨床ロジック / リソース出力 / user-visible 数値に影響
する全スカラ定数、閾値、cutoff、magic number は:

1. **命名** — 式中に bare リテラルとしてインライン化しない。
2. **docstring 注釈** で:
   - purpose — 何を意味するか、
   - unit — mg/dL、日、count、probability、…、
   - source / rationale — 臨床参考文献、spec section、経験的
     チューニング、design ADR または外部ソースへの link。
3. **配置** は以下のいずれか:
   - モジュールローカル `_constants.py` (モジュール private)、
   - 定数が API の一部なら モジュール public `__init__.py`、
   - 実行時可変なら `clinosim/config/*.yaml`、
   - typed config モデルなら `clinosim/types/config.py`。

docstring なしの bare `MAGIC_NUMBER = 42` は review-blocker。

---

## 6. Dead-code 衛生

- CI は `ruff` を F401 (未使用 import) と F841 (未使用 local) を
  error として実行。これが baseline。
- CI はまた `vulture` を 60% confidence で
  ([`.vulture-whitelist.py`](../../.vulture-whitelist.py) の
  プロジェクトレベル by-design whitelist に対して) 全 PR で実行
  (`vulture dead-code` ジョブ — merge-blocking)。既存 whitelist エン
  トリでカバーされない新規 finding はジョブ fail。
- Whitelist はカテゴリ分け。新規エントリ追加時は正しいカテゴリ
  (dataclass / Pydantic field; Protocol / ABC signature; test-only
  public API; test 参照 constants; あるモジュールが set し別モジュ
  ールが read する属性; 削除保留候補) 配下に配置。完全カテゴリ定義
  はファイル header 参照。
- 60% 閾値は偵察後に選択: 80% では tree が 1 finding しか出さない
  (ruff F401 が 80-99% 帯を支配する未使用 imports クラスを既に sweep
  しているため)、60% がこの codebase に有用な signal 帯。
- Dead code 削除時は完全削除を優先。"removed by X" のようなプレース
  ホルダコメントを残さない — commit 履歴が権威的記録。

---

## 7. Contributing ワークフロー

- `master` に直接 commit 禁止。全変更は branch + PR + CI + merge で
  ランド。
- 全 commit は sign off (`Signed-off-by:` trailer)。DCO CI ジョブが
  trailer 欠如の commit を merge から blocking。
- 全 commit は `ruff format` clean かつ `ruff check` clean。
- PR あたり 1 論理変更。無関係リファクタを bundle しない。
- User-facing 挙動変更は CHANGELOG エントリ必須。
- Test plan は各 PR description で必須。

完全な contribution ワークフロー (local セットアップ、DCO signoff
機構、CI ジョブ説明) は [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
参照。

---

## 8. ポリシー変更方法

本ポリシーは codebase の大部分と将来の全 PR を統治。変更は routine
ではない。変更を提案するには:

1. 変更、その動機、既存コード / ドキュメントへの期待される影響を
   記述する GitHub Issue を open。
2. PR を open する前に方向性について maintainer 合意を得る。
3. PR は本文書を更新、下流ポインタ (`AGENTS.md`、`CONTRIBUTING.md`、
   両トップレベル READMEs) を更新、以下の `## 変更履歴` エントリを
   日付 + 1 文サマリで追加。
4. 変更がポリシーを厳しくする場合、既存コード / ドキュメントが
   コンプライアンス外に落ちるものに対する follow-up Issue を起票
   し、mixed standard で放置せず codebase を追いつかせる。

### 変更履歴

- **2026-08-09** — Policy 作成。
  [`docs/superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md`](../superpowers/specs/2026-08-09-doc-code-quality-campaign-design.md)
  campaign 設計 spec の §2 から抽出。
