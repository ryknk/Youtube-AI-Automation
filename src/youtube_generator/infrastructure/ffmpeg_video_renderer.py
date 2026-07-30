"""FFmpegを利用してシーン素材をMP4へ結合する。"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from youtube_generator.domain.audio_duration_provider import AudioDurationProvider
from youtube_generator.domain.video_renderer import VideoRenderer
from youtube_generator.exceptions import VideoRenderingError
from youtube_generator.services.scene_image_timing import build_scene_segments, distribute_duration
from youtube_generator.services.subtitle_alignment import SubtitleAlignmentProvider
from youtube_generator.services.subtitle_style import build_ass_subtitle_style


SCENE_IMAGE_PATTERN = re.compile(r"scene(\d{2})_(\d{2})\.png$", re.IGNORECASE)
SRT_TIMING_PATTERN = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})")

# zoompanのズーム速度・可動範囲。
# zoompanの実際のクロップ幅/高さは入力フレーム基準の iw/zoom, ih/zoom になるため、
# x/y式は ow/oh ではなく iw/ih を基準に計算する（ow/zoom基準だと中心・端がずれる）。
# また画像を大きめ(_ZOOM_SUPERSAMPLE_FACTOR倍)にscaleしてからzoompanへ渡すことで、
# 1フレームあたりの移動量が1px未満に量子化されて動きがガタつく現象を防ぐ
# （小さい入力のままだと移動量が0pxの停止フレームと数px分の跳躍フレームが交互になり、
# カクカクした見た目になる）。
_ZOOM_SUPERSAMPLE_FACTOR = 4.0
_ZOOM_IN_RATE = 0.00015
_ZOOM_MAX_SCALE = 1.10
_ZOOM_MIN_SCALE = 1.0
_PAN_RATE = 0.0006

# シーン画像に適用するズーム/パン演出のバリエーション。
# (zoom式, x式, y式) の組で、画像ごとに順番に切り替えてワンパターン化を防ぐ。
_ZOOM_PAN_EFFECTS: tuple[tuple[str, str, str], ...] = (
    (f"min(1+on*{_ZOOM_IN_RATE},{_ZOOM_MAX_SCALE})", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    (f"max({_ZOOM_MAX_SCALE}-on*{_ZOOM_IN_RATE},{_ZOOM_MIN_SCALE})", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    (f"{_ZOOM_MAX_SCALE}", f"min(on*ow*{_PAN_RATE},(iw-iw/zoom))", "(ih-ih/zoom)/2"),
    (f"{_ZOOM_MAX_SCALE}", f"max((iw-iw/zoom)-on*ow*{_PAN_RATE},0)", "(ih-ih/zoom)/2"),
    (f"min(1+on*{_ZOOM_IN_RATE},{_ZOOM_MAX_SCALE})", "0", "0"),
    (f"min(1+on*{_ZOOM_IN_RATE},{_ZOOM_MAX_SCALE})", "(iw-iw/zoom)", "(ih-ih/zoom)"),
)


@dataclass(frozen=True, slots=True)
class VideoRenderSettings:
    """動画レンダリングに必要な設定。"""

    width: int
    height: int
    fps: int
    bgm_enabled: bool
    bgm_file: Path
    bgm_volume: float
    bgm_loop: bool = True
    bgm_fade_in: float = 0.0
    bgm_fade_out: float = 0.0
    gap_seconds: float = 0.0
    subtitle_font: str = "Arial"
    subtitle_size: int = 36
    subtitle_color: str = "&H00FFFFFF"
    subtitle_position: str = "bottom"
    subtitle_alignment: str = "center"
    subtitle_bottom_margin: int = 80
    subtitle_box_enabled: bool = False
    subtitle_background_color: str = "&H00000000"
    subtitle_background_opacity: float = 0.6


@dataclass(frozen=True, slots=True)
class RenderImage:
    """シーン内で表示する1枚の画像とその表示秒数。"""

    image_file: Path
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class RenderScene:
    """レンダリング対象となる1シーンの素材。"""

    index: int
    images: tuple[RenderImage, ...]
    audio_file: Path
    duration_seconds: float


class FfmpegVideoRenderer(VideoRenderer):
    """静止画ズーム・字幕・BGMを含むH.264 MP4を生成する。"""

    def __init__(
        self,
        duration_provider: AudioDurationProvider,
        settings: VideoRenderSettings,
        executable: str = "ffmpeg",
        alignment_provider: SubtitleAlignmentProvider | None = None,
    ) -> None:
        self._duration_provider = duration_provider
        self._settings = settings
        self._executable = executable
        self._alignment_provider = alignment_provider

    def render(self, scenes_dir: Path, output_file: Path) -> None:
        """sceneNN_MM.pngとsceneNN.mp3、subtitles.srtから動画を出力する。"""
        scenes = self._find_scenes(scenes_dir)
        subtitle_file = scenes_dir / "subtitles.srt"
        if not subtitle_file.is_file():
            raise FileNotFoundError(f"字幕ファイルが見つかりません: {subtitle_file}")
        if self._settings.bgm_enabled and not self._settings.bgm_file.is_file():
            raise FileNotFoundError(f"BGMファイルが見つかりません: {self._settings.bgm_file}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        # 延長区間でも直前の字幕を表示し続けるため、焼き込み用にのみ末尾字幕の終了時刻を延長する
        # （scenes_dir直下のsubtitles.srt自体は元の音声長のまま維持する）。
        render_subtitle_file = subtitle_file
        temporary_subtitle_file: Path | None = None
        if self._settings.gap_seconds > 0:
            temporary_subtitle_file = scenes_dir / ".subtitles_gap.srt"
            temporary_subtitle_file.write_text(
                self._extend_last_subtitle_cue(subtitle_file.read_text(encoding="utf-8"), self._settings.gap_seconds),
                encoding="utf-8",
            )
            render_subtitle_file = temporary_subtitle_file
        try:
            command = self.build_command(scenes, render_subtitle_file, output_file)
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
            except FileNotFoundError as error:
                raise VideoRenderingError("ffmpeg が見つかりません。FFmpegを導入し、PATHへ追加してください。") from error
            except subprocess.CalledProcessError as error:
                details = error.stderr[-2000:] if error.stderr else "詳細ログなし"
                raise VideoRenderingError(f"動画生成に失敗しました: {details}") from error
            if not output_file.is_file() or output_file.stat().st_size == 0:
                raise VideoRenderingError(f"MP4ファイルを保存できませんでした: {output_file}")
        finally:
            if temporary_subtitle_file is not None:
                temporary_subtitle_file.unlink(missing_ok=True)

    def build_command(self, scenes: tuple[RenderScene, ...], subtitle_file: Path, output_file: Path) -> list[str]:
        """動画生成に使用するFFmpegコマンドを構築する。"""
        if not scenes:
            raise ValueError("レンダリング対象のシーンがありません。")

        gap_seconds = self._settings.gap_seconds
        command = [self._executable, "-y"]
        input_layout: list[tuple[tuple[int, ...], int]] = []
        input_index = 0
        for scene_index, scene in enumerate(scenes):
            is_last_scene = scene_index == len(scenes) - 1
            last_image_position = len(scene.images) - 1
            image_inputs: list[int] = []
            for image_position, image in enumerate(scene.images):
                # 最後のシーンの最後の画像だけナレーション終了後も延長し、エンディングとの区切りを明確にする。
                # ズームが同じzoompanフィルター内で継続するよう、別セグメントではなく画像の表示秒数自体を延ばす。
                extended = gap_seconds if is_last_scene and image_position == last_image_position else 0.0
                # image2's default is 25 fps.  Keep its input clock aligned with
                # zoompan/output fps so the final scene is not shortened.
                command.extend([
                    "-loop", "1", "-framerate", str(self._settings.fps),
                    "-t", f"{image.duration_seconds + extended:.3f}", "-i", str(image.image_file),
                ])
                image_inputs.append(input_index)
                input_index += 1
            command.extend(["-i", str(scene.audio_file)])
            audio_input = input_index
            input_index += 1
            input_layout.append((tuple(image_inputs), audio_input))

        bgm_input_index: int | None = None
        if self._settings.bgm_enabled:
            bgm_input_index = input_index
            if self._settings.bgm_loop:
                command.extend(["-stream_loop", "-1"])
            command.extend(["-i", str(self._settings.bgm_file)])

        command.extend([
            "-filter_complex", self._build_filter_complex(scenes, input_layout, subtitle_file, bgm_input_index),
            "-map", "[video]", "-map", "[audio]", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(self._settings.fps), "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output_file),
        ])
        return command

    def _build_filter_complex(
        self,
        scenes: tuple[RenderScene, ...],
        input_layout: list[tuple[tuple[int, ...], int]],
        subtitle_file: Path,
        bgm_input_index: int | None,
    ) -> str:
        filters: list[str] = []
        concat_inputs: list[str] = []
        gap_seconds = self._settings.gap_seconds
        effect_index = 0
        for scene_index, (scene, (image_inputs, audio_input)) in enumerate(zip(scenes, input_layout)):
            video_label = f"v{scene_index}"
            if len(image_inputs) == 1:
                filters.append(self._scaled_zoompan_filter(image_inputs[0], video_label, effect_index))
                effect_index += 1
            else:
                # シーン内の複数画像を順番にズーム演出したうえで連結し、シーンとして1本の映像にする
                # （zoompanはフィルターごとにズーム量がリセットされるため、切り替えごとに新鮮な見た目になる）。
                # effect_indexを画像ごとに進めることで、ズームイン/ズームアウト/パンなど
                # 複数の演出パターンを順番に使い分け、ワンパターンな見た目を避ける。
                sub_labels = []
                for sub_index, image_input in enumerate(image_inputs):
                    sub_label = f"v{scene_index}_{sub_index}"
                    filters.append(self._scaled_zoompan_filter(image_input, sub_label, effect_index))
                    effect_index += 1
                    sub_labels.append(f"[{sub_label}]")
                filters.append(f"{''.join(sub_labels)}concat=n={len(image_inputs)}:v=1:a=0[{video_label}]")
            if scene_index == len(scenes) - 1 and gap_seconds > 0:
                # 延長した画像の表示秒数に合わせ、ナレーション終了後を無音でpadする。
                filters.append(f"[{audio_input}:a]apad=pad_dur={gap_seconds:.3f}[a{scene_index}]")
                concat_inputs.extend([f"[{video_label}]", f"[a{scene_index}]"])
            else:
                concat_inputs.extend([f"[{video_label}]", f"[{audio_input}:a]"])

        filters.append(f"{''.join(concat_inputs)}concat=n={len(scenes)}:v=1:a=1[concatenated_video][narration]")
        subtitle_path = self._escape_filter_path(subtitle_file)
        subtitle_style = build_ass_subtitle_style(
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
        filters.append(
            f"[concatenated_video]subtitles=filename='{subtitle_path}':charenc=UTF-8:"
            f"force_style='{subtitle_style}'[video]"
        )
        if bgm_input_index is None:
            filters.append("[narration]anull[audio]")
        else:
            total_duration = sum(scene.duration_seconds for scene in scenes) + gap_seconds
            fade_in = min(self._settings.bgm_fade_in, total_duration)
            fade_out = min(self._settings.bgm_fade_out, total_duration)
            fade_out_start = max(0.0, total_duration - fade_out)
            bgm_filters = [
                f"[{bgm_input_index}:a]atrim=duration={total_duration:.3f}",
                f"volume={self._settings.bgm_volume}",
            ]
            if fade_in > 0:
                bgm_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
            if fade_out > 0:
                bgm_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")
            filters.append(",".join(bgm_filters) + "[bgm]")
            filters.append("[narration][bgm]amix=inputs=2:duration=first:weights='1 1':normalize=0[audio]")
        return ";".join(filters)

    def _scaled_zoompan_filter(self, image_input: int, output_label: str, effect_index: int) -> str:
        scale_width = round(self._settings.width * _ZOOM_SUPERSAMPLE_FACTOR)
        scale_height = round(self._settings.height * _ZOOM_SUPERSAMPLE_FACTOR)
        zoom_expr, x_expr, y_expr = _ZOOM_PAN_EFFECTS[effect_index % len(_ZOOM_PAN_EFFECTS)]
        return (
            f"[{image_input}:v]scale={scale_width}:{scale_height},"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d=1:"
            f"s={self._settings.width}x{self._settings.height}:fps={self._settings.fps},"
            f"setsar=1[{output_label}]"
        )

    def _find_scenes(self, scenes_dir: Path) -> tuple[RenderScene, ...]:
        if not scenes_dir.is_dir():
            raise FileNotFoundError(f"シーンフォルダが見つかりません: {scenes_dir}")
        images_by_scene: dict[int, list[tuple[int, Path]]] = {}
        for image_file in scenes_dir.glob("scene*.png"):
            match = SCENE_IMAGE_PATTERN.fullmatch(image_file.name)
            if not match:
                continue
            index = int(match.group(1))
            sub_index = int(match.group(2))
            images_by_scene.setdefault(index, []).append((sub_index, image_file))

        scenes: list[RenderScene] = []
        for index in sorted(images_by_scene):
            image_files = tuple(path for _, path in sorted(images_by_scene[index]))
            audio_file = image_files[0].with_name(f"scene{index:02d}.mp3")
            if not audio_file.is_file():
                raise FileNotFoundError(f"対応する音声ファイルが見つかりません: {audio_file}")
            duration = self._duration_provider.get_duration_seconds(audio_file)
            durations = self._resolve_image_durations(image_files, audio_file, duration, index)
            images = tuple(RenderImage(path, seconds) for path, seconds in zip(image_files, durations))
            scenes.append(RenderScene(index, images, audio_file, duration))
        return tuple(scenes)

    def _resolve_image_durations(
        self, image_files: tuple[Path, ...], audio_file: Path, duration: float, scene_index: int,
    ) -> tuple[float, ...]:
        if len(image_files) == 1:
            return (duration,)
        text_file = audio_file.with_suffix(".txt")
        if not text_file.is_file():
            return distribute_duration(len(image_files), duration, ())
        text = text_file.read_text(encoding="utf-8-sig")
        alignment_file = audio_file.with_suffix(".alignment.json")
        segments = build_scene_segments(text, duration, scene_index, alignment_file, self._alignment_provider)
        boundary_times = tuple(segment.end_time for segment in segments[:-1])
        return distribute_duration(len(image_files), duration, boundary_times)

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        """FFmpegフィルター内で使用できるWindowsパスへ変換する。"""
        return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    @classmethod
    def _extend_last_subtitle_cue(cls, srt_text: str, extra_seconds: float) -> str:
        """SRT本文の最後の字幕キューの終了時刻だけをextra_seconds分延長する。"""
        matches = list(SRT_TIMING_PATTERN.finditer(srt_text))
        if not matches:
            return srt_text
        start, end = matches[-1].span(2)
        extended_end = cls._add_seconds_to_timestamp(matches[-1].group(2), extra_seconds)
        return srt_text[:start] + extended_end + srt_text[end:]

    @staticmethod
    def _add_seconds_to_timestamp(timestamp: str, extra_seconds: float) -> str:
        time_part, milliseconds_part = timestamp.split(",")
        hours, minutes, seconds = (int(part) for part in time_part.split(":"))
        total_milliseconds = (
            (hours * 3_600_000) + (minutes * 60_000) + (seconds * 1_000) + int(milliseconds_part)
            + round(extra_seconds * 1000)
        )
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
