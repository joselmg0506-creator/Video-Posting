"""
One-time OAuth for YouTube Shorts uploads. Run once PER CHANNEL.

  python -m src.auth_youtube                                   # default channel token
  python -m src.auth_youtube --token-file ./secrets/youtube_token_reddit.json
  python -m src.auth_youtube --token-file ./secrets/youtube_token_characters.json

Opens a browser, asks you to grant the upload + read-only scopes (read-only is needed for
the metrics digest), then caches the token at the given path (or YOUTUBE_TOKEN_FILE /
./secrets/youtube_token.json by default). Sign in with the Google account that owns the
target channel — switch accounts / brand account in the consent screen to bind each token
to a different channel. The path here must match that channel's `token_file` in config.yaml.
"""
import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from .config import env

# Must match src/poster/youtube.py SCOPES so the cached token carries every scope the
# uploader AND the metrics digest use (otherwise readonly stats calls fail).
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="One-time YouTube OAuth (run once per channel).")
    ap.add_argument("--token-file", default=None,
                    help="where to save the token (default: $YOUTUBE_TOKEN_FILE or "
                         "./secrets/youtube_token.json). Use a distinct path per channel.")
    ap.add_argument("--client-secrets", default=None,
                    help="OAuth Desktop client JSON (default: $YOUTUBE_CLIENT_SECRETS or "
                         "./secrets/youtube_client_secret.json). Shared across channels.")
    args = ap.parse_args()

    client_secrets = args.client_secrets or env(
        "YOUTUBE_CLIENT_SECRETS", "./secrets/youtube_client_secret.json")
    token_file = args.token_file or env(
        "YOUTUBE_TOKEN_FILE", "./secrets/youtube_token.json")
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
