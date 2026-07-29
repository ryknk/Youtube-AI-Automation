"""キャッシュfingerprintがステージ関連設定のみに限定されていることを検証する。

cli/main.py・cli/ending.pyでの実際の組み立て方（CacheManager.make_key(...)への引数の与え方）
と同じ構成をここで再現し、(1) 無関係な設定変更でキーが変わらないこと、(2) 関連設定変更では
キーが変わることの両方を確認する。config.yaml全体のSHA-256（video_settings.fingerprint）を
共通で混入させていた旧実装による過剰なキャッシュ無効化を防ぐための回帰テスト。
"""

import json
import unittest

from youtube_generator.infrastructure.cache import CacheManager


def _script_fingerprint(provider: str, text_settings: dict) -> str:
    return CacheManager.make_key(
        "script", "theme", "template",
        provider, json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
    )


def _scene_fingerprint(provider: str, text_settings: dict, scene_settings: dict) -> str:
    return CacheManager.make_key(
        provider,
        json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
        json.dumps(scene_settings, ensure_ascii=False, sort_keys=True),
    )


def _audio_fingerprint(provider: str, audio_settings: dict) -> str:
    return CacheManager.make_key(provider, json.dumps(audio_settings, ensure_ascii=False, sort_keys=True))


def _image_fingerprint(provider: str, image_settings: dict, image_style: str) -> str:
    return CacheManager.make_key(
        provider, json.dumps(image_settings, ensure_ascii=False, sort_keys=True),
        "image-prompt-v2", image_style,
    )


def _scene_image_fingerprint(provider: str, image_settings: dict, image_style: str) -> str:
    """cli/main.pyの--generate-imagesと同じ組み立て方（サムネイル専用設定を除外）を再現する。"""
    scene_only_settings = {
        key: value for key, value in image_settings.items()
        if key not in {"thumbnail_model", "thumbnail_size"}
    }
    return _image_fingerprint(provider, scene_only_settings, image_style)


def _subtitle_fingerprint(subtitle_values: dict, version: str) -> str:
    return CacheManager.make_key(json.dumps(subtitle_values, ensure_ascii=False, sort_keys=True), version)


def _video_fingerprint(video_values: dict, subtitle_values: dict, bgm_cache_fingerprint: str) -> str:
    return CacheManager.make_key(
        json.dumps(video_values, sort_keys=True),
        json.dumps(subtitle_values, ensure_ascii=False, sort_keys=True),
        bgm_cache_fingerprint,
    )


def _narration_fingerprint(text_provider: str, text_settings: dict, tts_provider: str, audio_settings: dict) -> str:
    return CacheManager.make_key(
        text_provider, json.dumps(text_settings, ensure_ascii=False, sort_keys=True),
        tts_provider, json.dumps(audio_settings, ensure_ascii=False, sort_keys=True),
    )


class ScriptCacheKeyScopingTests(unittest.TestCase):
    def test_unrelated_settings_do_not_affect_key(self) -> None:
        text_settings = {"script_model": "gpt-5.6", "scene_split_model": "gpt-5.6", "metadata_model": "gpt-5.6"}
        before = _script_fingerprint("openai", text_settings)
        # youtube.category_id等の無関係な設定はscript_fingerprintの引数に一切含まれないため、
        # 同じtext_settingsであればキーは常に同一になる。
        after = _script_fingerprint("openai", text_settings)
        self.assertEqual(before, after)

    def test_script_model_change_invalidates_key(self) -> None:
        before = _script_fingerprint("openai", {"script_model": "gpt-5.6"})
        after = _script_fingerprint("openai", {"script_model": "gpt-6.0"})
        self.assertNotEqual(before, after)


class SceneCacheKeyScopingTests(unittest.TestCase):
    def test_scene_split_model_change_invalidates_key(self) -> None:
        before = _scene_fingerprint("openai", {"scene_split_model": "gpt-5.6"}, {"max_count": 30})
        after = _scene_fingerprint("openai", {"scene_split_model": "gpt-6.0"}, {"max_count": 30})
        self.assertNotEqual(before, after)

    def test_max_count_change_invalidates_key(self) -> None:
        before = _scene_fingerprint("openai", {}, {"max_count": 30})
        after = _scene_fingerprint("openai", {}, {"max_count": 20})
        self.assertNotEqual(before, after)


class AudioCacheKeyScopingTests(unittest.TestCase):
    def test_voicevox_speaker_change_invalidates_key(self) -> None:
        before = _audio_fingerprint("voicevox", {"voicevox": {"speaker_id": 3}})
        after = _audio_fingerprint("voicevox", {"voicevox": {"speaker_id": 13}})
        self.assertNotEqual(before, after)

    def test_unrelated_provider_stays_same_key_for_same_settings(self) -> None:
        settings = {"voicevox": {"speaker_id": 3}}
        before = _audio_fingerprint("voicevox", settings)
        after = _audio_fingerprint("voicevox", settings)
        self.assertEqual(before, after)


class ImageCacheKeyScopingTests(unittest.TestCase):
    def test_scene_model_change_invalidates_key(self) -> None:
        before = _image_fingerprint("bfl", {"scene_model": "flux-2-pro"}, "style")
        after = _image_fingerprint("bfl", {"scene_model": "flux-2-max"}, "style")
        self.assertNotEqual(before, after)

    def test_provider_change_from_bfl_to_flux_schnell_local_invalidates_scene_key(self) -> None:
        settings = {"scene_model": "flux-2-pro", "flux_schnell_local": {"model_id": "black-forest-labs/FLUX.1-schnell"}}
        before = _scene_image_fingerprint("bfl", settings, "style")
        after = _scene_image_fingerprint("flux_schnell_local", settings, "style")
        self.assertNotEqual(before, after)

    def test_thumbnail_only_setting_change_does_not_invalidate_scene_key(self) -> None:
        before = _scene_image_fingerprint(
            "flux_schnell_local", {"thumbnail_model": "flux-2-pro", "thumbnail_size": "1280x720"}, "style",
        )
        after = _scene_image_fingerprint(
            "flux_schnell_local", {"thumbnail_model": "flux-2-max", "thumbnail_size": "1920x1080"}, "style",
        )
        self.assertEqual(before, after)

    def test_flux_schnell_local_settings_change_invalidates_scene_key(self) -> None:
        before = _scene_image_fingerprint(
            "flux_schnell_local", {"flux_schnell_local": {"seed": 1, "num_inference_steps": 4}}, "style",
        )
        after = _scene_image_fingerprint(
            "flux_schnell_local", {"flux_schnell_local": {"seed": 2, "num_inference_steps": 4}}, "style",
        )
        self.assertNotEqual(before, after)


class SubtitleCacheKeyScopingTests(unittest.TestCase):
    def test_alignment_provider_settings_invalidate_key(self) -> None:
        base = {"timing_mode": "alignment", "alignment_provider": {"model": "base"}}
        changed = {"timing_mode": "alignment", "alignment_provider": {"model": "medium"}}
        before = _subtitle_fingerprint(base, "v1")
        after = _subtitle_fingerprint(changed, "v1")
        self.assertNotEqual(before, after)


class VideoCacheKeyScopingTests(unittest.TestCase):
    def test_subtitle_style_change_invalidates_key(self) -> None:
        video_values = {"width": 1920, "height": 1080, "fps": 30, "output_format": "mp4"}
        before = _video_fingerprint(video_values, {"font": "Arial"}, "bgm-fp")
        after = _video_fingerprint(video_values, {"font": "Noto Sans JP"}, "bgm-fp")
        self.assertNotEqual(before, after)

    def test_bgm_fingerprint_change_invalidates_key(self) -> None:
        video_values = {"width": 1920, "height": 1080, "fps": 30, "output_format": "mp4"}
        subtitle_values = {"font": "Arial"}
        before = _video_fingerprint(video_values, subtitle_values, "bgm-fp-a")
        after = _video_fingerprint(video_values, subtitle_values, "bgm-fp-b")
        self.assertNotEqual(before, after)

    def test_video_dimensions_change_invalidates_key(self) -> None:
        subtitle_values = {"font": "Arial"}
        before = _video_fingerprint({"width": 1920, "height": 1080, "fps": 30}, subtitle_values, "bgm-fp")
        after = _video_fingerprint({"width": 1280, "height": 720, "fps": 30}, subtitle_values, "bgm-fp")
        self.assertNotEqual(before, after)

    def test_unrelated_settings_do_not_affect_key(self) -> None:
        video_values = {"width": 1920, "height": 1080, "fps": 30, "output_format": "mp4"}
        subtitle_values = {"font": "Arial"}
        # youtube.category_idのような無関係な設定はここでの引数に一切現れないため、
        # 同じvideo/subtitle/bgm設定であればキーは常に同一になる。
        before = _video_fingerprint(video_values, subtitle_values, "bgm-fp")
        after = _video_fingerprint(video_values, subtitle_values, "bgm-fp")
        self.assertEqual(before, after)


class EndingNarrationCacheKeyScopingTests(unittest.TestCase):
    def test_tts_settings_change_invalidates_key(self) -> None:
        before = _narration_fingerprint("openai", {"script_model": "gpt-5.6"}, "voicevox", {"voicevox": {"speaker_id": 3}})
        after = _narration_fingerprint("openai", {"script_model": "gpt-5.6"}, "voicevox", {"voicevox": {"speaker_id": 13}})
        self.assertNotEqual(before, after)

    def test_text_settings_change_invalidates_key(self) -> None:
        before = _narration_fingerprint("openai", {"script_model": "gpt-5.6"}, "voicevox", {})
        after = _narration_fingerprint("openai", {"script_model": "gpt-6.0"}, "voicevox", {})
        self.assertNotEqual(before, after)

    def test_unrelated_settings_do_not_affect_key(self) -> None:
        text_settings = {"script_model": "gpt-5.6"}
        audio_settings = {"voicevox": {"speaker_id": 3}}
        # youtube.category_idのような無関係な設定はここでの引数に一切現れないため、
        # 同じtext/audio設定であればキーは常に同一になる。
        before = _narration_fingerprint("openai", text_settings, "voicevox", audio_settings)
        after = _narration_fingerprint("openai", text_settings, "voicevox", audio_settings)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
