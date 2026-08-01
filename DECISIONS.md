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

## 関連ドキュメント

- [CLAUDE.md](CLAUDE.md) — 開発方針・アーキテクチャ・コーディング規約
- [TASKS.md](TASKS.md) — 今後実装予定のタスク一覧
- [CONTRIBUTING.md](CONTRIBUTING.md) — Git運用ルール
