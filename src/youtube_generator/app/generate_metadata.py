"""動画完成後のメタデータをファイル保存するユースケース。"""

from pathlib import Path

from youtube_generator.domain.metadata_generator import MetadataGenerator


class GenerateMetadataUseCase:
    def __init__(self, generator: MetadataGenerator) -> None:
        self._generator = generator

    def execute(self, project_dir: Path) -> tuple[Path, ...]:
        script_file = project_dir / "script.txt"
        try:
            metadata = self._generator.generate(script_file.read_text(encoding="utf-8-sig"))
        except OSError as error:
            raise FileNotFoundError(f"台本ファイルを読み込めません: {script_file}") from error
        files = {
            "titles.txt": "\n".join(f"{index}. {title}" for index, title in enumerate(metadata.titles, 1)) + "\n",
            "description.txt": metadata.description + "\n",
            "tags.txt": ", ".join(metadata.tags) + "\n",
            "hashtags.txt": " ".join(metadata.hashtags) + "\n",
            "thumbnail_copies.txt": "\n".join(f"{index}. {copy}" for index, copy in enumerate(metadata.thumbnail_copies, 1)) + "\n",
        }
        paths = []
        for name, content in files.items():
            path = project_dir / name
            path.write_text(content, encoding="utf-8")
            paths.append(path)
        return tuple(paths)
