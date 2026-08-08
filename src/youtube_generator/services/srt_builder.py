"""SRT字幕本文を組み立てる。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """1つの字幕表示区間。"""

    text: str
    duration_seconds: float


class SrtBuilder:
    """音声時間に合わせた連続SRT字幕を生成する。"""

    def build(self, cues: tuple[SubtitleCue, ...], start_offset_seconds: float = 0.0) -> str:
        """字幕キューからSRT形式の文字列を返す。start_offset_secondsだけ開始時刻を遅らせる。"""
        if not cues:
            raise ValueError("字幕キューがありません。")

        elapsed_milliseconds = round(start_offset_seconds * 1000)
        blocks: list[str] = []
        for index, cue in enumerate(cues, start=1):
            if not cue.text.strip() or cue.duration_seconds <= 0:
                raise ValueError("字幕テキストまたは音声長が不正です。")
            duration_milliseconds = round(cue.duration_seconds * 1000)
            end_milliseconds = elapsed_milliseconds + duration_milliseconds
            blocks.append(
                f"{index}\n"
                f"{self._format_timestamp(elapsed_milliseconds)} --> "
                f"{self._format_timestamp(end_milliseconds)}\n"
                f"{cue.text.strip()}"
            )
            elapsed_milliseconds = end_milliseconds
        return "\n\n".join(blocks) + "\n"

    @staticmethod
    def _format_timestamp(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
