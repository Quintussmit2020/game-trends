#!/usr/bin/env python3
"""Generate the weekly game-trends HTML report from a snapshot.

Two tabs:
  Market        - the wider Steam picture, indie lens
  Visual Novels - VN sub-genre clusters, with a standing focus on the
                  horror / psychological / point-and-click hybrid lane

Usage: python3 report.py [--week 2026-W33] [--datadir ../data] [--docsdir ../docs]
Writes docs/reports/<week>.html and docs/index.html (redirect to latest).

Template placeholders use @@NAME@@ tokens rather than str.format, so CSS and JS
braces need no escaping.
"""
import argparse
import csv
import datetime as dt
import glob
import html
import json
import os

ESC = html.escape


def load_week(datadir, week):
    base = os.path.join(datadir, week)
    out = {}
    for name in ("summary", "new_releases", "topsellers", "mostplayed", "vn"):
        p = os.path.join(base, f"{name}.json")
        out[name] = json.load(open(p)) if os.path.exists(p) else None
    return out


def load_history(datadir):
    weeks = sorted(os.path.basename(p) for p in glob.glob(os.path.join(datadir, "*-W*")))
    hist = []
    for w in weeks:
        p = os.path.join(datadir, w, "summary.json")
        if os.path.exists(p):
            hist.append(json.load(open(p)))
    return hist


def load_vn_cluster_history(datadir):
    p = os.path.join(datadir, "vn_cluster_history.csv")
    if not os.path.exists(p):
        return {}, []
    series, weeks = {}, []
    with open(p) as f:
        for row in csv.DictReader(f):
            w = row["week"]
            if w not in weeks:
                weeks.append(w)
            series.setdefault(row["cluster"], {})[w] = int(row.get("releases_this_week") or 0)
    return series, sorted(weeks)


def load_baseline(datadir):
    p = os.path.join(datadir, "vn_baseline.json")
    return json.load(open(p)) if os.path.exists(p) else None


def fmt_usd(n):
    if n is None:
        return "-"
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}k"
    return f"${n:,.0f}"


def fmt_int(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "-"


def fmt_hours(h):
    """Playtime, rounded to a resolution the estimate can actually support."""
    if not h:
        return "-"
    if h < 10:
        return f"{h:.1f}h"
    return f"{round(h)}h"


def ai_badge(rec):
    """Steam AI disclosure, shown with its scope. Absence of a badge means the
    developer filed no disclosure, not that no AI was used."""
    if not rec.get("ai_disclosed"):
        return ""
    scope = rec.get("ai_scope") or "unspecified"
    heavy = scope in ("core assets", "visuals + audio")
    note = ESC(rec.get("ai_note") or "")
    return (f'<span class="ai{" ai-heavy" if heavy else ""}" title="{note}">'
            f'AI: {ESC(scope)}</span>')


def store_link(appid, name):
    """Game name linked to its Steam store page. Names are untrusted data, so they
    are escaped; the appid is coerced to int so it can never break out of the href."""
    label = ESC(str(name))
    try:
        aid = int(appid)
    except (TypeError, ValueError):
        return label
    return (f'<a href="https://store.steampowered.com/app/{aid}/" '
            f'target="_blank" rel="noopener noreferrer">{label}</a>')


# --------------------------------------------------------------------------
# Market tab
# --------------------------------------------------------------------------

def market_analysis(summary, releases):
    paras = []
    br = summary.get("breakouts") or []
    if br:
        top = br[0]
        team = {"self_published_indie": "a self-published team",
                "indie_with_publisher": "an indie team with a publisher",
                "aaa_or_publisher": "a major publisher"}.get(top["team_class"], "an unknown team")
        tags = ", ".join(top["tags"][:4]) if top.get("tags") else "no tag data"
        paras.append(
            f"The breakout of the week is <strong>{ESC(top['name'])}</strong> from {team}, "
            f"released {ESC(top.get('release_date') or 'recently')} at ${top.get('price_usd', 0):.2f}. "
            f"It has {top.get('total_reviews', 0):,} reviews ({top.get('pct_positive') or '-'}% positive), "
            f"which points to roughly {fmt_usd(top.get('est_net_usd'))} net revenue on the standard "
            f"reviews-to-sales heuristic. Its defining tags: {ESC(tags)}.")
    tm = summary.get("tag_momentum") or []
    if tm:
        top5 = ", ".join(t["tag"] for t in tm[:5])
        paras.append(
            f"Among indie releases that gained real traction this week, the tags carrying the most "
            f"estimated revenue are: <strong>{ESC(top5)}</strong>. Watch how these shift week over week - "
            f"sustained climbs are the signal that a niche is heating up, single-week spikes usually "
            f"just mean one hit game.")
    solo = [r for r in (releases or []) if r.get("team_class") == "self_published_indie"
            and (r.get("est_net_usd") or 0) > 10000]
    if solo:
        names = ", ".join(ESC(r["name"]) for r in solo[:5])
        paras.append(
            f"{len(solo)} self-published releases cleared an estimated $10k net in their launch window: "
            f"{names}. These are the games worth studying - they won without publisher marketing muscle.")
    paras.append(
        "Method note: revenue figures are estimates derived from public review counts "
        "(reviews x 35 x price x 0.55) and should be read as order-of-magnitude signals, "
        "not accounting. Team classification is inferred from developer/publisher records.")
    return "".join(f"<p>{p}</p>" for p in paras)


def build_market_tab(data, summary, history):
    releases = (data["new_releases"] or {}).get("releases", [])
    sellers = (data["topsellers"] or {}).get("top_sellers", [])
    breakouts = summary.get("breakouts") or []
    tags = (summary.get("tag_momentum") or [])[:15]
    counts = summary.get("counts") or {}

    kpis = [
        ("New releases tracked", str(counts.get("new_releases_tracked", 0)), ""),
        ("Indie releases", str(counts.get("indie_new_releases", 0)), "of those tracked"),
        ("Top breakout", ESC(breakouts[0]["name"]) if breakouts else "-",
         fmt_usd(breakouts[0]["est_net_usd"]) + " est. net" if breakouts else ""),
        ("Hot tag", ESC(tags[0]["tag"]) if tags else "-",
         fmt_usd(tags[0]["weight_usd"]) + " est. weight" if tags else ""),
    ]
    kpi_html = "".join(
        f'<div class="tile"><div class="tlabel">{l}</div><div class="tvalue">{v}</div>'
        f'<div class="tsub">{s}</div></div>' for l, v, s in kpis)

    def release_row(r):
        tags_s = ESC(", ".join(r.get("tags", [])[:5]))
        return (f"<tr><td>{store_link(r.get('appid'), r['name'])}{ai_badge(r)}</td>"
                f"<td>{ESC(r.get('release_date') or '-')}</td>"
                f"<td class='num'>${r.get('price_usd', 0):.2f}</td>"
                f"<td>{ESC((r.get('team_class') or '').replace('_', ' '))}</td>"
                f"<td class='num'>{fmt_int(r.get('total_reviews', 0))}</td>"
                f"<td class='num'>{r.get('pct_positive') if r.get('pct_positive') is not None else '-'}%</td>"
                f"<td class='num'>{fmt_usd(r.get('est_net_usd'))}</td>"
                f"<td class='tags'>{tags_s}</td></tr>")

    breakout_rows = "".join(release_row(r) for r in breakouts)
    seller_rows = "".join(
        f"<tr{' class=hl' if s.get('team_class') != 'aaa_or_publisher' else ''}>"
        f"<td>{i+1}</td><td>{store_link(s.get('appid'), s['name'])}</td>"
        f"<td class='num'>${s.get('price_usd', 0):.2f}</td>"
        f"<td>{ESC((s.get('team_class') or '').replace('_', ' '))}</td>"
        f"<td class='num'>{fmt_int(s.get('ccu_now')) if s.get('ccu_now') is not None else '-'}</td>"
        f"<td class='num'>{s.get('pct_positive') if s.get('pct_positive') is not None else '-'}%</td></tr>"
        for i, s in enumerate(sellers[:25]))

    trend = ("<p class='note'>Trend lines over time appear here from week two onward, "
             "as the data record accumulates.</p>" if len(history) < 2
             else "<div id='tagtrend' class='chart'></div>")

    return f"""
<div class="kpis">{kpi_html}</div>

<h2>Breakouts of the week</h2>
<p class="sub">Indie releases (last 14 days) ranked by estimated net revenue.</p>
<div id="breakoutchart" class="chart"></div>
<table><thead><tr><th>Game</th><th>Released</th><th>Price</th><th>Team</th><th>Reviews</th>
<th>Positive</th><th>Est. net</th><th>Top tags</th></tr></thead>
<tbody>{breakout_rows}</tbody></table>

<h2>Tag momentum</h2>
<p class="sub">Tags of successful indie releases this week, weighted by estimated net revenue.</p>
<div id="tagchart" class="chart"></div>
{trend}

<h2>Most played - biggest climbers</h2>
<div id="gainerchart" class="chart"></div>

<h2>Top sellers right now</h2>
<p class="sub">Current global top sellers (hardware excluded). Blue edge = indie.</p>
<table><thead><tr><th>#</th><th>Game</th><th>Price</th><th>Team</th><th>Players now</th>
<th>Positive</th></tr></thead><tbody>{seller_rows}</tbody></table>

<h2>What this means</h2>
<div class="analysis">{market_analysis(summary, releases)}</div>
"""


# --------------------------------------------------------------------------
# Visual Novels tab
# --------------------------------------------------------------------------

def build_vn_tab(vn, baseline):
    if not vn and not baseline:
        return ("<p class='note'>No visual novel data yet. Run vn_collect.py to populate "
                "this tab.</p>")

    vn = vn or {}
    counts = vn.get("counts") or {}
    lane_names = vn.get("hybrid_lane_clusters") or (
        baseline or {}).get("lane_analysis", {}).get("lane_clusters", [])
    la = (baseline or {}).get("lane_analysis", {})
    overlap = la.get("horror_and_pointclick_overlap", {})

    # KPI row leads with the lane, because that is the question this tab exists to answer
    kpis = []
    if overlap:
        kpis.append(("Horror x point-and-click", str(overlap.get("both", 0)),
                     f"of {(baseline or {}).get('corpus_size', 0)} VNs do both"))
        kpis.append(("Median reviews, that overlap", fmt_int(overlap.get("both_median_reviews", 0)),
                     f"vs {fmt_int(la.get('lane_median_reviews', 0))} lane, "
                     f"{fmt_int(baseline_median(baseline))} all VNs"))
    kpis.append(("VN releases tracked", str(counts.get("releases", 0)),
                 f"last {vn.get('window_days', 30)} days"))
    kpis.append(("Proven titles", str(counts.get("proven", counts.get("market_titles", 0))),
                 f"{vn.get('proven_min_reviews', 500)}+ reviews"))
    kpi_html = "".join(
        f'<div class="tile"><div class="tlabel">{l}</div><div class="tvalue">{v}</div>'
        f'<div class="tsub">{s}</div></div>' for l, v, s in kpis)

    # Cluster table: baseline share vs this week's new supply
    base_clusters = {c["cluster"]: c for c in (baseline or {}).get("cluster_summary", [])}
    week_clusters = {c["cluster"]: c for c in vn.get("cluster_summary", [])}
    rel_clusters = vn.get("release_clusters", {})
    rows = []
    for name in sorted(set(base_clusters) | set(week_clusters),
                       key=lambda n: -(base_clusters.get(n, {}).get("count", 0))):
        b = base_clusters.get(name, {})
        lane = name in lane_names
        rows.append(
            f"<tr class='{'lane' if lane else ''}'><td>{ESC(name)}"
            f"{' <span class=badge>lane</span>' if lane else ''}</td>"
            f"<td class='num'>{b.get('share_pct', '-')}%</td>"
            f"<td class='num'>{fmt_int(b.get('median_reviews', 0))}</td>"
            f"<td class='num'>{b.get('over_1k_reviews', '-')}</td>"
            f"<td class='num'>${b.get('median_price_usd', 0):.2f}</td>"
            f"<td class='num'>{rel_clusters.get(name, 0)}</td></tr>")
    cluster_rows = "".join(rows)

    # Tag lift within the lane
    lift_rows = "".join(
        f"<tr><td>{ESC(t['tag'])}</td><td class='num'>{t['lift']:.2f}x</td>"
        f"<td class='num'>{t['top_count']}</td><td class='num'>{t['lane_count']}</td></tr>"
        for t in (la.get("tag_lift") or [])[:14])

    # This week's VN releases
    tr = vn.get("top_releases") or []
    if tr:
        rel_rows = "".join(
            f"<tr><td>{store_link(r.get('appid'), r['name'])}{ai_badge(r)}</td>"
            f"<td>{ESC(r.get('release_date') or '-')}</td>"
            f"<td class='num'>${r.get('price_usd', 0):.2f}</td>"
            f"<td class='num'>{fmt_int(r.get('total_reviews', 0))}</td>"
            f"<td class='num'>{r.get('pct_positive') if r.get('pct_positive') is not None else '-'}%</td>"
            f"<td class='num'>{fmt_hours(r.get('playtime_hours'))}</td>"
            f"<td class='tags'>{ESC(', '.join(r.get('clusters', [])[:3]))}</td></tr>"
            for r in tr)
        releases_block = f"""<table><thead><tr><th>Game</th><th>Released</th><th>Price</th>
<th>Reviews</th><th>Positive</th><th>Length</th><th>Clusters</th></tr></thead>
<tbody>{rel_rows}</tbody></table>"""
    else:
        releases_block = ("<p class='note'>No VN releases with review traction in the window. "
                          "VNs release in a slower rhythm than the wider market, so quiet weeks "
                          "are normal.</p>")

    # Lane watchlist
    lane_list = vn.get("hybrid_lane") or []
    if lane_list:
        lane_rows = "".join(
            f"<tr><td>{store_link(r.get('appid'), r['name'])}{ai_badge(r)}</td>"
            f"<td class='num'>{fmt_int(r.get('total_reviews', 0))}</td>"
            f"<td class='num'>{r.get('pct_positive') if r.get('pct_positive') is not None else '-'}%</td>"
            f"<td class='num'>${r.get('price_usd', 0):.2f}</td>"
            f"<td class='num'>{fmt_hours(r.get('playtime_hours'))}</td>"
            f"<td class='tags'>{ESC(', '.join(r.get('clusters', [])[:3]))}</td></tr>"
            for r in lane_list[:15])
        lane_block = f"""<table><thead><tr><th>Game</th><th>Reviews</th><th>Positive</th>
<th>Price</th><th>Length</th><th>Clusters</th></tr></thead>
<tbody>{lane_rows}</tbody></table>"""
    else:
        lane_block = "<p class='note'>No lane titles in this week's sample.</p>"

    # Proven titles: the "what do people actually like" view
    proven_sum = vn.get("proven_summary") or []
    proven_titles = vn.get("proven_titles") or []
    min_rev = vn.get("proven_min_reviews", 500)
    if proven_sum:
        prov_rows = "".join(
            f"<tr class='{'lane' if c.get('hybrid_lane') else ''}'><td>{ESC(c['cluster'])}"
            f"{' <span class=badge>lane</span>' if c.get('hybrid_lane') else ''}</td>"
            f"<td class='num'>{c['count']}</td>"
            f"<td class='num'>{c['median_pct_positive'] if c['median_pct_positive'] is not None else '-'}%</td>"
            f"<td class='num'>{fmt_int(c['median_reviews'])}</td>"
            f"<td class='num'>{fmt_hours(c.get('median_hours'))}</td>"
            f"<td class='num'>${c['median_price_usd']:.2f}</td></tr>"
            for c in proven_sum)
        proven_block = f"""<table><thead><tr><th>Cluster</th><th>Titles</th><th>Median positive</th>
<th>Median reviews</th><th>Median length</th><th>Median price</th></tr></thead>
<tbody>{prov_rows}</tbody></table>
<div id="provenchart" class="chart"></div>"""
    else:
        proven_block = ("<p class='note'>Proven-title data appears once the collector has run "
                        "with the proven-titles sweep enabled.</p>")

    if proven_titles:
        pt_rows = "".join(
            f"<tr><td>{store_link(r.get('appid'), r['name'])}{ai_badge(r)}</td>"
            f"<td class='num'>{fmt_int(r.get('total_reviews', 0))}</td>"
            f"<td class='num'>{r.get('pct_positive') if r.get('pct_positive') is not None else '-'}%</td>"
            f"<td class='num'>{fmt_hours(r.get('playtime_hours'))}</td>"
            f"<td class='num'>${r.get('price_usd', 0):.2f}</td>"
            f"<td>{'self-pub' if r.get('self_published') else 'publisher'}</td>"
            f"<td class='tags'>{ESC(', '.join(r.get('clusters', [])[:3]))}</td></tr>"
            for r in proven_titles[:60])
        proven_list = f"""<table><thead><tr><th>Game</th><th>Reviews</th><th>Positive</th>
<th>Length</th><th>Price</th><th>Team</th><th>Clusters</th></tr></thead>
<tbody>{pt_rows}</tbody></table>"""
    else:
        proven_list = ""

    exemplars = ", ".join(ESC(n) for n in (overlap.get("examples") or [])[:6])
    caveat = ESC(vn.get("caveat") or (baseline or {}).get("caveat", ""))

    analysis = f"""
<p>The VN tag space has a spine that is not a differentiator: Story Rich, Singleplayer,
Anime and Adventure sit on two thirds to three quarters of everything tagged Visual Novel.
The sub-genre lives in what comes after those, and most VNs stack three or four clusters
at once rather than picking one.</p>

<p><strong>The lane.</strong> Of {(baseline or {}).get('corpus_size', 0)} visible VNs,
{overlap.get('both', 0)} carry both horror/psychological and point-and-click/puzzle tags.
That overlap has a median of {fmt_int(overlap.get('both_median_reviews', 0))} reviews against
{fmt_int(la.get('lane_median_reviews', 0))} for the broader lane and
{fmt_int(baseline_median(baseline))} across all visible VNs. Company in that space:
{exemplars}.</p>

<p><strong>What travels with the winners.</strong> Inside the lane, the tags that over-index
among titles doing at least twice the lane median are shown in the lift table - Great Soundtrack,
Atmospheric, Detective, Psychological and Point &amp; Click lead, with Episodic and Dark Comedy
appearing far more often than their share of the lane would predict. Pixel Graphics over-indexing
is worth noting for scope: it is not a penalty at this end of the market.</p>

<p class="caveat">{caveat}</p>
"""

    return f"""
<div class="kpis">{kpi_html}</div>

<h2>The hybrid lane</h2>
<p class="sub">Horror / psychological, point-and-click / puzzle, and mystery / detective VNs -
the clusters that out-perform pure romance among visible titles. Watchlist by review count.</p>
{lane_block}

<h2>What performs</h2>
<p class="sub">Every cluster measured only on VNs with {min_rev}+ reviews, so this reflects
titles that found an audience rather than everything that shipped. Sorted by how well
players rate them.</p>
{proven_block}

<h2>Proven titles</h2>
<p class="sub">The {min_rev}+ review set, most-reviewed first.</p>
{proven_list}

<h2>Tags that over-index among lane winners</h2>
<p class="sub">Within the lane, how much more often a tag appears on titles doing at least
2x the lane's median reviews. Above 1.0 means over-represented among the winners.</p>
<div id="liftchart" class="chart"></div>
<table><thead><tr><th>Tag</th><th>Lift</th><th>On winners</th><th>In lane</th></tr></thead>
<tbody>{lift_rows}</tbody></table>

<h2>Sub-genre clusters</h2>
<p class="sub">Share of the visible VN market, with this week's new releases per cluster.
Highlighted rows are the lane.</p>
<table><thead><tr><th>Cluster</th><th>Share</th><th>Median reviews</th><th>Titles &gt;1k reviews</th>
<th>Median price</th><th>New this week</th></tr></thead><tbody>{cluster_rows}</tbody></table>

<h2>VN releases in the window</h2>
{releases_block}

<h2>Reading this</h2>
<div class="analysis">{analysis}</div>
"""


def baseline_median(baseline):
    """Median reviews across all clusters' members, approximated from the corpus summary."""
    if not baseline:
        return 0
    cs = baseline.get("cluster_summary") or []
    if not cs:
        return 0
    vals = sorted(c["median_reviews"] for c in cs)
    return vals[len(vals) // 2]


# --------------------------------------------------------------------------

def build_html(week, data, history, baseline, vn_hist, vn_hist_weeks):
    summary = data["summary"] or {}
    vn = data["vn"]
    ranks = (data["mostplayed"] or {}).get("ranks", [])
    names = (data["mostplayed"] or {}).get("names", {})

    movers = [r for r in ranks if r.get("last_week_rank")]
    for m in movers:
        m["delta"] = (m["last_week_rank"] - m["rank"]) if m.get("last_week_rank") else 0
        m["name"] = names.get(str(m["appid"]), f"app {m['appid']}")
    gainers = sorted(movers, key=lambda m: m["delta"], reverse=True)[:8]

    hist_tag_series = {}
    for h in history:
        for t in (h.get("tag_momentum") or [])[:8]:
            hist_tag_series.setdefault(t["tag"], {})[h["week"]] = t["weight_usd"]

    la = (baseline or {}).get("lane_analysis", {})
    payload = {
        "week": week,
        "breakouts": summary.get("breakouts") or [],
        "tags": (summary.get("tag_momentum") or [])[:15],
        "gainers": gainers,
        "history_weeks": [h["week"] for h in history],
        "history_tags": hist_tag_series,
        # bar length measures lift above 1.0, since 1.0 is "no different from the
        # lane average" - drawing these from zero would make 1.8x and 1.3x look alike
        "lift": [{**t, "excess": round(t["lift"] - 1.0, 3)}
                 for t in (la.get("tag_lift") or [])[:14]],
        "proven": [{"cluster": c["cluster"], "pct": c.get("median_pct_positive") or 0,
                    "reviews": c["median_reviews"], "lane": c.get("hybrid_lane", False)}
                   for c in ((vn or {}).get("proven_summary") or [])],
        "vn_clusters": [{"cluster": c["cluster"], "share_pct": c["share_pct"],
                         "median_reviews": c["median_reviews"],
                         "lane": c.get("hybrid_lane", False)}
                        for c in (baseline or {}).get("cluster_summary", [])],
    }

    page = HTML_TEMPLATE
    page = page.replace("@@WEEK@@", ESC(week))
    page = page.replace("@@GENERATED@@", ESC(summary.get("generated_utc", "")))
    page = page.replace("@@MARKET@@", build_market_tab(data, summary, history))
    page = page.replace("@@VN@@", build_vn_tab(vn, baseline))
    page = page.replace("@@PAYLOAD@@", json.dumps(payload).replace("</", "<\\/"))
    return page


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Trends - @@WEEK@@</title>
<style>
/* Colours live as custom properties on .report, which paints its own surface.
   That matters: this file gets viewed inside panels and iframes that impose
   their own background, and a page relying on the host's surface ends up with
   dark-mode text on a light body or vice versa. .report always brings its own. */
:root { color-scheme: light dark; }
.report {
  --surface:      #fcfcfb;
  --surface-card: #ffffff;
  --border:       #e8e7e3;
  --border-soft:  #f0efec;
  --ink:          #0b0b0b;
  --ink-2:        #45443f;   /* secondary text: 8.0:1 on the light surface */
  --ink-3:        #5c5b55;   /* tertiary / tag text: 6.0:1 */
  --accent:       #256abf;   /* 5.26:1 on the light surface, clears 4.5:1 as link text */
  --accent-warm:  #eb6834;
  --accent-3:     #1baf7a;
  --accent-4:     #eda100;
  --muted-bar:    #a8a79f;
  color-scheme: light;
  background: var(--surface);
  color: var(--ink);
  display: block;
  padding: 24px;
  max-width: 1080px;
  margin-inline: auto;
}
.report[data-theme="dark"] {
  --surface:      #1a1a19;
  --surface-card: #232322;
  --border:       #3d3d39;
  --border-soft:  #2c2c2a;
  --ink:          #ffffff;
  --ink-2:        #d6d5cb;   /* secondary text: 11.4:1 on the dark surface */
  --ink-3:        #b9b8ad;   /* tertiary / tag text: 8.5:1 */
  --accent:       #6ea8ea;   /* raised from #3987e5 to clear 4.5:1 as link text */
  --accent-warm:  #f08050;
  --accent-3:     #35c48f;
  --accent-4:     #e0ae3c;
  --muted-bar:    #6e6e65;
  color-scheme: dark;
}
body {
  margin: 0; padding: 0; font: 15px/1.5 system-ui, sans-serif;
  background: #fcfcfb;
}
body:has(.report[data-theme="dark"]) { background: #1a1a19; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 36px 0 10px; }
.sub { color: var(--ink-2); margin-bottom: 20px; }
.tabs { display: flex; gap: 4px; align-items: center; border-bottom: 1px solid var(--border); margin: 20px 0 24px; }
.tabs button {
  font: inherit; font-weight: 600; color: var(--ink-2); background: none; border: none;
  padding: 10px 16px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tabs button[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
.panel[hidden] { display: none; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.tile { background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tlabel { font-size: 13px; color: var(--ink-2); }
.tvalue { font-size: 26px; font-weight: 600; margin-top: 2px; }
.tsub { font-size: 12px; color: var(--ink-2); }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th { text-align: left; color: var(--ink-2); font-weight: 600; border-bottom: 1px solid var(--border); padding: 6px 8px; }
td { border-bottom: 1px solid var(--border-soft); padding: 6px 8px; vertical-align: top; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.hl td:first-child, tr.lane td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
.badge {
  font-size: 11px; font-weight: 600; color: var(--accent); border: 1px solid var(--accent);
  border-radius: 4px; padding: 0 5px; margin-left: 6px; vertical-align: 1px;
}
.tags { color: var(--ink-3); font-size: 12.5px; }
.ai {
  display: inline-block; font-size: 10.5px; font-weight: 600; letter-spacing: .02em;
  color: var(--ink-2); border: 1px solid var(--border); border-radius: 4px;
  padding: 0 5px; margin-left: 6px; white-space: nowrap; cursor: help;
}
.ai-heavy { color: var(--accent-warm); border-color: var(--accent-warm); }
.chart { margin: 8px 0 4px; }
.chart svg { display: block; width: 100%; height: auto; }
.note { color: var(--ink-2); font-style: italic; }
.analysis p { max-width: 75ch; }
.analysis p.caveat { color: var(--ink-2); font-size: 13.5px; border-left: 2px solid var(--border); padding-left: 12px; }
.tooltip {
  position: fixed; pointer-events: none; background: var(--surface-card); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12.5px;
  box-shadow: 0 2px 8px rgba(0,0,0,.28); display: none; z-index: 10;
}
.tooltip .v { font-weight: 600; }
footer { margin-top: 40px; color: var(--ink-2); font-size: 12.5px; border-top: 1px solid var(--border); padding-top: 12px; }
a { color: var(--accent); text-decoration-color: color-mix(in srgb, var(--accent) 45%, transparent); }
a:hover { text-decoration-thickness: 2px; }
.themetoggle {
  margin-left: auto; font: inherit; font-size: 13px; font-weight: 600;
  color: var(--ink-2); background: none; border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 10px; cursor: pointer;
}
.themetoggle:hover { color: var(--ink); }
</style></head><body>
<div class="report" id="report">
<h1>Game Trends</h1>
<div class="sub">Week @@WEEK@@ &middot; generated @@GENERATED@@ &middot; indie lens, Steam data</div>

<div class="tabs" role="tablist">
  <button role="tab" aria-selected="true" aria-controls="tab-market" id="btn-market">Market</button>
  <button role="tab" aria-selected="false" aria-controls="tab-vn" id="btn-vn">Visual Novels</button>
  <button class="themetoggle" id="themetoggle" type="button">Dark</button>
</div>

<div class="panel" id="tab-market" role="tabpanel" aria-labelledby="btn-market">
@@MARKET@@
</div>

<div class="panel" id="tab-vn" role="tabpanel" aria-labelledby="btn-vn" hidden>
@@VN@@
</div>

<footer>game-trends &middot; public Steam data (charts, store, reviews) + SteamSpy &middot;
revenue estimated via review-count heuristic &middot; built by Claude, weekly on Fridays</footer>
<div class="tooltip" id="tt"></div>
</div>
<script>
const DATA = @@PAYLOAD@@;
const report = document.getElementById('report');
const themeBtn = document.getElementById('themetoggle');

// Chart colours are read back off the live CSS variables rather than hard-coded,
// so the SVGs can never disagree with the stylesheet.
let C = {};
function readTheme() {
  const s = getComputedStyle(report);
  const v = n => s.getPropertyValue(n).trim();
  C = { accent: v('--accent'), warm: v('--accent-warm'), third: v('--accent-3'),
        fourth: v('--accent-4'), ink: v('--ink'), sub: v('--ink-2'),
        grid: v('--border-soft'), surface: v('--surface'), muted: v('--muted-bar') };
}
function isDark() { return report.getAttribute('data-theme') === 'dark'; }
function setTheme(mode) {
  if (mode === 'dark') report.setAttribute('data-theme', 'dark');
  else report.removeAttribute('data-theme');
  themeBtn.textContent = mode === 'dark' ? 'Light' : 'Dark';
  readTheme();
  drawCharts();
}
themeBtn.addEventListener('click', () => setTheme(isDark() ? 'light' : 'dark'));

// tabs
const tabs = [['btn-market','tab-market'], ['btn-vn','tab-vn']];
tabs.forEach(([b, p]) => document.getElementById(b).addEventListener('click', () => {
  tabs.forEach(([bb, pp]) => {
    const on = bb === b;
    document.getElementById(bb).setAttribute('aria-selected', on ? 'true' : 'false');
    document.getElementById(pp).hidden = !on;
  });
}));

const tt = document.getElementById('tt');
function showTT(e, valueText, labelText) {
  tt.textContent = '';
  const v = document.createElement('span');
  v.className = 'v'; v.textContent = valueText;
  tt.appendChild(v);
  tt.appendChild(document.createTextNode(' \\u00b7 ' + labelText));
  tt.style.display = 'block';
  tt.style.left = Math.min(e.clientX + 14, innerWidth - 240) + 'px';
  tt.style.top = (e.clientY + 14) + 'px';
}
function hideTT() { tt.style.display = 'none'; }
function fmtUsd(n) {
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + Math.round(n/1e3) + 'k';
  return '$' + Math.round(n);
}
function hbar(el, items, valueKey, labelKey, fmt, colorFn) {
  if (!el || !items.length) return;
  el.textContent = '';
  const W = 1040, rowH = 30, pad = 4, labelW = 260, valueW = 120;
  const H = items.length * rowH + pad * 2;
  const max = Math.max(...items.map(d => d[valueKey]), 1);
  const bw = W - labelW - valueW - 20;
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  items.forEach((d, i) => {
    const y = pad + i * rowH, w = Math.max(2, d[valueKey] / max * bw), bh = 18;
    const label = document.createElementNS(svgNS, 'text');
    label.setAttribute('x', labelW - 8); label.setAttribute('y', y + 14);
    label.setAttribute('text-anchor', 'end'); label.setAttribute('font-size', '12.5');
    label.setAttribute('fill', C.ink);
    const raw = String(d[labelKey]);
    label.textContent = raw.length > 34 ? raw.slice(0, 33) + '\\u2026' : raw;
    svg.appendChild(label);
    const bar = document.createElementNS(svgNS, 'path');
    bar.setAttribute('d', `M${labelW} ${y} h${Math.max(0, w-4)} a4 4 0 0 1 4 4 v${bh-8} a4 4 0 0 1 -4 4 h-${Math.max(0, w-4)} z`);
    bar.setAttribute('fill', colorFn ? colorFn(d) : C.accent);
    bar.addEventListener('pointermove', e => showTT(e, fmt(d[valueKey]), raw));
    bar.addEventListener('pointerleave', hideTT);
    svg.appendChild(bar);
    const val = document.createElementNS(svgNS, 'text');
    val.setAttribute('x', labelW + w + 8); val.setAttribute('y', y + 14);
    val.setAttribute('font-size', '12'); val.setAttribute('fill', C.sub);
    val.textContent = fmt(d[valueKey]);
    svg.appendChild(val);
  });
  el.appendChild(svg);
}

function drawCharts() {
hbar(document.getElementById('breakoutchart'), DATA.breakouts, 'est_net_usd', 'name', fmtUsd);
hbar(document.getElementById('tagchart'), DATA.tags, 'weight_usd', 'tag', fmtUsd);
hbar(document.getElementById('gainerchart'),
  DATA.gainers.map(g => ({ name: `${g.name} (#${g.last_week_rank} \\u2192 #${g.rank})`, delta: g.delta }))
    .filter(g => g.delta > 0), 'delta', 'name', v => '+' + v + ' ranks');

// VN tab charts
hbar(document.getElementById('liftchart'), DATA.lift, 'excess', 'tag',
  v => '+' + Math.round(v * 100) + '% vs lane');
hbar(document.getElementById('provenchart'), DATA.proven, 'reviews', 'cluster',
  v => v.toLocaleString(), d => d.lane ? C.accent : C.muted);

const trendEl = document.getElementById('tagtrend');
if (trendEl && DATA.history_weeks.length > 1) {
  const W = 1040, H = 260, padL = 60, padR = 160, padY = 24;
  const weeks = DATA.history_weeks;
  const series = Object.entries(DATA.history_tags)
    .map(([tag, byWeek]) => ({ tag, pts: weeks.map(w => byWeek[w] ?? null) }))
    .filter(s => s.pts.filter(v => v !== null).length > 1).slice(0, 4);
  const max = Math.max(...series.flatMap(s => s.pts.filter(v => v !== null)), 1);
  const x = i => padL + i * (W - padL - padR) / Math.max(1, weeks.length - 1);
  const y = v => H - padY - v / max * (H - padY * 2);
  const hues = [C.accent, C.warm, C.third, C.fourth];
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  weeks.forEach((w, i) => {
    s += `<line x1="${x(i)}" y1="${padY}" x2="${x(i)}" y2="${H - padY}" stroke="${C.grid}"/>`;
    s += `<text x="${x(i)}" y="${H - 6}" font-size="11" fill="${C.sub}" text-anchor="middle">${w}</text>`;
  });
  series.forEach((sr, si) => {
    const pts = sr.pts.map((v, i) => v === null ? null : `${x(i)},${y(v)}`).filter(Boolean);
    s += `<polyline points="${pts.join(' ')}" fill="none" stroke="${hues[si]}" stroke-width="2" stroke-linejoin="round"/>`;
    const last = sr.pts.length - 1;
    if (sr.pts[last] !== null) {
      s += `<circle cx="${x(last)}" cy="${y(sr.pts[last])}" r="4" fill="${hues[si]}" stroke="${C.surface}" stroke-width="2"/>`;
      s += `<text x="${x(last) + 10}" y="${y(sr.pts[last]) + 4}" font-size="12" fill="${C.ink}">${sr.tag}</text>`;
    }
  });
  s += '</svg>';
  trendEl.innerHTML = s;
}
}

// Start from the viewer's preference, then let the toggle take over. Following the
// system setting live matters when a host panel switches theme under us.
const mq = matchMedia('(prefers-color-scheme: dark)');
let manual = false;
setTheme(mq.matches ? 'dark' : 'light');
themeBtn.addEventListener('click', () => { manual = true; });
mq.addEventListener('change', e => { if (!manual) setTheme(e.matches ? 'dark' : 'light'); });
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    iso = dt.date.today().isocalendar()
    ap.add_argument("--week", default=f"{iso[0]}-W{iso[1]:02d}")
    ap.add_argument("--datadir", default="../data")
    ap.add_argument("--docsdir", default="../docs")
    args = ap.parse_args()

    data = load_week(args.datadir, args.week)
    if not data["summary"]:
        raise SystemExit(f"no summary.json for {args.week} - run collect.py first")
    history = load_history(args.datadir)
    baseline = load_baseline(args.datadir)
    vn_hist, vn_weeks = load_vn_cluster_history(args.datadir)
    page = build_html(args.week, data, history, baseline, vn_hist, vn_weeks)

    os.makedirs(os.path.join(args.docsdir, "reports"), exist_ok=True)
    report_path = os.path.join(args.docsdir, "reports", f"{args.week}.html")
    with open(report_path, "w") as f:
        f.write(page)
    print("wrote", report_path)

    index_path = os.path.join(args.docsdir, "index.html")
    with open(index_path, "w") as f:
        f.write(
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">\n'
            f'<meta http-equiv="refresh" content="0; url=reports/{args.week}.html">\n'
            f'<title>Game Trends - latest</title></head><body>\n'
            f'<p>Redirecting to the latest report: '
            f'<a href="reports/{args.week}.html">{args.week}</a></p></body></html>\n')
    print("wrote", index_path)


if __name__ == "__main__":
    main()
