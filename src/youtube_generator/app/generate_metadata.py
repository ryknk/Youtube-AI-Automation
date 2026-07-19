"""動画完成後のメタデータをファイル保存するユースケース。"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from youtube_generator.domain.metadata_generator import (
    MetadataGenerationContext,
    MetadataGenerator,
)
from youtube_generator.infrastructure.cache import CacheManager


@dataclass(frozen=True, slots=True)
class MetadataCacheResult:
    files: tuple[Path, ...]
    titles_cache_hit: bool
    details_cache_hit: bool
    titles_cache_key: str
    details_cache_key: str
    title_prompt_hash: str


class GenerateMetadataUseCase:
    def __init__(self, generator: MetadataGenerator) -> None:
        self._generator = generator

    def execute(
        self, project_dir: Path, *, topic: str = "", template_name: str = "",
        title_prompt: str | None = None,
    ) -> tuple[Path, ...]:
        context = self._context(project_dir, topic, template_name, title_prompt)
        metadata = self._generator.generate(context)
        files = {
            "titles.txt": "\n".join(f"{index}. {title}" for index, title in enumerate(metadata.titles, 1)) + "\n",
            "description.txt": metadata.description + "\n",
            "tags.txt": ", ".join(metadata.tags) + "\n",
            "hashtags.txt": " ".join(metadata.hashtags) + "\n",
            "thumbnail_copies.txt": "\n".join(f"{index}. {copy}" for index, copy in enumerate(metadata.thumbnail_copies, 1)) + "\n",
        }
        return self._save(project_dir, files)

    def generate_titles(
        self, project_dir: Path, *, topic: str = "", template_name: str = "",
        title_prompt: str | None = None,
    ) -> tuple[Path, ...]:
        context = self._context(project_dir, topic, template_name, title_prompt)
        titles = self._generator.generate_titles(context)
        return self._save(
            project_dir,
            {"titles.txt": "\n".join(f"{index}. {title}" for index, title in enumerate(titles, 1)) + "\n"},
        )

    def generate_details(self, project_dir: Path) -> tuple[Path, ...]:
        script = self._read_script(project_dir)
        details = self._generator.generate_details(script)
        return self._save(project_dir, {
            "description.txt": details.description + "\n",
            "tags.txt": ", ".join(details.tags) + "\n",
            "hashtags.txt": " ".join(details.hashtags) + "\n",
            "thumbnail_copies.txt": "\n".join(
                f"{index}. {copy}" for index, copy in enumerate(details.thumbnail_copies, 1)
            ) + "\n",
        })

    def execute_cached(
        self, project_dir: Path, cache_manager: CacheManager | None, *,
        fingerprint: str, topic: str, template_id: str, template_name: str,
        title_prompt: str | None,
    ) -> MetadataCacheResult:
        """タイトルとその他のメタデータを別々にキャッシュする。"""
        prompt = title_prompt or ""
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        script_file = project_dir / "script.txt"
        titles_key = CacheManager.make_file_key(
            "metadata_titles", (script_file,),
            f"{fingerprint}:{template_id}:{topic}:{prompt_hash}",
        )
        details_key = CacheManager.make_file_key(
            "metadata_details", (script_file,), fingerprint,
        )
        titles_hit = cache_manager is not None and cache_manager.exists(titles_key, "metadata_titles")
        details_hit = cache_manager is not None and cache_manager.exists(details_key, "metadata_details")

        if cache_manager is None or (not titles_hit and not details_hit):
            files = self.execute(
                project_dir, topic=topic, template_name=template_name, title_prompt=title_prompt,
            )
            title_files = tuple(path for path in files if path.name == "titles.txt")
            detail_files = tuple(path for path in files if path.name != "titles.txt")
            if cache_manager is not None:
                cache_manager.save_files(titles_key, "metadata_titles", title_files)
                cache_manager.save_files(details_key, "metadata_details", detail_files)
        else:
            if titles_hit:
                title_files = cache_manager.restore_files(titles_key, "metadata_titles", project_dir)
            else:
                title_files = self.generate_titles(
                    project_dir, topic=topic, template_name=template_name,
                    title_prompt=title_prompt,
                )
                cache_manager.save_files(titles_key, "metadata_titles", title_files)
            if details_hit:
                detail_files = cache_manager.restore_files(details_key, "metadata_details", project_dir)
            else:
                detail_files = self.generate_details(project_dir)
                cache_manager.save_files(details_key, "metadata_details", detail_files)
            files = title_files + detail_files

        return MetadataCacheResult(
            files, titles_hit, details_hit, titles_key, details_key, prompt_hash,
        )

    def _context(
        self, project_dir: Path, topic: str, template_name: str,
        title_prompt: str | None,
    ) -> MetadataGenerationContext:
        return MetadataGenerationContext(topic, self._read_script(project_dir), template_name, title_prompt)

    @staticmethod
    def _read_script(project_dir: Path) -> str:
        script_file = project_dir / "script.txt"
        try:
            return script_file.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise FileNotFoundError(f"台本ファイルを読み込めません: {script_file}") from error

    @staticmethod
    def _save(project_dir: Path, files: dict[str, str]) -> tuple[Path, ...]:
        paths: list[Path] = []
        for name, content in files.items():
            path = project_dir / name
            path.write_text(content, encoding="utf-8")
            paths.append(path)
        return tuple(paths)
