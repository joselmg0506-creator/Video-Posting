# 📋 VideoPOsting — To-Do

Running list of what we want to build next. Newest priorities at the top.
Each item gets its own file in this folder once we start scoping it.

## Up next
- [x] **Improve the UI dashboard** — DONE (maxed-out "Pulse Cockpit"); see [dashboard-ui.md](dashboard-ui.md)
  - [x] Mobile-first redesign + live in-browser refresh
  - [x] `YT_API_KEY` added → live numbers on
  - [x] Schedule pulse, hero odometer, velocity, heat-score grades, scoreboard, trend, leaderboard, best-time heatmap, thumbnails
  - [ ] (optional follow-up) commit `data/history.json` daily for REAL day-over-day trend lines + reliable WoW deltas

## Backlog / someday
- [ ] Confirm Google OAuth consent screen is **Published** (Testing → In production) so tokens don't expire after ~7 days
- [ ] Add "best posting time" insight (which hour gets the most views per channel)

## Done
- [x] Deploy to GitHub Actions cloud (posts with laptop off)
- [x] 3x/day schedule on Texas/Central time (12pm / 3pm / 8pm CT)
- [x] Publish dashboard online via GitHub Pages (phone-viewable)
- [x] Disable local Windows scheduled tasks (no double-posting)
