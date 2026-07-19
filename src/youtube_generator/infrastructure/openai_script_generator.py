"""OpenAI Responses APIを利用した台本生成実装。"""

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from youtube_generator.domain.script_generator import ScriptGenerator
from youtube_generator.domain.template import VideoTemplate
from youtube_generator.exceptions import ScriptGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.services.retry import RetryPolicy, retry_on_failure


class OpenAIScriptGenerator(ScriptGenerator):
    """テーマに対する日本語YouTube台本をResponses APIで生成する。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        retry_policy: RetryPolicy,
        client: OpenAI | None = None,
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._retry_policy = retry_policy
        self._logger = get_logger(__name__)

    def generate(self, theme: str, template: VideoTemplate) -> str:
        """テンプレートの指示を反映した台本を生成する。"""
        cleaned_theme = theme.strip()
        if not cleaned_theme:
            raise ValueError("テーマを入力してください。")

        response = self._create_response(cleaned_theme, template)
        script = response.output_text.strip()
        if not script:
            raise ScriptGenerationError("OpenAI APIから台本文を取得できませんでした。")
        return script

    def _create_response(self, theme: str, template: VideoTemplate):  # type: ignore[no-untyped-def]
        @retry_on_failure(
            policy=self._retry_policy,
            retryable_exceptions=(APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            logger=self._logger,
        )
        def request():  # type: ignore[no-untyped-def]
            return self._client.responses.create(
                model=self._model,
                instructions=(
                    "あなたはYouTube動画の日本語台本を書くプロの構成作家です。\n"
                    f"テンプレートの方針: {template.script_instruction}\n"
                    "動画のナレーションとして自然な文章だけを出力してください。"
                    "見出し、注釈、Markdownは含めないでください。"
                ),
                input=(
                    f"動画テーマ: {theme}\n"
                    f"想定シーン構成: {' → '.join(template.scene_structure)}\n"
                    f"画像の方向性: {template.image_style}"
                ),
            )

        return request()
