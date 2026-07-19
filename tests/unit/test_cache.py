"""SHA-256 ベースの成果物キャッシュのテスト。"""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from youtube_generator.infrastructure.cache import CacheManager


class CacheManagerTests(unittest.TestCase):
    def test_save_restore_exists_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source" / "script.txt"
            source.parent.mkdir()
            source.write_text("テスト台本", encoding="utf-8")
            manager = CacheManager(root / "cache")
            cache_key = CacheManager.make_key("theme", "テスト")

            manager.save_files(cache_key, "script", (source,))
            restored = manager.restore_files(cache_key, "script", root / "restored")

            self.assertTrue(manager.exists(cache_key, "script"))
            self.assertEqual(restored[0].read_text(encoding="utf-8"), "テスト台本")
            self.assertTrue(manager.delete(cache_key))
            self.assertFalse(manager.exists(cache_key, "script"))

    def test_clear_and_remove_expired(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "image.png"
            source.write_bytes(b"png")
            manager = CacheManager(root / "cache")
            expired_key = CacheManager.make_key("expired")
            active_key = CacheManager.make_key("active")
            manager.save_files(expired_key, "image", (source,))
            manager.save_files(active_key, "image", (source,))
            metadata_file = root / "cache" / expired_key / "metadata.json"
            metadata_file.write_text(
                json.dumps({"created_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}),
                encoding="utf-8",
            )

            self.assertEqual(manager.remove_expired(expiration_days=1), 1)
            self.assertFalse(manager.exists(expired_key, "image"))
            self.assertEqual(manager.clear(), 1)

    def test_file_key_changes_when_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "scene01.txt"
            source.write_text("最初の内容", encoding="utf-8")
            first_key = CacheManager.make_file_key("voice", (source,), "settings")
            source.write_text("変更後の内容", encoding="utf-8")
            second_key = CacheManager.make_file_key("voice", (source,), "settings")

        self.assertNotEqual(first_key, second_key)


if __name__ == "__main__":
    unittest.main()
