"""既存CLIパイプラインをジョブ単位で逐次実行するアダプター。"""

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from youtube_generator.app.generate_script import GenerateScriptUseCase
from youtube_generator.config import PROJECT_ROOT, load_settings
from youtube_generator.jobs.manager import Job, JobStage
from youtube_generator.services.template_service import TemplateManager

# generate_scene_images.pyが出力する進捗ログ（例: 画像生成: (3/10) / 画像編集: (3/10)）を
# サブプロセス出力から抽出し、キュー側の進捗通知へ転送するためのパターン。
_IMAGE_PROGRESS_PATTERN = re.compile(r"画像(生成|編集): \(\d+/\d+\)")


class ExistingPipelineRunner:
    """既存のCLIを再利用し、工程別成果物をジョブ出力へコピーする。"""

    def __init__(self, skip_thumbnail: bool = False) -> None:
        self._skip_thumbnail = skip_thumbnail

    def __call__(
        self,
        job: Job,
        update_stage: Callable[[JobStage], None],
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        work_dir = job.output_dir / ".work"
        work_dir.mkdir(exist_ok=True)

        update_stage(JobStage.SCRIPT_GENERATION)
        self._run(
            "--theme", job.theme, "--template", job.template,
            "--run-id", job.job_id,
        )
        script_file = self._script_output_dir(job) / "script.txt"
        self._copy(script_file, work_dir / "script.txt")
        self._copy(script_file, job.output_dir / "script" / "script.txt")

        update_stage(JobStage.SCENE_SPLIT)
        self._run("--split-script", str(work_dir / "script.txt"), "--template", job.template)
        self._copy_matching(work_dir, "scene*.txt", job.output_dir / "script")

        update_stage(JobStage.VOICE_GENERATION)
        self._run("--generate-audio", str(work_dir), "--template", job.template)
        self._copy_matching(work_dir, "scene*.mp3", job.output_dir / "audio")

        update_stage(JobStage.IMAGE_GENERATION)
        self._run(
            "--generate-images", str(work_dir), "--template", job.template,
            on_line=self._make_image_progress_handler(on_progress) if on_progress else None,
        )
        self._copy_matching(work_dir, "scene*.png", job.output_dir / "images")

        update_stage(JobStage.SUBTITLE_GENERATION)
        self._run("--generate-subtitles", str(work_dir), "--template", job.template)
        self._copy(work_dir / "subtitles.srt", job.output_dir / "subtitle" / "subtitles.srt")

        update_stage(JobStage.QUALITY_CHECK)
        update_stage(JobStage.VIDEO_RENDER)
        self._run("--generate-video", str(work_dir), "--template", job.template)
        self._copy(work_dir / "video.mp4", job.output_dir / "video" / "video.mp4")
        self._copy_matching(work_dir, "quality_report.*", job.output_dir / "quality_report")

        update_stage(JobStage.METADATA_GENERATION)
        self._run(*self._metadata_arguments(job, work_dir))
        self._copy_matching(work_dir, "*.txt", job.output_dir / "metadata", exclude={"script.txt"})

        update_stage(JobStage.THUMBNAIL_GENERATION)
        if not self._skip_thumbnail:
            self._run("--generate-thumbnail", str(work_dir), "--template", job.template)
            self._copy(work_dir / "thumbnail.png", job.output_dir / "thumbnail" / "thumbnail.png")

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _copy_matching(self, source_dir: Path, pattern: str, destination_dir: Path, exclude: set[str] | None = None) -> None:
        for source in source_dir.glob(pattern):
            if exclude is None or source.name not in exclude:
                self._copy(source, destination_dir / source.name)

    @staticmethod
    def _script_output_dir(job: Job) -> Path:
        """cli/main.pyの--themeが台本を書き込む出力先を、スキャンせず直接計算する。

        run_id（job.job_id）を渡して台本生成しているため、出力先は
        GenerateScriptUseCase.output_directoryと同じ計算式で一意に定まる。
        他ジョブの並行書き込みに影響されるファイルスキャンを避けるための実装。
        """
        settings = load_settings()
        template = TemplateManager(settings.templates_dir).get(job.template)
        return GenerateScriptUseCase.output_directory(settings.output_dir, job.theme, template, job.job_id)

    @staticmethod
    def _metadata_arguments(job: Job, work_dir: Path) -> tuple[str, ...]:
        """ジョブのテーマとテンプレートをメタデータ工程へ渡す。"""
        return (
            "--generate-metadata", str(work_dir), "--template", job.template,
            "--topic", job.theme,
        )

    @staticmethod
    def _make_image_progress_handler(on_progress: Callable[[str], None]) -> Callable[[str], None]:
        """サブプロセスの出力行から画像生成の進捗ログのみを抽出し、キュー側へ転送する。"""
        def handle_line(line: str) -> None:
            match = _IMAGE_PROGRESS_PATTERN.search(line)
            if match:
                on_progress(match.group(0))
        return handle_line

    @staticmethod
    def _run(*arguments: str, on_line: Callable[[str], None] | None = None) -> None:
        command = [sys.executable, str(PROJECT_ROOT / "main.py"), *arguments]
        if on_line is None:
            completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr[-2000:] or completed.stdout[-2000:] or "既存パイプラインが失敗しました。")
            return

        # 進捗をリアルタイムに転送するため、完了を待たず1行ずつストリーミングで読み取る。
        process = subprocess.Popen(
            command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1,
        )
        output_lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line)
            on_line(line.rstrip("\n"))
        process.wait()
        if process.returncode != 0:
            raise RuntimeError("".join(output_lines)[-2000:] or "既存パイプラインが失敗しました。")
