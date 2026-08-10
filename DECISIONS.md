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

## Qwen-Imageプロバイダーを既存のFLUX self-hostパターンで追加

**課題**: 画像生成プロバイダーとしてQwen-Imageを追加したい。

**決定**: 既存のFLUX.1 Schnell self-host実装（`dataclass`のSettings + 遅延importするProvider、`PluginManager`への1分岐追加で完結する構成）と同じアーキテクチャパターンを踏襲し、`QwenImageLocalSettings`/`QwenImageLocalImageProvider`を追加した。

**理由**: CLAUDE.mdの「Providerは既存インターフェースを利用する」「動画生成PipelineへProvider固有処理を書かない」方針に沿い、確立済みパターンを再利用することで実装・レビューコストを下げるため。

---

## nunchaku(4bit量子化)版を既存のqwen_image_localとは別プロバイダーとして追加

**課題**: 通常のQwen-Image（bf16）は約20Bパラメータ分のVRAMを要し、12GB級GPUではCPUオフロードが必須で生成が低速になる。4bit量子化（nunchaku/SVDQuant）でVRAM使用量・速度を改善したい。

**決定**: 既存の`qwen_image_local`を置き換えず、`qwen_image_nunchaku_local`という別プロバイダーとして追加した。`providers.image.scene`で明示的に切り替える。

**理由**: 量子化により生成品質・挙動が変わりうるため、ユーザーが両方を比較しながら明示的に選択できるようにする必要があったため。

---

## nunchaku利用時はdiffusersを0.36.0に固定

**課題**: nunchaku 1.2.1環境で実際に画像生成すると、当初導入していたdiffusers 0.39.0では`TypeError: QwenEmbedRope.forward() got multiple values for argument 'device'`が発生し生成に失敗することを実機で確認した。

**決定**: `requirements-qwen-image-nunchaku-local.txt`とpyproject.tomlの`qwen-image-nunchaku-local` extraで`diffusers==0.36.0`に固定した。

**理由**: nunchaku 1.2.1のCI extra自体が`diffusers==0.36`を明示的にピン留めしており、この組み合わせでのみ動作を確認できたため。より新しいdiffusersとの非互換は実機で再現・確認済み。

---

## nunchaku量子化transformerのキャッシュ先を、huggingface_hub.constants.HF_HUB_CACHEの上書きで解決

**課題**: nunchaku本体の`NunchakuQwenImageTransformer2DModel.from_pretrained()`は`cache_dir`引数を受け取っても内部の`hf_hub_download()`呼び出しへ転送しないため、`image.qwen_image_nunchaku_local.model_cache_dir`が量子化transformer本体のダウンロード先に反映されない（`nunchaku/utils.py`の実装を確認済み）。

**決定**: `QwenImageNunchakuLocalImageProvider`がモデルロード時に`huggingface_hub.constants.HF_HUB_CACHE`（`hf_hub_download()`がcache_dir未指定時に参照する既定値）を`model_cache_dir`の値へ直接上書きする方式にした。

**却下した代替案**: `run.ps1`で`HF_HUB_CACHE`環境変数を設定する対処を一度実装したが、ユーザーの指示により撤回した。

**理由**: config.yamlを設定の唯一の情報源とする既存方針（CLAUDE.mdの「設定はconfig.yamlが基本設定」）に合わせるため。実行ラッパー（run.ps1）側にモデル固有の挙動を持たせるより、プロバイダーコード内で完結させる方が責務が明確になる。

---

## 画像プロバイダー共通のプロンプト追記設定を`prompt_suffix`に統一し、コード上の既定値を空文字列にする

**課題**: Qwen-Image系のみ`quality_suffix`という独自名称を使っており、FLUX/BFL/OpenAIの`prompt_suffix`と名称が不統一だった。また各プロバイダーのコード上のデフォルト値に`"No text."`等の文言をハードコードしていたため、実際に付加される内容がコードを読まないと分からない状態だった。

**決定**: 全プロバイダーで名称を`prompt_suffix`に統一した。コード上の既定値は空文字列にし、実際に付加する内容はconfig.yamlでのみ定義する。

**理由**: ユーザーの明示的な指示。「より汎用的なサフィックス設定項目として使いたい」という意図に合わせ、config.yamlを見るだけで実際の挙動が分かるようにするため。

---

## 共有ImagePromptBuilderから"no text"制約を削除し、各プロバイダーのprompt_suffixへ移管

**課題**: 画面内への意図しない文字描画を防ぐ"no text."指示が、全プロバイダー共有の`ImagePromptBuilder`にハードコードされていた。

**決定**: 共有コードから削除し、FLUX/BFL/OpenAI/Qwen-Image系それぞれの`prompt_suffix`設定（config.yaml）で個別に指定する方式に変更した。FLUXはguidance_scale=0.0の蒸留モデルで`negative_prompt`が効かず、BFL APIには`negative_prompt`相当のパラメータがないため、いずれもポジティブプロンプトへの追記という同じ方式で統一実装した。

**理由**: CLAUDE.mdの「動画生成PipelineへProvider固有処理を書かないこと」方針に沿うため。

---

## Windows開発者モードの有効化を採用し、Pythonの管理者権限実行は行わない

**課題**: huggingface_hubのモデルキャッシュがWindowsでsymlinkを使えず、「劣化モード」（ファイルコピー）で動作しディスク使用量が増えていた。対処法はOS側の開発者モード有効化、またはPythonを管理者権限で実行する方法の2通りが存在する。

**決定**: Windows開発者モードの有効化（ユーザー側で実施）を採用し、アプリを管理者権限で実行する方式は導入しなかった。

**却下した代替案**: `run.ps1`の自己昇格によるアプリ全体の管理者権限実行。技術的には可能だが不採用とした。

**理由**: 開発者モードはシンボリックリンク作成権限のみを解放する限定的な変更である一方、管理者権限化はアプリが行う全処理（サードパーティ製ライブラリの実行を含む）にシステム全体への読み書き権限を与えることになり、最小権限の原則に反しセキュリティ上の影響範囲がはるかに大きいため。

---

## stable-tsの部分的なアライメント失敗による字幕の累積ズレを、シーン境界のパディングで補正

**課題**: stable-tsは音声全体ではなく検出できた単語区間のみのタイムスタンプを返す。シーン内の最初の単語より前・最後の単語より後に無音区間があると（`Failed to align the last N words after ...`という警告が出るケース）、そのシーンの字幕合計時間がシーン音声の実際の長さより短くなる。この不足が全シーンに積み重なり、動画全体で字幕表示が音声より先行する（音声が遅れて聞こえる）ドリフトを引き起こしていた。また動画全体で見たときに字幕終端と音声合計長の差が品質チェックの閾値（1.0秒）を超え、`RuntimeError`で動画生成が停止する不具合も発生していた。

**決定**: `JsonSubtitleAlignmentProvider.align()`で、各シーンの先頭セグメントの開始時刻を`0`、末尾セグメントの終了時刻をシーン音声の全長（`duration`）まで拡張し、無音区間を隣接する字幕の表示時間へ吸収させる。加えて`GenerateSubtitlesUseCase`側に、全シーン処理後の字幕合計時間が音声合計時間よりまだ短い場合にのみ最終行を延長する`_pad_tail`をセーフティネットとして追加した。

**理由**: シーン単位で音声全長と字幕合計時間を一致させることで、シーン境界ごとの累積時間ズレそのものを解消できる（動画全体の末尾だけを合わせる対処では、途中経過のズレは残ってしまうため）。拡張は常に時間を延ばす方向のみに限定し、`character_ratio`方式やアライメントが完全に成功しているシーンの挙動には影響しない。

---

## シーン画像プロンプトへ生の日本語ナレーション文を渡さず、OpenAIで生成した英語の場面説明を渡す

**課題**: Qwen-Image等の文字レンダリング精度が高いモデルでは、シーン画像プロンプトに日本語ナレーション文をそのまま含めると、その文章が字幕・キャプションのように画面へ描画されてしまう問題があった。

**決定**: `providers.text`が`openai`の場合に限り、`image.scene_description.enabled: true`で有効化できる`OpenAISceneVisualDescriber`を追加した。動画1本分のシーン文をまとめて1回のAPI呼び出しで短い英語の場面説明へ変換し、画像プロンプトにはナレーション文の代わりにこの説明文を渡す。未設定時は従来どおり原文をそのまま使う。

**理由**: プロンプト側の否定的な指示（"no text"等）だけでは、モデルの文字描画能力が高いほど原文がそのまま描画される問題を防ぎきれなかったため、そもそも日本語の生文をプロンプトへ渡さない方式に切り替えた。

**参照**: [openai_scene_visual_describer.py](src/youtube_generator/infrastructure/openai_scene_visual_describer.py)、[scene_visual_describer.py](src/youtube_generator/plugins/base/scene_visual_describer.py)、`config/config.yaml`の`image.scene_description`。

---

## シーン画像の後処理として`ImageEditor` Protocolを新設し、既存Providerの抽象と分離した

**課題**: シーン画像に字幕・キャプション風の文字が写り込む場合があり、生成後に除去する後処理が必要になった。既存の`ImageProvider`（生成）とは責務が異なる。

**決定**: 生成とは別の`ImageEditor` Protocol（[image_editor.py](src/youtube_generator/plugins/base/image_editor.py)）を新設し、`QwenImageEditNunchakuLocalImageProvider`（Qwen-Image-Edit-2509のnunchaku 4bit量子化版）を実装した。`image.scene_edit.enabled`で有効化し、`PluginManager`経由で取得する（`create_image_editor`）。未設定時は編集ステップをスキップする。

**理由**: CLAUDE.mdの「Providerは既存インターフェースを利用する」「動画生成PipelineへProvider固有処理を書かない」方針に沿い、生成と編集という異なる責務を1つのインターフェースに混在させないため。編集後の画像で下部の帯を除去した領域が反転コピー（鏡写し）される副作用を実測で確認したため、既定プロンプトにそれを避ける指示を含めている。

**参照**: [qwen_image_edit_nunchaku_local.py](src/youtube_generator/plugins/image/qwen_image_edit_nunchaku_local.py)、[generate_scene_images.py](src/youtube_generator/app/generate_scene_images.py)、`config/config.yaml`の`image.scene_edit`/`image.qwen_image_edit_nunchaku_local`。

---

## シーン内の複数画像・表示タイミングを「推定生成→実時間スナップ」の2段階方式にした

**課題**: 1シーン1画像だと、音声が長いシーンで画像が単調に見え続ける。かといって画像生成時点の表示時間を実際の音声長・stable-tsアライメントへ直接連動させると、TTSや字幕設定を変更するたびに無関係なシーン画像まで再生成されてしまい、CLAUDE.mdの「必要最小限のみ再生成」というキャッシュ方針に反する。

**決定**: 画像生成時は`characters_per_second`による文字数からの推定時間のみを使い、文単位の自然な区切りで`image.min_display_seconds`〜`image.max_display_seconds`の範囲に収まるよう複数画像（`sceneNN_MM.png`）へ分割する。動画レンダリング時には、生成済みの実画像枚数を正として、実音声長・アライメント結果の区切りへ表示秒数をスナップさせる（`distribute_duration`）。

**理由**: 画像生成とタイミング確定を分離することで、音声・字幕設定の変更時にシーン画像が不要に再生成されるのを防ぎつつ、最終的な表示タイミングは実際の音声に自然に合わせられるため。

**参照**: [scene_image_timing.py](src/youtube_generator/services/scene_image_timing.py)、[generate_scene_images.py](src/youtube_generator/app/generate_scene_images.py)、`config/config.yaml`の`image.min_display_seconds`/`image.max_display_seconds`。

---

## Civitai配布の単一ファイルモデル（`transformer_path`）でPixelWave等のFLUX派生モデルに対応

**課題**: Civitaiで配布されているFLUX.1 Schnell派生モデル（PixelWave等）の多くは、transformer（拡散モデル本体）のみを含む単一safetensorsファイルで配布されており、VAE・テキストエンコーダ（CLIP L, T5xxl）・tokenizer・schedulerを含まない。

**決定**: `image.flux_schnell_local.transformer_path`が指定された場合のみ`FluxTransformer2DModel.from_single_file()`でtransformerを読み込み、他のコンポーネントは`model_id`のベースモデルからそのまま流用する構成にした。未指定時は従来どおり`model_id`のtransformerを使う。

**理由**: 既存の`FluxSchnellLocalImageProvider`の構造を変えずに拡張でき、ベースモデルを再利用することでVAE・テキストエンコーダの二重ダウンロードを避けられるため。

**参照**: [flux_schnell_local_image.py](src/youtube_generator/plugins/image/flux_schnell_local_image.py)、READMEの「Civitai等の単一ファイルモデル（transformer_path）を使う方法」。

---

## 字幕背景ボックスの透過不具合を`BorderStyle=4`への変更で修正

**課題**: `subtitles.box_enabled=true`時、`background_opacity`を設定しても背景ボックスが常に完全不透明で描画されていた。

**決定**: ASSスタイルの`BorderStyle`を、不透明ボックスを描画する`BorderStyle=3`から、アルファ値を尊重する`BorderStyle=4`へ変更した。`BorderStyle=4`では`Outline`と`Shadow`の役割が変わる（`Outline`が通常の文字縁取り、`Shadow`がボックスの余白）ため、既存の余白量を維持するようこれらの値も調整した。

**理由**: 実機でffmpeg出力のピクセル値を検証した結果、libassの`BorderStyle=3`は`BackColour`のアルファ値を無視して常に完全不透明になる既知の制限があり、`BorderStyle=4`のみ意図通り半透明合成されることを確認したため。

**参照**: [subtitle_style.py](src/youtube_generator/services/subtitle_style.py)。

---

## シーン画像プロンプトから引用符付きセリフを除去し、否定列挙による対策は撤回した

**課題**: 台本中の「」『』等の引用符で囲まれたセリフが、シーン画像にそのまま崩れた文字として描画される問題があった。

**却下した代替案**: `no speech bubbles`等の禁止事項を列挙して強化する方式を一度実装したが、BFL公式プロンプトガイドが「FLUXはnegative_prompt非対応であり、禁止事項ではなく望む内容を記述すべき」「禁止事項の列挙はむしろその概念を想起させ逆効果になりうる」と明記しており、撤回した。

**決定**: 台本中の引用記号（`「」『』""`等）を正規表現で除去してからプロンプトへ渡す方式にした。禁止事項の列挙は`no text`のみに縮小した。

**理由**: BFL公式ガイドに「引用符付き文言は画面内描画指示として解釈される」と明記されており、引用符そのものを除去する方が根本的かつガイドラインに沿った対策だったため。

**参照**: [image_prompt_builder.py](src/youtube_generator/services/image_prompt_builder.py)。

---

## 性別・日本人らしさを反映するCharacter depiction指示を、config設定ではなく共通ImagePromptBuilderへ常時追加

**課題**: シーン画像生成結果で、人物の性別が視覚的に判別しづらい場合や、日本人向け動画にもかかわらず人物の見た目が日本人らしくない場合があった。

**決定**: シーンごと・キャラクターごとの属性を保持するドメインモデルは新設せず、全テンプレート共通の`ImagePromptBuilder`に「Character depiction」指示（性別ごとの体格・服装描写、日本人向け動画である旨の容姿描写）を常時追加した。config設定によるON/OFFは設けていない。

**理由**: 現状のドメインにシーンごとのキャラクター属性を保持する構造がなく、個別設定の仕組みを新設すると変更範囲が広がるため、既存の共通プロンプト強化で対応した。

**参照**: [image_prompt_builder.py](src/youtube_generator/services/image_prompt_builder.py)。

---

## BGMミックスの`amix`に`normalize=0`を明示し、ナレーション音量をBGM有無に関わらず統一

**課題**: ffmpegの`amix`フィルターは既定で`normalize=1`のため、BGM有効時にナレーション音量が自動的に下げられていた。本編はBGM無効だとミックス処理自体をスキップするため減衰の影響を受けず、BGM有効なエンディングとの間でナレーション音量に差が生じていた。

**決定**: 本編・エンディング・`final_mix`すべての`amix`フィルターへ`normalize=0`を明示した。

**理由**: BGMの有効・無効やレンダリング対象（本編/エンディング/final_mix）に関わらず、ナレーション音量を一定に保つため。

**参照**: [ffmpeg_video_renderer.py](src/youtube_generator/infrastructure/ffmpeg_video_renderer.py)、[ending/renderer.py](src/youtube_generator/ending/renderer.py)、[final_bgm_renderer.py](src/youtube_generator/infrastructure/final_bgm_renderer.py)。

---

## ジョブキューの実行順序のタイブレークを、ランダムな`job_id`からSQLite組み込みの`rowid`へ変更

**課題**: `jobs`テーブルの`created_at`は秒未満の精度を持たず、同時刻でタイになった場合、従来のタイブレーク（ランダムなUUIDの`job_id`）では登録順を保証できず、キュー実行順が意図せず入れ替わることがあった。

**決定**: `ORDER BY created_at, rowid`とし、タイブレークをSQLite組み込みの挿入順連番`rowid`に変更した。スキーマ変更・マイグレーションは不要だった。

**理由**: `rowid`は挿入順に単調増加するSQLiteの組み込み機能のため、スキーマを変更せずに登録順序を確定的に保証できるため。

**参照**: [jobs/manager.py](src/youtube_generator/jobs/manager.py)の`list()`・`_next_pending()`。

---

## ジョブ再試行時の画像生成・編集を、既存ファイル判定と編集済みマーカーで部分再開できるようにした

**課題**: `--generate-images`/`--edit-images`はいずれもバッチ単位（全件成功して初めて）でしかキャッシュを保存しないため、生成・編集の途中でプロセスが強制終了された場合（生成用モデルと編集用モデルの切り替え時にVRAM/システムメモリを圧迫しハングし得ることは既知）、キューからのジョブ再試行時にキャッシュmiss扱いとなり、既に完了していた画像まで最初から生成・編集し直していた。

**決定**: `GenerateSceneImagesUseCase.execute()`は出力先の`sceneNN_MM.png`が既に存在する画像の生成をスキップするようにした。`--generate-images`側は、作業フォルダに既存の`scene*.png`がある場合はキャッシュからの復元（上書き）を行わず既存ファイルを活かして不足分のみ生成する（復元による編集済み内容の上書き事故を防止）。`--edit-images`側は画像ごとに編集済みマーカー（`sceneNN_MM.png.edited`、編集キー入り）を新設し、同じ編集設定で既に編集済みの画像はスキップする（編集は破壊的処理のため二重編集は画質劣化を招く）。

**理由**: CLAUDE.mdの「設定変更時は必要最小限のみ再生成すること」「不要な再生成は禁止」に従うため。既存のバッチ単位キャッシュ機構（`CacheManager`）はそのまま維持し、中断からの部分再開のみを追加する形にすることで変更範囲を最小限にした。

**参照**: [generate_scene_images.py](src/youtube_generator/app/generate_scene_images.py)、[cli/main.py](src/youtube_generator/cli/main.py)の`args.generate_images`/`args.edit_images`分岐。

---

## `queue`コマンド実行時にRUNNINGジョブをPID生存確認付きで自動回収するようにした

**課題**: `recover_interrupted()`（RUNNINGのまま残ったジョブをPENDINGへ戻す処理）は`queue run`（`run_pending()`）内でしか呼ばれておらず、PowerShellを閉じる等でプロセスが強制終了されると、ジョブはDB上`RUNNING`のまま残り続けた。`retry`/`cancel`/`delete`はいずれも`RUNNING`状態のジョブを拒否する実装のため、次に`queue run`を実行しない限り復旧不可能だった。

**決定**: `jobs`テーブルに`pid`列を追加（既存DBはマイグレーションで自動追加）し、`run_pending()`実行時に自プロセスのPIDを記録するようにした。`recover_interrupted()`はPIDが生存していないジョブのみをPENDINGへ回収するよう変更し、`cli/queue.py`の`manager`生成直後、すべてのサブコマンド（`add`/`list`/`retry`/`cancel`/`delete`等）の実行前に呼ぶようにした。

**却下した代替案**: 単純に「RUNNINGなら全部PENDINGへ戻す」実装を全コマンドから呼ぶ案も検討したが、別ターミナルで実際に`queue run`が稼働中のジョブまで誤って巻き戻し、二重実行（同じジョブが同時に2回処理される）を招く恐れがあるため採用しなかった。

**理由**: PID生存確認（Windows API `OpenProcess`+`GetExitCodeProcess`）により、「プロセスが強制終了された中断」と「別プロセスで実際に実行中」を区別できるため。PIDは再利用され得るため、プロセス終了後に別プロセスが同じPIDを取得した場合に誤判定する可能性は既知の限界としてコード内に明記している。

**参照**: [jobs/manager.py](src/youtube_generator/jobs/manager.py)の`recover_interrupted()`/`_is_process_alive()`、[cli/queue.py](src/youtube_generator/cli/queue.py)。

---

## `--force`フラグを`--generate-images`/`--edit-images`にも適用

**課題**: 中断ジョブの部分再開機能（既存ファイル判定・編集済みマーカー）を追加した結果、`--generate-images`/`--edit-images`を同じ作業フォルダに対して再実行すると常にスキップ判定が優先され、意図的にすべて生成・編集し直す手段がなくなった。

**決定**: 既存の`--generate-video`と同じ`--force`フラグを`--generate-images`/`--edit-images`でも参照するようにした。`--force`指定時は既存ファイル・キャッシュの状態を無視し、常に全件生成・編集し直す。

**理由**: 「`--generate-video`に`--force`フラグを追加」した際と同じ考え方（既存の類似オプションとの一貫性）に基づく。

---

## `qwen_image_local`にQwen-Image-Lightning LoRAをオプションとして追加し、既定は無効のままにした

**課題**: ユーザーから[Qwen-Image-Lightning](https://huggingface.co/lightx2v/Qwen-Image-Lightning)（8 stepsで生成できる蒸留LoRA、公式実測で12〜25倍高速）の導入を依頼された。現在アクティブなシーン画像プロバイダーは`qwen_image_local`（`providers.image.scene`）。

**決定**: `QwenImageLocalSettings`へ`lightning_lora_enabled`/`lightning_lora_repo_id`/`lightning_lora_weight_name`を追加し、有効時のみ`pipeline.load_lora_weights()`でLoRAをロードし、公式サンプル（[generate_with_diffusers.py](https://github.com/ModelTC/Qwen-Image-Lightning/blob/main/generate_with_diffusers.py)）と同一の`FlowMatchEulerDiscreteScheduler`設定へ差し替えるようにした。`config.yaml`側の既定値は`lightning_lora_enabled: false`のまま追加し、有効化はユーザーの明示設定に委ねた。

**理由**: Lightning LoRAは公式に`true_cfg_scale=1.0`を推奨しており、これは`negative_prompt`によるガイダンスを実質無効化する（実機ログで`negative_prompt is passed but classifier-free guidance is not enabled since true_cfg_scale <= 1`を確認済み）。現在の`qwen_image_local.negative_prompt`はYouTubeロゴ・字幕風文字の写り込みを抑えるために個別に調整された既存設定であり、既定で有効化すると既存の生成品質（開発方針「既存機能を壊さない」）を無断で変更することになるため。

**動作確認**: 実機（RTX 4070/12GB）でLoRAダウンロード・スケジューラ差し替え・8 steps推論・VAE decode・画像保存まで一連の成功を確認済み（640x368で生成成功）。1664x928（本番相当解像度）では`low_vram_mode: true`使用時にVAE decode段階でCUDA OOMが発生したが、拡散ループ自体は成功しており、テスト時に他アプリがGPUメモリを使用していたことによるVRAM逼迫が原因の可能性が高い（LoRA自体に起因する追加のVRAM増加要因は無い: `true_cfg_scale=1.0`はnegative batch分の計算・メモリを不要にするため、既定の`true_cfg_scale=4.0`よりむしろ軽くなる）。また、`low_vram_mode: true`（sequential CPU offload）環境では1stepあたり約130〜145秒かかっており、ステップ数を50→8に減らしても総生成時間の短縮効果が薄いことも実測で判明した（CPU⇔GPU間の重み転送がボトルネックのため、解像度非依存）。

**参照**: [qwen_image_local.py](src/youtube_generator/plugins/image/qwen_image_local.py)、[README.md](README.md)の「Qwen-Image-Lightning LoRA（高速化・任意）」。

---

## シーン画像スタイルテンプレート・場面説明生成プロンプトを、カンマ区切りの単語列挙から主語・動詞を備えた自然文へ統一

**課題**: 各テンプレートの`image_prompt.txt`（画風・表現方針）は`photorealistic, high-production-value documentary style, realistic lighting, ...`のようなカンマ区切りの単語・タグ列挙形式だった。`OpenAISceneVisualDescriber`が生成する場面説明も同様の指示になっていなかったため、出力形式が不揃いになりやすかった。

**決定**: 全テンプレートの`image_prompt.txt`を「Render the scene as a photorealistic, ... photograph with realistic lighting ...」のような、主語と動詞を備えた文章形式へ書き換えた。`OpenAISceneVisualDescriber`の指示文にも「カンマ区切りの単語・タグの羅列ではなく、主語と動詞を備えた具体的で明確な文章にしてください」を追加した。

**理由**: 画像生成モデルへ渡すプロンプトとして、タグの羅列より自然文のほうが意図が明確に伝わりやすいと判断したため（ユーザー指示）。

**参照**: `templates/*/image_prompt.txt`、[openai_scene_visual_describer.py](src/youtube_generator/infrastructure/openai_scene_visual_describer.py)。

---

## テンプレートの画像・サムネイルプロンプトに、プロバイダー別の上書きファイルを追加できるようにした

**課題**: `image_prompt.txt`/`thumbnail_prompt.txt`はテンプレートごとに1つしか持てず、画像プロバイダーを切り替えても同じ画風指示が使われていた。プロバイダーによって得意な表現・トークンの解釈が異なるため、プロバイダーごとに文言を調整したい場合があった。

**決定**: `VideoTemplate`に`image_style_overrides`/`thumbnail_instruction_overrides`（`dict[str, str]`）を追加し、`TemplateManager`がテンプレートフォルダ内の`image_prompt.<provider>.txt`/`thumbnail_prompt.<provider>.txt`（`provider`は`plugin_manager.image_provider_name()`が返す値、例: `qwen_image_nunchaku_local`）を検出して読み込むようにした。`template.image_style_for(provider_name)`/`thumbnail_instruction_for(provider_name)`は該当プロバイダー専用ファイルがあればそれを、無ければ既定の`image_style`/`thumbnail_instruction`を返す。既存のテンプレートで専用ファイルを追加していない場合は従来どおり既定ファイルのみが使われ、後方互換性を維持する。

**理由**: テンプレートごとの差分は`templates/<template>`のみで表現し、コード側でプロバイダー分岐を書かない（CLAUDE.md）という既存方針に沿って、プロバイダー分岐もテンプレート側のファイル追加のみで完結できるようにしたため。

**参照**: [template.py](src/youtube_generator/domain/template.py)、[template_service.py](src/youtube_generator/services/template_service.py)、`templates/psychology/image_prompt.qwen_image_nunchaku_local.txt`（現状唯一の上書き例、内容は既定と同一）。

---

## 場面説明生成に前後の場面の文脈を考慮させつつ、シーン画像プロンプトの引用符除去はFLUX系プロバイダーのみへ限定した

**課題1**: `OpenAISceneVisualDescriber`は各シーンのナレーション文を独立に扱っていたため、動画全体を通して見たときに場面同士のつながり（登場人物・場所・時間帯・雰囲気の流れ）が不自然になる場合があった。

**決定1**: 指示文に「前後の場面の文脈を踏まえ、動画全体として自然につながる描写にする」旨を追加した。ただし各説明はあくまでその場面固有の状況を1〜2文で説明するものとし、前後の場面の内容を書き込んだり複数場面を1つにまとめたりしないよう明記した。

**課題2**: シーン画像プロンプトからの引用符除去（本ドキュメント内「シーン画像プロンプトから引用符付きセリフを除去し、否定列挙による対策は撤回した」の項で決定）は、当時唯一使用していたFLUX系プロバイダー（BFL/flux_schnell_local）にのみ必要な対策だったが、`ImagePromptBuilder`は全プロバイダー共通で無条件に除去を行っていた。Qwen-Image系にはこの制約がなく、除去すると台詞のニュアンスが失われるだけだった。

**決定2**: `ImagePromptBuilder.__init__`に`provider_name`引数を追加し、`bfl`/`flux_schnell_local`使用時のみ引用符を除去するようにした（`_FLUX_PROVIDER_NAMES`）。呼び出し側（`cli/main.py`）は`plugin_manager.image_provider_name("scene")`で解決したプロバイダー名を渡す。動作が変わるため画像キャッシュfingerprintを`image-prompt-v3`→`image-prompt-v4`へ更新した。

**理由**: 引用符除去はFLUX固有の制約への対策であり、他プロバイダーへ一律適用する根拠がないため、プロバイダーごとの実際の挙動に合わせた。

**参照**: [image_prompt_builder.py](src/youtube_generator/services/image_prompt_builder.py)、[openai_scene_visual_describer.py](src/youtube_generator/infrastructure/openai_scene_visual_describer.py)、[cli/main.py](src/youtube_generator/cli/main.py)。

---

## `--edit-images`に画像ファイルの直接複数指定を追加（新規キューコマンドは不採用）

**課題**: `--edit-images`は動画1本分のフォルダ内`scene*.png`をすべて処理するため、字幕帯が残った画像など一部だけをQwen-Image-Editでやり直したい場合でも全件処理してしまい時間がかかる。

**検討**: 当初、`main.py queue`と同様のSQLite永続キュー（`edit-queue add/list/run/...`）を新設する案を実装したが、ユーザーの意向により撤回し、既存の`--edit-images`オプションへ複数画像ファイルを直接渡せるようにする方式へ変更した。

**決定**: `--edit-images`を`nargs="+"`にし、(1) 単一のフォルダを渡した場合は従来どおりフォルダ内`scene*.png`全件が対象（キャッシュ・sidecar・二重編集防止マーカーの挙動は変更なし）、(2) それ以外（画像ファイルを1つ以上直接指定）の場合は指定ファイルのみを対象にする、という2モードに分岐させた。個別ファイル指定モードでは、フォルダ横断で選んだ画像を指定できるようにするため、フォルダ単位の生成キャッシュキー（sidecar）とは紐付けず、編集設定のフィンガープリントのみで二重編集防止マーカーを判定する（`CacheManager`によるバッチ保存・復元も指定画像の組み合わせが毎回変わりうるため行わない）。

**理由**: 永続キュー（DB・別サブコマンド体系）を新設せず既存オプションを拡張するだけで済むため、変更範囲を最小限にできる（CLAUDE.mdの「大規模リファクタリングは禁止」「変更範囲は必要最小限」に合致）。フォルダモードは既存動作を1バイトも変えずに温存し、後方互換性を維持した。

**参照**: [cli/main.py](src/youtube_generator/cli/main.py)、[README.md](README.md)の「キューを使わずに1件実行する」内`--edit-images`の項。

---

## Qwen-Image-Edit（nunchaku）に参照画像入力を追加し、テンプレート単位で編集設定を上書きできるようにした

**課題**: シーン画像の後処理（`scene_edit`）は編集対象画像1枚のみを`QwenImageEditNunchakuLocalImageEditor`へ渡す設計で、テンプレートごとに「統一デザインのキャラクターへ寄せる」といった参照画像を使った編集ができなかった。また`image.qwen_image_edit_nunchaku_local`はconfig.yaml側の単一設定しか持てず、テンプレートごとに`prompt`等を変えられなかった。

**決定**: `QwenImageEditNunchakuLocalSettings`に`reference_image`（任意のパス、既定`null`）を追加し、設定時はQwenImageEditPlusPipeline（2509の複数画像入力対応パイプライン）へ編集対象画像と合わせて2枚を渡す方式にした。あわせて`TemplateManager.image_edit_settings()`を新設し、`video.yaml`の`image.qwen_image_edit_nunchaku_local`を共通設定→`default`テンプレート→選択テンプレートの順に差分マージする（既存の`audio.voicevox`/`subtitles`/`ending.subtitles`と同じ差分マージパターンを踏襲）。`reference_image`の相対パスは、それを定義したテンプレートのディレクトリ基準で絶対パスへ解決する。

**理由**: 既存の差分マージパターンを再利用することで実装・レビューコストを抑えつつ（CLAUDE.mdの大規模リファクタリング禁止方針に合致）、テンプレートごとに異なる編集内容（参照画像・プロンプト）を指定できるようにするため。`lightning_steps`/`num_inference_steps`/`width`/`height`/`seed`/`model_cache_dir`/`reference_image`の7項目のみ`null`を「未指定として安全に上書きできる」設計にしているのは、これら以外の項目に`null`を渡すと型変換エラーや意図しない無効化（例: `ending.subtitles.enabled: null`）を招くため。

**参照**: [qwen_image_edit_nunchaku_local.py](src/youtube_generator/plugins/image/qwen_image_edit_nunchaku_local.py)、[template_service.py](src/youtube_generator/services/template_service.py)、READMEの「テンプレート別画像編集設定（Qwen-Image-Edit参照画像）」「video.yamlで上書きできる設定の一覧」、`templates/psychology/character_reference.png`（利用例）。

---

## `--edit-images`の個別ファイル指定時は、`image.scene_edit.enabled=false`でも編集を実行する

**課題**: `--edit-images`にファイルを直接複数指定するモード（前項参照）を追加した後も、`plugin_manager.create_image_editor()`は`image.scene_edit.enabled`が`false`（既定）だと常に`None`を返しており、フォルダ一括モードと同じ理由でスキップされていた。しかし個別ファイル指定は、ユーザーが特定の画像を見て明示的に編集を依頼している操作であり、パイプライン自動実行時の既定スキップとは意図が異なる。

**決定**: `PluginManager.create_image_editor()`に`force: bool = False`引数を追加し、`--edit-images`が個別ファイル指定モードのときのみ`force=True`で呼び出すようにした。フォルダ一括モード（パイプライン自動実行が使う従来の呼び出し）は`force=False`のまま据え置き、`enabled=false`なら引き続きスキップする。

**理由**: `enabled=false`は「パイプライン内で自動的には編集しない」という既定挙動の制御であり、ユーザーがコマンドで名指しした画像の編集意図までは制限すべきでないと判断したため。

**参照**: [plugins/manager.py](src/youtube_generator/plugins/manager.py)の`create_image_editor()`、[cli/main.py](src/youtube_generator/cli/main.py)。

---

## 本編・エンディング接続部に画面のみのフェードイン/アウトを追加し、既存のend_padding方式を踏襲してstart_paddingも新設した

**課題**: 本編からエンディングへの切り替わりが唐突だった。またエンディング側は末尾の余白（`end_padding_seconds`）のみ持ち、冒頭に余白を作る手段がなかった。

**決定**: `ending.main_fade_out_seconds`（既定0.5秒、本編終了時）・`ending.fade_in_seconds`（既定0.5秒、エンディング開始時）を追加し、ffmpegの`fade`フィルターで映像のみをフェードさせる（BGM・ナレーション音声は対象外）。`main_fade_out_seconds`は`ending.auto_append: false`（エンディング非結合）の場合は常に無効化する。あわせて`ending.start_padding_seconds`（既定0.5秒）を新設し、既存の`end_padding_seconds`と対称になるよう、最初の画像の表示時間延長・ナレーション音声の`adelay`による遅延・字幕開始時刻のオフセット（`SrtBuilder.build(start_offset_seconds=...)`）を実装した。1画像のみのエンディングでは最初=最後の画像のため、start・end両方の延長が加算される。

**理由**: 既存の`end_padding_seconds`実装（1枚目/最後の画像を延長する方式）と対称のパターンを再利用することで、変更範囲とレビューコストを抑えるため。フェードを映像のみに限定したのは、音声（ナレーション・BGM）側には既存の`bgm_fade_in`/`bgm_fade_out`が別途あり、無関係な音声挙動を変えないため。

**参照**: [ending/manager.py](src/youtube_generator/ending/manager.py)、[ending/renderer.py](src/youtube_generator/ending/renderer.py)、[ffmpeg_video_renderer.py](src/youtube_generator/infrastructure/ffmpeg_video_renderer.py)、[srt_builder.py](src/youtube_generator/services/srt_builder.py)。

---

## シーン画像プロンプトの品質対策を、共通ImagePromptBuilder（抽象的な指示）とプロバイダー別negative_prompt（具体的な抑制語）に役割分担した

**課題**: 生成画像で(1)実在企業のロゴ・商標が写り込む、(2)屋内・屋外など複数の場所が1枚の画像に混在する、という2つの問題が確認された。対策として`ImagePromptBuilder`（ポジティブプロンプト）に具体的な抑制文言を追加する案を試したが、屋内外混在対策では「indoor office interior」「outdoor street scene」のような具体的な名詞を例示すると、かえってモデルがその構図（対比構図）へ誘導されやすいことが実機確認で判明した。

**決定**: 共通`ImagePromptBuilder`には「Product design: 汎用・無地のデザインにする」「Setting: 単一の場所のみを一貫して描写する（屋内なら壁・床・天井が揃った完全に囲まれた部屋、屋外なら屋内什器を含めない）」という抽象的な指示のみを持たせ、実在ブランド名（Apple/Windows/Microsoft/Google/Samsung/Sony/Nikeロゴ等）や複数場所混在を示す具体語（"multiple locations in one image"等）はQwen系プロバイダーの`negative_prompt`（`config/config.yaml`の`image.qwen_image_local`/`qwen_image_nunchaku_local`）側に追加した。あわせて、顔の目の下に不自然な筋が生成される問題（`true_cfg_scale`を4.0/6.0いずれにしても発生することを実機確認済み）に対しても、CFG値の調整ではなく`negative_prompt`へ`under-eye lines`/`tear trough`等を追加する方式で対応した。

**理由**: ポジティブプロンプト側は抽象的な指示に留めて意図しない構図誘導を避け、抑制したい具体的要素はモデルが直接抑制できる`negative_prompt`側に寄せる、という役割分担にすることで、プロンプトチューニングの見通しを良くするため。

**参照**: [image_prompt_builder.py](src/youtube_generator/services/image_prompt_builder.py)、`config/config.yaml`の`image.qwen_image_local.negative_prompt`/`image.qwen_image_nunchaku_local.negative_prompt`、[openai_scene_visual_describer.py](src/youtube_generator/infrastructure/openai_scene_visual_describer.py)（場面説明生成側にも単一場所限定の指示を追加）。

---

## `queue clear`/`youtube upload`の確認プロンプトで、確認メッセージを`input()`と分離してflushする

**課題**: `input("メッセージ Continue? [y/N] ")`は、実行環境によってはメッセージが表示される前に`input()`が入力待ちでブロックし、ユーザーから見てメッセージが表示されないまま応答待ちになっているように見える不具合があった。

**決定**: 確認メッセージを`print(..., flush=True)`で明示的にフラッシュしてから、`input()`は空プロンプトで呼び出す形に分離した。

**理由**: `print`と`input`のプロンプト文字列を1つの`input()`呼び出しにまとめると、標準出力のバッファリング挙動次第でメッセージの表示タイミングが保証されないため、明示的な`flush=True`で表示順序を確定させた。

**参照**: [cli/queue.py](src/youtube_generator/cli/queue.py)、[cli/youtube.py](src/youtube_generator/cli/youtube.py)。

---

## `--generate-images`にも画像ファイルの直接複数指定を追加（`--edit-images`と同じ設計）

**課題**: `--generate-images`はフォルダ内`scene*.txt`から計画した`sceneNN_MM.png`のうち未生成分のみを生成する（既存ファイルはスキップ）。生成結果が気に入らず特定の画像だけ作り直したい場合、そのファイルを手動で削除してから再実行する必要があった。`--edit-images`に個別ファイル指定モードを追加した際と同じ動機。

**決定**: `--edit-images`と同じ「フォルダ1件指定＝フォルダモード（既存挙動を完全維持）／それ以外＝個別ファイル指定モード」の分岐を`--generate-images`にも追加した。個別ファイル指定モードでは`GenerateSceneImagesUseCase.execute`に新設した`only_files`引数（計画上の該当`sceneNN_MM.png`のみを対象にし、既存の有無に関わらず常に生成し直す）を使う。指定ファイルは同じフォルダ内である必要があり、フォルダ単位のバッチキャッシュ（`image_cache_key`の保存・復元）とは紐付けない（`--edit-images`の個別ファイル指定モードと同じ理由）。

**理由**: 既存の`--edit-images`個別ファイル指定モードと対称的なUI・実装にすることで一貫性を保ち、変更範囲を最小限にした（`GenerateSceneImagesUseCase.execute`は`only_files=None`の場合の挙動を一切変更していない）。

**参照**: [app/generate_scene_images.py](src/youtube_generator/app/generate_scene_images.py)、[cli/main.py](src/youtube_generator/cli/main.py)、[README.md](README.md)の`--generate-images`個別ファイル指定の項。

---

## 関連ドキュメント

- [CLAUDE.md](CLAUDE.md) — 開発方針・アーキテクチャ・コーディング規約
- [TASKS.md](TASKS.md) — 今後実装予定のタスク一覧
- [CONTRIBUTING.md](CONTRIBUTING.md) — Git運用ルール
