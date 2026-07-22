"""アライメント結果のキャッシュキー構築に関するテスト（cli/main.pyと同じ組み立て方を検証）。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.infrastructure.cache import CacheManager


def _alignment_fingerprint(provider: str, model: str, language: str) -> str:
    return CacheManager.make_key(provider, model, language)


class AlignmentCacheKeyTests(unittest.TestCase):
    def test_key_changes_when_provider_settings_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio = Path(temporary_directory) / "scene01.mp3"
            audio.write_bytes(b"audio")
            text = Path(temporary_directory) / "scene01.txt"
            text.write_text("台本", encoding="utf-8")

            base_key = CacheManager.make_file_key(
                "alignment", (audio, text), _alignment_fingerprint("stable_ts", "base", "ja"),
            )
            model_changed_key = CacheManager.make_file_key(
                "alignment", (audio, text), _alignment_fingerprint("stable_ts", "medium", "ja"),
            )
            language_changed_key = CacheManager.make_file_key(
                "alignment", (audio, text), _alignment_fingerprint("stable_ts", "base", "en"),
            )

            self.assertNotEqual(base_key, model_changed_key)
            self.assertNotEqual(base_key, language_changed_key)

    def test_key_changes_when_audio_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio = Path(temporary_directory) / "scene01.mp3"
            audio.write_bytes(b"audio-v1")
            text = Path(temporary_directory) / "scene01.txt"
            text.write_text("台本", encoding="utf-8")
            fingerprint = _alignment_fingerprint("stable_ts", "base", "ja")

            first_key = CacheManager.make_file_key("alignment", (audio, text), fingerprint)
            audio.write_bytes(b"audio-v2-re-synthesized")
            second_key = CacheManager.make_file_key("alignment", (audio, text), fingerprint)

            self.assertNotEqual(first_key, second_key)

    def test_key_is_stable_for_unchanged_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio = Path(temporary_directory) / "scene01.mp3"
            audio.write_bytes(b"audio")
            text = Path(temporary_directory) / "scene01.txt"
            text.write_text("台本", encoding="utf-8")
            fingerprint = _alignment_fingerprint("stable_ts", "base", "ja")

            first_key = CacheManager.make_file_key("alignment", (audio, text), fingerprint)
            second_key = CacheManager.make_file_key("alignment", (audio, text), fingerprint)

            self.assertEqual(first_key, second_key)


if __name__ == "__main__":
    unittest.main()
