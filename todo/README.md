# 📋 VideoPOsting — To-Do

Running list of what we want to build next. Newest priorities at the top.
Each item gets its own file in this folder once we start scoping it.

## Up next
- [ ] (nothing queued — pick the next idea from Backlog, or react to the dashboard playbook)

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
