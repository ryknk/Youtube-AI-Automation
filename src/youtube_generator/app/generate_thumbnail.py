"""台本からYouTubeサムネイル画像を生成するユースケース。"""

from pathlib import Path

from youtube_generator.plugins.base.image_provider import ImageProvider


class GenerateThumbnailUseCase:
    """プロジェクトの台本を基にthumbnail.pngを生成する。"""

    def __init__(self, image_generator: ImageProvider, thumbnail_instruction: str) -> None:
        self._image_generator = image_generator
        self._thumbnail_instruction = thumbnail_instruction

    def execute(self, project_dir: Path) -> Path:
        script_file = project_dir / "script.txt"
        if not script_file.is_file():
            raise FileNotFoundError(f"script.txt が見つかりません: {project_dir}")
        script = script_file.read_text(encoding="utf-8").strip()
        if not script:
            raise ValueError("サムネイル生成に使用する台本が空です。")

        primary_request = self._build_primary_request(project_dir, script)

        prompt = (
            "Use case: a single wide illustration used as an eye-catching video cover image.\n"
            f"Primary request: {primary_request}\n"
            f"Style/medium: {self._thumbnail_instruction} Follow this template-specific medium and "
            "style exactly, matching the visual style used for the video's scene artwork.\n"
            "Composition/framing: 16:9 landscape, one instantly recognizable focal subject, "
            "bold composition, strong contrast, clear at small display sizes.\n"
            "Character depiction: when the scene depicts people, render each person with clearly "
            "distinguishable gender-appropriate features (male: masculine build, facial structure, "
            "and attire; female: feminine build, facial structure, and attire) matching the gender "
            "implied by the narration, so male and female characters are visually unambiguous. This "
            "video is for a Japanese audience, so depict every person with Japanese ethnicity facial "
            "features, hairstyles, and attire appropriate to the scene.\n"
            "Constraints: no text, no subtitles, no logos, no watermark."
        )
        output_file = project_dir / "thumbnail.png"
        self._image_generator.generate_image(prompt, output_file)
        return output_file

    @staticmethod
    def _build_primary_request(project_dir: Path, script: str) -> str:
        """thumbnail_copies.txt（--generate-metadataの出力）があれば優先利用する。

        台本全文（最大2000文字）をそのまま渡すと、Qwen-Image系プロバイダーの
        max_sequence_length（既定512トークン）を日本語の台本だけで使い切り、
        後続のStyle/medium等が切り詰められる問題があった。thumbnail_copies.txtは
        動画の要点を凝縮した短い文言（5案）のため、この問題を避けられる。
        存在しない場合（--generate-metadata未実行等）は従来どおり台本を使う。
        """
        thumbnail_copies_file = project_dir / "thumbnail_copies.txt"
        if thumbnail_copies_file.is_file():
            thumbnail_copies = thumbnail_copies_file.read_text(encoding="utf-8").strip()
            if thumbnail_copies:
                return (
                    "Create a compelling visual for this Japanese video, capturing the hook "
                    f"conveyed by these candidate thumbnail headline options: {thumbnail_copies}"
                )
        return f"Create a compelling visual that summarizes this Japanese video script: {script[:2000]}"
