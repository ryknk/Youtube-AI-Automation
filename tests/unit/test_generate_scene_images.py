"""シーン画像生成ユースケースのユニットテスト。"""

import base64
import tempfile
import unittest
from pathlib import Path

from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.infrastructure.openai_image_generator import OpenAIImageGenerator
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.retry import RetryPolicy


class MockImageProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.release_calls = 0

    def generate_image(self, prompt: str, output_file: Path) -> None:
        self.prompts.append(prompt)
        output_file.write_bytes(b"fake-png")

    def release(self) -> None:
        self.release_calls += 1


class FakeImageData:
    b64_json = base64.b64encode(b"fake-png").decode("ascii")


class FakeImageResult:
    data = [FakeImageData()]


class FakeImagesResource:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    def generate(self, **kwargs: object) -> FakeImageResult:
        self.request = kwargs
        return FakeImageResult()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.images = FakeImagesResource()


class FakeImageEditor:
    def __init__(self) -> None:
        self.edited_files: list[Path] = []

    def edit(self, image_file: Path) -> None:
        self.edited_files.append(image_file)
        image_file.write_bytes(b"edited-png")


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


class GenerateSceneImagesUseCaseTests(unittest.TestCase):
    def test_execute_generates_png_for_all_scene_files_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene02_01.png"])
            self.assertEqual(len(generator.prompts), 2)
            self.assertIn("1番目の場面", generator.prompts[0])
            self.assertIn("clean 2D digital illustration", generator.prompts[0])
            self.assertNotIn("realistic photography", generator.prompts[0])

    def test_execute_saves_prompt_file_next_to_each_generated_image(self) -> None:
        """組み立てた画像プロンプトを、画像と同じフォルダ（scenes_dir、ジョブ実行時は.work）へ
        sceneNN_MM.prompt.txtとして保存し、後から生成内容を確認できるようにする。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            prompt_file = GenerateSceneImagesUseCase.prompt_file_for(image_files[0])
            self.assertEqual(prompt_file, scenes_dir / "scene01_01.prompt.txt")
            self.assertTrue(prompt_file.is_file())
            self.assertEqual(prompt_file.read_text(encoding="utf-8"), generator.prompts[0])

    def test_execute_does_not_rewrite_prompt_file_for_already_generated_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.png").write_bytes(b"already-generated")
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            use_case.execute(scenes_dir)

            self.assertFalse((scenes_dir / "scene01_01.prompt.txt").exists())

    def test_execute_logs_progress_against_total_image_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            with self.assertLogs("youtube_generator.app.generate_scene_images", level="INFO") as logs:
                use_case.execute(scenes_dir)

            messages = [record.getMessage() for record in logs.records]
            self.assertIn("画像生成: (1/2)", messages)
            self.assertIn("画像生成: (2/2)", messages)

    def test_long_scene_generates_multiple_images_split_by_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            # characters_per_second=6.0のため、60文字は推定10秒。文単位に区切りつつ
            # min=5/max=10秒の範囲へグルーピングされ、複数枚に分割されることを確認する。
            long_text = "あ" * 30 + "。" + "い" * 30 + "。"
            (scenes_dir / "scene01.txt").write_text(long_text, encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=3.0, max_display_seconds=5.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene01_02.png"])
            self.assertEqual(len(generator.prompts), 2)

    def test_invalid_display_seconds_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), MockImageProvider(),
                min_display_seconds=10.0, max_display_seconds=5.0, characters_per_second=6.0,
            )

    def test_image_editor_runs_after_each_generated_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            editor = FakeImageEditor()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                image_editor=editor,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual(editor.edited_files, list(image_files))
            for image_file in image_files:
                self.assertEqual(image_file.read_bytes(), b"edited-png")

    def test_image_editor_runs_only_after_generator_is_released(self) -> None:
        """生成モデルと編集モデルを同時にVRAMへ乗せないよう、全画像生成→解放→全画像編集の
        順で実行されることを確認する（1枚ごとの交互ロードはVRAM不足を招くため禁止）。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            events: list[str] = []

            class TrackingImageProvider(MockImageProvider):
                def generate_image(self, prompt: str, output_file: Path) -> None:
                    events.append(f"generate:{output_file.name}")
                    super().generate_image(prompt, output_file)

                def release(self) -> None:
                    events.append("release")
                    super().release()

            class TrackingImageEditor(FakeImageEditor):
                def edit(self, image_file: Path) -> None:
                    events.append(f"edit:{image_file.name}")
                    super().edit(image_file)

            generator = TrackingImageProvider()
            editor = TrackingImageEditor()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                image_editor=editor,
            )

            use_case.execute(scenes_dir)

            self.assertEqual(
                events,
                [
                    "generate:scene01_01.png", "generate:scene02_01.png", "release",
                    "edit:scene01_01.png", "edit:scene02_01.png",
                ],
            )
            self.assertEqual(generator.release_calls, 1)

    def test_execute_skips_already_generated_images(self) -> None:
        """中断されたジョブの再試行等で一部の画像が既に生成済みの場合、再生成しない。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.png").write_bytes(b"already-generated")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene02_01.png"])
            self.assertEqual(len(generator.prompts), 1)
            self.assertIn("2番目の場面", generator.prompts[0])
            self.assertEqual((scenes_dir / "scene01_01.png").read_bytes(), b"already-generated")

    def test_execute_logs_skip_count_for_already_generated_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.png").write_bytes(b"already-generated")
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            with self.assertLogs("youtube_generator.app.generate_scene_images", level="INFO") as logs:
                use_case.execute(scenes_dir)

            messages = [record.getMessage() for record in logs.records]
            self.assertIn("生成済みの画像 1/2 件をスキップします。", messages)
            self.assertIn("画像生成: (2/2)", messages)

    def test_execute_with_force_regenerates_already_generated_images(self) -> None:
        """--forceオプション指定時は既存ファイルの有無を無視し、常に全件生成し直す。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.png").write_bytes(b"already-generated")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir, force=True)

            self.assertEqual([file.name for file in image_files], ["scene01_01.png", "scene02_01.png"])
            self.assertEqual(len(generator.prompts), 2)
            self.assertEqual((scenes_dir / "scene01_01.png").read_bytes(), b"fake-png")

    def test_execute_does_not_call_scene_visual_describer_for_already_generated_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.png").write_bytes(b"already-generated")
            describer = FakeSceneVisualDescriber()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                scene_visual_describer=describer,
            )

            use_case.execute(scenes_dir)

            self.assertEqual(describer.received, ("2番目の場面",))

    def test_without_image_editor_generated_image_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            image_files = use_case.execute(scenes_dir)

            self.assertEqual(image_files[0].read_bytes(), b"fake-png")

    def test_scene_visual_describer_replaces_narration_text_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            describer = FakeSceneVisualDescriber(("A calm morning scene.", "A busy evening street."))
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                scene_visual_describer=describer,
            )

            use_case.execute(scenes_dir)

            # シーン数分ではなく、1動画につき1回だけまとめて呼び出すこと（API課金削減のため）。
            self.assertEqual(describer.call_count, 1)
            self.assertEqual(describer.received, ("1番目の場面", "2番目の場面"))
            self.assertIn("A calm morning scene.", generator.prompts[0])
            self.assertNotIn("1番目の場面", generator.prompts[0])
            self.assertIn("A busy evening street.", generator.prompts[1])
            self.assertNotIn("2番目の場面", generator.prompts[1])

    def test_scene_visual_describer_mismatched_count_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            describer = FakeSceneVisualDescriber(("説明が1件だけ",))
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                scene_visual_describer=describer,
            )

            with self.assertRaises(ValueError):
                use_case.execute(scenes_dir)

    def test_precomputed_description_files_are_used_without_calling_describer(self) -> None:
        """--generate-scene-descriptionsが書き出したsceneNN_MM.description.txtが揃っていれば、
        --generate-images側はOpenAI APIを呼ばずにそれを使う。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.description.txt").write_text("A calm morning scene.", encoding="utf-8")
            (scenes_dir / "scene02_01.description.txt").write_text("A busy evening street.", encoding="utf-8")
            generator = MockImageProvider()
            describer = FakeSceneVisualDescriber()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                scene_visual_describer=describer,
            )

            use_case.execute(scenes_dir)

            self.assertEqual(describer.call_count, 0)
            self.assertIn("A calm morning scene.", generator.prompts[0])
            self.assertIn("A busy evening street.", generator.prompts[1])

    def test_partial_precomputed_description_files_fall_back_to_describer(self) -> None:
        """一部の場面説明ファイルしか無い場合は、まとめて1回で呼び出す方針を崩さないよう
        フォールバックしてdescriber側でまとめて生成する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            (scenes_dir / "scene02.txt").write_text("2番目の場面", encoding="utf-8")
            (scenes_dir / "scene01_01.description.txt").write_text("A calm morning scene.", encoding="utf-8")
            describer = FakeSceneVisualDescriber()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("style"), MockImageProvider(),
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
                scene_visual_describer=describer,
            )

            use_case.execute(scenes_dir)

            self.assertEqual(describer.call_count, 1)
            self.assertEqual(describer.received, ("1番目の場面", "2番目の場面"))

    def test_without_scene_visual_describer_uses_narration_text_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenes_dir = Path(temporary_directory)
            (scenes_dir / "scene01.txt").write_text("1番目の場面", encoding="utf-8")
            generator = MockImageProvider()
            use_case = GenerateSceneImagesUseCase(
                ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), generator,
                min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
            )

            use_case.execute(scenes_dir)

            self.assertIn("1番目の場面", generator.prompts[0])

    def test_openai_image_generator_requests_high_quality_landscape_png(self) -> None:
        client = FakeOpenAIClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "scene01.png"
            generator = OpenAIImageGenerator(
                api_key="test-key",
                model="gpt-image-2",
                size="2048x1152",
                quality="high",
                retry_policy=RetryPolicy(max_attempts=1),
                client=client,  # type: ignore[arg-type]
            )

            generator.generate("realistic scene", output_file)

            self.assertEqual(output_file.read_bytes(), b"fake-png")
            self.assertEqual(client.images.request["size"], "2048x1152")
            self.assertEqual(client.images.request["quality"], "high")
            self.assertEqual(client.images.request["prompt"], "realistic scene")

    def test_openai_image_generator_prompt_suffix_is_appended_when_configured(self) -> None:
        client = FakeOpenAIClient()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = Path(temporary_directory) / "scene01.png"
            generator = OpenAIImageGenerator(
                api_key="test-key",
                model="gpt-image-2",
                size="2048x1152",
                quality="high",
                retry_policy=RetryPolicy(max_attempts=1),
                client=client,  # type: ignore[arg-type]
                prompt_suffix="No text.",
            )

            generator.generate("realistic scene", output_file)

            self.assertEqual(client.images.request["prompt"], "realistic scene, No text.")
