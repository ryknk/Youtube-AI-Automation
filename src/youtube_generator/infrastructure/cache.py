"""テーマ単位で中間成果物を再利用するローカルキャッシュ。"""

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable


class CacheManager:
    """SHA-256 キー単位で成果物を保存・復元するファイルキャッシュ。"""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(*values: str) -> str:
        """テーマや入力ファイル内容から、保存先に安全なキーを生成する。"""
        digest = hashlib.sha256()
        for value in values:
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    @classmethod
    def make_file_key(cls, artifact_name: str, files: Iterable[Path], fingerprint: str = "") -> str:
        """入力ファイルの内容と設定値からキャッシュキーを生成する。"""
        digest = hashlib.sha256()
        digest.update(artifact_name.encode("utf-8"))
        digest.update(fingerprint.encode("utf-8"))
        for file_path in sorted(files, key=lambda path: path.name.lower()):
            digest.update(file_path.name.encode("utf-8"))
            digest.update(file_path.read_bytes())
        return digest.hexdigest()

    def exists(self, cache_key: str, artifact_name: str) -> bool:
        """指定成果物がキャッシュ済みか確認する。"""
        artifact_dir = self._artifact_dir(cache_key, artifact_name)
        return artifact_dir.is_dir() and any(path.is_file() for path in artifact_dir.iterdir())

    def save_files(self, cache_key: str, artifact_name: str, files: Iterable[Path]) -> tuple[Path, ...]:
        """成果物をキャッシュへコピーして保存する。"""
        artifact_dir = self._artifact_dir(cache_key, artifact_name)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True)

        saved_files: list[Path] = []
        for source_file in files:
            if not source_file.is_file():
                raise FileNotFoundError(f"キャッシュ対象のファイルが見つかりません: {source_file}")
            destination = artifact_dir / source_file.name
            shutil.copy2(source_file, destination)
            saved_files.append(destination)
        if not saved_files:
            raise ValueError("キャッシュ対象のファイルがありません。")
        self._write_metadata(cache_key)
        return tuple(saved_files)

    def restore_files(self, cache_key: str, artifact_name: str, destination_dir: Path) -> tuple[Path, ...]:
        """キャッシュ済み成果物を出力フォルダへコピーして復元する。"""
        artifact_dir = self._artifact_dir(cache_key, artifact_name)
        if not self.exists(cache_key, artifact_name):
            raise FileNotFoundError(f"キャッシュが見つかりません: {artifact_name}")
        destination_dir.mkdir(parents=True, exist_ok=True)
        restored_files: list[Path] = []
        for cached_file in sorted(artifact_dir.iterdir(), key=lambda path: path.name.lower()):
            if cached_file.is_file():
                destination = destination_dir / cached_file.name
                shutil.copy2(cached_file, destination)
                restored_files.append(destination)
        return tuple(restored_files)

    def delete(self, cache_key: str) -> bool:
        """キーに対応するキャッシュ一式を削除する。"""
        cache_entry = self._entry_dir(cache_key)
        if not cache_entry.exists():
            return False
        shutil.rmtree(cache_entry)
        return True

    def clear(self) -> int:
        """すべてのキャッシュエントリを削除し、削除数を返す。"""
        removed_count = 0
        for entry in self._cache_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
                removed_count += 1
        return removed_count

    def remove_expired(self, expiration_days: int) -> int:
        """保存日時から期限切れのキャッシュを削除する。"""
        if expiration_days < 0:
            raise ValueError("expiration_days は0以上にしてください。")
        expires_before = datetime.now(UTC) - timedelta(days=expiration_days)
        removed_count = 0
        for entry in self._cache_dir.iterdir():
            if not entry.is_dir() or not self._is_expired(entry, expires_before):
                continue
            shutil.rmtree(entry)
            removed_count += 1
        return removed_count

    def _entry_dir(self, cache_key: str) -> Path:
        if len(cache_key) != 64 or any(character not in "0123456789abcdef" for character in cache_key):
            raise ValueError("キャッシュキーはSHA-256の16進数文字列で指定してください。")
        return self._cache_dir / cache_key

    def _artifact_dir(self, cache_key: str, artifact_name: str) -> Path:
        safe_name = artifact_name.replace("/", "_").replace("\\", "_")
        return self._entry_dir(cache_key) / safe_name

    def _write_metadata(self, cache_key: str) -> None:
        metadata_file = self._entry_dir(cache_key) / "metadata.json"
        metadata_file.write_text(
            json.dumps({"created_at": datetime.now(UTC).isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _is_expired(entry: Path, expires_before: datetime) -> bool:
        metadata_file = entry / "metadata.json"
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(str(metadata["created_at"]))
            return created_at < expires_before
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            modified_at = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
            return modified_at < expires_before
