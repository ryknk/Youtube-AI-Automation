"""stable-tsアライメントプラグインのユニットテスト（stable-ts本体はモック）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_generator.exceptions import AlignmentGenerationError
from youtube_generator.plugins.alignment.stable_ts_alignment import StableTSAlignmentProvider


class FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end


class FakeSegment:
    def __init__(self, text: str, start: float, end: float, words: list[FakeWord] | None = None) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.words = words


class FakeResult:
    def __init__(self, segments: list[FakeSegment]) -> None:
        self.segments = segments


class FakeModel:
    """stable_whisperのモデルの``align()``だけを模したフェイク。"""

    def __init__(self, result: FakeResult) -> None:
        self._result = result
        self.calls: list[tuple[str, str, str]] = []

    def align(self, audio_path: str, text: str, language: str) -> FakeResult:
        self.calls.append((audio_path, text, language))
        return self._result


class RaisingModel:
    def align(self, audio_path: str, text: str, language: str) -> FakeResult:
        raise RuntimeError("モデル内部エラー")


class StableTSAlignmentProviderTests(unittest.TestCase):
    def test_align_writes_word_level_units_json(self) -> None:
        provider = StableTSAlignmentProvider(model="base", language="ja")
        fake_model = FakeModel(FakeResult([
            FakeSegment("こんにちは 世界", 0.0, 1.0, words=[
                FakeWord("こんにちは", 0.0, 0.6), FakeWord("世界", 0.6, 1.0),
            ]),
        ]))
        provider._loaded_model = fake_model  # noqa: SLF001 - テスト用にキャッシュへ直接注入

        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            audio_file = tmp_path / "scene01.mp3"
            audio_file.write_bytes(b"fake-audio")
            output_file = tmp_path / "scene01.alignment.json"

            provider.align(audio_file, "こんにちは 世界", output_file)

            payload = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["provider"], "stable_ts")
            self.assertEqual(payload["text"], "こんにちは 世界")
            self.assertEqual(payload["units"], [
                {"text": "こんにちは", "start": 0.0, "end": 0.6},
                {"text": "世界", "start": 0.6, "end": 1.0},
            ])
            self.assertEqual(fake_model.calls, [(str(audio_file), "こんにちは 世界", "ja")])

    def test_align_falls_back_to_segment_level_units_when_words_missing(self) -> None:
        provider = StableTSAlignmentProvider(model="base", language="ja")
        provider._loaded_model = FakeModel(FakeResult([  # noqa: SLF001
            FakeSegment("台本全文", 0.0, 2.0, words=None),
        ]))

        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            audio_file = tmp_path / "scene01.mp3"
            audio_file.write_bytes(b"fake-audio")
            output_file = tmp_path / "scene01.alignment.json"

            provider.align(audio_file, "台本全文", output_file)

            payload = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["units"], [{"text": "台本全文", "start": 0.0, "end": 2.0}])

    def test_align_wraps_model_failure_as_alignment_generation_error(self) -> None:
        provider = StableTSAlignmentProvider(model="base", language="ja")
        provider._loaded_model = RaisingModel()  # noqa: SLF001

        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            audio_file = tmp_path / "scene01.mp3"
            audio_file.write_bytes(b"fake-audio")

            with self.assertRaises(AlignmentGenerationError):
                provider.align(audio_file, "テスト", tmp_path / "scene01.alignment.json")

    def test_load_model_raises_when_stable_ts_not_installed(self) -> None:
        provider = StableTSAlignmentProvider(model="base", language="ja")
        with patch.dict(sys.modules, {"stable_whisper": None}):
            with self.assertRaises(AlignmentGenerationError):
                provider._load_model()  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
