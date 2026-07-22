"""プラグイン生成時の画像サイズ設定を検証する。"""

import unittest
from unittest.mock import patch

from youtube_generator.config import Settings
from youtube_generator.plugins.manager import PluginManager
from youtube_generator.services.retry import RetryPolicy


class PluginManagerTests(unittest.TestCase):
    @patch("youtube_generator.plugins.manager.OpenAIImageProvider")
    def test_image_provider_uses_requested_size_setting(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(openai_api_key="test-key"), {"image": "openai"},
            {"script_model": "gpt-5.6", "scene_split_model": "gpt-5.6", "metadata_model": "gpt-5.6"},
        )
        image_settings = {
            "openai_model": "gpt-image-2", "quality": "high",
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "scene_model": "flux-2-pro", "thumbnail_model": "flux-2-max",
        }

        manager.create_image_provider(
            image_settings, RetryPolicy(max_attempts=1), size_setting="thumbnail_size"
        )

        self.assertEqual(provider_class.call_args.args[2], "1280x720")

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    def test_bfl_provider_uses_model_for_image_purpose(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(bfl_api_key="test-key"), {"image": "bfl"},
            {"script_model": "gpt-5.6", "scene_split_model": "gpt-5.6", "metadata_model": "gpt-5.6"},
        )
        image_settings = {
            "openai_model": "gpt-image-2", "quality": "high",
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "scene_model": "flux-2-pro", "thumbnail_model": "flux-2-max",
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))
        self.assertEqual(provider_class.call_args.args[1:3], ("flux-2-pro", "1920x1080"))

        manager.create_image_provider(
            image_settings, RetryPolicy(max_attempts=1), size_setting="thumbnail_size"
        )
        self.assertEqual(provider_class.call_args.args[1:3], ("flux-2-max", "1280x720"))

    def test_create_text_generator_rejects_unsupported_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "unknown"}, {})

        with self.assertRaisesRegex(ValueError, "未対応のtextプロバイダー"):
            manager.create_text_generator(RetryPolicy(max_attempts=1))

    def test_create_scene_splitter_rejects_unsupported_text_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "unknown"}, {})

        with self.assertRaisesRegex(ValueError, "未対応のtextプロバイダー"):
            manager.create_scene_splitter(RetryPolicy(max_attempts=1))

    def test_create_scene_splitter_rejects_text_provider_without_scene_split_support(self) -> None:
        """openai以外のTextGeneratorが将来追加された場合に備えた分岐（現状は到達不能）を検証する。"""
        manager = PluginManager(
            Settings(openai_api_key="test-key"), {"text": "openai"},
            {"script_model": "gpt-5.6", "scene_split_model": "gpt-5.6", "metadata_model": "gpt-5.6"},
        )

        with patch.object(manager, "create_text_generator", return_value=object()):
            with self.assertRaisesRegex(ValueError, "シーン分割"):
                manager.create_scene_splitter(RetryPolicy(max_attempts=1))

    def test_create_tts_provider_rejects_unsupported_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"tts": "unknown"}, {})

        with self.assertRaisesRegex(ValueError, "未対応のttsプロバイダー"):
            manager.create_tts_provider({}, RetryPolicy(max_attempts=1))

    def test_create_image_provider_rejects_unsupported_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"image": "unknown"}, {})

        with self.assertRaisesRegex(ValueError, "未対応のimageプロバイダー"):
            manager.create_image_provider({}, RetryPolicy(max_attempts=1))

    def test_create_metadata_generator_rejects_unsupported_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "unknown"}, {})

        with self.assertRaisesRegex(ValueError, "未対応のtextプロバイダー"):
            manager.create_metadata_generator(RetryPolicy(max_attempts=1), title_count=5)

    def test_provider_name_rejects_empty_string(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"tts": ""}, {})

        with self.assertRaisesRegex(ValueError, "providers.tts"):
            manager.create_tts_provider({}, RetryPolicy(max_attempts=1))

    def test_provider_name_requires_category_present(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {}, {})

        with self.assertRaisesRegex(ValueError, "providers.image"):
            manager.create_image_provider({}, RetryPolicy(max_attempts=1))
