"""最終MP4動画を生成するユースケース。"""

from pathlib import Path

from youtube_generator.domain.video_renderer import VideoRenderer


class GenerateVideoUseCase:
    """シーン素材フォルダからvideo.mp4を生成する。"""

    def __init__(self, renderer: VideoRenderer) -> None:
        self._renderer = renderer

    def execute(self, scenes_dir: Path, output_format: str = "mp4") -> Path:
        """video.mp4を出力してそのパスを返す。"""
        output_file = scenes_dir / f"video.{output_format}"
        self._renderer.render(scenes_dir, output_file)
        return output_file
