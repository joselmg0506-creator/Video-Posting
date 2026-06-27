# 📋 VideoPOsting — To-Do

Running list of what we want to build next. Newest priorities at the top.
Each item gets its own file in this folder once we start scoping it.

## Focus right now: make the VIDEOS as good as possible
Strategy (set 2026-06-27): perfect video creation/quality on YouTube FIRST. Distribution
(cross-posting to TikTok/IG) is deferred until we see videos actually landing — 3× of low
views is still low; prove the content can pop on one platform, then multiply it.

## Up next — video quality
From the 4-repo research sweep (2026-06-27, SamurAIGPT/MoneyPrinter/ShortGPT/rushindrasinha vs
our code). We already do the advanced version of most of what those repos are known for; these are
the genuine polish gaps, ranked by impact-per-effort. Knock them down top to bottom.

- [x] **1. Per-word caption POP** (small, ALL channels) — DONE (commit 30d122a). Active word now
      scales up (130→112% pop-in bounce) + turns yellow while the rest stay white; one Dialogue line
      per word in `src/transform/compose.py` (_word_pop). Verified via real render + frame grabs.
- [ ] **2. Music bed + speech-aware ducking on CLIPS** (medium, clips) — clips have NO music layer;
      add a Content-ID-safe bed looped+ducked (drop to ~0.12 during speech regions, ~0.25 in gaps
      using the word timings we already compute). `src/transform/compose.py` (3rd amix branch).
- [x] **3. Seed-pinned character images** (small, brainrot) — DONE (commit 8e44167). `seeds` threaded
      through visuals gen functions; brainrot assigns a stable sha1-derived seed per character and
      seeds each scene on its speaker. Best-effort consistency (not a LoRA); shows on next render.
- [ ] **4. Free caption timing from per-line TTS durations** (medium, stories) — derive caption
      windows from known Kokoro per-scene/per-line durations; skip a faster-whisper pass (whisper
      stays as fallback for long lines). `reddit_story.py` _seg_durations + `brainrot_movie.py`.
- [x] **5. Clip-judge same-video dedupe + content-type hint** (small, clips) — DONE (commit d943134).
      Staged peaks from one video (youtube:VID:120/:340) are grouped by _video_key and runners-up
      demoted so a different video is picked first (variety); judge prompt now infers clip type
      (reaction vs just-chatting) and weighs the hook accordingly. NB: literal time-overlap was
      already prevented at staging (_pick_segments spaces peaks ≥1.2×clip_len).
- [x] **6. AI thumbnail / cover frame** (medium, all) — DONE (commit a391089). `src/transform/
      thumbnail.py`: midpoint frame (past the hook) + bold ALL-CAPS title in the UPPER third (clear
      of captions) with heavy outline; emoji/hashtags stripped, wrapped ≤3 lines. Uploaded via
      poster `thumbnails().set` best-effort (toggle `transform.thumbnail.enabled`). NB: custom Shorts
      covers need a channel verified for custom thumbnails — else it logs + keeps the auto frame.

Skipped (deliberately): MoviePy editing-engine rewrite, stock-footage/Bing scraping, fake Reddit-card
hook, green-screen subscribe overlay, paid/ElevenLabs TTS, Gemini image provider, TikTok-TTS proxies,
atempo speed-fit, Haar faces (YuNet is better), per-niche YAML refactor. See workflow run wf_0e1020bf.

## Done (recent)
- [x] **LLM-as-judge clip ranker** (`src/clip_judge.py`) — before downloading, Claude scores each
      candidate clip on hook/clarity/shareability (1-5 each) from its title+views+length, and we
      post the best one WITHIN each creator-priority tier (Kai/Speed order preserved; the judge
      only re-ranks a creator's own clips). Cheap (one metadata-only call/run on the transform
      LLM), best-effort (any failure falls back to the old order). Verified live: it floated Kai's
      "WILDEST Try Not To Laugh 😂" (16.8M views) over "Streamer University applications". Toggle:
      `sources.clip_judge.enabled`. From the `data/info` research brief.
      NOTE: skipped two-pass loudnorm from the same brief — audio is entangled in compose's
      filter_complex, so it'd need a full extra render pass/clip (~2x time) for a minor gain;
      single-pass already hits the -14 LUFS target.
- [x] **Niche hashtag analysis** — `--suggestions` now scrapes the hashtags the niche LEADERS
      actually use (their video descriptions), ranks them by how many leaders use each, and
      stores `niche_hashtags` per channel in suggestions.json. New uploads blend these into the
      description below the video's own AI tags (capped at 8; first 3 show above the title), and
      the dashboard shows a "Hashtags niche leaders use" chip row per channel. Found, e.g.:
      clips → #kaicenat #ishowspeed #tota #rakai · stories → #redditstories #storytime #textingstory
      · characters → #brainrot #italianbrainrot #fyp #tralalerotralala #bombardirocrocodilo
- [x] **Posting cadence analysis** — niche leaders' uploads/day (from their upload history) vs ours,
      in the suggestions + dashboard playbook. Finding: leaders range wildly (~0.1–10/day); our ~2/day
      actual is in range — cadence isn't the bottleneck (titles/timing/length matter more)
- [x] **Posting times** → shifted to 3pm/8pm/11pm CT after data showed midday is dead
- [x] **Kokoro natural TTS** on stories (+ fixed a dedup bug capping stories at 1 post)
- [x] **Title patterns + length** matched to niche leaders

## Backlog / someday
- [ ] 🚀 **Cross-post to TikTok + IG Reels** — GATED: only once video creation is consistently good
      (see Focus above). Biggest *reach* lever; TikTok is the native home of brainrot + reddit-story
      formats, so it also tests a 2nd algorithm that may suit the content better than YT Shorts.
      Two paths: (a) **relay** (Post for Me / PostPeer / upload-post, ~$3/mo at ~270 posts/mo) —
      a pre-approved middleman that posts to TikTok+IG via one API, skipping the platform audits;
      live in days, stays unattended, but a paid 3rd-party dependency. (b) **direct API (free)** —
      native TikTok Content Posting API + IG Reels Graph API, but needs TikTok audit (2–6 wks, posts
      forced private until approved) + IG Business acct & App Review (2–4 wks). Recommendation: start
      with brainrot → TikTok to validate, then expand. Code is ~1 call after render; the cost is the
      audits (direct) or the fee (relay). See `data/info` §7 for the exact API flows.
- [ ] ⚠️ Confirm Google OAuth consent screen is **Published** (Testing → In production) so tokens
      don't expire after ~7 days — the #1 silent-failure risk for the unattended poster (USER action)
- [x] commit `data/history.json` daily for REAL day-over-day trend lines — DONE: `main.py --snapshot`
      (nightly in metrics.yml) records per-video counts; dashboard sparklines use real daily totals
      once 2+ days accrue, else fall back to the publish-date approximation
- [ ] Italian-voice Kokoro trial for the brainrot channel (stories already on Kokoro)
- [ ] Caption polish — WhisperX tighter timing + clipify-style karaoke (from the research sweep)
- [x] Add "best posting time" insight — DONE (posting-time analysis: our slots + niche hours)

## Done
- [x] **Title patterns matched to leaders** — title prompts now add emojis + ALL-CAPS hooks (and
      numbers when natural): clips "Kai LOSES IT 😂", brainrot "CAPPUCCINA vs BOMBARDIRO 💥",
      stories "New Kid DESTROYED The Bully 😱" — closing the 0%→winning-pattern gap
- [x] **Compare videos/metrics vs creators (deeper)** — `src/suggestions.py` now benchmarks
      structured TITLE patterns (word count, emoji/CAPS/number/question %) + LENGTH, leaders vs us;
      tips cite the exact gaps; dashboard shows a "Title & length playbook · vs leaders" per channel
- [x] **Dashboard UI** — "Studio" redesign (Manrope/Space Mono, All↔channel tabs), live in-browser
      refresh via `YT_API_KEY`, schedule pulse, velocity/heat grades, real thumbnails, best-time
      heatmap, competitor-aware "Ways to grow/improve" tips + "Vs niche leaders" benchmark
- [x] Deploy to GitHub Actions cloud (posts with laptop off)
- [x] 3x/day schedule on Texas/Central time (12pm / 3pm / 8pm CT)
- [x] Publish dashboard online via GitHub Pages (phone-viewable)
- [x] Disable local Windows scheduled tasks (no double-posting)
- [x] Clips: drop "Made with AI" label + prioritize top creators first
- [x] Stories: balance boy/girl narrators (was always boy)
- [x] Brainrot: clean, easy-to-follow English (kept Italian voices)
