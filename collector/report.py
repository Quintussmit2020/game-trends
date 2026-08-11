#!/usr/bin/env python3
"""Generate the weekly game-trends HTML report from a snapshot.

Usage: python3 report.py [--week 2026-W33] [--datadir ../data] [--docsdir ../docs]
Writes docs/index.html (latest) and docs/reports/<week>.html (archive).
"""
import argparse
import datetime as dt
import glob
import html
import json
import os

ESC = html.escape


def load_week(datadir, week):
    base = os.path.join(datadir, week)
    out = {}
    for name in ("summary", "new_releases", "topsellers", "mostplayed"):
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


def fmt_usd(n):
    if n is None:
        return "-"
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}k"
    return f"${n:,.0f}"


def analysis_paragraphs(summary, releases):
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
    return paras


def build_html(week, data, history):
    summary = data["summary"] or {}
    releases = (data["new_releases"] or {}).get("releases", [])
    sellers = (data["topsellers"] or {}).get("top_sellers", [])
    ranks = (data["mostplayed"] or {}).get("ranks", [])

    breakouts = summary.get("breakouts") or []
    tags = (summary.get("tag_momentum") or [])[:15]
    counts = summary.get("counts") or {}

    names = (data["mostplayed"] or {}).get("names", {})
    movers = [r for r in ranks if r.get("last_week_rank")]
    for m in movers:
        m["delta"] = (m["last_week_rank"] - m["rank"]) if m.get("last_week_rank") else 0
        m["name"] = names.get(str(m["appid"]), f"app {m['appid']}")
    gainers = sorted(movers, key=lambda m: m["delta"], reverse=True)[:8]

    hist_weeks = [h["week"] for h in history]
    hist_tag_series = {}
    for h in history:
        for t in (h.get("tag_momentum") or [])[:8]:
            hist_tag_series.setdefault(t["tag"], {})[h["week"]] = t["weight_usd"]

    payload = {
        "week": week,
        "breakouts": breakouts,
        "tags": tags,
        "gainers": gainers,
        "history_weeks": hist_weeks,
        "history_tags": hist_tag_series,
    }

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

    def release_row(r, highlight=False):
        cls = ' class="hl"' if highlight else ""
        tags_s = ESC(", ".join(r.get("tags", [])[:5]))
        return (f"<tr{cls}><td>{ESC(r['name'])}</td><td>{ESC(r.get('release_date') or '-')}</td>"
                f"<td class='num'>${r.get('price_usd', 0):.2f}</td>"
                f"<td>{ESC((r.get('team_class') or '').replace('_', ' '))}</td>"
                f"<td class='num'>{r.get('total_reviews', 0):,}</td>"
                f"<td class='num'>{r.get('pct_positive') if r.get('pct_positive') is not None else '-'}%</td>"
                f"<td class='num'>{fmt_usd(r.get('est_net_usd'))}</td>"
                f"<td class='tags'>{tags_s}</td></tr>")

    breakout_rows = "".join(release_row(r) for r in breakouts)
    seller_rows = "".join(
        f"<tr{' class=hl' if s.get('team_class') != 'aaa_or_publisher' else ''}>"
        f"<td>{i+1}</td><td>{ESC(s['name'])}</td>"
        f"<td class='num'>${s.get('price_usd', 0):.2f}</td>"
        f"<td>{ESC((s.get('team_class') or '').replace('_', ' '))}</td>"
        f"<td class='num'>{s.get('ccu_now') if s.get('ccu_now') is not None else '-'}</td>"
        f"<td class='num'>{s.get('pct_positive') if s.get('pct_positive') is not None else '-'}%</td></tr>"
        for i, s in enumerate(sellers[:25]))

    analysis = "".join(f"<p>{p}</p>" for p in analysis_paragraphs(summary, releases))

    if len(history) < 2:
        trend_note = ("<p class='note'>Trend lines over time will appear here from week two onward, "
                      "as the data record accumulates.</p>")
    else:
        trend_note = "<div id='tagtrend' class='chart'></div>"

    generated = summary.get("generated_utc", "")

    return HTML_TEMPLATE.format(
        week=week, generated=ESC(generated), kpis=kpi_html,
        breakout_rows=breakout_rows, seller_rows=seller_rows,
        analysis=analysis, trend_note=trend_note,
        payload=json.dumps(payload).replace("</", "<\\/"))


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Trends - {week}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{
  margin: 0; padding: 24px; font: 15px/1.5 system-ui, sans-serif;
  background: #fcfcfb; color: #0b0b0b; max-width: 1080px; margin-inline: auto;
}}
h1 {{ font-size: 26px; margin: 0 0 4px; }}
h2 {{ font-size: 19px; margin: 36px 0 10px; }}
.sub {{ color: #52514e; margin-bottom: 20px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
.tile {{ background: #fff; border: 1px solid #e8e7e3; border-radius: 10px; padding: 14px 16px; }}
.tlabel {{ font-size: 13px; color: #52514e; }}
.tvalue {{ font-size: 26px; font-weight: 600; margin-top: 2px; }}
.tsub {{ font-size: 12px; color: #52514e; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th {{ text-align: left; color: #52514e; font-weight: 600; border-bottom: 1px solid #e8e7e3; padding: 6px 8px; }}
td {{ border-bottom: 1px solid #f0efec; padding: 6px 8px; vertical-align: top; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.hl td:first-child {{ box-shadow: inset 3px 0 0 #2a78d6; }}
.tags {{ color: #52514e; font-size: 12.5px; }}
.chart {{ margin: 8px 0 4px; }}
.chart svg {{ display: block; width: 100%; height: auto; }}
.note {{ color: #52514e; font-style: italic; }}
.analysis p {{ max-width: 75ch; }}
.tooltip {{
  position: fixed; pointer-events: none; background: #fff; border: 1px solid #e8e7e3;
  border-radius: 8px; padding: 6px 10px; font-size: 12.5px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
  display: none; z-index: 10;
}}
.tooltip .v {{ font-weight: 600; }}
footer {{ margin-top: 40px; color: #52514e; font-size: 12.5px; border-top: 1px solid #e8e7e3; padding-top: 12px; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a19; color: #fff; }}
  .tile, .tooltip {{ background: #232322; border-color: #383835; }}
  .tlabel, .tsub, .sub, .tags, .note, footer {{ color: #c3c2b7; }}
  th {{ color: #c3c2b7; border-color: #383835; }}
  td {{ border-color: #2c2c2a; }}
  tr.hl td:first-child {{ box-shadow: inset 3px 0 0 #3987e5; }}
}}
</style></head><body>
<h1>Game Trends</h1>
<div class="sub">Week {week} &middot; generated {generated} &middot; indie lens, Steam data</div>

<div class="kpis">{kpis}</div>

<h2>Breakouts of the week</h2>
<p class="sub">Indie releases (last 14 days) ranked by estimated net revenue. Blue edge = indie.</p>
<div id="breakoutchart" class="chart"></div>
<table><thead><tr><th>Game</th><th>Released</th><th>Price</th><th>Team</th><th>Reviews</th>
<th>Positive</th><th>Est. net</th><th>Top tags</th></tr></thead>
<tbody>{breakout_rows}</tbody></table>

<h2>Tag momentum</h2>
<p class="sub">Tags of successful indie releases this week, weighted by estimated net revenue.</p>
<div id="tagchart" class="chart"></div>
{trend_note}

<h2>Most played - biggest climbers</h2>
<div id="gainerchart" class="chart"></div>

<h2>Top sellers right now</h2>
<p class="sub">Current global top sellers (hardware excluded). Blue edge = indie.</p>
<table><thead><tr><th>#</th><th>Game</th><th>Price</th><th>Team</th><th>Players now</th>
<th>Positive</th></tr></thead><tbody>{seller_rows}</tbody></table>

<h2>What this means</h2>
<div class="analysis">{analysis}</div>

<footer>game-trends &middot; public Steam data (charts, store, reviews) + SteamSpy &middot;
revenue estimated via review-count heuristic &middot; built by Claude, weekly on Fridays</footer>
<div class="tooltip" id="tt"></div>
<script>
const DATA = {payload};
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const C = {{ accent: dark ? '#3987e5' : '#2a78d6', ink: dark ? '#ffffff' : '#0b0b0b',
  sub: dark ? '#c3c2b7' : '#52514e', grid: dark ? '#2c2c2a' : '#f0efec' }};
const tt = document.getElementById('tt');
function showTT(e, html) {{
  tt.innerHTML = html; tt.style.display = 'block';
  tt.style.left = Math.min(e.clientX + 14, innerWidth - 220) + 'px';
  tt.style.top = (e.clientY + 14) + 'px';
}}
function hideTT() {{ tt.style.display = 'none'; }}
function fmtUsd(n) {{
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + Math.round(n/1e3) + 'k';
  return '$' + Math.round(n);
}}
function hbar(el, items, valueKey, labelKey, fmt) {{
  const W = 1040, rowH = 30, pad = 4, labelW = 260, valueW = 80;
  const H = items.length * rowH + pad * 2;
  const max = Math.max(...items.map(d => d[valueKey]), 1);
  const bw = W - labelW - valueW - 20;
  let s = `<svg viewBox="0 0 ${{W}} ${{H}}" role="img">`;
  items.forEach((d, i) => {{
    const y = pad + i * rowH, w = Math.max(2, d[valueKey] / max * bw), bh = 18;
    s += `<text x="${{labelW - 8}}" y="${{y + 14}}" text-anchor="end" font-size="12.5" fill="${{C.ink}}">${{d[labelKey].length > 34 ? d[labelKey].slice(0, 33) + '\\u2026' : d[labelKey]}}</text>`;
    s += `<path d="M${{labelW}} ${{y}} h${{Math.max(0, w-4)}} a4 4 0 0 1 4 4 v${{bh-8}} a4 4 0 0 1 -4 4 h-${{Math.max(0, w-4)}} z" fill="${{C.accent}}" data-i="${{i}}"/>`;
    s += `<text x="${{labelW + w + 8}}" y="${{y + 14}}" font-size="12" fill="${{C.sub}}">${{fmt(d[valueKey])}}</text>`;
  }});
  s += '</svg>';
  el.innerHTML = s;
  el.querySelectorAll('path').forEach(p => {{
    p.addEventListener('pointermove', e => {{
      const d = items[+p.dataset.i];
      const span = document.createElement('span');
      span.textContent = d[labelKey];
      showTT(e, `<span class="v">${{fmt(d[valueKey])}}</span> &middot; ` + span.outerHTML.replace(/<\\/?span>/g, ''));
    }});
    p.addEventListener('pointerleave', hideTT);
  }});
}}
if (DATA.breakouts.length)
  hbar(document.getElementById('breakoutchart'), DATA.breakouts, 'est_net_usd', 'name', fmtUsd);
if (DATA.tags.length)
  hbar(document.getElementById('tagchart'), DATA.tags, 'weight_usd', 'tag', fmtUsd);
if (DATA.gainers.length)
  hbar(document.getElementById('gainerchart'),
    DATA.gainers.map(g => ({{ name: `${{g.name}} (#${{g.last_week_rank}} \\u2192 #${{g.rank}})`,
      delta: g.delta }})).filter(g => g.delta > 0), 'delta', 'name', v => '+' + v + ' ranks');
const trendEl = document.getElementById('tagtrend');
if (trendEl && DATA.history_weeks.length > 1) {{
  const W = 1040, H = 260, padL = 60, padR = 160, padY = 24;
  const weeks = DATA.history_weeks;
  const series = Object.entries(DATA.history_tags)
    .map(([tag, byWeek]) => ({{ tag, pts: weeks.map(w => byWeek[w] ?? null) }}))
    .filter(s => s.pts.filter(v => v !== null).length > 1).slice(0, 4);
  const max = Math.max(...series.flatMap(s => s.pts.filter(v => v !== null)), 1);
  const x = i => padL + i * (W - padL - padR) / Math.max(1, weeks.length - 1);
  const y = v => H - padY - v / max * (H - padY * 2);
  const hues = [C.accent, dark ? '#d95926' : '#eb6834', dark ? '#199e70' : '#1baf7a', dark ? '#c98500' : '#eda100'];
  let s = `<svg viewBox="0 0 ${{W}} ${{H}}">`;
  weeks.forEach((w, i) => {{
    s += `<line x1="${{x(i)}}" y1="${{padY}}" x2="${{x(i)}}" y2="${{H - padY}}" stroke="${{C.grid}}"/>`;
    s += `<text x="${{x(i)}}" y="${{H - 6}}" font-size="11" fill="${{C.sub}}" text-anchor="middle">${{w}}</text>`;
  }});
  series.forEach((sr, si) => {{
    const pts = sr.pts.map((v, i) => v === null ? null : `${{x(i)}},${{y(v)}}`).filter(Boolean);
    s += `<polyline points="${{pts.join(' ')}}" fill="none" stroke="${{hues[si]}}" stroke-width="2" stroke-linejoin="round"/>`;
    const lastIdx = sr.pts.length - 1;
    if (sr.pts[lastIdx] !== null) {{
      s += `<circle cx="${{x(lastIdx)}}" cy="${{y(sr.pts[lastIdx])}}" r="4" fill="${{hues[si]}}" stroke="${{dark ? '#1a1a19' : '#fcfcfb'}}" stroke-width="2"/>`;
      s += `<text x="${{x(lastIdx) + 10}}" y="${{y(sr.pts[lastIdx]) + 4}}" font-size="12" fill="${{C.ink}}">${{sr.tag}}</text>`;
    }}
  }});
  s += '</svg>';
  trendEl.innerHTML = s;
}}
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
    page = build_html(args.week, data, history)

    os.makedirs(os.path.join(args.docsdir, "reports"), exist_ok=True)
    for path in (os.path.join(args.docsdir, "index.html"),
                 os.path.join(args.docsdir, "reports", f"{args.week}.html")):
        with open(path, "w") as f:
            f.write(page)
        print("wrote", path)


if __name__ == "__main__":
    main()
