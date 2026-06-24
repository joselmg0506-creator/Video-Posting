# GO-LIVE checklist

How to take the pipeline from "renders locally" to "posting to 3 YouTube channels."
Work top to bottom. Nothing posts until **Step 5** (`posting.enabled: true`) — until then every
channel just renders to `data/processed/` so you can inspect the output safely.

The three channels (defined under `channels:` in `config.yaml`):

| name | content_type | token file | what it posts |
|---|---|---|---|
| `clips` | `clips` | `secrets/youtube_token.json` | Twitch/YouTube streamer clips (already working) |
| `movies` | `story_film` | `secrets/youtube_token_movies.json` | original AI story films (Pixar-style animated shorts) |
| `characters` | `ai_character` | `secrets/youtube_token_characters.json` | recurring AI-character "brainrot" episodes |

> The Reddit-story brainrot producer still ships (set a channel's `content_type: reddit_story`)
> but channel #2's default is now the cinematic **`story_film`** mode.

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

## 2. Channel #2 — `movies` (AI story films)

Original AI stories told like short animated movies: the AI writes a self-contained story +
a cast with locked looks, generates each scene with Flux (default Pixar-style 3D), and narrates
it over a cinematic slideshow with captions. Fully original → no reused-content/licensing risk.

- [ ] **Flux key**: set `FAL_KEY` in `.env` (https://fal.ai) — this channel generates every
      scene image. *(Alt: `REPLICATE_API_TOKEN` + `story_film.image_provider: replicate`.)*
- [ ] *(optional)* Drop Content-ID-safe score tracks (YouTube Audio Library) into `data/music/`
- [ ] *(optional)* Tune `config.yaml → channels[movies].story_film`: `style`
      (`3d_animated` | `anime` | `cinematic_realistic` | `storybook`), `scenes`, `themes`, `voice`
- [ ] **Create the YouTube channel** for this content (a Brand Account under your Google login
      lets all 3 channels share one login)
- [ ] **Authorize it** (pick that channel/brand account in the consent screen):
      ```powershell
      .\.venv\Scripts\python -m src.auth_youtube --token-file ./secrets/youtube_token_movies.json
      ```
- [ ] Dry-run: `.\scripts\run.ps1 -DryRun -Channel movies` (makes real Flux calls — small cost)
- [ ] Flip `channels[movies].enabled: true` in `config.yaml`

> Character consistency is by **locked descriptions**: the AI fixes each character's appearance
> once and reuses that exact text in every scene. Good and free to start; if faces drift too
> much, the upgrade is reference-image conditioning (more cost) — ask when you want it.

---

## 3. Channel #3 — `characters` (AI-character brainrot)

- [ ] **Flux key**: set `FAL_KEY` in `.env` (https://fal.ai) — *or* `REPLICATE_API_TOKEN` and
      set `image_provider: replicate`
- [ ] *(optional)* Content-ID-safe music: drop YouTube Audio Library tracks into `data/music/`
      (leave empty for narration-only)
- [ ] **Create the YouTube channel**, then **authorize it**:
      ```powershell
      .\.venv\Scripts\python -m src.auth_youtube --token-file ./secrets/youtube_token_characters.json
      ```
- [ ] Dry-run: `.\scripts\run.ps1 -DryRun -Channel characters` (this makes the first real Flux call)
- [ ] Flip `channels[characters].enabled: true`

The cast persists in `data/character_bible.json` — characters recur (`recurring_rate: 0.4`) so
the universe builds over time. Delete that file to start the cast fresh.

---

## 4. Keys quick-reference (`.env`)

| Key | Needed by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | all channels | titles / scripts / screenwriting / quality score |
| `TWITCH_CLIENT_ID` / `_SECRET` | clips | Twitch Helix |
| `YOUTUBE_COOKIES_FILE` | clips (YT source) | cookies.txt to dodge bot-block |
| `FAL_KEY` *(or `REPLICATE_API_TOKEN`)* | movies, characters | Flux scene/character image gen |
| `DISCORD_WEBHOOK_URL` | optional | per-post + crash + metrics alerts |

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
