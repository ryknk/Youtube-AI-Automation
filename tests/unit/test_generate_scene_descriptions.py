"""場面説明のみを独立して生成するユースケースのユニットテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_scene_descriptions import GenerateSceneDescriptionsUseCase


class FakeSceneVisualDescriber:
    def __init__(self, descriptions: tuple[str, ...] | None = None) -> None:
        self._descriptions = descriptions
        self.received: tuple[str, ...] | None = None
        self.call_count = 0

    def describe_scenes(self, narration_texts: tuple[str, ...]) -> tuple[str, ...]:
        self.call_count += 1
        self.received = narration_texts
        if self._descriptions is not None:
            return self._descriptions
        return tuple(f"description: {text}" for text in narration_texts)


class GenerateSceneDescriptionsUseCaseTests(unittest.TestCase):
    def test_execute_writes_one_description_file_per_image_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            describer = FakeSceneVisualDescriber(("A calm morning scene.", "A busy evening street."))
            use_case = GenerateSceneDescriptionsUseCase(
                describer, min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            description_files = use_case.execute(scenes_dir)

            self.assertEqual(
                [file.name for file in description_files],
                ["scene01_01.description.txt", "scene02_01.description.txt"],
            )
            self.assertEqual(describer.call_count, 1)
            self.assertEqual(
                (scenes_dir / "scene01_01.description.txt").read_text(encoding="utf-8"),
                "A calm morning scene.",
            )
            self.assertEqual(
                (scenes_dir / "scene02_01.description.txt").read_text(encoding="utf-8"),
                "A busy evening street.",
            )

    def test_execute_skips_already_generated_descriptions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.description.txt").write_text("既存の場面説明", encoding="utf-8")
            describer = FakeSceneVisualDescriber()
            use_case = GenerateSceneDescriptionsUseCase(
                describer, min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            use_case.execute(scenes_dir)

            self.assertEqual(describer.received, ("2番目の場面",))
            self.assertEqual(
                (scenes_dir / "scene01_01.description.txt").read_text(encoding="utf-8"), "既存の場面説明",
            )

    def test_execute_with_force_regenerates_already_generated_descriptions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.description.txt").write_text("古い場面説明", encoding="utf-8")
            describer = FakeSceneVisualDescriber(("新しい場面説明",))
            use_case = GenerateSceneDescriptionsUseCase(
                describer, min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            use_case.execute(scenes_dir, force=True)

            self.assertEqual(describer.call_count, 1)
            self.assertEqual(
                (scenes_dir / "scene01_01.description.txt").read_text(encoding="utf-8"), "新しい場面説明",
            )

    def test_execute_without_describer_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            use_case = GenerateSceneDescriptionsUseCase(
                None, min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            result = use_case.execute(scenes_dir)

            self.assertEqual(result, ())
            self.assertFalse((scenes_dir / "scene01_01.description.txt").exists())

    def test_execute_logs_skip_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.description.txt").write_text("既存の場面説明", encoding="utf-8")
            use_case = GenerateSceneDescriptionsUseCase(
                FakeSceneVisualDescriber(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            with self.assertLogs("youtube_generator.app.generate_scene_descriptions", level="INFO") as logs:
                use_case.execute(scenes_dir)

            messages = [record.getMessage() for record in logs.records]
            self.assertIn("生成済みの場面説明 1/2 件をスキップします。", messages)

    def test_execute_mismatched_count_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            describer = FakeSceneVisualDescriber(("説明が1件だけ",))
            use_case = GenerateSceneDescriptionsUseCase(
                describer, min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            with self.assertRaises(ValueError):
                use_case.execute(scenes_dir)


if __name__ == "__main__":
    unittest.main()
