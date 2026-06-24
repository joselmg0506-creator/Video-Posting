# Improve the UI dashboard

**Goal:** make the analytics dashboard (https://joselmg0506-creator.github.io/Video-Posting/)
nicer to look at and more useful — especially on the **phone**, since that's where it's viewed.

Current state: dark page with a totals row, per-channel cards, and one flat table of every
video (title / channel / views / likes / comments / date). Functional but plain and static.
Source: `src/dashboard_html.py` (builds `data/dashboard.html`), published by `.github/workflows/pages.yml`.

## Ideas to pick from (decide priorities when we start)
- [ ] **Mobile-first layout** — bigger touch targets, cards stack cleanly, table scrolls/collapses on small screens
- [ ] **Charts** — views-over-time line, per-channel comparison bars (Chart.js via CDN, or matplotlib PNG — matplotlib already a dep)
- [ ] **Thumbnails** — show each Short's thumbnail next to the title
- [ ] **Top performers** — highlight the best video per channel + overall
- [ ] **Engagement rate** — likes/views and comments/views, not just raw counts
- [ ] **Sort/filter the table** — by views, channel, or date (clickable headers)
- [ ] **"Did today post?" status** — green/red indicator per channel for today's 3 slots
- [ ] **Growth velocity** — views/day so new videos aren't buried under old totals
- [ ] **Light/dark toggle** + polish (fonts, spacing, channel color accents)

## Notes / constraints
- Stays a single self-contained HTML file (no server) so GitHub Pages can serve it.
- Data comes from `state.json` + live YouTube `videos.list(statistics)` per channel token.
- Deeper metrics (retention, CTR, traffic source) need the **YouTube Analytics API**
  + `yt-analytics.readonly` scope — bigger lift, flag before committing to it.
- Already has a 15-min `<meta refresh>`; keep it.

## First step when we resume
Decide the top 3 from the list above, then rework `build()` in `src/dashboard_html.py`.
