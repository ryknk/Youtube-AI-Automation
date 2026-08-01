"""設定に基づき生成プロバイダーを組み立てるファクトリ。"""

from typing import Any

from youtube_generator.config import Settings
from youtube_generator.domain.scene_splitter import SceneSplitter
from youtube_generator.domain.metadata_generator import MetadataGenerator
from youtube_generator.infrastructure.openai_metadata_generator import OpenAIMetadataGenerator
from youtube_generator.infrastructure.openai_scene_visual_describer import OpenAISceneVisualDescriber
from youtube_generator.plugins.base.image_provider import ImageProvider
from youtube_generator.plugins.base.scene_visual_describer import SceneVisualDescriber
from youtube_generator.plugins.base.text_generator import TextGenerator
from youtube_generator.plugins.base.tts_provider import TTSProvider
from youtube_generator.plugins.image.openai_image import OpenAIImageProvider
from youtube_generator.plugins.image.bfl_image import BFLImageProvider
from youtube_generator.plugins.image.flux_schnell_local_image import (
    FluxSchnellLocalImageProvider,
    FluxSchnellLocalSettings,
)
from youtube_generator.plugins.image.image_provider_fallback import FallbackImageProvider
from youtube_generator.plugins.image.qwen_image_local import (
    QwenImageLocalImageProvider,
    QwenImageLocalSettings,
)
from youtube_generator.plugins.image.qwen_image_nunchaku_local import (
    QwenImageNunchakuLocalImageProvider,
    QwenImageNunchakuLocalSettings,
)
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

    def image_provider_name(self, purpose: str) -> str:
        """シーン('scene')・サムネイル('thumbnail')ごとに解決した画像プロバイダー名を返す。

        キャッシュfingerprintの組み立て等、Provider生成を伴わない箇所から
        参照するための公開ヘルパー。
        """
        return self._provider_name("image", purpose)

    def create_image_provider(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy,
        size_setting: str = "scene_size",
    ) -> ImageProvider:
        purpose = "thumbnail" if size_setting == "thumbnail_size" else "scene"
        provider_name = self._provider_name("image", purpose)
        return self._build_named_image_provider(provider_name, image_settings, retry_policy, size_setting)

    def _build_named_image_provider(
        self, provider_name: str, image_settings: dict[str, Any], retry_policy: RetryPolicy,
        size_setting: str,
    ) -> ImageProvider:
        model_setting = "thumbnail_model" if size_setting == "thumbnail_size" else "scene_model"
        if provider_name == "bfl":
            if (
                self._settings.bfl_api_key is None
                or not self._settings.bfl_api_key.get_secret_value().strip()
            ):
                raise ValueError("BFL画像プロバイダーには BFL_API_KEY が必要です。")
            return BFLImageProvider(
                self._settings.bfl_api_key.get_secret_value(),
                str(image_settings[model_setting]), str(image_settings[size_setting]), retry_policy,
                prompt_suffix=self._prompt_suffix(image_settings, "bfl"),
            )
        if provider_name == "openai":
            return OpenAIImageProvider(
                self._api_key(), str(image_settings["openai_model"]), str(image_settings[size_setting]),
                str(image_settings["quality"]), retry_policy,
                prompt_suffix=self._prompt_suffix(image_settings, "openai"),
            )
        if provider_name == "flux_schnell_local":
            return self._create_flux_schnell_local_provider(image_settings, retry_policy, size_setting)
        if provider_name == "qwen_image_local":
            return self._create_qwen_image_local_provider(image_settings, retry_policy, size_setting)
        if provider_name == "qwen_image_nunchaku_local":
            return self._create_qwen_image_nunchaku_local_provider(image_settings, retry_policy, size_setting)
        raise ValueError(f"未対応のimageプロバイダーです: {provider_name}")

    def _create_flux_schnell_local_provider(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy, size_setting: str,
    ) -> ImageProvider:
        flux_settings_raw = image_settings.get("flux_schnell_local", {})
        if not isinstance(flux_settings_raw, dict):
            raise ValueError("config.yaml の image.flux_schnell_local 設定が不正です。")
        flux_settings = FluxSchnellLocalSettings.from_mapping(flux_settings_raw)
        primary: ImageProvider = FluxSchnellLocalImageProvider(
            flux_settings, str(image_settings[size_setting]),
        )
        if flux_settings.fallback_provider is None:
            return primary
        if flux_settings.fallback_provider == "flux_schnell_local":
            raise ValueError(
                "image.flux_schnell_local.fallback_provider に flux_schnell_local は指定できません。"
            )
        fallback = self._build_named_image_provider(
            flux_settings.fallback_provider, image_settings, retry_policy, size_setting,
        )
        return FallbackImageProvider(primary, fallback, flux_settings.fallback_provider)

    def _create_qwen_image_local_provider(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy, size_setting: str,
    ) -> ImageProvider:
        qwen_settings_raw = image_settings.get("qwen_image_local", {})
        if not isinstance(qwen_settings_raw, dict):
            raise ValueError("config.yaml の image.qwen_image_local 設定が不正です。")
        qwen_settings = QwenImageLocalSettings.from_mapping(qwen_settings_raw)
        primary: ImageProvider = QwenImageLocalImageProvider(
            qwen_settings, str(image_settings[size_setting]),
        )
        if qwen_settings.fallback_provider is None:
            return primary
        if qwen_settings.fallback_provider == "qwen_image_local":
            raise ValueError(
                "image.qwen_image_local.fallback_provider に qwen_image_local は指定できません。"
            )
        fallback = self._build_named_image_provider(
            qwen_settings.fallback_provider, image_settings, retry_policy, size_setting,
        )
        return FallbackImageProvider(primary, fallback, qwen_settings.fallback_provider)

    def _create_qwen_image_nunchaku_local_provider(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy, size_setting: str,
    ) -> ImageProvider:
        nunchaku_settings_raw = image_settings.get("qwen_image_nunchaku_local", {})
        if not isinstance(nunchaku_settings_raw, dict):
            raise ValueError("config.yaml の image.qwen_image_nunchaku_local 設定が不正です。")
        nunchaku_settings = QwenImageNunchakuLocalSettings.from_mapping(nunchaku_settings_raw)
        primary: ImageProvider = QwenImageNunchakuLocalImageProvider(
            nunchaku_settings, str(image_settings[size_setting]),
        )
        if nunchaku_settings.fallback_provider is None:
            return primary
        if nunchaku_settings.fallback_provider == "qwen_image_nunchaku_local":
            raise ValueError(
                "image.qwen_image_nunchaku_local.fallback_provider に "
                "qwen_image_nunchaku_local は指定できません。"
            )
        fallback = self._build_named_image_provider(
            nunchaku_settings.fallback_provider, image_settings, retry_policy, size_setting,
        )
        return FallbackImageProvider(primary, fallback, nunchaku_settings.fallback_provider)

    def create_scene_visual_describer(
        self, image_settings: dict[str, Any], retry_policy: RetryPolicy,
    ) -> SceneVisualDescriber | None:
        """``image.scene_description.enabled`` がtrueの場合のみ生成する。falseまたは未設定
        の場合はNoneを返し、呼び出し側は従来どおり生のナレーション文を画像プロンプトへ使う。"""
        scene_description_settings = image_settings.get("scene_description", {})
        if not isinstance(scene_description_settings, dict):
            raise ValueError("config.yaml の image.scene_description 設定が不正です。")
        if not bool(scene_description_settings.get("enabled", False)):
            return None
        if self._provider_name("text") != "openai":
            raise ValueError(
                "image.scene_description.enabled=true はproviders.textがopenaiの場合のみ利用できます。"
            )
        model = scene_description_settings.get("model") or self._text_settings.get("scene_split_model")
        if not model:
            raise ValueError(
                "config.yaml の image.scene_description.model または text.scene_split_model を指定してください。"
            )
        return OpenAISceneVisualDescriber(self._api_key(), str(model), retry_policy)

    @staticmethod
    def _prompt_suffix(image_settings: dict[str, Any], provider_name: str) -> str:
        """``image.<provider_name>.prompt_suffix``を読み取る。既定は空文字列（何も付加しない）。"""
        provider_settings = image_settings.get(provider_name, {})
        if not isinstance(provider_settings, dict):
            raise ValueError(f"config.yaml の image.{provider_name} 設定が不正です。")
        return str(provider_settings.get("prompt_suffix", ""))

    def create_metadata_generator(
        self, retry_policy: RetryPolicy, title_count: int
    ) -> MetadataGenerator:
        if self._provider_name("text") == "openai":
            return OpenAIMetadataGenerator(
                self._api_key(), str(self._text_settings["metadata_model"]), retry_policy,
                title_count=title_count,
            )
        raise ValueError(f"未対応のtextプロバイダーです: {self._provider_name('text')}")

    def _provider_name(self, category: str, purpose: str | None = None) -> str:
        value = self._provider_settings.get(category)
        label = f"{category}.{purpose}" if purpose else category
        if isinstance(value, dict):
            if purpose is None:
                raise ValueError(f"config.yaml の providers.{category} を指定してください。")
            value = value.get(purpose)
        if not isinstance(value, str) or not value:
            raise ValueError(f"config.yaml の providers.{label} を指定してください。")
        return value.lower()

    def _api_key(self) -> str:
        if self._settings.openai_api_key is None:
            raise ValueError("選択中のOpenAIプロバイダーには OPENAI_API_KEY が必要です。")
        return self._settings.openai_api_key.get_secret_value()
