"""エンディング用のFFmpegレンダリングと動画結合。"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from youtube_generator.exceptions import VideoRenderingError
from youtube_generator.infrastructure.ffmpeg_video_renderer import VideoRenderSettings
from youtube_generator.services.subtitle_style import build_ass_subtitle_style


@dataclass(frozen=True, slots=True)
class EndingRenderRequest:
    audio_file: Path
    subtitle_file: Path | None
    image_files: tuple[Path, ...]
    output_file: Path
    duration_seconds: float


class FfmpegEndingRenderer:
    """本編と同じH.264/AAC構成の短いエンディングを生成する。"""

    def __init__(self, settings: VideoRenderSettings, executable: str = "ffmpeg") -> None:
        self._settings = settings
        self._executable = executable

    def render(self, request: EndingRenderRequest) -> None:
        request.output_file.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(request)
        self._run(command, "エンディング動画の生成")
        self._validate(request.output_file)

    def concat(self, main_video: Path, ending_video: Path, output_file: Path) -> None:
        if not main_video.is_file() or not ending_video.is_file():
            raise FileNotFoundError("結合する本編またはエンディング動画が見つかりません。")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_file.with_suffix(".concat.txt")
        try:
            list_file.write_text(
                f"file '{self._concat_path(main_video)}'\nfile '{self._concat_path(ending_video)}'\n",
                encoding="utf-8",
            )
            self._run(
                [self._executable, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_file)],
                "動画結合",
            )
            self._validate(output_file)
        finally:
            list_file.unlink(missing_ok=True)

    def build_command(self, request: EndingRenderRequest) -> list[str]:
        command = [self._executable, "-y"]
        image_count = max(1, len(request.image_files))
        segment_duration = request.duration_seconds / image_count
        if request.image_files:
            for image_file in request.image_files:
                command.extend([
                    "-loop", "1", "-framerate", str(self._settings.fps), "-t", f"{segment_duration:.3f}",
                    "-i", str(image_file),
                ])
        else:
            command.extend([
                "-f", "lavfi", "-t", f"{request.duration_seconds:.3f}", "-i",
                f"color=c=black:s={self._settings.width}x{self._settings.height}:r={self._settings.fps}",
            ])
        command.extend(["-i", str(request.audio_file)])
        if self._settings.bgm_enabled and self._settings.bgm_file.is_file():
            if self._settings.bgm_loop:
                command.extend(["-stream_loop", "-1"])
            command.extend(["-i", str(self._settings.bgm_file)])
        command.extend([
            "-filter_complex", self._filters(request, image_count),
            "-map", "[video]", "-map", "[audio]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", str(self._settings.fps), "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(request.output_file),
        ])
        return command

    def _filters(self, request: EndingRenderRequest, image_count: int) -> str:
        parts: list[str] = []
        audio_index = image_count
        segment_duration = request.duration_seconds / image_count
        for index in range(image_count):
            parts.append(
                f"[{index}:v]scale={self._settings.width}:{self._settings.height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={self._settings.width}:{self._settings.height}:"
                "(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"fps={self._settings.fps},trim=duration={segment_duration:.3f},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
        if image_count == 1:
            parts.append("[v0]null[visual]")
        else:
            concat_inputs = "".join(f"[v{index}]" for index in range(image_count))
            parts.append(f"{concat_inputs}concat=n={image_count}:v=1:a=0[visual]")
        if request.subtitle_file is None:
            parts.append("[visual]null[video]")
            return self._audio_filters(parts, audio_index, request.duration_seconds)
        subtitle_path = self._escape_path(request.subtitle_file)
        style = build_ass_subtitle_style(
            font=self._settings.subtitle_font,
            size=self._settings.subtitle_size,
            primary_color=self._settings.subtitle_color,
            position=self._settings.subtitle_position,
            alignment=self._settings.subtitle_alignment,
            margin=self._settings.subtitle_bottom_margin,
            box_enabled=self._settings.subtitle_box_enabled,
            background_color=self._settings.subtitle_background_color,
            background_opacity=self._settings.subtitle_background_opacity,
        )
        parts.append(f"[visual]subtitles=filename='{subtitle_path}':charenc=UTF-8:force_style='{style}'[video]")
        return self._audio_filters(parts, audio_index, request.duration_seconds)

    def _audio_filters(
        self, parts: list[str], audio_index: int, duration_seconds: float,
    ) -> str:
        if self._settings.bgm_enabled and self._settings.bgm_file.is_file():
            fade_in = min(self._settings.bgm_fade_in, duration_seconds)
            fade_out = min(self._settings.bgm_fade_out, duration_seconds)
            fade_out_start = max(0.0, duration_seconds - fade_out)
            bgm_filters = [
                f"[{audio_index + 1}:a]atrim=duration={duration_seconds:.3f}",
                f"volume={self._settings.bgm_volume}",
            ]
            if fade_in > 0:
                bgm_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
            if fade_out > 0:
                bgm_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")
            parts.append(",".join(bgm_filters) + "[bgm]")
            parts.append(f"[{audio_index}:a][bgm]amix=inputs=2:duration=shortest:weights='1 1':normalize=0[audio]")
        else:
            parts.append(f"[{audio_index}:a]anull[audio]")
        return ";".join(parts)

    def _run(self, command: list[str], action: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError as error:
            raise VideoRenderingError("ffmpeg が見つかりません。FFmpegを導入し、PATHへ追加してください。") from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr[-2000:] if error.stderr else "詳細ログなし"
            raise VideoRenderingError(f"{action}に失敗しました: {detail}") from error

    @staticmethod
    def _validate(file_path: Path) -> None:
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise VideoRenderingError(f"MP4ファイルを保存できませんでした: {file_path}")

    @staticmethod
    def _concat_path(file_path: Path) -> str:
        return str(file_path.resolve()).replace("\\", "/").replace("'", "\\'")

    @staticmethod
    def _escape_path(file_path: Path) -> str:
        return str(file_path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
