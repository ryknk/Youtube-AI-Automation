"""YouTube Data APIクライアント。"""

from pathlib import Path

from youtube_generator.youtube.auth import authenticate


def build_youtube_client(client_secrets_file: Path, token_file: Path):  # type: ignore[no-untyped-def]
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=authenticate(client_secrets_file, token_file), cache_discovery=False)
