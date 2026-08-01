"""アプリケーション固有の例外定義。"""


class ScriptGenerationError(RuntimeError):
    """台本生成APIから有効な台本を取得できなかった場合の例外。"""


class SceneSplitError(RuntimeError):
    """台本を有効なシーン群へ分割できなかった場合の例外。"""


class SpeechSynthesisError(RuntimeError):
    """音声合成の入力または出力が不正な場合の例外。"""


class ImageGenerationError(RuntimeError):
    """画像生成APIから有効な画像を取得できなかった場合の例外。"""


class SubtitleGenerationError(RuntimeError):
    """音声長の取得またはSRT字幕の生成に失敗した場合の例外。"""


class AlignmentGenerationError(RuntimeError):
    """音声と台本のアライメント生成に失敗した場合の例外。"""


class VideoRenderingError(RuntimeError):
    """FFmpegによる動画の生成に失敗した場合の例外。"""


class MetadataGenerationError(RuntimeError):
    """動画メタデータを有効な形式で生成できなかった場合の例外。"""


class SceneDescriptionError(RuntimeError):
    """画像生成プロンプト用の場面説明を生成できなかった場合の例外。"""
