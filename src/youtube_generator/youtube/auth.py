"""OAuth 2.0認証とトークンの永続化。"""

from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def authenticate(client_secrets_file: Path, token_file: Path):  # type: ignore[no-untyped-def]
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if token_file.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if not client_secrets_file.is_file():
            raise FileNotFoundError(f"OAuthクライアント設定が見つかりません: {client_secrets_file}")
        credentials = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES).run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials
