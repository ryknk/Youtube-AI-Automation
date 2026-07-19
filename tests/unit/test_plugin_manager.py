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
