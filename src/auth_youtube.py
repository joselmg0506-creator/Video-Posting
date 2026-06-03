"""
One-time OAuth for YouTube Shorts uploads.

  python -m src.auth_youtube

Opens a browser, asks you to grant the youtube.upload scope, then caches
the token at YOUTUBE_TOKEN_FILE (default ./secrets/youtube_token.json).
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from .config import env

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    client_secrets = env("YOUTUBE_CLIENT_SECRETS", "./secrets/youtube_client_secret.json")
    token_file = env("YOUTUBE_TOKEN_FILE", "./secrets/youtube_token.json")
    if not Path(client_secrets).exists():
        raise SystemExit(
            f"Missing {client_secrets}. Download the OAuth Desktop client JSON "
            f"from Google Cloud Console and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    creds = flow.run_local_server(port=0)
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    Path(token_file).write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved token to {token_file}")


if __name__ == "__main__":
    main()
