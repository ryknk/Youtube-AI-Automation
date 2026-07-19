"""OpenAIを利用するLLMテキストプラグイン。"""

from youtube_generator.domain.scene_splitter import SceneSplitter
from youtube_generator.domain.template import VideoTemplate
from youtube_generator.infrastructure.openai_scene_splitter import OpenAISceneSplitter
from youtube_generator.infrastructure.openai_script_generator import OpenAIScriptGenerator
from youtube_generator.plugins.base.text_generator import TextGenerator
from youtube_generator.services.retry import RetryPolicy


class OpenAITextProvider(TextGenerator):
    """既存のOpenAI実装をプラグイン契約へ適合させるアダプター。"""

    def __init__(
        self, api_key: str, script_model: str, scene_split_model: str,
        retry_policy: RetryPolicy, max_scenes: int = 30,
    ) -> None:
        self._script_generator = OpenAIScriptGenerator(api_key, script_model, retry_policy)
        self._scene_splitter = OpenAISceneSplitter(
            api_key, scene_split_model, retry_policy, max_scenes=max_scenes
        )

    def generate_text(self, theme: str, template: VideoTemplate) -> str:
        return self._script_generator.generate(theme, template)

    def split_scenes(self, script: str) -> tuple[str, ...]:
        return self._scene_splitter.split(script)

    def scene_splitter(self) -> SceneSplitter:
        return _SceneSplitterAdapter(self)


class _SceneSplitterAdapter(SceneSplitter):
    def __init__(self, provider: OpenAITextProvider) -> None:
        self._provider = provider

    def split(self, script: str) -> tuple[str, ...]:
        return self._provider.split_scenes(script)
