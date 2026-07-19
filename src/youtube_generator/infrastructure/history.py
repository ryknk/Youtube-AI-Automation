"""実行履歴をJSON Linesで永続化する。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunHistoryRecorder:
    """工程の開始・完了・失敗を1行1イベントとして記録する。"""

    def __init__(self, history_file: Path) -> None:
        self._history_file = history_file

    def record(self, run_id: str, event: str, **details: Any) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "event": event,
            **details,
        }
        try:
            with self._history_file.open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as error:
            raise RuntimeError(f"実行履歴を保存できません: {self._history_file}") from error
