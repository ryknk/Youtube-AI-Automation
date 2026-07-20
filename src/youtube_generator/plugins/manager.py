"""設定に基づき生成プロバイダーを組み立てるファクトリ。"""

from typing import Any

from youtube_generator.config import Settings
from youtube_generator.domain.scene_splitter import SceneSplitter
from youtube_generator.domain.metadata_generator import MetadataGenerator
from youtube_generator.infrastructure.openai_metadata_generator import OpenAIMetadataGenerator
from youtube_generator.plugins.base.image_provider import ImageProvider
from youtube_generator.plugins.base.text_generator import TextGenerator
from youtube_generator.plugins.base.tts_provider import TTSProvider
from youtube_generator.plugins.image.openai_image import OpenAIImageProvider
from youtube_generator.plugins.image.bfl_image import BFLImageProvider
from youtube_generator.plugins.text.openai_text import OpenAITextProvider
from youtube_generator.plugins.tts.openai_tts import OpenAITTSProvider
from youtube_generator.plugins.tts.voicevox_tts import VOICEVOXTTSProvider
from youtube_generator.services.retry import RetryPolicy


class PluginManager:
    """プロバイダー名を実装へ解決する。新規追加はこの登録だけでよい。"""

    def __init__(
        self, settings: Settings, provider_settings: dict[str, Any], text_settings: dict[str, Any]
    ) -> None:
        self._settings = settings
        self._provider_settings = provider_settings
        self._text_settings = text_settings

    def create_text_generator(self, retry_policy: RetryPolicy, max_scenes: int = 30) -> TextGenerator:
        if self._provider_name("text") == "openai":
            return OpenAITextProvider(
                self._api_key(), str(self._text_settings["script_model"]),
                str(self._text_settings["scene_split_model"]), retry_policy,
                max_scenes=max_scenes,
            )
        raise ValueError(f"未対応のtextプロバイダーです: {self._provider_name('text')}")

    def create_scene_splitter(self, retry_policy: RetryPolicy, max_scenes: int = 30) -> SceneSplitter:
        provider = self.create_text_generator(retry_policy, max_scenes=max_scenes)
        if isinstance(provider, OpenAITextProvider):
            return provider.scene_splitter()
        raise ValueError("選択中のtextプロバイダーはシーン分割に対応していません。")

    def create_tts_provider(self, audio_settings: dict[str, Any], retry_policy: RetryPolicy) -> TTSProvider:
        if self._provider_name("tts") == "openai":
            return OpenAITTSProvider(
                self._api_key(), str(audio_settings["model"]), str(audio_settings["voice"]),
                float(audio_settings["speed"]), str(audio_settings["instructions"]), retry_policy,
            )
        if self._provider_name("tts") == "voicevox":
            values = audio_settings.get("voicevox", {})
            if not isinstance(values, dict):
                raise ValueError("config.yaml の audio.voicevox 設定が不正です。")
            return VOICEVOXTTSProvider(str(values.get("base_url", "http://127.0.0.1:50021")), int(values.get("speaker_id", 3)), float(values.get("timeout", 30)), {
                "speedScale": float(values.get("speed_scale", 1.0)), "pitchScale": float(values.get("pitch_scale", 0.0)),
                "intonationScale": float(values.get("intonation_scale", 1.0)), "volumeScale": float(values.get("volume_scale", 1.0)),
                "prePhonemeLength": float(values.get("pre_phoneme_length", 0.1)), "postPhonemeLength": float(values.get("post_phoneme_length", 0.1)),
            }, retry_policy)
        raise ValueError(f"未対応のttsプロバイダーです: {self._provider_name('tts')}")

    def create_image_provider(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy,
        size_setting: str = "scene_size",
    ) -> ImageProvider:
        model_setting = "thumbnail_model" if size_setting == "thumbnail_size" else "scene_model"
        if self._provider_name("image") == "bfl":
            if (
                self._settings.bfl_api_key is None
                or not self._settings.bfl_api_key.get_secret_value().strip()
            ):
                raise ValueError("BFL画像プロバイダーには BFL_API_KEY が必要です。")
            return BFLImageProvider(
                self._settings.bfl_api_key.get_secret_value(),
                str(image_settings[model_setting]), str(image_settings[size_setting]), retry_policy,
            )
        if self._provider_name("image") == "openai":
            return OpenAIImageProvider(
                self._api_key(), str(image_settings["openai_model"]), str(image_settings[size_setting]),
                str(image_settings["quality"]), retry_policy,
            )
        raise ValueError(f"未対応のimageプロバイダーです: {self._provider_name('image')}")

    def create_metadata_generator(
        self, retry_policy: RetryPolicy, title_count: int
    ) -> MetadataGenerator:
        if self._provider_name("text") == "openai":
            return OpenAIMetadataGenerator(
                self._api_key(), str(self._text_settings["metadata_model"]), retry_policy,
                title_count=title_count,
            )
        raise ValueError(f"未対応のtextプロバイダーです: {self._provider_name('text')}")

    def _provider_name(self, category: str) -> str:
        value = self._provider_settings.get(category)
        if not isinstance(value, str) or not value:
            raise ValueError(f"config.yaml の providers.{category} を指定してください。")
        return value.lower()

    def _api_key(self) -> str:
        if self._settings.openai_api_key is None:
            raise ValueError("選択中のOpenAIプロバイダーには OPENAI_API_KEY が必要です。")
        return self._settings.openai_api_key.get_secret_value()
