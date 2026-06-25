# 📋 VideoPOsting — To-Do

Running list of what we want to build next. Newest priorities at the top.
Each item gets its own file in this folder once we start scoping it.

## Up next
- [ ] **Improve the UI dashboard** — see [dashboard-ui.md](dashboard-ui.md)
  - [x] Mobile-first redesign
  - [x] Live in-browser refresh (updates on tab refresh, not just after a post)
  - [ ] **YOUR STEP:** create a YouTube Data API key + add GitHub secret `YT_API_KEY` to switch live numbers on
  - [ ] (later) charts, thumbnails, sortable table — deferred for now

## Backlog / someday
- [ ] Confirm Google OAuth consent screen is **Published** (Testing → In production) so tokens don't expire after ~7 days
- [ ] Add "best posting time" insight (which hour gets the most views per channel)

## Done
- [x] Deploy to GitHub Actions cloud (posts with laptop off)
- [x] 3x/day schedule on Texas/Central time (12pm / 3pm / 8pm CT)
- [x] Publish dashboard online via GitHub Pages (phone-viewable)
- [x] Disable local Windows scheduled tasks (no double-posting)
