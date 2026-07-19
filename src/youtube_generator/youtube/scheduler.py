"""予約公開日時の検証。"""

from datetime import UTC, datetime


def validate_publish_at(publish_at: datetime | None, privacy: str) -> str | None:
    if publish_at is None:
        return None
    if publish_at.tzinfo is None:
        raise ValueError("予約日時にはタイムゾーンを含めてください。")
    if privacy != "private":
        raise ValueError("予約公開では公開設定を private にしてください。")
    if publish_at <= datetime.now(UTC):
        raise ValueError("予約日時は未来の日時を指定してください。")
    return publish_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
