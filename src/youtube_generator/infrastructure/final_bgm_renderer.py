"""本編からエンディングまで連続する単一BGMを最終ミックスする。"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.logger import get_logger
from youtube_generator.services.bgm_manager import BgmSettings


@dataclass(frozen=True, slots=True)
class FinalRenderSettings:
    width: int
    height: int
    fps: int
    keep_intermediate: bool = True


class FinalBGMRenderer:
    """結合済みナレーションにBGMを一度だけミックスするFFmpegレンダラー。

    Duckingは将来、_build_mix_commandのBGMフィルターへsidechaincompressを追加して拡張する。
    """

    def __init__(
        self,
        settings: FinalRenderSettings,
        cache_manager: CacheManager | None = None,
        ffmpeg_executable: str = "ffmpeg",
        ffprobe_executable: str = "ffprobe",
    ) -> None:
        self._settings = settings
        self._cache = cache_manager
        self._ffmpeg = ffmpeg_executable
        self._ffprobe = ffprobe_executable
        self._logger = get_logger(__name__)

    def render(
        self,
        main_file: Path,
        ending_file: Path | None,
        output_dir: Path,
        bgm: BgmSettings,
        force: bool = False,
    ) -> Path:
        if not main_file.is_file():
            raise FileNotFoundError(f"main.mp4 が見つかりません: {main_file}")
        if ending_file is not None and not ending_file.is_file():
            raise FileNotFoundError(f"ending.mp4 が見つかりません: {ending_file}")
        output_dir.mkdir(parents=True, exist_ok=True)
        final_file = output_dir / "final.mp4"
        cache_key = self._cache_key(main_file, ending_file, bgm)
        if self._cache is not None and not force and self._cache.exists(cache_key, "final_video"):
            self._cache.restore_files(cache_key, "final_video", output_dir)
            self._logger.info("最終BGMミックスをキャッシュから復元しました: %s", final_file)
            return final_file

        combined_file = output_dir / "combined_without_bgm.mp4"
        self._logger.info("最終動画結合を開始します: main=%s ending=%s", main_file, ending_file)
        self._combine(main_file, ending_file, combined_file)
        duration = self._duration(combined_file)
        self._logger.info(
            "最終BGMミックスを開始します: duration=%.3f, bgm=%s, loop=%s, volume=%s",
            duration, bgm.file, bgm.loop, bgm.volume,
        )
        if bgm.enabled and bgm.file is not None:
            self._run(self._build_mix_command(combined_file, final_file, bgm, duration), "最終BGMミックス")
        else:
            shutil.copy2(combined_file, final_file)
        self._validate(final_file)
        if self._cache is not None:
            self._cache.save_files(cache_key, "final_video", (final_file,))
        if not self._settings.keep_intermediate:
            combined_file.unlink(missing_ok=True)
        self._logger.info("最終BGMミックスを終了しました: %s", final_file)
        return final_file

    def _combine(self, main_file: Path, ending_file: Path | None, output_file: Path) -> None:
        prepared_files: list[Path] = []
        prepared_main = self._with_silence_if_needed(main_file, output_file, "main", prepared_files)
        prepared_ending = (
            self._with_silence_if_needed(ending_file, output_file, "ending", prepared_files)
            if ending_file is not None else None
        )
        if prepared_ending is None:
            shutil.copy2(prepared_main, output_file)
            for temporary in prepared_files:
                temporary.unlink(missing_ok=True)
            return
        list_file = output_file.with_suffix(".concat.txt")
        try:
            list_file.write_text(
                f"file '{self._concat_path(prepared_main)}'\nfile '{self._concat_path(prepared_ending)}'\n", encoding="utf-8"
            )
            try:
                self._run(
                    [self._ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_file)],
                    "最終動画の結合",
                )
            except RuntimeError:
                self._logger.warning("再エンコードなしの結合に失敗したため、再エンコードして結合します。")
                self._run([
                    self._ffmpeg, "-y", "-i", str(prepared_main), "-i", str(prepared_ending),
                    "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(self._settings.fps),
                    "-c:a", "aac", str(output_file),
                ], "最終動画の再エンコード結合")
        finally:
            list_file.unlink(missing_ok=True)
            for temporary in prepared_files:
                temporary.unlink(missing_ok=True)
        self._validate(output_file)

    def _with_silence_if_needed(
        self, source_file: Path, output_file: Path, label: str, temporary_files: list[Path]
    ) -> Path:
        if self._has_audio(source_file):
            return source_file
        temporary = output_file.with_name(f".{label}_with_silence.mp4")
        self._logger.warning("音声ストリームがないため無音トラックを追加します: %s", source_file)
        self._run([
            self._ffmpeg, "-y", "-i", str(source_file), "-f", "lavfi", "-t", f"{self._duration(source_file):.3f}",
            "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            str(temporary),
        ], "無音トラックの追加")
        temporary_files.append(temporary)
        return temporary

    def _build_mix_command(self, combined_file: Path, final_file: Path, bgm: BgmSettings, duration: float) -> list[str]:
        command = [self._ffmpeg, "-y", "-i", str(combined_file)]
        narration_input = "[0:a]" if self._has_audio(combined_file) else "[1:a]"
        if narration_input == "[1:a]":
            command.extend(["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"])
        bgm_input_index = 1 if narration_input == "[0:a]" else 2
        if bgm.loop:
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", str(bgm.file)])
        fade_in = min(bgm.fade_in, duration)
        fade_out = min(bgm.fade_out, duration)
        fade_out_start = max(0.0, duration - fade_out)
        bgm_filters = [f"[1:a]atrim=duration={duration:.3f}", f"volume={bgm.volume}"]
        if fade_in > 0:
            bgm_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            bgm_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")
        filter_graph = ";".join([
            f"{narration_input}volume=1.0[narration]",
            ",".join(filter.replace("[1:a]", f"[{bgm_input_index}:a]", 1) for filter in bgm_filters) + "[bgm]",
            "[narration][bgm]amix=inputs=2:duration=first:weights='1 1':normalize=0[audio]",
        ])
        return [
            *command, "-filter_complex", filter_graph, "-map", "0:v:0", "-map", "[audio]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final_file),
        ]

    def _cache_key(self, main_file: Path, ending_file: Path | None, bgm: BgmSettings) -> str:
        digest = hashlib.sha256()
        for file_path in (main_file, ending_file):
            if file_path is not None:
                digest.update(file_path.read_bytes())
        digest.update(bgm.cache_fingerprint.encode("utf-8"))
        digest.update(f"{self._settings.width}x{self._settings.height}:{self._settings.fps}".encode("utf-8"))
        digest.update(b"final_mix")
        return digest.hexdigest()

    def _duration(self, video_file: Path) -> float:
        completed = subprocess.run([
            self._ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
            "default=noprint_wrappers=1:nokey=1", str(video_file),
        ], check=True, capture_output=True, text=True, encoding="utf-8")
        duration = float(completed.stdout.strip())
        if duration <= 0:
            raise RuntimeError("結合後動画の時間が不正です。")
        return duration

    def _has_audio(self, video_file: Path) -> bool:
        completed = subprocess.run([
            self._ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
            "default=noprint_wrappers=1:nokey=1", str(video_file),
        ], check=True, capture_output=True, text=True, encoding="utf-8")
        return bool(completed.stdout.strip())

    def _run(self, command: list[str], action: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError as error:
            raise RuntimeError("FFmpegまたはFFprobeが見つかりません。") from error
        except subprocess.CalledProcessError as error:
            details = error.stderr[-2000:] if error.stderr else "詳細ログなし"
            raise RuntimeError(f"{action}に失敗しました: {details}") from error

    @staticmethod
    def _validate(file_path: Path) -> None:
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise RuntimeError(f"動画を保存できませんでした: {file_path}")

    @staticmethod
    def _concat_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace("'", "\\'")
