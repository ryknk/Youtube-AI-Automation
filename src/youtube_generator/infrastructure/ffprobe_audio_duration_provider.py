"""FFprobeを使用して音声ファイルの再生時間を取得する。"""

import subprocess
from pathlib import Path

from youtube_generator.exceptions import SubtitleGenerationError


class FfprobeAudioDurationProvider:
    """FFprobeのformat.durationを利用する音声長プロバイダー。"""

    def __init__(self, executable: str = "ffprobe") -> None:
        self._executable = executable

    def get_duration_seconds(self, audio_file: Path) -> float:
        """MP3などの音声ファイルの再生時間を秒単位で返す。"""
        if not audio_file.is_file():
            raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")
        command = [
            self._executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file),
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            duration = float(completed.stdout.strip())
        except FileNotFoundError as error:
            raise SubtitleGenerationError(
                "ffprobe が見つかりません。FFmpegを導入し、PATHへ追加してください。"
            ) from error
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            raise SubtitleGenerationError(f"音声長を取得できませんでした: {audio_file}") from error
        if duration <= 0:
            raise SubtitleGenerationError(f"音声長が不正です: {audio_file}")
        return duration
