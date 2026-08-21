# clinosim へのコントリビュート

ご興味ありがとうございます。

**clinosim は独立した個人プロジェクト**です
([README](README.ja.md))。本ドキュメントは手続きを軽く保ちつつ、
プロジェクトが依拠する 2 つの hard property を保護します:

- **決定論** — `(seed, config, country, start, end, population)`
  タプル固定で、同一 MINOR release 系列内は出力 byte-identical。
  `random.random()` や global 共有 RNG state を絶対に導入しない。
  全乱数 draw は渡された `numpy.random.Generator` の sub-seed から
  派生させる。
- **合成データのみ** — 実患者データ / PHI / PII を参照 / 埋め込み
  / 再現しない。全出力は完全合成。[README](README.ja.md#clinosim)
  の免責参照。

コードに触れる予定なら以下も読んでください:

- [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) —
  新モジュール / plug-in / FHIR builder 追加の実務 playbook
  (Base vs Module 判別、enricher stage、registry 利用、
  `clinosim audit run` による PR 検証)。
- [`DESIGN.md`](DESIGN.md) — 55+ の architecture decision record
  (`docs/architecture/` 配下 3 file に split 済み)。
  日本語版: [`DESIGN.ja.md`](DESIGN.ja.md)。
- [`AGENTS.md`](AGENTS.md) — repo 全体の規約と invariant
  ([AGENTS.md convention](https://agentmd.dev) 準拠の
  canonical AI-agent instruction; `CLAUDE.md` は本 file への
  thin pointer)。
- [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md)
  — 新モジュールディレクトリの boilerplate。
- [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)
  — ドキュメント言語 pairing (英語 + 日本語)、source code コメント
  言語ルール、self-contained OSS quality 標準、定数 documentation
  ルール、dead-code 衛生。全 PR は本ポリシーに対して review されます。

---

## セットアップ

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Sanity check:

```bash
clinosim --help
pytest tests/unit -q               # ~1 分、green 必須
```

---

## ワークフロー

1. **非自明な変更はまず issue を開く** — scope とアプローチに合意
   してから時間を投じるため。バグ報告と機能要望は専用テンプレート
   あり。
2. **`master` から fork + branch**。descriptive な branch 名
   (`fix/…` / `feat/…` / `docs/…`) を使う。
3. **小さく focus した commit**。1 PR = 1 論点は mega-diff より
   遥かにレビューしやすい。
4. **commit に sign off (DCO — 必須)**。下記
   [DCO](#dco--signed-off-by-必須) 参照。
5. **PR を開く前に local で test 実行**:

   ```bash
   pytest tests/unit -q                       # 必須、~1 分
   pytest tests/integration -q                # simulator / output / FHIR
                                              # コード経路に触るとき推奨
                                              # (local ~18 分、CI ~30 分)
   ```

   任意 local check (CI と同じ command; 既存 lint / type 負債の
   解消途中のため CI では現在 informational マーク):

   ```bash
   make lint                                  # ruff check + ruff format --check
   make typecheck                             # mypy clinosim/
   ```

6. **`CHANGELOG.md` を更新** — `[Unreleased]` 節にユーザー向け挙動
   変更の bullet を追記。docs-only PR のみ省略可。
7. **PR を開く** — PR テンプレートが checklist を案内。
8. **merge 前に CI 必須 job がすべて green**:
   - `Unit tests (Py 3.12)`
   - `Integration tests (shard 1/3, 2/3, 3/3)`
   - `Build sdist + wheel`
   - `Signed-off-by check`
   - `mkdocs build`
   - `JP-CLINS lab compliance gate`
   - `ruff dead-code (F401 / F841)`
   - `vulture dead-code`

   Informational (merge-block しない):
   - `Quality (informational)` — ruff check + ruff format --check + mypy

   Python 3.11 unit-test 互換性は nightly 実行
   ([`.github/workflows/nightly.yml`](.github/workflows/nightly.yml))。
   Full workflow は [`.github/workflows/`](.github/workflows/) 参照。

---

## DCO — Signed-off-by (必須)

CLA の代わりに
[Developer Certificate of Origin](https://developercertificate.org/)
(DCO) を採用。全 PR 上の全 commit は author に一致する
`Signed-off-by:` trailer を持つ必要があります。これはあなたが本
プロジェクトのライセンスで変更を提供する権利を持つ声明です。

**commit の sign 方法**:

```bash
git commit -s -m "your message"
# または、branch 内の全 commit を自動 sign:
git config format.signOff true
```

Trailer 形式:

```
Signed-off-by: Jane Doe <jane@example.com>
```

**branch の retro-sign** (maintainer が merge する前に):

```bash
git rebase --signoff origin/master
# 単一 commit なら:
git commit --amend --signoff --no-edit
git push --force-with-lease
```

`DCO` GitHub Actions job は trailer 欠落 commit があれば merge を
block します。

---

## 良い PR とは

- **具体的なバグ報告 or 機能要望と紐づく** (issue link)。動機となる
  問題が無い「Refactor X for readability」は通常良い PR ではない。
- **無関係な変更を混ぜない**。1 バグを直しつつ 400 file を reformat
  しない — pre-existing な lint / format 負債は別 issue で消化
  ([`good first issue`](https://github.com/TomoOkuyama/clinosim/labels/good%20first%20issue))。
- **バグを捕らえたはずの test** (fix の場合) または新挙動を exercise
  する test (feature の場合)。simulation 経路に触る変更は determinism
  check が必須 — 最も簡単なのは同一 seed で 2 回実行して byte-diff。
- **CHANGELOG entry** — diff で何が変わったかではなく、ライブラリ
  ユーザーにとって何が変わったかを記す。
- **doc 更新** — 新モジュール / YAML field / CLI subcommand / 公開
  API 表面を追加する変更で必須。

---

## Documentation + code コメント言語ポリシー

全 PR は
[`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)
に対して review されます。要点:

- ドキュメント file は言語ペアで提供: 英語 `README.md` + 日本語
  `README.ja.md` (`docs/` 配下も同じ)。
- 英語ドキュメント内リンクは英語ドキュメントを指し、日本語
  ドキュメント内リンクは日本語ドキュメントを指す。
- README + issue body は self-contained。session 識別子 / 内輪の
  代名詞 / gitignore file への参照は禁止。
- source code コメントは英語 default。日本語は JP-Core / JP-CLINS
  profile invariant、JLAC10 / JJ1017 / MEDIS code system 固有事項、
  日本語 authoritative source の verbatim 引用のみ許可。
- 全 scalar 定数 / threshold / magic number は名前付与 + docstring
  (purpose / unit / source) 付与し、ポリシーに従った適切な場所に
  配置。
- CI が dead-code baseline (`ruff` F401 / F841) と DCO signoff を
  強制。

ドキュメント追加 / 変更を含む PR は開く前に完全なポリシーを一読
してください。

---

## バグ報告 + 機能要望

[issue templates](https://github.com/TomoOkuyama/clinosim/issues/new/choose)
を使用。セキュリティ問題は [`SECURITY.ja.md`](SECURITY.ja.md) 参照
— 公開 issue は **開かないでください**。

---

## Code of Conduct

参加は [Code of Conduct](CODE_OF_CONDUCT.ja.md) の対象。

---

## Licensing

全 contribution は [MIT License](LICENSE) の条件で licensed される。
DCO で commit を sign することにより、当該コードを本ライセンス下で
提出する権利を保持する旨を宣言します。

英語版: [`CONTRIBUTING.md (English)`](CONTRIBUTING.md)。
