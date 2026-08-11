# Youtube AI Automation

**Youtube AI Automation**は、テーマから台本、シーン音声、画像、字幕、動画、メタデータ、サムネイルを生成するPythonアプリケーションです。ジョブキューによる一括実行と、明示操作によるYouTube投稿にも対応しています。

## 必要環境

- Python 3.12以上
- FFmpeg（`ffmpeg`と`ffprobe`をPATHへ追加）
- Windows PowerShell

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
Copy-Item .env.example .env
```

`.env`へ次のAPIキーを設定します。

```dotenv
OPENAI_API_KEY=
BFL_API_KEY=
```

OpenAIは台本・シーン分割・音声・メタデータ生成、Black Forest Labsは画像生成に使用します。ログレベルなど、APIキー以外の環境固有設定も`.env`で管理します。

## 設定

実行設定は[config/config.yaml](config/config.yaml)へ集約されています。主な項目は次のとおりです。

- 動画：`1920×1080`、30fps
- シーン画像：FLUX.2 Pro、`1920×1080`
- サムネイル：FLUX.2 Pro、`1280×720`
- 最大シーン数：30
- 音声、字幕、BGM、品質検査、キャッシュ、リトライ
- YouTubeの公開範囲とアップロード許可

Windows PowerShell 5.1では、すべてのコマンドを`run.cmd`経由で実行します。このラッパーは内部の`run.ps1`を実行し、PythonとPowerShellの文字コードを一時的にUTF-8へ揃え、標準出力と標準エラーを`Out-Host`へ渡します。処理後は元の文字コード設定へ戻るため、プロンプト位置の乱れと文字化けを共通して防止できます。PowerShellの実行ポリシーを変更する必要はありません。

PowerShell 7など、問題が発生しない環境では`python main.py`またはセットアップ時に登録される`youtube-ai-automation`コマンドも使用できます。

## テンプレート機能

テンプレートは、動画ジャンルごとの生成方針とシーン構成を切り替える機能です。`--template <テンプレートID>`で選択し、省略時は`default`が使用されます。

```powershell
.\run.cmd --theme "宇宙の不思議" --template science
```

同梱テンプレート：

| テンプレートID | 表示名 | 主な用途 |
| --- | --- | --- |
| `default` | Default | 汎用 |
| `zatsugaku` | 雑学 | 雑学・豆知識 |
| `history` | 歴史 | 歴史上の人物・出来事 |
| `toshidensetsu` | 都市伝説 | 噂・都市伝説の紹介と検証 |
| `psychology` | 心理学 | 心理学の解説と実践例 |
| `science` | 科学 | 科学知識・現象の解説 |

`trivia`は`zatsugaku`、`urban_legend`は`toshidensetsu`の別名としても使用できます。利用可能なテンプレートは次のコマンドで確認できます。

```powershell
.\run.cmd --list-templates
```

テンプレートは`templates/<テンプレートID>/`に配置し、次の5ファイルで構成します。

| ファイル | 用途 |
| --- | --- |
| `prompt.txt` | 台本の文体、内容、構成に関する指示 |
| `image_prompt.txt` | シーン画像の画風と表現方針 |
| `title_prompt.txt` | YouTubeタイトル専用の生成方針 |
| `thumbnail_prompt.txt` | サムネイルの構図と表現方針 |
| `video.yaml` | 表示名、シーン構成、VOICEVOX、BGM、エンディング字幕の設定 |

新しいテンプレートを追加する場合は、既存フォルダを複製して上記ファイルを編集します。`video.yaml`には少なくとも表示名とシーン構成を指定してください。

`image_prompt.txt`・`thumbnail_prompt.txt`は、`image_prompt.<プロバイダー名>.txt`・`thumbnail_prompt.<プロバイダー名>.txt`という名前のファイルを同じフォルダへ追加すると、そのプロバイダー使用時のみ既定ファイルの代わりに読み込まれます（プロバイダー名は`config/config.yaml`の`providers.image.scene`/`thumbnail`に設定する値と同じもの、例: `qwen_image_nunchaku_local`、`bfl`）。該当プロバイダー専用の上書きファイルが無い場合は、既定の`image_prompt.txt`/`thumbnail_prompt.txt`がそのまま使われます。

`title_prompt.txt`には、タイトルのトーン、煽りの強さ、キーワードの使い方、人物名や固有名詞を含めるか、答えをタイトルで明かすか、推奨構成などを記述できます。この方針はタイトルにのみ適用され、概要欄、タグ、ハッシュタグには適用されません。`title_prompt.txt`を変更するとタイトル用キャッシュだけが無効になり、次回のメタデータ生成時から新しい方針が反映されます。台本、音声、画像、動画とタイトル以外のメタデータは既存キャッシュを再利用します。

```yaml
display_name: 料理
scene_structure: [導入, 材料, 調理手順, まとめ]
```

フォルダ名が`cooking`の場合は、`--template cooking`で選択できます。`display_name`はジャンル名として出力フォルダの階層に使用されます。

### テンプレート別VOICEVOX設定

`config/config.yaml`の`providers.tts`が`voicevox`の場合、各テンプレートの`video.yaml`で話者や読み上げ方を上書きできます。

```yaml
audio:
  voicevox:
    speaker_id: 3
    speed_scale: 1.0
    pitch_scale: 0.0
    intonation_scale: 1.0
    volume_scale: 1.0
    pre_phoneme_length: 0.1
    post_phoneme_length: 0.1
```

`base_url`と`timeout`もテンプレート側で上書きできます。設定は`config/config.yaml`の共通値、`default`テンプレート、選択テンプレートの順に上書きされます。テンプレート側の`video.yaml`でVOICEVOX設定を変更した場合は、対象テンプレートの音声キャッシュだけが無効になります。`config/config.yaml`側の共通設定を変更した場合は、`config.yaml`全体のハッシュを台本・シーン分割・音声・画像・字幕の各キャッシュキーが共有しているため、音声キャッシュだけでなく他の工程のキャッシュもあわせて無効になります。テンプレート側でTTSプロバイダー自体を切り替えることはできません。

### テンプレート別字幕設定

`config/config.yaml`の`subtitles`設定は、各テンプレートの`video.yaml`で上書きできます。変更する項目だけを記述できます。

```yaml
subtitles:
  font: Arial
  size: 24
  color: "&H00FFFFFF"
  segmentation_mode: semantic
  max_lines: 2
  max_chars_per_line: 20
  min_chars_per_segment: 6
  timing_mode: alignment
  fallback_timing_mode: character_ratio
  position: bottom
  alignment: center
  bottom_margin: 80
  box_enabled: true
  background_color: "#000000"
  background_opacity: 0.6
```

設定は`config/config.yaml`の共通値、`default`テンプレート、選択テンプレートの順に上書きされます。`box_enabled`を`true`にすると字幕の周囲に背景ボックスを表示します。`background_color`は`#RRGGBB`またはASS形式、`background_opacity`は`0.0`（透明）～`1.0`（不透明）で指定します。背景色と透明度は、本編とエンディングの両方に反映されます。テンプレート別字幕設定は本編の字幕分割・動画描画とエンディングの字幕スタイルに反映されます。字幕（SRT）はキャッシュされ、字幕設定を変更すると字幕キャッシュのみが無効になります。動画（MP4）はキャッシュ対象外のため、字幕キャッシュの有無にかかわらず`--generate-video`実行のたびに再生成されます。エンディング字幕の表示・非表示は、従来どおり`ending.subtitles.enabled`で個別に設定します。

### テンプレート別画像編集設定（Qwen-Image-Edit参照画像）

`image.scene_edit.provider`が`qwen_image_edit_nunchaku_local`の場合、各テンプレートの`video.yaml`で編集設定を上書きできます。変更する項目だけを記述できます。

```yaml
image:
  qwen_image_edit_nunchaku_local:
    prompt: "編集内容を指示するプロンプト"
    reference_image: character_reference.png
```

`reference_image`は任意の参照画像パスです。設定すると、編集対象画像に加えこの参照画像もQwen-Image-Edit-2509（複数画像入力に対応したパイプライン）へ渡し、`prompt`で参照画像の要素（例: 統一デザインのキャラクター）を編集対象画像へ反映させられます。相対パスは、その設定を記述したテンプレートのディレクトリ（例: `templates/psychology/`）を基準に解決されます。既定（未指定時）は`null`で、編集対象画像1枚のみを使う従来動作です。設定は`config/config.yaml`の共通値、`default`テンプレート、選択テンプレートの順に上書きされます。

### video.yamlで上書きできる設定の一覧

各テンプレートの`video.yaml`で上書き可能な設定は次の4系統です。いずれも「変更する項目だけを記述する」形式（差分マージ）で、記述しなかった項目は`config/config.yaml`の値（または`default`テンプレートの値）をそのまま引き継ぎます。

| 系統 | 主な項目 | 参照 |
| --- | --- | --- |
| `audio.voicevox` | `base_url`, `speaker_id`, `timeout`, `speed_scale`, `pitch_scale`, `intonation_scale`, `volume_scale`, `pre_phoneme_length`, `post_phoneme_length` | 「テンプレート別VOICEVOX設定」 |
| `subtitles` | `font`, `size`, `color`, `segmentation_mode`, `max_lines`, `max_chars_per_line`, `min_chars_per_segment`, `timing_mode`, `fallback_timing_mode`（現状未使用）, `position`, `alignment`, `bottom_margin`, `box_enabled`, `background_color`, `background_opacity`, `alignment_provider`（`provider`/`language`/`model`をブロック単位で上書き） | 「テンプレート別字幕設定」「stable-tsによる字幕タイミングのアライメント」 |
| `ending.subtitles` | `enabled` | 「テンプレート別エンディング字幕」 |
| `image.qwen_image_edit_nunchaku_local` | `base_model_id`, `transformer_repo_id`, `precision`, `rank`, `lightning_steps`, `num_inference_steps`, `true_cfg_scale`, `width`, `height`, `prompt`, `negative_prompt`, `reference_image`, `offload_threshold_gb`, `low_vram_use_pin_memory`, `low_vram_num_blocks_on_gpu`, `seed`, `model_cache_dir` | 「テンプレート別画像編集設定（Qwen-Image-Edit参照画像）」 |

**`null`の扱いについての注意**: 上記のほとんどの項目は、`video.yaml`に`項目名: null`と明記すると「未指定として既定値を引き継ぐ」のではなく、その項目の値が実際に`null`（Python上の`None`）で上書きされます。多くの項目は数値・文字列として無条件に変換されるため、`null`を書くとエラーになる（例: `size`, `bottom_margin`, `rank`など）か、意図せず挙動が変わる（例: `ending.subtitles.enabled: null`はエンディング字幕を強制的に無効化してしまう）ため、**基本的に`null`は指定しないでください**。上書きしたくない項目は、キーごと省略してください。

例外的に、`image.qwen_image_edit_nunchaku_local`の`lightning_steps`, `num_inference_steps`, `width`, `height`, `seed`, `model_cache_dir`, `reference_image`の7項目のみ、コード側で`None`を「未指定・自動」として正しく扱う設計になっているため、明示的に`null`と書いても安全です。

### stable-tsによる字幕タイミングのアライメント

`subtitles.timing_mode`が`alignment`の場合、音声生成（`--generate-audio`）の直後に、生成済みの音声（`sceneNN.mp3`）と元台本（`sceneNN.txt`）を[stable-ts](https://github.com/jianfch/stable-ts)で強制アライメント（Whisperによる文字起こしは行わず、既知の台本テキストを音声へ整合させる処理）し、`sceneNN.alignment.json`を生成します。字幕分割（`SubtitleSplitter`）で作成した各字幕セグメントは、このJSONの単語単位タイムスタンプを使って文字数比率方式より高精度な開始・終了時刻へ補正されます。

導入には`requirements.txt`に含まれる`stable-ts`（PyPI: `stable-ts`、importは`stable_whisper`）が必要です。

```powershell
python -m pip install -r requirements.txt
```

`config/config.yaml`の`subtitles.alignment_provider`でプロバイダーを設定します（字幕の水平配置を表す既存の`subtitles.alignment`(`center`/`left`/`right`)とは別のキーです）。

```yaml
subtitles:
  timing_mode: alignment
  alignment_provider:
    provider: stable_ts
    language: ja
    model: base
  fallback_timing_mode: character_ratio
```

`model`にはstable-ts（Whisper）のモデルサイズ（`tiny`/`base`/`small`/`medium`/`large`など）を指定します。値が大きいほど精度は上がりますが、初回実行時のモデルダウンロードと処理時間が増えます。テンプレート側`video.yaml`で`alignment_provider`を上書きする場合、設定は項目単位ではなくブロック単位で置き換わるため、`provider`・`language`・`model`をすべて記述してください。

`sceneNN.alignment.json`の形式は次のとおりです。

```json
{
  "provider": "stable_ts",
  "text": "元台本の全文",
  "units": [
    {"text": "単語やフレーズ", "start": 0.00, "end": 0.50}
  ]
}
```

アライメントの生成は`provider`・`model`・`language`・音声ファイル・元台本の内容からキャッシュされ、これらが変わらない限り再実行されません。`alignment_provider`の設定や音声（VOICEVOX設定変更など）が変わった場合は、`sceneNN.alignment.json`と字幕（SRT）のみが再生成されます。台本・画像・音声そのものは影響を受けません（動画はもともとキャッシュ対象外のため、`--generate-video`実行時に毎回作成されます）。

stable-tsが未インストール、またはアライメントに失敗した場合でも音声生成・動画生成は停止しません。失敗したシーンは`sceneNN.alignment.json`が作成されず、字幕生成時に自動的に`fallback_timing_mode`（既定: `character_ratio`）へフォールバックします。

シーン単位ではアライメントが成功しても、`Failed to align the last N words after ...`のように音声末尾（または先頭）の一部単語だけタイムスタンプを検出できない場合があります。この場合、その無音区間は該当シーンの最初または最後の字幕セグメントの表示時間へ吸収され、シーン音声の実際の長さ（`sceneNN.mp3`の全長）と字幕の合計時間が常に一致するように補正されます。これにより、無音区間を跨いで字幕の表示タイミングが音声より先行していく累積ズレを防いでいます。

## ジョブキューで動画を生成する

```powershell
.\run.cmd queue add "宇宙の雑学" --template science
.\run.cmd queue run
.\run.cmd queue status
```

ジョブは登録順に1件ずつ処理されます。成果物は次の構成で保存されます。

```text
output/<ジャンル名>/<実行ID>_<入力テーマ>/
├── script/
├── audio/
├── images/
├── subtitle/
├── video/
├── thumbnail/
├── metadata/
└── quality_report/
```

ジャンル別の階層を使用しない`output/jobs`直下へ保存する場合は、`output/jobs/<実行ID>_<ジャンル名>_<入力テーマ>/`という形式になります。

その他のキュー操作：

```powershell
.\run.cmd queue import topics.csv
.\run.cmd queue list
.\run.cmd queue retry <job_id>
.\run.cmd queue cancel <job_id>
.\run.cmd queue delete <job_id>
.\run.cmd queue clear
.\run.cmd queue clear --yes
```

CSVは`theme,template`ヘッダー、JSONは`theme`と`template`を持つオブジェクトの配列を使用します。

`queue list`と`queue status`は1ジョブを1行で表示します。これらを含むすべてのコマンド出力は`run.ps1`内部で`Out-Host`へ渡されます。

`config/config.yaml`の`queue.skip_thumbnail`を`true`にすると、キュー実行時のサムネイル生成工程（API呼び出し・成果物コピー）をスキップできます。画像生成中は`画像生成: (n/総数)`という進捗がジョブごとにログ出力されます。

PowerShellを閉じるなどで`queue run`のプロセスが強制終了された場合、該当ジョブは`RUNNING`のまま残りますが、次にいずれかの`queue`コマンド（`list`/`retry`/`cancel`/`delete`/`run`等）を実行した時点で自動的に`PENDING`へ戻され、`retry`/`cancel`/`delete`が行えるようになります。別ターミナルで実際に`queue run`が稼働中のジョブは、そのプロセスが生存している限り誤って巻き戻されることはありません。

## キューを使わずに1件実行する

キューを使用しない場合は、対象動画の各工程を順番に実行します。まず台本を生成します。

```powershell
.\run.cmd --theme "宇宙の不思議" --template science
```

生成された台本は`output/<ジャンル名>/<実行ID>_<入力テーマ>/script.txt`へ保存されます。直前に作成されたフォルダをPowerShell変数へ設定し、残りの工程を実行します。

```powershell
$workDir = (Get-ChildItem output\科学 -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName + "\.work"

.\run.cmd --split-script "$workDir\script.txt" --template science
.\run.cmd --generate-audio "$workDir" --template science
.\run.cmd --generate-scene-descriptions "$workDir" --template science
.\run.cmd --generate-images "$workDir" --template science
.\run.cmd --edit-images "$workDir" --template science
.\run.cmd --generate-subtitles "$workDir" --template science
.\run.cmd --generate-video "$workDir" --template science
.\run.cmd --generate-metadata "$workDir" --template science --topic "宇宙の不思議"
.\run.cmd --generate-thumbnail "$workDir" --template science
```

`--template`には台本生成時と同じIDを指定してください。テンプレートが異なると、画像・タイトル・サムネイルの生成方針も変わります。メタデータ生成では、タイトル生成に動画テーマを反映するため`--topic`も指定してください。ジョブ実行時はジョブのテーマが自動的に渡されます。`--theme`、`--split-script`、各`--generate-*`・`--edit-images`は同時指定できないため、工程ごとに個別実行します。

`--generate-scene-descriptions`は、[後述の`scene_description`](#シーン画像プロンプト用の場面説明生成scene_description)が有効な場合に、画像プロンプト用の場面説明（`sceneNN_MM.description.txt`）だけを独立して生成する任意の工程です。省略しても`--generate-images`実行時に内部で同様の呼び出しが行われるため、キューを使わずに1件実行する場合も必須ではありません。画像生成側の設定だけを変更して`--generate-images`をやり直したい場合や、場面説明だけを`--force`で再生成したい場合に、この工程を独立して呼び出せます。

`--generate-images`はシーン画像の生成のみを行います。`--edit-images`は生成済みの`scene*.png`に対する後述の[キャプション帯除去（scene_edit）](#シーン画像の後処理でキャプション帯を除去するscene_edit)のみを行う別コマンドです。2つのモデルを同一プロセス内で交互にロードするとVRAM/システムメモリを圧迫しやすいため、あえて別プロセス（別コマンド）に分離しています。`image.scene_edit.enabled`が`false`（既定）の場合、フォルダ指定（後述のフォルダ一括モード）での`--edit-images`は何もせず終了します。

中断されたジョブの再試行等で`--generate-images`/`--edit-images`を同じ作業フォルダに対して再実行した場合、既に生成済みの`sceneNN_MM.png`や、同じ編集設定で既に編集済みの画像はスキップされ、未処理分のみが処理されます（無駄なAPI課金・GPU処理を避けるため）。キャッシュ・既存ファイルの状態を無視してすべて生成・編集し直したい場合は`--force`を付けてください。

```powershell
.\run.cmd --generate-images "$workDir" --template science --force
.\run.cmd --edit-images "$workDir" --template science --force
```

`--edit-images`はフォルダを1つ指定すると従来どおりフォルダ内`scene*.png`全件を対象にしますが、字幕帯が残った画像など一部だけをやり直したい場合は、編集したい画像ファイルを直接複数指定できます。全件編集より時間を短縮できます。

```powershell
.\run.cmd --edit-images "$workDir\scene03_02.png" "$workDir\scene05_01.png" --template science
```

個別ファイル指定時は、フォルダ横断で選んだ画像を指定できるようフォルダ単位のキャッシュ（`--generate-images`が書き出す生成キャッシュキー）とは紐付けません。編集設定（`image.scene_edit`・`image.qwen_image_edit_nunchaku_local`）が変わっていなければ、同じファイルを指定しても既に編集済みの画像は再編集されません（二重編集による画質劣化を避けるため）。無視して再編集したい場合は`--force`を付けてください。また、個別ファイル指定時はユーザーが明示的に編集を要求しているとみなし、`image.scene_edit.enabled`が`false`でも編集を実行します（フォルダ一括モードのみ`enabled`に従いスキップします）。

`--generate-images`も同様にフォルダを1つ指定すると従来どおりフォルダ内`scene*.txt`から計画した`sceneNN_MM.png`のうち未生成分のみを対象にしますが、特定の画像だけ作り直したい場合は、対象の画像ファイル（`sceneNN_MM.png`）を直接複数指定できます。

```powershell
.\run.cmd --generate-images "$workDir\scene03_02.png" "$workDir\scene05_01.png" --template science
```

個別ファイル指定時は、指定したファイルが既に存在していても常に生成し直します（既存有無を見るフォルダ一括モードの挙動とは異なります）。`--edit-images`の個別ファイル指定と同様、フォルダ単位のバッチキャッシュ（`image_cache_key`）とは紐付けず、対象は指定した画像のみです（指定していない他の画像には触れません）。同じフォルダ内の画像のみ同時指定できます。

台本、シーン分割、音声、画像、メタデータ、サムネイルの生成では外部API利用料が発生します。字幕生成と動画レンダリングはローカルのFFmpegを使用します。

既存の台本文だけをAPIなしで品質チェックする場合は、次のように実行します。

```powershell
.\run.cmd --script "確認したい台本文" --template science
```

文字数、想定時間、禁止表現、重複文などが`config/config.yaml`の`quality`設定に基づいて検査されます。

同じ入力と設定で生成した中間成果物は`cache/`から再利用されます。`--generate-video`も、シーン画像・音声・字幕（SRT）・BGM・動画設定が変わっていなければ動画（`video.mp4`）をキャッシュから復元し、ffmpegによる再レンダリングを省略します。キャッシュを無視して強制的に再レンダリングしたい場合は`--force`を付けて実行してください。

```powershell
.\run.cmd --generate-video "$workDir" --template science --force
```

工程イベントは`logs/run_history.jsonl`、実行ごとの集計は`output/history.json`、アプリケーションログは`logs/application.log`へ保存されます。

## テンプレート共通エンディング

各テンプレート配下を再帰的に検索し、ファイル名が大文字・小文字を問わず`ending`で始まる`.txt`、`.png`、`.jpg`、`.jpeg`、`.webp`だけを共通エンディングの素材として利用します。たとえば`ending_message.txt`、`ending_logo.png`、`assets/ending_background.jpg`を配置できます。画像は背景やロゴ等として扱われます。テキスト（`ending*.txt`）が存在する場合は、その内容をそのまま結合してエンディングのナレーションとして読み上げます（LLMによる書き換えは行いません）。該当するテキストファイルが存在しないテンプレートでは、従来どおりテンプレートの`prompt.txt`などをもとにLLMがナレーションを生成します。生成結果は`generated_assets/endings/<template>/`に保存され、素材・動画スタイル・エンディング設定・字幕/BGM設定・音声（TTS）設定から計算したSHA-256ハッシュが一致する限り再利用されます。エンディングのナレーションも本編と同様にテンプレート別VOICEVOX設定（`video.yaml`の`audio.voicevox`上書き）が適用され、対象テンプレートの音声設定を変更するとそのテンプレートのエンディングキャッシュだけが無効になります。

```powershell
.\run.cmd ending generate --template zatsugaku
.\run.cmd ending generate --template zatsugaku --force
.\run.cmd ending generate-all
.\run.cmd ending list
.\run.cmd ending delete --template zatsugaku
```

`config/config.yaml` の `ending` セクションで、機能の有効化、5〜15秒の長さ、参照テキスト上限、画像選択（`first` / `random` / `sequence`）、本編への自動結合を設定できます。`auto_append: true`では動画レンダリング後に`main.mp4`、`ending.mp4`、`final.mp4`を作成します。YouTube投稿時は`final.mp4`を最優先で使用します。`gap_seconds`（既定1.0秒）を指定すると、本編最後のシーンの画像とBGMをナレーションなしでその秒数だけ延長し、エンディングとの音声の区切りを明確にします（黒画面や完全な無音は挟みません）。延長中も直前の字幕表示とズーム効果（同一zoompanフィルター内での継続）は途切れません。`render_mode`が`per_section`・`final_mix`のどちらでも本編動画（`video.mp4`/`main.mp4`）の生成時に適用され、変更時は本編動画以降のみ再生成されます。

`end_padding_seconds`（既定1.0秒）は、エンディング動画自体の末尾に追加する余白です。ナレーション終了直後に映像が途切れないよう、最後の画像をその秒数だけ延長し、音声も同じ長さだけ無音でパディングします。BGMが有効な場合はこの余白分も含めて再生・フェードアウトします。変更するとエンディングのキャッシュが無効になります。

`main_fade_out_seconds`（既定0.5秒）は本編終了時、`fade_in_seconds`（既定0.5秒）はエンディング開始時に、それぞれ画面のみをフェードアウト／フェードインさせる秒数です（BGM・ナレーション音声は対象外）。`0`にすると無効化できます。`main_fade_out_seconds`は`auto_append: false`の場合は常に無効です。`main_fade_out_seconds`を変更すると本編動画以降、`fade_in_seconds`を変更するとエンディング以降のキャッシュが無効になります。

`start_padding_seconds`（既定0秒）は、エンディング冒頭に追加する無音区間です。指定した秒数だけナレーション音声・字幕の開始を遅らせ、最初の画像もその秒数だけ表示を延長します（BGMが有効な場合はこの区間も含めて再生されます）。`fade_in_seconds`と併用すると、無音の間に画面がフェードインする演出になります。変更するとエンディングのキャッシュが無効になります。

## テンプレート共通BGM

テンプレートの`video.yaml`にBGMを記述し、音源はテンプレート配下に配置します。対応形式は`.mp3`、`.wav`、`.m4a`、`.aac`、`.ogg`です。

```yaml
bgm:
  enabled: true
  file: bgm/history.mp3
  volume: 0.08
  loop: true
  fade_in: 1.0
  fade_out: 2.0
  missing_file_behavior: fallback # fallback / disable / error
  main:
    volume: 0.08
  ending:
    file: assets/ending.mp3
    volume: 0.12
    fade_in: 0.5
```

`main` / `ending` / `final`には、共通設定の`enabled`・`file`・`volume`・`loop`・`fade_in`・`fade_out`・`missing_file_behavior`のうち上書きしたい項目だけを記述できます。`file`も対象ごとに個別のBGM音源へ差し替え可能です（上記例ではエンディングだけ`assets/ending.mp3`を使用）。個別設定がない項目・用途は共通値を継承します。BGMの優先順位は、テンプレート固有、`default`テンプレート、`config/config.yaml`のグローバル設定、BGMなしです。テンプレート側で`enabled: false`を指定した場合はフォールバックしません。音源ファイルまたは設定が変わると、エンディングのキャッシュキーも変わります。ナレーション音量はBGMの有効・無効に関わらず一定に保たれます（本編・エンディング・`final_mix`いずれも`amix`フィルターの自動音量正規化を無効化しています）。

```powershell
.\run.cmd bgm show --template history
.\run.cmd bgm list
.\run.cmd bgm validate --template history
.\run.cmd bgm validate-all
```

既定の`per_section`では、本編とエンディングをそれぞれBGM付きでレンダリングしてから結合します。連続再生が必要な場合は、以下の`final_mix`を選択してください。

## 最終BGMミックス（final_mix）

既定の`per_section`は本編・エンディングごとにBGMをミックスする互換モードです。`final_mix`では両方をナレーション付き・BGMなしで生成してから結合し、全尺へBGMを一度だけ重ねます。そのため本編からエンディングへの移行時もBGMの再生位置はリセットされません。

```yaml
bgm:
  render_mode: final_mix
  file: bgm/history.mp3
  final:
    volume: 0.08
    loop: true
    fade_in: 1.0
    fade_out: 2.0

final_render:
  keep_intermediate: true
```

`combined_without_bgm.mp4`は中間ファイルです。`final_render.keep_intermediate`を`false`にすると、`final.mp4`作成後に削除します。最終ミックスはmain・ending・BGM・エンコード設定の内容ハッシュでキャッシュするため、BGM変更時はmain／endingを再生成せずfinalだけを再作成します。`render remix-bgm`は`render final`のエイリアスで、実装上は同一の処理を実行します（BGMのみを変更した場合の再生成であることを示す呼び出し名として使い分けてください）。

```powershell
.\run.cmd render final <job_id>
.\run.cmd render remix-bgm <job_id>
.\run.cmd render final <job_id> --force
```

## テンプレート別エンディング字幕

`video.yaml` の設定で、エンディングだけの字幕表示を切り替えられます。本編字幕設定とは独立しています。未指定時は`config/config.yaml`の`ending.subtitles.enabled`を利用します。

```yaml
ending:
  enabled: true
  subtitles:
    enabled: false
```

この設定でもエンディング映像とナレーションは生成され、字幕焼き込みだけを省略します。設定変更時はエンディングと最終結合のみが再生成対象です。

## YouTubeへ投稿する

動画生成と投稿は分離されており、投稿は明示した場合だけ実行されます。

1. Google Cloud ConsoleでYouTube Data API v3を有効化します。
2. OAuth 2.0デスクトップアプリの認証情報を作成します。
3. クライアントJSONをプロジェクト直下の`client_secret.json`へ保存します。
4. `.\run.cmd youtube auth`を実行して認証します。
5. `config/config.yaml`の`youtube.upload_enabled`を`true`へ変更します。

```powershell
.\run.cmd youtube upload <job_id>
.\run.cmd youtube upload <job_id> --privacy private
.\run.cmd youtube schedule <job_id> --publish-at "2026-08-01T19:00:00+09:00"
.\run.cmd youtube status <job_id>
```

公開範囲は`private`、`unlisted`、`public`です。投稿前には確認が表示され、`--yes`を付けた場合だけ省略されます。同じジョブを再投稿する場合は`--force`が必要です。

## 画像プロバイダーをOpenAIへ戻す

既定の画像プロバイダーはBFLです。OpenAIへ切り替える場合は`config/config.yaml`を次のように変更します。

```yaml
providers:
  image: openai
```

この場合は`image.openai_model`と`image.quality`が使用されます。

## プロンプト末尾への追記設定（prompt_suffix）

すべての画像プロバイダーは、`prompt_suffix`という共通の設定項目を持ちます。指定した任意の文字列を、生成のたびにポジティブプロンプト末尾へ`, <prompt_suffix>`として自動付加する、汎用的な仕組みです。**コード上の既定値は空文字列（何も付加しない）で、実際に付加される内容はconfig.yamlで指定したものだけが反映されます。**

`config/config.yaml`には既定設定として、画面内への意図しない文字描画を防ぐ`No text.`（Qwen-Image系はこれに加えて公式ドキュメント推奨の品質向上用決まり文句）を設定済みです。

```yaml
image:
  bfl:
    prompt_suffix: "No text."
  openai:
    prompt_suffix: "No text."
  flux_schnell_local:
    prompt_suffix: "No text."
  qwen_image_local:
    prompt_suffix: "Ultra HD, 4K, cinematic composition. No text."
  qwen_image_nunchaku_local:
    prompt_suffix: "Ultra HD, 4K, cinematic composition. No text."
```

不要な場合は各`prompt_suffix`を空文字列（`""`）にすれば無効化できます。

FLUX.1 Schnellはguidance_scale=0.0の蒸留モデルのため`negative_prompt`が効かず、BFL APIも`negative_prompt`相当のパラメータを持たないため、いずれもポジティブプロンプトへの追記という同じ方式で実装しています。

シーン画像プロンプトの組み立て時、台本中の引用記号（`「」『』""`等）は`bfl`/`flux_schnell_local`使用時のみ自動的に除去されます（FLUXは引用符付き文言を画面内テキストとして描画する指示と解釈するため）。Qwen-Image系等それ以外のプロバイダーではこの制約がないため、引用記号はそのまま保持されます（[image_prompt_builder.py](src/youtube_generator/services/image_prompt_builder.py)）。

## レターボックス帯（黒帯）の自動検出・再生成（qwen_image_local / qwen_image_nunchaku_local）

Qwen-Imageは、ワイド画面のイラスト生成を指示した際に、プロンプト・`negative_prompt`での抑制だけでは防ぎきれず、まれに学習データ由来の「アニメ動画スクリーンショット」的な構図（上下に黒帯＋文字化けした字幕/タイトル風の文字）を生成することがあります。この問題には3段構えで対策しています。

1. **ポジティブプロンプト（`templates/<template>/image_prompt.txt`）**: 各テンプレートのスタイル記述へ「動画のワンシーンではなく、スタンドアロンのポスター調イラストである」旨を明示する文言を追加しています。`image_prompt_builder.py`は全テンプレート共通の骨組みを組み立てるだけの共通部品のため、ジャンル固有の対策文言はここではなくテンプレート側に持たせています（`CLAUDE.md`の「テンプレートごとの差分はtemplates/<template>のみで表現する」方針に合わせています）。
2. **negative_prompt（`qwen_image_local`/`qwen_image_nunchaku_local`）**: `anime screenshot, episode preview card, title card, broadcast slate, next episode preview`等、アニメ動画スクリーンショット特有の語を追加しています。また、`characters`が人物（登場人物）と誤解され意図せず人物描写を抑制するリスクがあったため、`text characters`と明示するよう整理しました。
3. **生成後の自動検出・再生成**（本節の内容）。

これを軽減するため、`qwen_image_local`/`qwen_image_nunchaku_local`は生成直後の画像の上端・下端を検査し、単色に近い黒帯を検出した場合は自動的に**別seedで1回だけ再生成**します（`src/youtube_generator/services/image_artifact_detector.py`）。再生成後も検出された場合は、警告ログを出力したうえでその画像をそのまま使用します（動画生成自体は停止しません）。

```yaml
image:
  qwen_image_local:
    letterbox_detection_enabled: true  # falseで検出・再生成を無効化（常に1回のみ生成）
  qwen_image_nunchaku_local:
    letterbox_detection_enabled: true
```

- 既定は`true`（有効）です。`false`にすると検出・再生成を一切行わず、常に1回のみ生成します。
- `seed`をconfig.yamlで固定している場合は、`letterbox_detection_enabled: true`でも再生成しても同じ画像になるため対象外です（検出時は警告ログのみ）。
- 判定は画像統計（上下端の輝度・ムラ）による簡易的なヒューリスティックのため、稀に自然な単色暗部（無地の暗い壁等）を誤検出し不要な再生成が発生する場合があります。誤検出時のコストは生成時間の増加のみで、出力内容が壊れることはありません。

## ローカルSelf-host画像生成の動作確認・テスト生成

以下のコマンドは、`providers.image`（またはproviders.image.scene）で選択中のSelf-hostプロバイダー（`flux_schnell_local` / `qwen_image_local` / `qwen_image_nunchaku_local`）に対して共通で動作します。個別のプロバイダーごとに別コマンドはありません。

### 環境確認（画像生成・API呼び出しは一切行わない）

```powershell
.\run.cmd image local-check
```

選択中のプロバイダーに応じて、torch/CUDA/diffusers（nunchaku利用時は`nunchaku`パッケージやPythonバージョン対応も含む）の導入状況、GPU名・VRAM容量、モデルのローカルキャッシュ有無、Provider構築可否などを表示します。

### テスト画像を1枚だけ生成する

```powershell
.\run.cmd image test-generate
.\run.cmd image test-generate --output output\local_image_check\sample.png --prompt "a calm mountain landscape"
```

実際にモデルのロード・推論が行われます（初回実行時はモデルのダウンロードも発生します）。既定の保存先は`output\local_image_check\test_image.png`です。

## FLUX.1 Schnell Self-host（ローカルGPU画像生成）

シーン画像をAPIではなくローカルGPU（Hugging Face Diffusers + FLUX.1 Schnell）で生成し、画像API費用を削減できます。サムネイルは従来どおりBFL/OpenAIのままにできます。

### 概要

- 追加されるプロバイダー: `flux_schnell_local`（`FluxSchnellLocalImageProvider`）
- モデルは既定で`black-forest-labs/FLUX.1-schnell`（`image.flux_schnell_local.model_id`で変更可）
- APIキーは不要。モデルは1ジョブ内で遅延ロード・再利用され、画像ごとに再ロードしない
- 既定ではAPIへの自動フォールバックは無効（`fallback_provider: null`）。意図しないAPI課金を避けるため、明示設定した場合のみBFL/OpenAIへ切り替わる

### 任意依存関係のインストール

torch/diffusers等は通常利用者には不要な重い依存関係のため、既定ではインストールされません。Self-hostを使う場合のみ、以下のいずれかを実行してください。

```powershell
python -m pip install -r requirements-flux-local.txt
```

または

```powershell
python -m pip install -e ".[flux-local]"
```

torchはお使いのGPU/CUDAバージョンに対応したビルドが必要な場合があります。事前に[PyTorch公式サイト](https://pytorch.org/get-started/locally/)でご自身の環境に合ったインストールコマンドを確認してください。

### モデルの初回ダウンロード

初回生成時（またはCLIの`test-generate`実行時）に、Hugging Faceから`model_id`のモデルが自動ダウンロードされ、既定では`%USERPROFILE%\.cache\huggingface\hub`へキャッシュされます。保存先を変更する場合は`image.flux_schnell_local.model_cache_dir`を指定してください。以降はダウンロード済みモデルが再利用されます。動作確認・テスト生成コマンドは[ローカルSelf-host画像生成の動作確認・テスト生成](#ローカルself-host画像生成の動作確認テスト生成)を参照してください。

### 設定例

```yaml
providers:
  image:
    scene: flux_schnell_local
    thumbnail: bfl

image:
  scene_size: 1920x1080
  thumbnail_size: 1280x720
  flux_schnell_local:
    model_id: black-forest-labs/FLUX.1-schnell
    device: auto
    dtype: auto
    num_inference_steps: 4
    guidance_scale: 0.0
    width: 1344
    height: 768
    seed: null
    # FLUX.1-schnellの公式サンプルはこの値(256)で蒸留・検証されている。超えると
    # プロンプトが切り捨てられるか、学習時と異なる長さとして扱われ品質が不安定になりうる。
    max_sequence_length: 256
    # negative_promptが効かない蒸留モデルのため、ポジティブプロンプト末尾に付加する。空文字列で無効化可能
    prompt_suffix: "No text."
    enable_cpu_offload: false
    enable_attention_slicing: false
    low_vram_mode: false
    model_cache_dir: null
    allow_cpu: false
    fallback_provider: null
```

`providers.image`は従来どおり単一の文字列（例: `image: bfl`）でも指定でき、その場合はシーン・サムネイル両方に同じプロバイダーが使われます（後方互換）。

### Civitai等の単一ファイルモデル（transformer_path）を使う方法

Civitaiで配布されているFLUX.1 Schnellベースのマージ/ファインチューンモデル（例: PixelWave）は、多くの場合**transformer（拡散モデル本体）のみ**を含む単一safetensorsファイルとして配布されており、VAE・テキストエンコーダ(CLIP L, T5xxl)・tokenizer・schedulerは含まれません。これらは`model_id`のベースモデル（既定は`black-forest-labs/FLUX.1-schnell`）からそのまま流用されます。

1. ダウンロードしたsafetensorsファイルをプロジェクト内の`huggingface\checkpoints\`へ配置する（`huggingface\model_cache`と同様に`.gitignore`の`huggingface/*`で除外済み）。
2. `image.flux_schnell_local.transformer_path`にそのファイルパスを指定する。

```yaml
image:
  flux_schnell_local:
    model_id: black-forest-labs/FLUX.1-schnell
    transformer_path: huggingface\checkpoints\pixelwave_flux1Schnell04.safetensors
```

`transformer_path`が未指定（`null`）の場合は、従来どおり`model_id`のtransformerがそのまま使われます。

- `transformer_path`使用時も`model_id`のベースモデル（VAE/テキストエンコーダ用）は初回ダウンロードが必要です。事前に`.\run.cmd image local-check`でベースモデルのキャッシュ状況を確認できます。
- 単一ファイル読み込み（`FluxTransformer2DModel.from_single_file`）には対応バージョンの`diffusers`が必要です。読み込みに失敗する場合は`requirements-flux-local.txt`のバージョンを最新化してください。
- モデルごとに推奨`num_inference_steps`が異なります（PixelWaveは公式に「Euler Normal, 8 steps」を推奨）。配布元の推奨設定に合わせて`image.flux_schnell_local.num_inference_steps`を調整してください。

### シーンだけSelf-host、サムネイルはBFLのまま、にする方法

`providers.image`を上記のように辞書形式にし、`scene`だけ`flux_schnell_local`、`thumbnail`は`bfl`（または`openai`）を指定してください。サムネイル生成は従来のBFL/OpenAI Providerのフローのまま変わりません。

### VRAM不足時の対処

CUDAメモリ不足時はエラーに`model_id`・`device`・`dtype`・生成サイズ・`cuda_oom=True`と対処法が表示されます。対策例:

- `image.flux_schnell_local.num_inference_steps`やSelf-host生成サイズ（`width`/`height`）を下げる
- `enable_cpu_offload: true`または`low_vram_mode: true`を有効化する
- 他のGPUプロセスを終了する

複数シーンの同時生成によるVRAM不足を避けるため、既定では逐次生成です。

### プロンプト長について

FLUX.1-schnellは公式サンプルで`max_sequence_length=256`を用いて蒸留・検証されています。これを超えるプロンプトは切り捨てられるか、学習時と異なる長さとして扱われ、顔・体などの構造的な破綻が増える一因になり得ます。`image.flux_schnell_local.max_sequence_length`（既定256）で調整できますが、値を上げても品質が改善するとは限りません。プロンプト生成自体（`ImagePromptBuilder`）はBFL/OpenAIとも共有される、Provider非依存の共通処理のため、Self-host専用には変更していません。

### CPU実行についての注意

GPU（CUDA）が検出できない場合、既定では停止し、原因が分かるエラーを表示します（意図せず長時間のCPU実行が始まったように見えることを防ぐため）。CPU実行を許可する場合は、`image.flux_schnell_local.allow_cpu: true`を明示してください。CPU実行はGPUに比べて非常に低速です。

### モデルキャッシュの保存先

既定は`%USERPROFILE%\.cache\huggingface\hub`（Hugging Faceの標準キャッシュ）です。`image.flux_schnell_local.model_cache_dir`で変更できます。

### APIへの自動フォールバックについて

`fallback_provider`は既定で`null`（無効）です。Self-host生成が失敗しても、明示的に`fallback_provider: bfl`のように設定しない限り、BFL/OpenAI APIは呼び出されず、API課金は発生しません。

### ライセンスの確認

FLUX.1 Schnellのライセンス・利用条件はこのドキュメントでは判断しません。公開・収益化する動画に使用する前に、必ず[Hugging Face上の公式モデルカード](https://huggingface.co/black-forest-labs/FLUX.1-schnell)で最新のライセンス内容をご自身で確認してください。

## Qwen-Image Self-host（ローカルGPU画像生成）

シーン画像をAPIではなくローカルGPU（Hugging Face Diffusers + Qwen-Image）で生成し、画像API費用を削減できます。サムネイルは従来どおりBFL/OpenAIのままにできます。仕組み・設定構造はFLUX.1 Schnell Self-hostと同様です。

### 概要

- 追加されるプロバイダー: `qwen_image_local`（`QwenImageLocalImageProvider`）
- モデルは既定で`Qwen/Qwen-Image`（`image.qwen_image_local.model_id`で変更可）
- APIキーは不要。モデルは1ジョブ内で遅延ロード・再利用され、画像ごとに再ロードしない
- 約20Bパラメータと大きいモデルのため、FLUX.1 Schnellよりも多くのVRAMを必要とする
- 既定ではAPIへの自動フォールバックは無効（`fallback_provider: null`）。意図しないAPI課金を避けるため、明示設定した場合のみBFL/OpenAIへ切り替わる

### 任意依存関係のインストール

```powershell
python -m pip install -r requirements-qwen-image-local.txt
```

または

```powershell
python -m pip install -e ".[qwen-image-local]"
```

torchはお使いのGPU/CUDAバージョンに対応したビルドが必要な場合があります。事前に[PyTorch公式サイト](https://pytorch.org/get-started/locally/)でご自身の環境に合ったインストールコマンドを確認してください。Qwen-Imageのモデルカードは最新版のdiffusersを推奨しています。モデルロードに失敗する場合は`pip install -U diffusers`を試してください。

### モデルの初回ダウンロード

初回生成時（またはCLIの`test-generate`実行時）に、Hugging Faceから`model_id`のモデルが自動ダウンロードされ、既定では`%USERPROFILE%\.cache\huggingface\hub`へキャッシュされます。保存先を変更する場合は`image.qwen_image_local.model_cache_dir`を指定してください。以降はダウンロード済みモデルが再利用されます。動作確認・テスト生成コマンドは[ローカルSelf-host画像生成の動作確認・テスト生成](#ローカルself-host画像生成の動作確認テスト生成)を参照してください。

### 設定例

```yaml
providers:
  image:
    scene: qwen_image_local
    thumbnail: bfl

image:
  scene_size: 1920x1080
  thumbnail_size: 1280x720
  qwen_image_local:
    model_id: Qwen/Qwen-Image
    device: auto
    dtype: auto
    # 公式サンプルはnum_inference_steps=50, true_cfg_scale=4.0を使用
    num_inference_steps: 50
    true_cfg_scale: 4.0
    width: 1664
    height: 928
    seed: null
    negative_prompt: ""
    # 任意のプロンプト追記文字列。既定は空文字列。例はQwen-Image公式ドキュメント推奨の
    # 品質向上用決まり文句 + 画面内テキスト描画を防ぐ制約
    prompt_suffix: "Ultra HD, 4K, cinematic composition. No text."
    enable_cpu_offload: false
    enable_attention_slicing: false
    low_vram_mode: false
    model_cache_dir: null
    allow_cpu: false
    fallback_provider: null
```

`providers.image`は従来どおり単一の文字列（例: `image: bfl`）でも指定でき、その場合はシーン・サムネイル両方に同じプロバイダーが使われます（後方互換）。シーンだけSelf-host、サムネイルはBFL/OpenAIのまま、にする方法もFLUX.1 Schnell Self-hostと同様です（`providers.image`を辞書形式にし、`scene`だけ`qwen_image_local`を指定）。

シーン画像生成用途（`providers.image.scene`）では、生成した画像は`width`/`height`（例: 1664x928）のまま保存され、`scene_size`（例: 1920x1080）への整形は行いません。動画レンダリング時にffmpegの`scale`フィルタで最終解像度へ引き伸ばされるため、生成時点でのリサイズが不要だからです（cover-crop処理の省略により生成の後処理が速くなります）。サムネイル用途（`providers.image.thumbnail`）はレンダリング側でリサイズされないため、従来どおり`thumbnail_size`へ正確に整形されます。

### VRAM不足時の対処

CUDAメモリ不足時はエラーに`model_id`・`device`・`dtype`・生成サイズ・`cuda_oom=True`と対処法が表示されます。対策例:

- Self-host生成サイズ（`width`/`height`）や`num_inference_steps`を下げる
- `enable_cpu_offload: true`または`low_vram_mode: true`を有効化する
- 他のGPUプロセスを終了する

複数シーンの同時生成によるVRAM不足を避けるため、既定では逐次生成です。

### Qwen-Image-Lightning LoRA（高速化・任意）

[Qwen-Image-Lightning](https://huggingface.co/lightx2v/Qwen-Image-Lightning)は、公式サンプルで`num_inference_steps=50`程度必要なQwen-Imageを、8 stepsで生成できるように蒸留したLoRAです（公式実測で12〜25倍高速。ただし細かい質感や密集した文字表現の精度は下がる場合があります）。既定では無効（`lightning_lora_enabled: false`）です。

```yaml
image:
  qwen_image_local:
    # 有効化する場合、num_inference_steps: 8, true_cfg_scale: 1.0を併せて設定する
    # （公式推奨値。true_cfg_scaleが1.0以外だとロード時に警告ログを出す）
    num_inference_steps: 8
    true_cfg_scale: 1.0
    lightning_lora_enabled: true
    lightning_lora_repo_id: lightx2v/Qwen-Image-Lightning
    lightning_lora_weight_name: Qwen-Image-Lightning-8steps-V2.0.safetensors
```

有効化すると、LoRAが前提とする専用のscheduler設定（`shift=1.0`, `use_dynamic_shifting=True`等。公式サンプル準拠）へ自動的に差し替わります。`true_cfg_scale: 1.0`は`negative_prompt`によるガイダンスを実質無効化するため、既定の`negative_prompt`で抑制している透かし・字幕風文字の写り込み対策が弱まる可能性がある点に注意してください。

なお、`low_vram_mode: true`（`enable_sequential_cpu_offload`）を使う環境では、1ステップあたりの時間がCPU⇔GPU間の重み転送に支配され、ステップ数を減らしても実測の総生成時間があまり短縮されない場合があります（動作確認時: RTX 4070/12GBで約130〜145秒/step）。Lightning LoRAによる高速化を活かすには、VRAMに余裕がある環境で`low_vram_mode: false`にするか、`enable_cpu_offload`を使うことを検討してください。

### CPU実行についての注意

GPU（CUDA）が検出できない場合、既定では停止し、原因が分かるエラーを表示します（意図せず長時間のCPU実行が始まったように見えることを防ぐため）。CPU実行を許可する場合は、`image.qwen_image_local.allow_cpu: true`を明示してください。20Bパラメータのモデルのため、CPU実行は極めて低速です。

### APIへの自動フォールバックについて

`fallback_provider`は既定で`null`（無効）です。Self-host生成が失敗しても、明示的に`fallback_provider: bfl`のように設定しない限り、BFL/OpenAI APIは呼び出されず、API課金は発生しません。

### ライセンスの確認

Qwen-Imageのライセンス・利用条件はこのドキュメントでは判断しません。公開・収益化する動画に使用する前に、必ず[Hugging Face上の公式モデルカード](https://huggingface.co/Qwen/Qwen-Image)で最新のライセンス内容をご自身で確認してください（モデルカード記載時点ではApache 2.0）。

## Qwen-Image nunchaku Self-host（4bit量子化・省VRAM）

[nunchaku](https://github.com/nunchaku-tech/nunchaku)（SVDQuant）による4bit量子化版Qwen-Imageをローカル実行するプロバイダーです。通常のQwen-Image Self-host（bf16、約20Bパラメータ分のVRAMが必要）に比べてVRAM使用量を大幅に削減でき、VRAMが少ないGPUでもCPUオフロードなし、または軽いオフロードだけで動作させられる可能性があります。

### 概要

- 追加されるプロバイダー: `qwen_image_nunchaku_local`（`QwenImageNunchakuLocalImageProvider`）
- ベースパイプラインは`Qwen/Qwen-Image`、transformer（拡散モデル本体）のみ`nunchaku-tech/nunchaku-qwen-image`の4bit量子化版に差し替える
- **CUDA専用**。nunchakuの量子化推論カーネルはCUDA向けのため、CPU実行には対応しない
- GPU VRAM量に応じて自動的にオフロード方式を切り替える（`image.qwen_image_nunchaku_local.offload_threshold_gb`、既定18GB）。しきい値超過時は`enable_model_cpu_offload`、以下では`transformer.set_offload`+`enable_sequential_cpu_offload`を使用
- 既定ではAPIへの自動フォールバックは無効（`fallback_provider: null`）

### nunchakuのインストール（重要・手動作業が必要）

torch/diffusers等とは異なり、`nunchaku`本体は通常の`pip install nunchaku`では導入できません。[nunchakuのリリースページ](https://github.com/nunchaku-tech/nunchaku/releases)から、お使いの**Pythonバージョン・PyTorchバージョン・CUDAバージョン**に対応するプリビルドwheelを選び、直接インストールしてください。

```powershell
python -m pip install -r requirements-qwen-image-nunchaku-local.txt
python -m pip install https://github.com/nunchaku-tech/nunchaku/releases/download/vX.Y.Z/nunchaku-X.Y.Z+cu12.8torch2.11-cp312-cp312-win_amd64.whl
```

（`vX.Y.Z`とwheelファイル名は実際のリリースページで確認したものに置き換えてください）

**動作確認済みの落とし穴（重要）**: `nunchaku`は`torchvision>=0.20`を必須依存として要求しますが、`pip install nunchaku-*.whl`だけを実行すると、torchのビルド（例: `+cu128`）と対応しない`torchvision`が自動インストールされ、`RuntimeError: operator torchvision::nms does not exist`のようなABI不一致エラーでnunchakuのimportに失敗することを確認しています。この場合は、[PyTorchのtorch/torchvision対応表](https://github.com/pytorch/vision#installation)で自分のtorchバージョンに対応する`torchvision`バージョンを確認し、torchと同じCUDAインデックスから明示的に入れ直してください。

```powershell
python -m pip install "torchvision==<対応バージョン>" --index-url https://download.pytorch.org/whl/cu128
```

また、`import torchaudio`（stable-tsの依存関係）が`Could not load this library: ...\torchaudio\lib\libtorchaudio.pyd`のようなDLLロードエラーを起こす場合は、torch/torchaudioを同じインデックスから揃えて強制再インストールすると解消することを確認しています。

```powershell
python -m pip install torch==<バージョン> torchaudio==<バージョン> --index-url https://download.pytorch.org/whl/cu128 --force-reinstall --no-deps
```

さらに、`diffusers`は**0.36.0に固定**してください（`requirements-qwen-image-nunchaku-local.txt`で指定済み）。nunchaku 1.2.1は`diffusers>=0.36`を要求しますが、より新しいバージョン（0.39.0で確認）では`TypeError: QwenEmbedRope.forward() got multiple values for argument 'device'`という非互換エラーで画像生成に失敗することを確認しています。nunchaku自体のCI extraも`diffusers==0.36`を明示的にピン留めしています。

**重要な制約**: 2026-08-01時点で、nunchakuのプリビルドwheelは **Python 3.10〜3.13向けのみ** 配布されています。プロジェクトの`.venv`がPython 3.14以降の場合、そのままでは`nunchaku`をインストールできません。この場合は以下のいずれかが必要です。

- Python 3.10〜3.13で別の仮想環境を用意し、そちらでnunchaku版プロバイダーを動かす
- nunchakuをソースからビルドする（CUDA Toolkit・C++コンパイラ等が別途必要。手順は本プロジェクトでは未検証）

`.\run.cmd image local-check`を実行すると、現在のPythonバージョンがnunchakuのプリビルドwheel対応範囲内かどうかを含めて確認できます。

### 量子化transformerのキャッシュ先について（重要）

nunchaku本体（`NunchakuQwenImageTransformer2DModel.from_pretrained()`）は`cache_dir`引数を受け取っても内部の`hf_hub_download()`呼び出しへ転送しないため、素朴には`image.qwen_image_nunchaku_local.model_cache_dir`が量子化transformer本体（`nunchaku-tech/nunchaku-qwen-image`）のダウンロード先には反映されません（実装を確認済み: `nunchaku/utils.py`の`hf_hub_download()`呼び出しに`cache_dir`が渡されていません）。

このプロジェクトでは、`QwenImageNunchakuLocalImageProvider`がモデルロード時に`huggingface_hub.constants.HF_HUB_CACHE`（`hf_hub_download()`がcache_dir未指定時に参照する既定キャッシュ先）を`model_cache_dir`の値へ直接上書きすることで対応しています。そのため、**`image.qwen_image_nunchaku_local.model_cache_dir`を設定するだけで**、ベースパイプラインと量子化transformerの両方が同じフォルダへキャッシュされます。diffusers側の`cache_dir`を明示指定している他の呼び出し（ベースパイプラインやFLUX/Qwen-Imageの通常版）はこの既定値より優先されるため、影響を受けません。

既に`%USERPROFILE%\.cache\huggingface\hub`へダウンロード済みの場合、`model_cache_dir`を設定しただけでは自動移動されません。該当フォルダ（`models--nunchaku-tech--nunchaku-qwen-image`）を削除してから再実行すると、`model_cache_dir`で指定したフォルダへ再ダウンロードされます。

### 設定例

```yaml
providers:
  image:
    scene: qwen_image_nunchaku_local
    thumbnail: bfl

image:
  scene_size: 1920x1080
  thumbnail_size: 1280x720
  qwen_image_nunchaku_local:
    base_model_id: Qwen/Qwen-Image
    transformer_repo_id: nunchaku-tech/nunchaku-qwen-image
    # auto: GPU世代から自動判定（Blackwell/50シリーズはnvfp4、それ以外はint4）
    precision: auto
    # 32: 高速（軽量） / 128: 高品質（重い）
    rank: 32
    offload_threshold_gb: 18.0
    # 低VRAM時（offload_threshold_gb以下）のtransformer.set_offload()に渡すパラメータ。
    # 公式サンプルの既定値。use_pin_memory: trueにすると環境によってはpin_memory()確保時に
    # CUDAメモリ不足で失敗することがある（実際に確認済み）。
    low_vram_use_pin_memory: false
    low_vram_num_blocks_on_gpu: 1
    num_inference_steps: 50
    true_cfg_scale: 4.0
    width: 1664
    height: 928
    seed: null
    negative_prompt: ""
    # 任意のプロンプト追記文字列。既定は空文字列。例はQwen-Image公式ドキュメント推奨の
    # 品質向上用決まり文句 + 画面内テキスト描画を防ぐ制約
    prompt_suffix: "Ultra HD, 4K, cinematic composition. No text."
    model_cache_dir: null
    fallback_provider: null
```

シーン画像生成用途では、生成した画像は`width`/`height`（例: 1664x928）のまま保存され、`scene_size`（例: 1920x1080）への整形は行いません（動画レンダリング時にffmpegの`scale`フィルタで最終解像度へ引き伸ばされるため）。サムネイル用途は従来どおり`thumbnail_size`へ正確に整形されます。

### 生成速度・VRAMについて

具体的な倍率はnunchaku公式ドキュメントに記載がありませんが、以下の環境で実測しました。

- GPU: NVIDIA GeForce RTX 4070（VRAM 12GB、`offload_threshold_gb`未満のためsequential offload経路）
- 設定: `precision: auto`（int4に自動判定）、`rank: 32`、`num_inference_steps: 50`、`true_cfg_scale: 4.0`、`1664x928`
- モデルロード: 約13秒（初回ダウンロード除く）
- 画像生成: 約198秒（約3分18秒）/ 1枚

`rank`（32/128）や`offload_threshold_gb`、VRAMに余裕がある環境での`enable_model_cpu_offload`経路（18GB超）では結果が変わります。お使いの環境で実際の生成時間・VRAM使用量を確認してください。

### ライセンスの確認

nunchaku（SVDQuant）およびQwen-Imageのライセンス・利用条件はこのドキュメントでは判断しません。公開・収益化する動画に使用する前に、必ず[nunchaku-qwen-imageのモデルカード](https://huggingface.co/nunchaku-ai/nunchaku-qwen-image)と[Qwen-Imageの公式モデルカード](https://huggingface.co/Qwen/Qwen-Image)で最新のライセンス内容をご自身で確認してください。

## シーン画像プロンプト用の場面説明生成（scene_description）

Qwen-Image等の文字レンダリング精度が高いモデルでは、シーン画像プロンプトへ生の日本語ナレーション文をそのまま渡すと、その文章が字幕・キャプションのように画面へ描画されてしまうことがあります。これを避けるため、`image.scene_description.enabled: true`（`providers.text`が`openai`の場合のみ利用可）にすると、ナレーション文の代わりにOpenAIで生成した短い英語の場面説明を画像プロンプトへ渡します。

```yaml
image:
  scene_description:
    enabled: true
    # nullの場合はtext.scene_split_modelを使用する。
    model: null
```

動画1本につきOpenAI APIを1回のみ呼び出し、全シーン分をまとめて生成します（追加課金あり）。実装は`OpenAISceneVisualDescriber`（[openai_scene_visual_describer.py](src/youtube_generator/infrastructure/openai_scene_visual_describer.py)）です。

生成した場面説明は、ナレーション文＋`scene_description`設定単位で独立してキャッシュされます（`CachingSceneVisualDescriber`）。これにより、画像生成側の設定（`qwen_image_nunchaku_local`等）だけを変更して`--generate-images`を再実行するような場合でも、シーン画像自体のキャッシュはミスしますが、ナレーション文が変わっていなければ場面説明のAPI呼び出しは発生しません。

場面説明は`--generate-scene-descriptions`で独立した工程としても生成できます（`--generate-audio`の後、`--generate-images`の前に実行する想定）。

```powershell
.\run.cmd --generate-scene-descriptions "$workDir" --template science
```

各画像window（`sceneNN_MM.png`に対応）ごとに`sceneNN_MM.description.txt`として保存され、`--generate-images`はこのファイルが揃っていればOpenAI APIを呼ばずにそのまま使います。同じ作業フォルダに対する再実行時は、既に生成済みの`.description.txt`はスキップされます。場面説明だけを明示的に再生成したい場合は`--force`を付けてください。この場合`CachingSceneVisualDescriber`のコンテンツハッシュキャッシュも経由せず、必ずOpenAI APIを再呼び出しします。

```powershell
.\run.cmd --generate-scene-descriptions "$workDir" --template science --force
```

## シーン画像の後処理でキャプション帯を除去する（scene_edit）

生成したシーン画像に字幕・キャプション風の文字が写り込んだ場合、Qwen-Image-Edit（nunchaku 4bit量子化版）による編集ステップで除去できます。既定は無効です。

```yaml
image:
  scene_edit:
    enabled: true
    # 現状qwen_image_edit_nunchaku_localのみ対応。
    provider: qwen_image_edit_nunchaku_local
```

有効化するとシーン画像1枚ごとに追加の推論が発生し処理時間が大きく増加します（実測: RTX 4070/12GBで`num_inference_steps=8`のとき約107秒/枚。別途モデルダウンロード・ロードで初回のみ約13分、ディスク使用量+約27GBが必要）。詳細な設定項目（`precision`/`rank`/`lightning_steps`等）は`config/config.yaml`の`image.qwen_image_edit_nunchaku_local`を参照してください。CUDA専用でCPU実行には対応していません。

生成用モデル（Qwen-Imageなど）と編集用モデルを同一プロセス内で交互にロードするとVRAM/システムメモリを圧迫するため、キュー実行（`queue run`）・単発実行いずれも生成と編集を別プロセスに分離しています。キュー実行時は`IMAGE_GENERATION`工程内で`--generate-images`の後に`--edit-images`が自動的に実行されます。キューを使わない場合は次のように個別に実行してください。

```powershell
.\run.cmd --generate-images "$workDir" --template science
.\run.cmd --edit-images "$workDir" --template science
```

`--edit-images`は`--generate-images`が対象フォルダへ書き出す生成キャッシュキー（`.image_cache_key`）と編集設定からキャッシュキーを組み立てるため、`--generate-images`より先に単独で実行することはできません。編集結果も`cache/`に保存され、生成設定・編集設定のいずれも変わっていなければ再編集をスキップします。同じ作業フォルダに対する再実行時は、画像単位でも既に同じ編集設定で編集済みのものはスキップされます（中断されたジョブの再試行時に二重編集を避けるため）。`--force`を付けるとキャッシュ・スキップ判定を無視してすべて再編集します。

編集時の推論解像度は既定で自動決定されます。シーン画像は生成解像度（例: 1664x928）のまま保存されるため、通常は画像ファイル自体のサイズがそのまま編集解像度になりますが、`providers.image.scene`で選択中の画像生成プロバイダー（`qwen_image_local`/`qwen_image_nunchaku_local`など、`width`/`height`設定を持つものであればどれでも対象）の`width`/`height`設定を自動的に参照する仕組みにより、生成側の設定変更に編集側が追従し、config.yaml内での二重管理を避けています。編集後は編集対象画像と同じ解像度へ戻して保存するため、最終的な出力サイズは変わりません。BFL/OpenAIのように`width`/`height`という概念を持たないプロバイダーを選択している場合は自動決定できず、従来どおり編集対象画像自身の解像度でそのまま推論します。

`image.qwen_image_edit_nunchaku_local.width`/`height`を明示的に指定すると、この自動決定より優先されます。

## シーン内の画像を複数枚・自然なタイミングで切り替える

1シーンの音声が長い場合、1枚の画像だけを表示し続けると単調になります。`image.min_display_seconds`（既定3.0秒）〜`image.max_display_seconds`（既定15.0秒）の範囲で、文単位の自然な区切りに沿って1シーン内に複数枚の画像（`sceneNN_MM.png`、MM=シーン内の通し番号）を生成・表示します。

```yaml
image:
  min_display_seconds: 3.0
  max_display_seconds: 15.0
```

画像生成時の区切りは`characters_per_second`による文字数からの推定のみを使用し、実際の音声長やstable-tsアライメントには依存しません（TTS設定変更のたびにシーン画像まで再生成されるのを防ぐため）。実際の表示秒数は動画レンダリング時に、生成済みの画像枚数を正として実音声長・アライメント結果へスナップされます。

## テスト

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
python -m pytest -m unit
python -m pytest -m integration
python -m pytest --cov=youtube_generator --cov-report=term-missing
```

通常のテストでは外部APIを呼び出しません。`external`マーカー付きテストは、`RUN_EXTERNAL_TESTS=true`を明示した場合だけ実行されます。

## ソース構成

- `src/youtube_generator/app/`：生成フローのユースケース
- `src/youtube_generator/domain/`：ドメインモデル
- `src/youtube_generator/infrastructure/`：API、FFmpeg、永続化
- `src/youtube_generator/plugins/`：テキスト、音声、画像プロバイダー
- `src/youtube_generator/services/`：品質検査や補助処理
- `src/youtube_generator/jobs/`：ジョブキューと一括生成
- `src/youtube_generator/youtube/`：YouTube投稿
- `tests/`：ユニット・結合テスト
