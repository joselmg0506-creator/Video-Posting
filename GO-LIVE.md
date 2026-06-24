# GO-LIVE checklist

How to take the pipeline from "renders locally" to "posting to 3 YouTube channels."
Work top to bottom. Nothing posts until **Step 5** (`posting.enabled: true`) — until then every
channel just renders to `data/processed/` so you can inspect the output safely.

The three channels (defined under `channels:` in `config.yaml`):

| name | content_type | token file | what it posts |
|---|---|---|---|
| `clips` | `clips` | `secrets/youtube_token.json` | Twitch/YouTube streamer clips (already working) |
| `stories` | `reddit_story` | `secrets/youtube_token_stories.json` | original AI storytime narrated over gameplay (UnlimitedStories style) |
| `characters` | `brainrot_movie` | `secrets/youtube_token_characters.json` | actual ANIMATED Italian-brainrot mini-films (image-to-video) |

> Producer options that still ship if you want to switch a channel: `story_film` (cinematic
> Flux animated story films), `ai_character` (single-character brainrot intros), and
> `reddit_story` with `visual: ai_illustrated` (per-scene Flux art) or `source: reddit`.

---

## 0. Base setup (once)

- [ ] `.venv` exists and deps installed: `pip install -r requirements.txt`
- [ ] `ffmpeg` + `ffprobe` on PATH (the run scripts auto-find the WinGet install)
- [ ] Copy `.env.example` → `.env` and fill keys as you go (below)
- [ ] `ANTHROPIC_API_KEY` set in `.env` — **required by all three channels** (titles/scripts)

Smoke-test without posting at any time:
```powershell
.\scripts\run.ps1 -DryRun -Channel clips      # renders 1 clip, prints the file, posts nothing
```

---

## 1. Channel #1 — `clips` (closest to live)

- [ ] **Twitch API**: set `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` in `.env`
      (create an app at https://dev.twitch.tv/console — "Application Integration", any redirect)
- [ ] **YouTube source cookies** (only if you keep the YouTube source enabled): export a
      `youtube.com` cookies.txt and set `YOUTUBE_COOKIES_FILE` (YouTube bot-blocks yt-dlp otherwise)
- [ ] **Google Cloud project**: create one, enable **YouTube Data API v3**, make an **OAuth
      client of type Desktop**, download the JSON → `secrets/youtube_client_secret.json`
      (this one client JSON is shared by all 3 channels)
- [ ] **Authorize this channel** (sign in with the account that owns it):
      ```powershell
      .\.venv\Scripts\python -m src.auth_youtube --token-file ./secrets/youtube_token.json
      ```
- [ ] Dry-run check: `.\scripts\run.ps1 -DryRun -Channel clips` → confirm a real `*_final.mp4`
      and a sensible title; watch the logged `quality: N/10` line

> ⚠️ **Source note:** `@IShowSpeed` (the configured YouTube source) is heavily re-clipped by
> everyone — both reference docs flag it as the over-saturated case. Consider leaning on the
> Twitch RaKai/AMP niche or swapping in less-saturated channels. (`config.yaml` → `sources.youtube`.)

---

## 2. Channel #2 — `stories` (AI storytime over gameplay)

Original AI-written storytime narrated over looping gameplay, with karaoke captions
(UnlimitedStories style). Fully original → no reused-content/licensing risk. Cheapest channel
(~$0.008/video: just the LLM script; TTS + gameplay are free).

- [ ] **Gameplay b-roll**: drop a few clean looping clips (Subway Surfers / Minecraft parkour /
      GTA / mobile games) into `data/broll_gameplay/` — **not** `data/broll/` (that's World Cup
      footage for music-edit). This is the one asset this channel needs.
- [ ] *(no Flux key needed)* — `source: original` writes its own stories; `visual: gameplay`
      uses your loops. *(Switch to `visual: ai_illustrated` for per-scene Flux art — needs FAL_KEY.)*
- [ ] *(optional)* Tune `config.yaml → channels[stories].reddit_story`: `themes`, `voice`,
      `target_seconds`. *(Switch `source: reddit` to rewrite real Reddit posts — needs Reddit keys.)*
- [ ] **Create the YouTube channel** (a Brand Account under your Google login lets all 3 share one login)
- [ ] **Authorize it** (pick that channel/brand account in the consent screen):
      ```powershell
      .\.venv\Scripts\python -m src.auth_youtube --token-file ./secrets/youtube_token_stories.json
      ```
- [ ] Dry-run: `.\scripts\run.ps1 -DryRun -Channel stories`
- [ ] Flip `channels[stories].enabled: true` in `config.yaml`

---

## 3. Channel #3 — `characters` (animated brainrot films)

Actual ANIMATED Italian-brainrot mini-films: the AI writes a brainrot story + cast, Flux
renders each scene, then **fal image-to-video animates each scene into a moving clip**, stitched
into a film with a hyped narrator + captions. **Costs ~$0.10–0.40/film** (the image-to-video step).

- [ ] **Flux key**: set `FAL_KEY` in `.env` (https://fal.ai) — used for both the stills and the
      image-to-video. Make sure the account has **credit** (image-to-video is the paid part).
- [ ] *(optional)* Content-ID-safe music: drop YouTube Audio Library tracks into `data/music/`
- [ ] *(optional)* Tune `config.yaml → channels[characters].brainrot_movie`: `scenes`,
      `num_frames` (clip length), `video_model` (budget LTX by default), `voice`
- [ ] **Create the YouTube channel**, then **authorize it**:
      ```powershell
      .\.venv\Scripts\python -m src.auth_youtube --token-file ./secrets/youtube_token_characters.json
      ```
- [ ] Dry-run: `.\scripts\run.ps1 -DryRun -Channel characters` (makes real Flux + video calls — costs credit)
- [ ] Flip `channels[characters].enabled: true`

---

## 4. Keys quick-reference (`.env`)

| Key | Needed by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | all channels | titles / scripts / storywriting / quality score |
| `TWITCH_CLIENT_ID` / `_SECRET` | clips | Twitch Helix |
| `YOUTUBE_COOKIES_FILE` | clips (YT source) | cookies.txt to dodge bot-block |
| `FAL_KEY` *(or `REPLICATE_API_TOKEN`)* | characters (always); stories only if `visual: ai_illustrated` | Flux stills + image-to-video |
| `DISCORD_WEBHOOK_URL` | optional | per-post + crash + metrics alerts |

> The `stories` channel needs **no** Flux key by default (gameplay + free TTS) — just gameplay
> loops in `data/broll_gameplay/`. The `characters` channel needs `FAL_KEY` **with credit**.

---

## 5. Go live

- [ ] Re-read each channel's title/description/tags once more in a dry-run
- [ ] Decide the YouTube **privacy** per channel (`config.yaml` → `channels[*].youtube.privacy`).
      Start at `private` or `unlisted` for the first few real uploads, then `public`
- [ ] *(optional)* Turn on the **quality gate**: set `transform.quality_min` to ~5–6 **after**
      watching the logged `quality: N/10` scores for a few runs (clips channel)
- [ ] **Flip the master switch:** `posting.enabled: true` in `config.yaml`
- [ ] First live run, one item, one channel:
      ```powershell
      .\scripts\run.ps1 -Channel clips -Max 1
      ```
- [ ] Verify it appears on the channel, then let the others run

---

## 6. Automate (Windows Task Scheduler)

`scripts/setup_schedule.ps1` registers 3 daily posting runs (09:00 / 13:00 / 19:00, 1 item each)
+ a metrics digest (22:00). Each run processes **all enabled channels**.

```powershell
.\scripts\setup_schedule.ps1            # register the tasks
.\scripts\remove_schedule.ps1           # unregister
```

To run one channel on its own cadence, schedule `run.ps1 -Channel <name>` instead.

---

## Crash-safety / ops cheatsheet (already built in)

- Interrupted mid-upload? The clip is parked **pending** (never double-posted). Release with:
  `.\.venv\Scripts\python main.py --clear-pending`
- YouTube daily quota (~6 uploads/project/day) exhausting → the run stops cleanly with a Discord
  alert and retries next run; raise it via a Google quota increase or a second Cloud project.
- Any uncaught crash fires a Discord alert (if `DISCORD_WEBHOOK_URL` is set).
- `state.json` is written atomically; a manual run and a scheduled run won't corrupt it.
