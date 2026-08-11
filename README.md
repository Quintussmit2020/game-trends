# game-trends

Weekly tracker of game industry trends with an indie/small-team lens, built to answer
one question over time: **which types of games do well, and what are their defining
features?**

Every Friday a scheduled Claude session collects public Steam data, appends a weekly
snapshot to this repo, and regenerates the HTML report.

**Latest report:** `docs/index.html` (via GitHub Pages once enabled: Settings -> Pages ->
deploy from branch `main`, folder `/docs`). Archived weeks live in `docs/reports/`.

## What gets tracked

- **Breakouts** - new releases (last 14 days) whose estimated revenue outruns their
  likely team size, with tags, price, review velocity, and team classification
- **Tag momentum** - which tag combinations carry the most estimated revenue among
  successful indie releases, accumulating week over week into trend lines
- **Most played** - Steam top 100 by concurrent players with week-over-week movement
- **Top sellers** - current global top sellers, indies highlighted

## Data sources

All public, no keys: Steam charts service (most played), Steam store search
(top sellers, new releases), Steam appdetails + review summaries, SteamSpy (tags,
owner ranges), per-app current player counts.

## Estimates and their limits

Revenue is estimated with a review-count heuristic (Boxleiter method):
`sales ~ total_reviews x 35`, `net revenue ~ sales x price x 0.55`.
Team size is inferred from developer/publisher records. Both are directional
signals for spotting patterns, not accounting data.

## Repo layout

```
collector/collect.py   data collection -> data/<week>/*.json + history CSVs
collector/report.py    report generation -> docs/index.html + docs/reports/<week>.html
data/<YYYY-Www>/       weekly JSON snapshots (the permanent record)
data/*_history.csv     long-run derived series (tag momentum, weekly summary)
docs/                  generated HTML reports (GitHub Pages root)
```

## Running manually

```
cd collector
python3 collect.py            # ~20 min, polite request pacing
python3 report.py
```

Both default to the current ISO week; pass `--week 2026-W33` to target a specific week.
