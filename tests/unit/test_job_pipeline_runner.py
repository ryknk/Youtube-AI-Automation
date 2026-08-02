"""ExistingPipelineRunnerの単体テスト（main.pyのサブプロセス呼び出しはモック化）。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_generator.app.generate_script import GenerateScriptUseCase
from youtube_generator.config import Settings
from youtube_generator.jobs.manager import Job, JobStage, JobStatus
from youtube_generator.jobs.pipeline import ExistingPipelineRunner
from youtube_generator.services.template_service import TemplateManager


def _write_template(root: Path, template_id: str, display_name: str) -> None:
    template_dir = root / template_id
    template_dir.mkdir(parents=True)
    for name in ("prompt.txt", "image_prompt.txt", "title_prompt.txt", "thumbnail_prompt.txt"):
        (template_dir / name).write_text("テスト", encoding="utf-8")
    (template_dir / "video.yaml").write_text(
        f"display_name: {display_name}\nscene_structure: [導入]\n", encoding="utf-8",
    )


def _make_job(job_id: str, theme: str, template: str, output_dir: Path) -> Job:
    # JobManager.addが実行時に作成する成果物フォルダを模す。
    output_dir.mkdir(parents=True, exist_ok=True)
    return Job(
        job_id=job_id, theme=theme, template=template, created_at="2026-01-01T00:00:00+00:00",
        started_at=None, finished_at=None, status=JobStatus.RUNNING, stage=None,
        output_dir=output_dir, error_message=None, retry_count=0,
    )


class ExistingPipelineRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        tmp_path = Path(self._temporary_directory.name)
        self.settings = Settings(output_dir=tmp_path / "output", templates_dir=tmp_path / "templates")
        _write_template(self.settings.templates_dir, "default", "汎用")
        self.calls: list[tuple[str, ...]] = []
        self.job = _make_job("job-1", "宇宙の不思議", "default", tmp_path / "jobs" / "job-1")

    def _fake_run(self, *arguments: str, on_line=None) -> None:
        self.calls.append(arguments)
        command = arguments[0]
        if command == "--theme":
            theme, template_id, run_id = arguments[1], arguments[3], arguments[5]
            template = TemplateManager(self.settings.templates_dir).get(template_id)
            script_dir = GenerateScriptUseCase.output_directory(self.settings.output_dir, theme, template, run_id)
            script_dir.mkdir(parents=True, exist_ok=True)
            (script_dir / "script.txt").write_text("本物の台本", encoding="utf-8")
        elif command == "--split-script":
            work_dir = Path(arguments[1]).parent
            (work_dir / "scene01.txt").write_text("シーン1", encoding="utf-8")
        elif command == "--generate-audio":
            (Path(arguments[1]) / "scene01.mp3").write_bytes(b"audio")
        elif command == "--generate-images":
            (Path(arguments[1]) / "scene01.png").write_bytes(b"image")
            if on_line is not None:
                on_line("2026-01-01 00:00:00,000 | INFO | youtube_generator.app.generate_scene_images | 画像生成: (1/1)")
                on_line("2026-01-01 00:00:01,000 | INFO | youtube_generator.app.generate_scene_images | 画像編集: (1/1)")
        elif command == "--generate-subtitles":
            (Path(arguments[1]) / "subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nテスト\n", encoding="utf-8",
            )
        elif command == "--generate-video":
            (Path(arguments[1]) / "video.mp4").write_bytes(b"video")
        elif command == "--generate-metadata":
            (Path(arguments[1]) / "titles.txt").write_text("1. タイトル", encoding="utf-8")
        elif command == "--generate-thumbnail":
            (Path(arguments[1]) / "thumbnail.png").write_bytes(b"thumbnail")
        else:
            raise AssertionError(f"未知のコマンドです: {command}")

    def _run_pipeline(
        self, update_stage=lambda stage: None, skip_thumbnail: bool = False, on_progress=None,
    ) -> None:
        with patch("youtube_generator.jobs.pipeline.load_settings", return_value=self.settings), \
             patch.object(ExistingPipelineRunner, "_run", side_effect=self._fake_run):
            ExistingPipelineRunner(skip_thumbnail=skip_thumbnail)(self.job, update_stage, on_progress)

    def test_copies_each_stage_output_into_job_directory(self) -> None:
        stages: list[JobStage] = []

        self._run_pipeline(stages.append)

        self.assertEqual((self.job.output_dir / "script" / "script.txt").read_text(encoding="utf-8"), "本物の台本")
        self.assertTrue((self.job.output_dir / "script" / "scene01.txt").is_file())
        self.assertTrue((self.job.output_dir / "audio" / "scene01.mp3").is_file())
        self.assertTrue((self.job.output_dir / "images" / "scene01.png").is_file())
        self.assertTrue((self.job.output_dir / "subtitle" / "subtitles.srt").is_file())
        self.assertTrue((self.job.output_dir / "video" / "video.mp4").is_file())
        self.assertTrue((self.job.output_dir / "metadata" / "titles.txt").is_file())
        self.assertTrue((self.job.output_dir / "thumbnail" / "thumbnail.png").is_file())
        self.assertEqual(stages, [
            JobStage.SCRIPT_GENERATION, JobStage.SCENE_SPLIT, JobStage.VOICE_GENERATION,
            JobStage.IMAGE_GENERATION, JobStage.SUBTITLE_GENERATION, JobStage.QUALITY_CHECK,
            JobStage.VIDEO_RENDER, JobStage.METADATA_GENERATION, JobStage.THUMBNAIL_GENERATION,
        ])

    def test_ignores_newer_script_txt_written_elsewhere_in_output(self) -> None:
        """他ジョブ・他プロセスが同時にscript.txtを書いても、決定的なパス計算のため影響されない。

        旧実装（mtime最大のscript.txtを推測で選ぶ方式）ではこのデコイファイルを誤って
        選んでしまう可能性があったことの回帰テスト。
        """
        decoy_dir = self.settings.output_dir / "汎用" / "decoy-run-id_別のテーマ"
        decoy_dir.mkdir(parents=True)
        (decoy_dir / "script.txt").write_text("デコイの台本", encoding="utf-8")

        self._run_pipeline()

        self.assertEqual(
            (self.job.output_dir / "script" / "script.txt").read_text(encoding="utf-8"), "本物の台本",
        )

    def test_skip_thumbnail_omits_generation_and_copy(self) -> None:
        stages: list[JobStage] = []

        self._run_pipeline(stages.append, skip_thumbnail=True)

        self.assertNotIn("--generate-thumbnail", [call[0] for call in self.calls])
        self.assertFalse((self.job.output_dir / "thumbnail" / "thumbnail.png").exists())
        self.assertIn(JobStage.THUMBNAIL_GENERATION, stages)

    def test_image_generation_progress_is_forwarded_with_log_noise_stripped(self) -> None:
        progress_messages: list[str] = []

        self._run_pipeline(on_progress=progress_messages.append)

        # 生成の進捗（画像生成）だけでなく、編集ステップの進捗（画像編集）も転送されること。
        self.assertEqual(progress_messages, ["画像生成: (1/1)", "画像編集: (1/1)"])

    def test_run_invoked_with_expected_arguments_per_stage(self) -> None:
        self._run_pipeline()

        commands = [call[0] for call in self.calls]
        self.assertEqual(commands, [
            "--theme", "--split-script", "--generate-audio", "--generate-images",
            "--generate-subtitles", "--generate-video", "--generate-metadata", "--generate-thumbnail",
        ])
        self.assertEqual(self.calls[0], ("--theme", "宇宙の不思議", "--template", "default", "--run-id", "job-1"))
        metadata_call = self.calls[6]
        self.assertIn("--topic", metadata_call)
        self.assertEqual(metadata_call[metadata_call.index("--topic") + 1], "宇宙の不思議")


if __name__ == "__main__":
    unittest.main()
