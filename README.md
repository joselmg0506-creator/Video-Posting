# VideoPOsting

For-fun Python pipeline that pulls clips from Twitch and videos from YouTube, converts them to vertical 9:16, and posts them to **YouTube Shorts** (default) or **TikTok**.

```
sources ──► download ──► ffmpeg 9:16 ──► post ──► dedupe state
(Twitch, YouTube)                       (Shorts / TikTok)
```

## Layout

```
main.py                  # CLI orchestrator (--dry-run supported)
config.yaml              # sources, processing, posting target
src/
  config.py              # loads .env + config.yaml
  state.py               # JSON dedupe of already-posted clip IDs
  sources/
    twitch.py            # Twitch Helix API + yt-dlp download
    youtube.py           # yt-dlp wrapper
  processor/video.py     # ffmpeg → 1080x1920 (blur_pad / crop / letterbox)
  poster/
    youtube.py           # YouTube Data API v3 uploader
    tiktok.py            # TikTok Content Posting API client
  auth_youtube.py        # one-time OAuth for Shorts
  auth_tiktok.py         # one-time OAuth for TikTok
```

## Setup

1. Install [ffmpeg](https://ffmpeg.org/download.html) and put it on PATH.
2. `pip install -r requirements.txt`
3. `cp .env.example .env` and fill in the keys you need.
4. Edit `config.yaml` — broadcaster logins, YouTube URLs, posting target.

### Twitch source

Create an app at https://dev.twitch.tv/console (instant). Put the client id + secret in `.env`:

```
TWITCH_CLIENT_ID=...
TWITCH_CLIENT_SECRET=...
```

### Posting target

Set `posting.target` in `config.yaml` to `youtube_shorts` (recommended) or `tiktok`.

**YouTube Shorts** (free, instant access):
1. https://console.cloud.google.com → new project → enable **YouTube Data API v3**.
2. Create an OAuth client (Desktop type). Download the JSON to `./secrets/youtube_client_secret.json`.
3. `python -m src.auth_youtube` — grant access in the browser; token caches at `./secrets/youtube_token.json`.

A video auto-classifies as a Short when it is vertical and ≤60s; `#Shorts` is added to title/description by the default template. Default privacy is `private` — flip to `public` in `config.yaml` once you're confident.

**TikTok** (requires app approval):
1. Register at https://developers.tiktok.com/, add the **Content Posting API** product, request `video.publish`.
2. Until production review passes, posts only work as `SELF_ONLY` on the developer's own account.
3. `python -m src.auth_tiktok` → paste the printed tokens into `.env`.

## Usage

```bash
python main.py --dry-run     # fetch + process, skip posting
python main.py               # full pipeline (requires posting.enabled: true)
```

Outputs land in `data/processed/` as ready-to-post MP4s. Posted clip IDs are tracked in `data/state.json` so the same clip won't go up twice.

## Caveats

- **Copyright**: reposting other creators' content without permission can get the account struck. Prefer creators who allow clips, your own streams, or transformative edits.
- **YouTube quota**: a video upload costs 1600 units against the default 10,000/day quota — about 6 uploads/day per project before you need a quota increase.
- **TikTok approval**: real reviews can take weeks and apps that look like generic reposting bots get rejected. Frame the use case carefully if you apply.
