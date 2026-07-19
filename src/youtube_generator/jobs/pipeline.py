"""既存CLIパイプラインをジョブ単位で逐次実行するアダプター。"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from youtube_generator.config import PROJECT_ROOT
from youtube_generator.jobs.manager import Job, JobStage


class ExistingPipelineRunner:
    """既存のCLIを再利用し、工程別成果物をジョブ出力へコピーする。"""

    def __call__(self, job: Job, update_stage: Callable[[JobStage], None]) -> None:
        work_dir = job.output_dir / ".work"
        work_dir.mkdir(exist_ok=True)

        update_stage(JobStage.SCRIPT_GENERATION)
        before = {
            path.resolve() for path in (PROJECT_ROOT / "output").rglob("script.txt")
        }
        self._run(
            "--theme", job.theme, "--template", job.template,
            "--run-id", job.job_id,
        )
        source_dir = self._new_script_dir(before)
        script_file = source_dir / "script.txt"
        self._copy(script_file, work_dir / "script.txt")
        self._copy(script_file, job.output_dir / "script" / "script.txt")

        update_stage(JobStage.SCENE_SPLIT)
        self._run("--split-script", str(work_dir / "script.txt"), "--template", job.template)
        self._copy_matching(work_dir, "scene*.txt", job.output_dir / "script")

        update_stage(JobStage.VOICE_GENERATION)
        self._run("--generate-audio", str(work_dir), "--template", job.template)
        self._copy_matching(work_dir, "scene*.mp3", job.output_dir / "audio")

        update_stage(JobStage.IMAGE_GENERATION)
        self._run("--generate-images", str(work_dir), "--template", job.template)
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
        self._run("--generate-metadata", str(work_dir), "--template", job.template)
        self._copy_matching(work_dir, "*.txt", job.output_dir / "metadata", exclude={"script.txt"})

        update_stage(JobStage.THUMBNAIL_GENERATION)
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
    def _new_script_dir(before: set[Path]) -> Path:
        candidates = [
            path.parent for path in (PROJECT_ROOT / "output").rglob("script.txt")
            if path.resolve() not in before
        ]
        if not candidates:
            raise RuntimeError("既存パイプラインのscript.txt出力を確認できませんでした。")
        return max(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _run(*arguments: str) -> None:
        command = [sys.executable, str(PROJECT_ROOT / "main.py"), *arguments]
        completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr[-2000:] or completed.stdout[-2000:] or "既存パイプラインが失敗しました。")
