# リリース前チェックリスト

リリースタグ (`vX.Y.Z`) を push する前に、以下のすべての項目を完了することが必須です。タグの push は取り消せません。PyPI は同じバージョンの再アップロードを受け付けないため ([PyPI への公開](publishing-to-pypi.ja.md) を参照)、タグ後に見つかった問題は新しいパッチリリースが必要になります。タグを打つコミットに対して各節を順に実施し、結果 (数値、実行リンク) をリリース PR またはリリースノートに記録します。

`__version__` の更新、CHANGELOG 見出しの置き換え、タグの push は、以下の全節が完了し、メンテナがリリースを承認した後にのみ行います。

## 1. ドキュメントがコードと一致している

- [ ] `CHANGELOG.md` の `## [Unreleased]` に、前回タグ以降に merge したすべての PR が載っている。`git log vPREV..HEAD --oneline` と項目を突き合わせ、CIF の値が変わる変更はその旨を明記する。
- [ ] バージョン区分がバージョニング方針に従っている。CIF (または CIF とその narrative) が変わる変更は MINOR、FHIR のみの変更は PATCH。
- [ ] 前回タグ以降に変更したモジュールの `README.md` / `SPEC.md` が現在の挙動を記述している。記載された式・定数・既定値・ファイル名がコードと一致する。
- [ ] 前回タグ以降に変更した英語ページの `.ja.md` 版も更新されている (逆も同様、`git diff --stat vPREV..HEAD -- '*.md'`)。
- [ ] `README.md` と `docs/` に書かれた件数・既定値 (疾患数、リソース種別、CLI の既定値) がコードと一致する。
- [ ] ローカルで `mkdocs build --strict` が通る (`docs.yml` workflow も同じコマンドを実行する)。

## 2. 生成速度が劣化していない

- [ ] 前回タグとリリースコミットで同じコホート (同じ国・`--population`・`--seed`、US と JP を 1 回ずつ) を生成し、CIF 生成と FHIR 生成の実行時間とピークメモリを記録する。
- [ ] テンプレート narrative (`clinosim narrate`) の処理量も同様に記録する。
- [ ] いずれかの工程で 20 % を超える遅延があれば、リリース前に調査する。修正するか、リリースノートで理由を説明する。
- [ ] 測定した数値をリリース PR に記録し、次回リリースの基準値にする。

## 3. 品質ゲートがリリースコミットで green

- [ ] リリースコミットで `Nightly` を手動実行 (`workflow_dispatch`) し、全ジョブが green (再現性と slow の e2e テスト)。
- [ ] リリースコミットで `US Core narrow compliance gate` と `JP compliance gate (JP-CLINS lab + JP Core)` が green。
- [ ] `US FHIR validate` と `JP FHIR validate` が green (リリースコミットで走っていなければ手動実行する)。
- [ ] リリースコミットで生成した US と JP の新しいコホートを `clinosim eval` ([eval](../eval.ja.md)) で採点し、前回タグより下がった軸がない (下がった場合は理由を説明する)。
- [ ] 新しいコホートに対してコホート全体のデータ品質レビュー (構造、時系列、因果、経年、ロケール、用語、narrative、文書密度) と、層化抽出した患者単位のレビューを行う。確認された問題はすべて Issue 化し、リリースを止めるかどうかを判定する。
- [ ] 両コホートで `python scripts/verify_medical_stats.py <cohort_dir> <US|JP>` を実行し、有病率・在院日数・死亡率・イベント発生率が目標範囲内にあり、動いた指標はすべて CHANGELOG の項目で説明できる。

## 4. 前回リリースからの変化を説明できる

- [ ] 第 2 節で前回タグとリリースコミットから生成したコホートの集計値 (リソース種別ごとの件数、在院日数、死亡率、文書数) を比較し、目立つ差はそれぞれ CHANGELOG の項目に対応づける。
- [ ] 生成したコホートは数値を記録した後に削除する。

## 5. パッケージがインストールでき、動く

- [ ] wheel をビルド (`python -m build`、`twine check dist/*`) し、空の仮想環境にインストールして US と JP で小さな `clinosim simulate` を実行する。データファイルの欠落や import エラーがない。
- [ ] `release.yml` がビルドするデータセットプリセット (us-100 / us-1000 / jp-100 / jp-1000) が、workflow と同じ環境設定でローカルでもビルドできる。

## 6. Issue と PR が整理されている

- [ ] このリリースに入れる予定の未 merge の PR がない。
- [ ] open の `bug` と `data-quality` の Issue を判定済みで、リリースを止めるものがない (あれば修正済み)。
- [ ] merge した PR で直した Issue がすべて close されている (PR 本文に `Addresses #N` がないと Issue は close されない)。

## 7. リリースを切る

メンテナの承認後にのみ、[PyPI への公開](publishing-to-pypi.ja.md) の「リリースを切る」に従う。`__version__` を更新し、`## [Unreleased]` の内容を新しいバージョン見出しの下に移し、commit し、タグを push して、`release.yml` が GitHub Release と PyPI へのアップロードを完了するまで見届ける。
