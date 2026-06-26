# 📋 VideoPOsting — To-Do

Running list of what we want to build next. Newest priorities at the top.
Each item gets its own file in this folder once we start scoping it.

## Up next
- [ ] **Apply the title-pattern findings** → our generated titles use ~0% emojis/numbers/ALL-CAPS,
  but niche leaders use them heavily (clips 83% emoji, characters 83% CAPS + 42% num). Update the
  title-generation prompts in the producers to match the winning patterns. (Surfaced by the
  competitor playbook below.)

## Backlog / someday
- [ ] Confirm Google OAuth consent screen is **Published** (Testing → In production) so tokens don't expire after ~7 days
- [ ] Add "best posting time" insight (which hour gets the most views per channel)
- [ ] (optional) commit `data/history.json` daily for REAL day-over-day trend lines + reliable WoW deltas

## Done
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
