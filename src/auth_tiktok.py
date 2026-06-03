"""
One-time OAuth helper. Run with:

  python -m src.auth_tiktok

It opens a browser to TikTok's consent screen, captures the code on a tiny
local HTTP server, exchanges it for tokens, and prints them so you can paste
into .env (TIKTOK_ACCESS_TOKEN / TIKTOK_REFRESH_TOKEN).
"""
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .config import env

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"


def main() -> None:
    client_key = env("TIKTOK_CLIENT_KEY", required=True)
    client_secret = env("TIKTOK_CLIENT_SECRET", required=True)
    redirect_uri = env("TIKTOK_REDIRECT_URI", "http://localhost:8080/callback")
    parsed = urlparse(redirect_uri)
    port = parsed.port or 8080

    state = secrets.token_urlsafe(16)
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    print(f"Opening browser:\n  {url}\n")
    webbrowser.open(url)

    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            captured.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"You can close this window.")

        def log_message(self, *_):
            pass

    httpd = HTTPServer(("localhost", port), Handler)
    while "code" not in captured and "error" not in captured:
        httpd.handle_request()

    if "error" in captured:
        raise SystemExit(f"OAuth error: {captured}")
    if captured.get("state") != state:
        raise SystemExit("State mismatch — possible CSRF.")

    r = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": captured["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    print("\nPaste these into your .env file:\n")
    print(f"TIKTOK_ACCESS_TOKEN={body['access_token']}")
    print(f"TIKTOK_REFRESH_TOKEN={body.get('refresh_token', '')}")
    print(f"\n(expires in {body.get('expires_in')}s)")


if __name__ == "__main__":
    main()
