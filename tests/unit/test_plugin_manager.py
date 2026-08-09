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

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    def test_bfl_provider_prompt_suffix_defaults_to_empty(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(bfl_api_key="test-key"), {"image": "bfl"}, {})
        image_settings = {"scene_model": "flux-2-pro", "scene_size": "1920x1080"}

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(provider_class.call_args.kwargs["prompt_suffix"], "")

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    def test_bfl_provider_prompt_suffix_is_configurable(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(bfl_api_key="test-key"), {"image": "bfl"}, {})
        image_settings = {
            "scene_model": "flux-2-pro", "scene_size": "1920x1080",
            "bfl": {"prompt_suffix": "No watermark."},
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(provider_class.call_args.kwargs["prompt_suffix"], "No watermark.")

    @patch("youtube_generator.plugins.manager.OpenAIImageProvider")
    def test_openai_provider_prompt_suffix_defaults_to_empty(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(openai_api_key="test-key"), {"image": "openai"}, {})
        image_settings = {"openai_model": "gpt-image-2", "quality": "high", "scene_size": "1920x1080"}

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(provider_class.call_args.kwargs["prompt_suffix"], "")

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

    @patch("youtube_generator.plugins.manager.FluxSchnellLocalImageProvider")
    def test_flux_schnell_local_provider_created_for_scene(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {"image": "flux_schnell_local"}, {})
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "flux_schnell_local": {"model_id": "org/model", "seed": 7},
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        args = provider_class.call_args.args
        self.assertEqual(args[0].model_id, "org/model")
        self.assertEqual(args[0].seed, 7)
        self.assertEqual(args[1], "1920x1080")

    @patch("youtube_generator.plugins.manager.FluxSchnellLocalImageProvider")
    def test_dict_form_providers_image_splits_scene_and_thumbnail(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(bfl_api_key="test-key"),
            {"image": {"scene": "flux_schnell_local", "thumbnail": "bfl"}}, {},
        )
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "scene_model": "flux-2-pro", "thumbnail_model": "flux-2-pro",
            "flux_schnell_local": {},
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))
        self.assertEqual(provider_class.call_count, 1)

        thumbnail_provider = manager.create_image_provider(
            image_settings, RetryPolicy(max_attempts=1), size_setting="thumbnail_size",
        )
        from youtube_generator.plugins.image.bfl_image import BFLImageProvider
        self.assertIsInstance(thumbnail_provider, BFLImageProvider)

    def test_dict_form_missing_purpose_raises_error(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"image": {"scene": "openai"}}, {})

        with self.assertRaisesRegex(ValueError, "providers.image.thumbnail"):
            manager.create_image_provider({}, RetryPolicy(max_attempts=1), size_setting="thumbnail_size")

    def test_image_provider_name_resolves_per_purpose(self) -> None:
        manager = PluginManager(
            Settings(), {"image": {"scene": "flux_schnell_local", "thumbnail": "bfl"}}, {},
        )

        self.assertEqual(manager.image_provider_name("scene"), "flux_schnell_local")
        self.assertEqual(manager.image_provider_name("thumbnail"), "bfl")

    def test_image_provider_name_supports_legacy_string_form(self) -> None:
        manager = PluginManager(Settings(), {"image": "bfl"}, {})

        self.assertEqual(manager.image_provider_name("scene"), "bfl")
        self.assertEqual(manager.image_provider_name("thumbnail"), "bfl")

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    @patch("youtube_generator.plugins.manager.FluxSchnellLocalImageProvider")
    def test_fallback_provider_wraps_primary_with_bfl(self, flux_provider_class, bfl_provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(bfl_api_key="test-key"), {"image": "flux_schnell_local"}, {},
        )
        image_settings = {
            "scene_size": "1920x1080", "scene_model": "flux-2-pro",
            "flux_schnell_local": {"fallback_provider": "bfl"},
        }

        from youtube_generator.plugins.image.image_provider_fallback import FallbackImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, FallbackImageProvider)
        flux_provider_class.assert_called_once()
        bfl_provider_class.assert_called_once()

    def test_fallback_provider_rejects_flux_schnell_local_itself(self) -> None:
        manager = PluginManager(Settings(), {"image": "flux_schnell_local"}, {})
        image_settings = {
            "scene_size": "1920x1080",
            "flux_schnell_local": {"fallback_provider": "flux_schnell_local"},
        }

        with self.assertRaisesRegex(ValueError, "fallback_provider"):
            manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

    def test_flux_schnell_local_without_fallback_returns_primary_directly(self) -> None:
        manager = PluginManager(Settings(), {"image": "flux_schnell_local"}, {})
        image_settings = {"scene_size": "1920x1080", "flux_schnell_local": {}}

        from youtube_generator.plugins.image.flux_schnell_local_image import FluxSchnellLocalImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, FluxSchnellLocalImageProvider)

    @patch("youtube_generator.plugins.manager.QwenImageLocalImageProvider")
    def test_qwen_image_local_provider_created_for_scene(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {"image": "qwen_image_local"}, {})
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "qwen_image_local": {"model_id": "org/model", "seed": 7},
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        args = provider_class.call_args.args
        self.assertEqual(args[0].model_id, "org/model")
        self.assertEqual(args[0].seed, 7)
        self.assertEqual(args[1], "1920x1080")
        # シーン画像は動画レンダリング時にffmpegがscene_sizeへ引き伸ばすため、生成時点の
        # cover-cropは不要（resize_to_output_size=False）。
        self.assertFalse(provider_class.call_args.kwargs["resize_to_output_size"])

    @patch("youtube_generator.plugins.manager.QwenImageLocalImageProvider")
    def test_qwen_image_local_provider_created_for_thumbnail_keeps_resize(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        """サムネイルは動画レンダリング側でリサイズされないため、従来どおり
        thumbnail_sizeへ正確に整形する必要がある（resize_to_output_size=True）。"""
        manager = PluginManager(Settings(), {"image": "qwen_image_local"}, {})
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "qwen_image_local": {},
        }

        manager.create_image_provider(
            image_settings, RetryPolicy(max_attempts=1), size_setting="thumbnail_size",
        )

        self.assertTrue(provider_class.call_args.kwargs["resize_to_output_size"])

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    @patch("youtube_generator.plugins.manager.QwenImageLocalImageProvider")
    def test_fallback_provider_wraps_qwen_image_local_primary_with_bfl(self, qwen_provider_class, bfl_provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(bfl_api_key="test-key"), {"image": "qwen_image_local"}, {},
        )
        image_settings = {
            "scene_size": "1920x1080", "scene_model": "flux-2-pro",
            "qwen_image_local": {"fallback_provider": "bfl"},
        }

        from youtube_generator.plugins.image.image_provider_fallback import FallbackImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, FallbackImageProvider)
        qwen_provider_class.assert_called_once()
        bfl_provider_class.assert_called_once()

    def test_fallback_provider_rejects_qwen_image_local_itself(self) -> None:
        manager = PluginManager(Settings(), {"image": "qwen_image_local"}, {})
        image_settings = {
            "scene_size": "1920x1080",
            "qwen_image_local": {"fallback_provider": "qwen_image_local"},
        }

        with self.assertRaisesRegex(ValueError, "fallback_provider"):
            manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

    def test_qwen_image_local_without_fallback_returns_primary_directly(self) -> None:
        manager = PluginManager(Settings(), {"image": "qwen_image_local"}, {})
        image_settings = {"scene_size": "1920x1080", "qwen_image_local": {}}

        from youtube_generator.plugins.image.qwen_image_local import QwenImageLocalImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, QwenImageLocalImageProvider)

    @patch("youtube_generator.plugins.manager.QwenImageNunchakuLocalImageProvider")
    def test_qwen_image_nunchaku_local_provider_created_for_scene(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {"image": "qwen_image_nunchaku_local"}, {})
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "qwen_image_nunchaku_local": {"rank": 128, "seed": 7},
        }

        manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        args = provider_class.call_args.args
        self.assertEqual(args[0].rank, 128)
        self.assertEqual(args[0].seed, 7)
        self.assertEqual(args[1], "1920x1080")
        self.assertFalse(provider_class.call_args.kwargs["resize_to_output_size"])

    @patch("youtube_generator.plugins.manager.QwenImageNunchakuLocalImageProvider")
    def test_qwen_image_nunchaku_local_provider_created_for_thumbnail_keeps_resize(self, provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {"image": "qwen_image_nunchaku_local"}, {})
        image_settings = {
            "scene_size": "1920x1080", "thumbnail_size": "1280x720",
            "qwen_image_nunchaku_local": {},
        }

        manager.create_image_provider(
            image_settings, RetryPolicy(max_attempts=1), size_setting="thumbnail_size",
        )

        self.assertTrue(provider_class.call_args.kwargs["resize_to_output_size"])

    @patch("youtube_generator.plugins.manager.BFLImageProvider")
    @patch("youtube_generator.plugins.manager.QwenImageNunchakuLocalImageProvider")
    def test_fallback_provider_wraps_qwen_image_nunchaku_local_primary_with_bfl(self, nunchaku_provider_class, bfl_provider_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(bfl_api_key="test-key"), {"image": "qwen_image_nunchaku_local"}, {},
        )
        image_settings = {
            "scene_size": "1920x1080", "scene_model": "flux-2-pro",
            "qwen_image_nunchaku_local": {"fallback_provider": "bfl"},
        }

        from youtube_generator.plugins.image.image_provider_fallback import FallbackImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, FallbackImageProvider)
        nunchaku_provider_class.assert_called_once()
        bfl_provider_class.assert_called_once()

    def test_fallback_provider_rejects_qwen_image_nunchaku_local_itself(self) -> None:
        manager = PluginManager(Settings(), {"image": "qwen_image_nunchaku_local"}, {})
        image_settings = {
            "scene_size": "1920x1080",
            "qwen_image_nunchaku_local": {"fallback_provider": "qwen_image_nunchaku_local"},
        }

        with self.assertRaisesRegex(ValueError, "fallback_provider"):
            manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

    def test_qwen_image_nunchaku_local_without_fallback_returns_primary_directly(self) -> None:
        manager = PluginManager(Settings(), {"image": "qwen_image_nunchaku_local"}, {})
        image_settings = {"scene_size": "1920x1080", "qwen_image_nunchaku_local": {}}

        from youtube_generator.plugins.image.qwen_image_nunchaku_local import QwenImageNunchakuLocalImageProvider
        provider = manager.create_image_provider(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsInstance(provider, QwenImageNunchakuLocalImageProvider)

    def test_scene_visual_describer_disabled_by_default(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "openai"}, {})

        describer = manager.create_scene_visual_describer({}, RetryPolicy(max_attempts=1))

        self.assertIsNone(describer)

    def test_scene_visual_describer_disabled_when_flag_false(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "openai"}, {})
        image_settings = {"scene_description": {"enabled": False}}

        describer = manager.create_scene_visual_describer(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsNone(describer)

    @patch("youtube_generator.plugins.manager.OpenAISceneVisualDescriber")
    def test_scene_visual_describer_uses_explicit_model(self, describer_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(openai_api_key="test-key"), {"text": "openai"},
            {"scene_split_model": "gpt-5.6"},
        )
        image_settings = {"scene_description": {"enabled": True, "model": "gpt-5.6-mini"}}

        manager.create_scene_visual_describer(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(describer_class.call_args.args[1], "gpt-5.6-mini")

    @patch("youtube_generator.plugins.manager.OpenAISceneVisualDescriber")
    def test_scene_visual_describer_falls_back_to_scene_split_model(self, describer_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(
            Settings(openai_api_key="test-key"), {"text": "openai"},
            {"scene_split_model": "gpt-5.6"},
        )
        image_settings = {"scene_description": {"enabled": True, "model": None}}

        manager.create_scene_visual_describer(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(describer_class.call_args.args[1], "gpt-5.6")

    def test_scene_visual_describer_requires_model_when_no_fallback(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "openai"}, {})
        image_settings = {"scene_description": {"enabled": True}}

        with self.assertRaisesRegex(ValueError, "scene_description.model"):
            manager.create_scene_visual_describer(image_settings, RetryPolicy(max_attempts=1))

    def test_scene_visual_describer_rejects_non_openai_text_provider(self) -> None:
        manager = PluginManager(Settings(openai_api_key="test-key"), {"text": "unknown"}, {})
        image_settings = {"scene_description": {"enabled": True, "model": "gpt-5.6-mini"}}

        with self.assertRaisesRegex(ValueError, "providers.textがopenai"):
            manager.create_scene_visual_describer(image_settings, RetryPolicy(max_attempts=1))

    def test_image_editor_disabled_by_default(self) -> None:
        manager = PluginManager(Settings(), {}, {})

        editor = manager.create_image_editor({}, RetryPolicy(max_attempts=1))

        self.assertIsNone(editor)

    def test_image_editor_disabled_when_flag_false(self) -> None:
        manager = PluginManager(Settings(), {}, {})
        image_settings = {"scene_edit": {"enabled": False}}

        editor = manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        self.assertIsNone(editor)

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_force_bypasses_disabled_flag(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        """--edit-imagesで画像を個別指定した場合など、force=Trueならenabled=falseでも生成する。"""
        manager = PluginManager(Settings(), {}, {})
        image_settings = {"scene_edit": {"enabled": False}}

        editor = manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1), force=True)

        self.assertIsNotNone(editor)
        editor_class.assert_called_once()

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_creates_qwen_image_edit_nunchaku_local_when_enabled(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {"rank": 128},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        self.assertEqual(editor_class.call_args.args[0].rank, 128)

    def test_image_editor_rejects_unsupported_provider(self) -> None:
        manager = PluginManager(Settings(), {}, {})
        image_settings = {"scene_edit": {"enabled": True, "provider": "unknown"}}

        with self.assertRaisesRegex(ValueError, "未対応のscene_editプロバイダー"):
            manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_auto_detects_resolution_from_scene_generation_provider(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        """widthとheight未指定時、providers.image.sceneで選択中のプロバイダーの
        width/height設定から編集時の推論解像度を自動決定すること。"""
        manager = PluginManager(Settings(), {"image": {"scene": "qwen_image_nunchaku_local"}}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {"rank": 128},
            "qwen_image_nunchaku_local": {"width": 1664, "height": 928},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        settings = editor_class.call_args.args[0]
        self.assertEqual(settings.width, 1664)
        self.assertEqual(settings.height, 928)

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_auto_detects_resolution_from_qwen_image_local(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        """自動決定はnunchaku版に限らず、providers.image.sceneで選択中の任意のプロバイダー
        （ここではqwen_image_local）のwidth/heightを汎用的に参照すること。"""
        manager = PluginManager(Settings(), {"image": {"scene": "qwen_image_local"}}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {},
            "qwen_image_local": {"width": 1664, "height": 928},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        settings = editor_class.call_args.args[0]
        self.assertEqual(settings.width, 1664)
        self.assertEqual(settings.height, 928)

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_explicit_resolution_overrides_auto_detection(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        manager = PluginManager(Settings(), {"image": {"scene": "qwen_image_nunchaku_local"}}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {"width": 800, "height": 450},
            "qwen_image_nunchaku_local": {"width": 1664, "height": 928},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        settings = editor_class.call_args.args[0]
        self.assertEqual(settings.width, 800)
        self.assertEqual(settings.height, 450)

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_resolution_stays_none_when_scene_provider_has_no_width_height(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        """BFL/OpenAI等、width/heightという概念を持たないプロバイダーを選択している場合は
        自動決定されず、従来どおり編集対象画像自身の解像度で推論すること。"""
        manager = PluginManager(Settings(), {"image": {"scene": "bfl"}}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        settings = editor_class.call_args.args[0]
        self.assertIsNone(settings.width)
        self.assertIsNone(settings.height)

    @patch("youtube_generator.plugins.manager.QwenImageEditNunchakuLocalImageEditor")
    def test_image_editor_resolution_stays_none_when_scene_provider_unconfigured(self, editor_class) -> None:  # type: ignore[no-untyped-def]
        """providers.image.sceneが未設定の場合もエラーにせず、自動決定をスキップすること。"""
        manager = PluginManager(Settings(), {}, {})
        image_settings = {
            "scene_edit": {"enabled": True},
            "qwen_image_edit_nunchaku_local": {"rank": 128},
        }

        manager.create_image_editor(image_settings, RetryPolicy(max_attempts=1))

        settings = editor_class.call_args.args[0]
        self.assertIsNone(settings.width)
        self.assertIsNone(settings.height)
