# VideoPOsting

For-fun Python pipeline that pulls clips from Twitch and videos from YouTube, converts them to vertical 9:16, and posts them to **YouTube Shorts** (default) or **TikTok**.

```
sources ──► download ──► ffmpeg 9:16 ──► transform ──────────► post ──► dedupe state
(Twitch, YouTube)                        (AI commentary +      (Shorts / TikTok)
                                          voiceover + captions)
```

The **transform** stage is what keeps the channel monetizable: both YouTube ("reused" /
"inauthentic" content) and TikTok ("unoriginal" content) demonetize bare clip reposts.
It adds genuinely-varied AI commentary, an offline voiceover, and burned-in captions per
clip — and discloses the content as AI-assisted on every post. Disable it with
`transform.enabled: false` to revert to plain reposting (not recommended).

> **Now multi-channel.** The pipeline drives **three** separate YouTube channels from one
> codebase via the `channels:` registry in `config.yaml`: `clips` (streamer clips, above),
> `reddit` (AI-narrated stories over gameplay / AI art), and `characters` (recurring
> AI-character "brainrot"). The shared back-half (9:16 render → karaoke captions → loop
> outro → post) is identical; only each channel's producer (`src/producers/`) differs.
> **To take any channel live, follow [GO-LIVE.md](GO-LIVE.md)** — the step-by-step checklist
> of accounts, keys, and switches.

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
  transform/
    script.py            # AI commentary + title/desc/hashtags + narrate decision (Anthropic)
    tts.py               # neural voiceover w/ word timings (edge-tts) + offline fallback
    transcribe.py        # local Whisper ASR — word timings for the streamer's own speech
    compose.py           # ffmpeg: mix voiceover + burn hook banner + karaoke captions
    endcard.py           # loop-back outro + corner CTA
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

### Transform stage (AI commentary)

On by default. The voiceover and captions are **fully offline** (no API key), but writing
the per-clip commentary uses the Anthropic API, so add one key to `.env`:

```
ANTHROPIC_API_KEY=...
```

Tune the voice/persona/length under `transform:` in `config.yaml`. Voiceover uses free
neural voices (edge-tts, needs internet); set `voiceover.backend: offline` for keyless
SAPI5/espeak. Captions are word-by-word "karaoke": timed to the voiceover when narrating,
or to the streamer's own speech via local Whisper (`captions.asr`) when not — the Whisper
model (~145 MB for `base`) downloads once on first run and is cached.
`transform.ai_label: true` sets the native AI-disclosure flag on each post
(YouTube `containsSyntheticMedia`, TikTok `is_aigc`) — labeling carries no reach or
monetization penalty and avoids strikes for non-disclosure.

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

## Scheduling (post automatically)

Run the pipeline a few times a day via Windows Task Scheduler:

```powershell
.\scripts\setup_schedule.ps1 -DryRun     # 3x/day, PREVIEW only (renders, never posts)
.\scripts\setup_schedule.ps1             # 3x/day, posts if posting.enabled: true
.\scripts\setup_schedule.ps1 -Times 10:00,20:00   # custom times
.\scripts\remove_schedule.ps1            # remove the schedule
```

Each slot posts **1** clip; the default morning/lunch/evening times = **3 Shorts/day**,
spaced out — the research sweet spot, and under YouTube's ~6-upload/day quota. The setup
also registers a **daily metrics dashboard** (`VideoPOsting_Metrics`, 10pm; or just that
task via `setup_schedule.ps1 -MetricsOnly`) — `run.ps1` is the
underlying runner (handles venv + ffmpeg). **Nothing posts until `posting.enabled: true`**
in `config.yaml` (+ a one-time `python -m src.auth_youtube`), so a non-`-DryRun` schedule is
still safe to register early — it just stages files until you flip the switch.

## Notifications & metrics

Set `DISCORD_WEBHOOK_URL` in `.env` (Discord → Server Settings → Integrations → Webhooks)
and the pipeline posts to Discord: a card per published Short, upload failures, a per-run
summary, and a daily digest (`python main.py --metrics`) with a top-clips leaderboard plus
**per-creator and narrated-vs-raw average views** so you can see what's working. Toggle with
`notifications.discord.enabled`; it's a no-op if the webhook is unset.

## Caveats

- **Copyright**: the transform stage adds commentary but the underlying footage is still someone else's — it lowers, not eliminates, copyright-strike risk. Prefer creators who allow clips, your own streams, or footage you have rights to.
- **AI disclosure**: commentary about *real* streamers should stay accurate and non-defamatory; the stage runs unattended, so spot-check occasionally if you post about real people. Keep `transform.ai_label: true` so posts are labeled as AI-assisted.
- **YouTube quota**: a video upload costs 1600 units against the default 10,000/day quota — about 6 uploads/day per project before you need a quota increase.
- **TikTok approval**: real reviews can take weeks and apps that look like generic reposting bots get rejected. Frame the use case carefully if you apply.
