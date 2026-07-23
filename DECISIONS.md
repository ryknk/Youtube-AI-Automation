# DECISIONS

技術選定の理由・設計意図を記録する。「何を」だけでなく「なぜ」を残すことが目的。

- 新しい技術的決定を行った場合はここへ追記する（何を検討し、何を選び、何を却下したか）。
- このドキュメント作成以前の決定（VOICEVOXを既定TTSにした理由、BFLを既定画像プロバイダーにした理由など）については、実際の経緯が確認できていないため記載していない。推測で理由を書くことは[CLAUDE.md](CLAUDE.md)の開発方針に反するため、ユーザーに確認できた範囲でのみ追記する。

---

## stable-tsを字幕アライメントに採用し、Whisper・WhisperXは導入しない

**課題**: `character_ratio`方式の字幕タイミングは文字数比例の近似に過ぎず精度が低い。`alignment.json`を読み込む仕組み（`JsonSubtitleAlignmentProvider`）は当初から存在したが、これを生成する実装はなかった。

**決定**: stable-tsの強制アライメント機能（`model.align()`）のみを使用する。Whisperによる音声認識・文字起こし、WhisperXは導入しない。

**理由**: 既知の台本を音声へ整合させるだけで十分であり、音声認識精度に結果が依存する設計を避けるため（ユーザー指定）。

---

## `subtitles.alignment_provider`という新規キー名を採用

**課題**: stable-ts設定（provider/language/model）を`subtitles.alignment`に配置する案は、既存の字幕水平配置設定（`center`/`left`/`right`）と同名で衝突し、動画の字幕描画を壊す恐れがあった。

**決定**: 新設定は`subtitles.alignment_provider`に配置し、既存の`subtitles.alignment`（水平配置）はそのまま維持する。

**理由**: 既存機能を壊さないことを最優先する方針（CLAUDE.md）に基づき、衝突が判明した時点でユーザーに確認して決定した。

---

## alignment.jsonのスキーマを`{"provider","text","units"}`形式に統一

**課題**: 旧`JsonSubtitleAlignmentProvider`はトップレベル配列形式（`[{"start_time","end_time"}]`）を期待していたが、これを生成する実装が存在せず、実運用では一度も使われていなかった。

**決定**: stable-tsの単語単位タイムスタンプを表現できる新形式（`provider`/`text`/`units`）へ置き換えた。読み込み側は、単語単位のタイムスタンプをSubtitleSplitterの分割結果へ文字オフセットの線形補間で対応付ける方式にした。

**理由**: 旧形式は実質未使用のため後方互換性コストがなく、要件で明示された仕様をそのまま採用できた。

---

## キャッシュfingerprintをステージ別の関連設定のみに限定（config.yaml全体ハッシュを廃止）

**課題**: script/scene/audio/image/subtitle・エンディング・メタデータの各キャッシュキーが`video_settings.fingerprint`（config.yaml全体のSHA-256）を共有しており、無関係な設定変更（例: `youtube.category_id`）でも巻き添えで無効化されていた。

**決定**: 各ステージが実際に依存する設定セクションのみをfingerprintに含めるよう変更した（例: script/sceneは`providers.text`+`text`、audioは`providers.tts`+`audio`、imageは`providers.image`+`image`、subtitleは`subtitles`、動画は`video`+`subtitles`+BGM設定）。

**理由**: CLAUDE.mdの「設定変更時は必要最小限のみ再生成すること」「不要な再生成は禁止」に従うため。API課金を伴う再生成（台本・音声・画像）を不要に発生させない実利もある。

---

## メタデータキャッシュを`fingerprint`と`title_fingerprint`の2系統に分離

**課題**: `metadata.title_count`（タイトル生成数）はタイトル生成にのみ影響するが、単一のfingerprintに含めると詳細情報（description/tags等）のキャッシュも無関係に無効化されてしまう。

**決定**: `fingerprint`（text/providerに影響、titles・details両方が共有）と`title_fingerprint`（metadataセクション、titlesのみに影響）を分離した。`GenerateMetadataUseCase.execute_cached`に`title_fingerprint`パラメータを追加。

**理由**: 過不足のないキャッシュ無効化範囲を実現するため。

---

## エンディング音声のテンプレート別TTSプロバイダーを`Callable`経由で解決

**課題**: `EndingManager`は`ending generate-all`のように複数テンプレートで1インスタンスを使い回す設計のため、TTSプロバイダーを固定インスタンスとして渡すとテンプレート別VOICEVOX設定（本編では既に対応済み）を反映できなかった。

**決定**: 既存の`renderer_for_template: Callable[[str], EndingRenderer]`と同じパターンで、`tts_provider_for_template: Callable[[str], TTSProvider]`を追加した。キャッシュキー（`asset_fingerprint_for_template`）にもテンプレート別の解決後audio設定を含めた。

**理由**: 既存アーキテクチャの確立されたパターンに合わせることで、大規模リファクタリングを避けつつ一貫性を保つため。

---

## 動画キャッシュの対象を「結合前のvideo.mp4」に限定

**課題**: エンディング結合（`EndingManager`）・BGM最終ミックス（`FinalBGMRenderer`）には、既にそれぞれ独自のSHA-256ベースのキャッシュ機構がある。

**決定**: 新設する動画キャッシュ（`--generate-video`）は本編レンダリング（`video.mp4`、結合前）のみを対象とし、結合後のmain/ending/final生成は既存機構にそのまま任せる。

**理由**: キャッシュ責務の重複を避け、変更範囲を最小限にするため。

---

## `--generate-video`に`--force`フラグを追加

**課題**: 動画キャッシュを追加すると、入力が変わっていない場合に強制的に再レンダリングする手段がなくなる（ffmpeg出力の異常確認、動画コーデック更新後の再生成などのユースケースに対応できない）。

**決定**: 既存の`ending generate --force`/`render final --force`と同じパターンで`--force`フラグを追加した。

**理由**: 既存の類似コマンドとの一貫性を保つため。事前にユーザーとこの設計の是非を相談し合意した。

---

## `render final`と`render remix-bgm`はエイリアスのまま維持し、機能分離しない

**課題**: `cli/render.py`では両コマンドのパーサー定義・処理内容が同一で、コード上の機能差がない。

**決定**: 分離せず現状維持とした。

**理由**: `FinalBGMRenderer`が既にmain/ending/BGM内容のハッシュで差分キャッシュしており、「BGMだけ変更→finalだけ再生成」という`remix-bgm`が意図する挙動は`render final`だけで自動的に実現される。コマンドを分けても実質的な挙動改善がなく、判断コストが増えるだけと判断した。

---

## PluginManagerのtext provider決め打ちは解消せず、テストのみ追加

**課題**: `create_scene_splitter`/`create_metadata_generator`は`providers.text == "openai"`前提の分岐になっている。

**決定**: 抽象化を広げず、未対応プロバイダー指定時に`ValueError`を返す既存分岐へのユニットテストのみ追加した。

**理由**: 現時点でtextプロバイダーの実装はOpenAIのみであり、抽象化の拡張は依頼にない将来対応（投機的一般化）になるため。2つ目のtextプロバイダーが必要になった時点で改めて検討する（[TASKS.md](TASKS.md)参照）。

---

## ジョブパイプラインの台本出力先を、スキャンではなく決定的な計算で特定

**課題**: `jobs/pipeline.py`の`ExistingPipelineRunner`は、台本生成後の出力先を`output/`以下の全走査＋mtime最大値の推測（`_new_script_dir`）で特定していた。他ジョブ・他プロセスが同時に`script.txt`を書き込むと誤ったディレクトリを選ぶ可能性があった。

**決定**: 台本生成時に既に`--run-id job.job_id`を渡していることに着目し、`GenerateScriptUseCase.output_directory(output_dir, theme, template, run_id)`（`cli/main.py`が内部で使うのと同じ関数）を直接呼んで出力先を計算する方式に置き換えた。スキャン・スナップショット比較を廃止。

**理由**: 出力先は`theme`・`template`・`run_id`から一意に決まる決定的な値であり、既に呼び出し元が知っている情報だけで計算できるため、ファイルスキャンによる競合リスクを完全に排除できる。既存の`GenerateScriptUseCase.output_directory`を再利用するため、パス計算ロジックの二重実装にもならない。

**却下した代替案**: `cli/main.py`の`--theme`処理に出力先を明示指定できるオプションを追加する案も検討したが、CLIパーサー本体の変更が必要になり変更範囲が広がるため見送った。

---

## 関連ドキュメント

- [CLAUDE.md](CLAUDE.md) — 開発方針・アーキテクチャ・コーディング規約
- [TASKS.md](TASKS.md) — 今後実装予定のタスク一覧
- [CONTRIBUTING.md](CONTRIBUTING.md) — Git運用ルール
