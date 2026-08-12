# game-trends

Weekly tracker of game industry trends with an indie/small-team lens, built to answer
one question over time: **which types of games do well, and what are their defining
features?**

Every Friday a scheduled Claude session collects public Steam data, appends a weekly
snapshot to this repo, and regenerates the HTML report.

**Latest report:** `docs/index.html` redirects to the newest week (via GitHub Pages once
enabled: Settings -> Pages -> deploy from branch `main`, folder `/docs`). Archived weeks
live in `docs/reports/`. The report has two tabs, Market and Visual Novels, and a
light/dark toggle.

## Market tab

- **Breakouts** - new releases (last 14 days) whose estimated revenue outruns their
  likely team size, with tags, price, review velocity and team classification
- **Tag momentum** - which tags carry the most estimated revenue among successful indie
  releases, accumulating week over week into trend lines
- **Most played** - Steam top 100 by concurrent players with week-over-week movement
- **Top sellers** - current global top sellers, indies highlighted

## Visual Novels tab

VN sub-genres are only legible through tag combinations, so cluster membership comes from
Steam's own multi-tag search (`tags=3799,<tag>` is an AND) rather than from SteamSpy,
which has no tag data for brand-new releases.

- **The hybrid lane** - horror/psychological, point-and-click/puzzle and mystery/detective
  VNs, the clusters that out-perform pure romance among visible titles
- **What performs** - every cluster measured only on VNs with 500+ reviews, with median
  rating, review count, length and price, so it reflects titles that found an audience
  rather than everything that shipped
- **Proven titles** - the 500+ review set itself, most-reviewed first
- **Tag lift** - tags that over-index among lane titles doing 2x the lane median
- **VN releases** - the last 30 days, with cluster membership

## Data sources

All public, no keys:

| Signal | Source |
|---|---|
| Most played | Steam charts service |
| Top sellers, new releases, tag intersections | Steam store search |
| Price, release date, developer/publisher | Steam appdetails |
| Review counts and scores | Steam review API |
| **Playtime** | Steam review API - each review carries the reviewer's own playtime. SteamSpy's playtime fields are paywalled and return 0. |
| **AI disclosure** | The store page. Steam's required AI Generated Content Disclosure is not in any API. |
| Tags and owner ranges for established titles | SteamSpy |

## Estimates and their limits

Revenue uses a review-count heuristic (Boxleiter method): `sales ~ total_reviews x 35`,
`net ~ sales x price x 0.55`. Team size is inferred from developer/publisher records.
Both are directional signals for spotting patterns, not accounting data.

Playtime is the median of a recent sample of reviewers' own playtime. Reviewers
self-select and tend to review early, so read it as "how long players actually spend",
not a completionist figure.

AI disclosure is self-reported by developers. No badge means no disclosure was filed, not
that no AI was used. The scope classification (translation only / some visuals / core
assets) matters more than the yes/no.

Proven-title medians describe survivors. Most VNs on Steam never reach them.

## Repo layout

```
collector/collect.py       market collection -> data/<week>/*.json + history CSVs
collector/vn_collect.py    VN collection     -> data/<week>/vn.json + vn_cluster_history.csv
collector/ai_disclosure.py shared: Steam AI content disclosure
collector/report.py        report generation -> docs/reports/<week>.html + docs/index.html
data/<YYYY-Www>/           weekly JSON snapshots (the permanent record)
data/vn_baseline.json      one-off 446-title VN corpus with lane analysis
data/*_history.csv         long-run derived series
docs/                      generated HTML reports (GitHub Pages root)
```

## Running manually

```
cd collector
python3 collect.py       # market, ~25-40 min
python3 vn_collect.py    # visual novels, ~35-45 min - run after, not in parallel
python3 report.py
```

Both collectors default to the current ISO week; pass `--week 2026-W33` to target one.
Run them sequentially: both hit Steam's store API and running them together triggers
HTTP 429 rate limiting. Re-running a week rewrites that week's history rows rather than
appending, so a repeat run cannot double-count.
