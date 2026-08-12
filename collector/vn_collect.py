#!/usr/bin/env python3
"""game-trends: visual novel module.

Tracks the visual novel corner of Steam specifically, because VN sub-genres are
only legible through tag combinations, not Steam's coarse genre field.

Cluster membership comes from Steam's own multi-tag search (tags=3799,<tag> is an
AND), not from SteamSpy. That matters: SteamSpy has no tag data for brand-new
releases, which is exactly the population this report needs to see each week.
SteamSpy is used only for review/price data on established titles; new releases
get their review counts from Steam's own review API, which works from day one.

Collects each week:
  - VN releases of the last 30 days, with cluster membership, length and any
    AI-generated-content disclosure
  - Current VN top sellers and most-reviewed VNs (the visible market)
  - Proven titles: VNs with 500+ reviews, swept per cluster, so "what performs"
    is measured on games that found an audience rather than on everything shipped
  - A hybrid-lane watchlist: horror/psychological, point-and-click/puzzle and
    mystery/detective VNs, the clusters that out-perform pure romance

Writes data/<week>/vn.json and updates data/vn_cluster_history.csv.

Usage: python3 vn_collect.py [--week 2026-W33] [--outdir ../data]
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics as st
import sys
import time
import urllib.request

import ai_disclosure

UA = {"User-Agent": "game-trends-collector/1.0 (weekly VN research snapshot)",
      "Accept-Encoding": "identity"}
VN_TAG_ID = 3799
RECENT_WINDOW_DAYS = 30
REVIEW_MULTIPLIER = 35
NET_FACTOR = 0.55
STEAMSPY_DELAY = 1.05
STORE_DELAY = 1.3          # Steam's store search rate-limits hard; stay well under it
MAX_STEAMSPY = 90          # bounded so a weekly run stays well under an hour

# Sub-genre clusters, defined by Steam tag ids. A VN usually sits in several at
# once; that overlap is the point, since "cozy romance with branching choices"
# is a stack rather than a single genre.
CLUSTERS = {
    "Romance / dating sim": {"Dating Sim": 9551, "Romance": 4947, "Otome": 31579},
    "Horror / psychological": {"Psychological Horror": 1721, "Horror": 1667,
                               "Gore": 4345, "Survival Horror": 3978},
    "Point & click / puzzle": {"Point & Click": 1698, "Puzzle": 1664, "Hidden Object": 1738},
    "Mystery / detective": {"Mystery": 5716, "Detective": 5613, "Crime": 6378,
                            "Investigation": 8369},
    "Choice-driven branching": {"Choices Matter": 6426, "Multiple Endings": 6971,
                                "Choose Your Own Adventure": 4486},
    "Slice of life / cozy": {"Cute": 4726, "Relaxing": 1654, "Wholesome": 552282,
                             "Casual": 597},
    "RPG hybrid": {"RPG": 122, "JRPG": 4434, "Turn-Based Combat": 4325},
    "Sim / management hybrid": {"Simulation": 599, "Life Sim": 10235, "Management": 12472,
                                "Resource Management": 8945},
    "LGBTQ+ / queer narrative": {"LGBTQ+": 44868},
    "Sci-fi / cyberpunk": {"Sci-fi": 3942, "Cyberpunk": 4115, "Space": 1755},
    "Interactive fiction / text": {"Interactive Fiction": 11014, "Text-Based": 31275},
    "Adult (explicit)": {"Hentai": 9130, "Sexual Content": 12095, "Nudity": 6650},
}

# The lane: narrative games that add a verb other than reading. Tracked every week.
HYBRID_LANE = ["Horror / psychological", "Point & click / puzzle", "Mystery / detective"]


def fetch(url, retries=4, delay=2.0):
    """GET with backoff. Steam returns 429 readily on the search endpoint, so a
    rate-limit response waits much longer than an ordinary error."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 20 * (attempt + 1)
                print(f"  . rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if attempt == retries - 1:
                print(f"  ! failed {url}: {e}", file=sys.stderr)
                return None
            time.sleep(delay * (attempt + 1))
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! failed {url}: {e}", file=sys.stderr)
                return None
            time.sleep(delay * (attempt + 1))
    return None


def search_appids(tag_ids, params="", pages=2, per=100):
    """Steam store search. Multiple tag ids are ANDed."""
    tags = ",".join(str(t) for t in tag_ids)
    out = {}
    for p in range(pages):
        d = fetch("https://store.steampowered.com/search/results/"
                  f"?tags={tags}&start={p*per}&count={per}&json=1&{params}")
        items = (d or {}).get("items", [])
        for it in items:
            m = re.search(r"/apps/(\d+)/", it.get("logo", ""))
            if m:
                out[int(m.group(1))] = it.get("name", "")
        time.sleep(STORE_DELAY)
        if len(items) < per:
            break
    return out


def build_tag_index():
    """appid -> set of cluster names, from VN+tag intersection searches.

    Each tag is swept twice: by relevance (which surfaces brand-new releases, the
    whole reason for not using SteamSpy tags) and by review count (which surfaces
    the established titles). The second sweep also returns the candidate pool for
    the proven-titles set, so every cluster is represented rather than only the
    ones big enough to reach a global top-sellers list.
    """
    index, proven_candidates = {}, {}
    for cluster, tags in CLUSTERS.items():
        for tag_name, tag_id in tags.items():
            fresh = search_appids([VN_TAG_ID, tag_id], pages=2)
            top = search_appids([VN_TAG_ID, tag_id], "sort_by=Reviews_DESC", pages=1)
            for appid in list(fresh) + list(top):
                index.setdefault(appid, set()).add(cluster)
            proven_candidates.update(top)
            print(f"   {cluster} / {tag_name}: {len(fresh)} recent, {len(top)} most-reviewed")
    return index, proven_candidates


def collect_proven(candidates, index, min_reviews=500, cap=200):
    """VNs that cleared a real audience bar, so cluster performance is measured on
    titles players actually bought rather than on everything that shipped."""
    out = []
    for appid, name in candidates.items():
        if len(out) >= cap:
            print(f"   cap of {cap} reached, {len(candidates) - len(out)} candidates not enriched")
            break
        rec = record_from_steamspy(appid, name, index.get(appid, set()))
        if not rec or rec["total_reviews"] < min_reviews:
            continue
        out.append(rec)
        if len(out) % 25 == 0:
            print(f"   {len(out)} proven titles enriched")
    out.sort(key=lambda r: -r["total_reviews"])
    return out


def summarise_proven(proven):
    """Per-cluster performance across proven titles: the 'what do people actually
    like' view, including how long the successful ones run."""
    rows = []
    for name in CLUSTERS:
        grp = [r for r in proven if name in r["clusters"]]
        if len(grp) < 3:
            continue
        revs = [r["total_reviews"] for r in grp]
        prices = [r["price_usd"] for r in grp if r["price_usd"]]
        poss = [r["pct_positive"] for r in grp if r["pct_positive"] is not None]
        hrs = [r["playtime_hours"] for r in grp if r.get("playtime_hours")]
        rows.append({
            "cluster": name,
            "count": len(grp),
            "share_pct": round(100.0 * len(grp) / max(1, len(proven)), 1),
            "median_reviews": int(st.median(revs)),
            "median_price_usd": round(st.median(prices), 2) if prices else 0,
            "median_pct_positive": round(st.median(poss), 1) if poss else None,
            "median_hours": round(st.median(hrs), 1) if hrs else None,
            "top_decile_reviews": int(sorted(revs)[int(len(revs) * 0.9)]) if len(revs) > 3 else None,
            "hybrid_lane": name in HYBRID_LANE,
        })
    rows.sort(key=lambda r: -r["median_pct_positive"] if r["median_pct_positive"] else 0)
    return rows


def appdetails(appid):
    d = fetch("https://store.steampowered.com/api/appdetails?appids=%d"
              "&filters=basic,genres,price_overview,release_date,developers,publishers" % appid)
    entry = (d or {}).get(str(appid), {})
    return entry.get("data") if entry.get("success") else None


def review_summary(appid):
    d = fetch("https://store.steampowered.com/appreviews/%d?json=1&num_per_page=0"
              "&language=all&purchase_type=all" % appid)
    return (d or {}).get("query_summary") or {}


def playtime_hours(appid, sample=100):
    """Median playtime in hours, from a sample of reviewers' own playtime.

    SteamSpy's playtime fields are paywalled and return 0, but every Steam review
    carries the reviewer's playtime, which is official and free. The median of a
    recent sample tracks published game-length figures closely (Doki Doki ~5h,
    VA-11 Hall-A ~12h, Disco Elysium ~29h).

    Returns (median_hours, sample_size). Reviewers are self-selecting and tend to
    review early, so read this as "how long players actually spend", not a
    completionist figure.
    """
    d = fetch("https://store.steampowered.com/appreviews/%d?json=1&num_per_page=%d"
              "&filter=recent&language=all&purchase_type=all&review_type=all"
              % (appid, sample))
    revs = (d or {}).get("reviews") or []
    mins = [r.get("author", {}).get("playtime_at_review") or 0 for r in revs]
    mins = [m for m in mins if m > 0]
    if len(mins) < 5:          # too thin to be meaningful
        return None, len(mins)
    return round(st.median(mins) / 60.0, 1), len(mins)


def steamspy(appid):
    return fetch(f"https://steamspy.com/api.php?request=appdetails&appid={appid}")


def parse_release_date(data):
    rd = (data or {}).get("release_date", {}).get("date", "")
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(rd, fmt).date()
        except ValueError:
            continue
    return None


def record_from_store(appid, name, clusters):
    """Store-API record. Works for games released minutes ago."""
    data = appdetails(appid)
    time.sleep(STORE_DELAY)
    if not data or data.get("type") != "game":
        return None
    rs = review_summary(appid)
    time.sleep(STORE_DELAY)
    price = ((data.get("price_overview") or {}).get("initial") or 0) / 100.0
    total = rs.get("total_reviews", 0) or 0
    pos = rs.get("total_positive", 0) or 0
    devs = data.get("developers") or []
    pubs = data.get("publishers") or []
    hours, hours_n = (None, 0)
    if total >= 5:
        hours, hours_n = playtime_hours(appid)
        time.sleep(STORE_DELAY)
    ai_flag, ai_note, ai_scope = ai_disclosure.check(appid)
    time.sleep(STORE_DELAY)
    return {
        "appid": appid,
        "name": data.get("name") or name,
        "release_date": (parse_release_date(data) or dt.date.min).isoformat(),
        "ai_disclosed": ai_flag,
        "ai_note": ai_note,
        "ai_scope": ai_scope,
        "clusters": sorted(clusters),
        "price_usd": round(price, 2),
        "developer": ", ".join(devs),
        "publisher": ", ".join(pubs),
        "self_published": bool(devs) and set(d.lower() for d in devs) == set(p.lower() for p in pubs),
        "total_reviews": total,
        "pct_positive": round(100.0 * pos / total, 1) if total else None,
        "est_net_usd": int(total * REVIEW_MULTIPLIER * price * NET_FACTOR),
        "playtime_hours": hours,
        "playtime_sample": hours_n,
    }


def record_from_steamspy(appid, name, clusters):
    """SteamSpy record for established titles - cheaper, one call."""
    spy = steamspy(appid)
    time.sleep(STEAMSPY_DELAY)
    if not spy or not spy.get("name"):
        return None
    pos = spy.get("positive") or 0
    neg = spy.get("negative") or 0
    total = pos + neg
    try:
        price = int(spy.get("initialprice") or 0) / 100.0
    except (TypeError, ValueError):
        price = 0.0
    dev, pub = spy.get("developer") or "", spy.get("publisher") or ""
    hours, hours_n = (None, 0)
    if total >= 5:
        hours, hours_n = playtime_hours(appid)
        time.sleep(STORE_DELAY)
    return {
        "appid": appid,
        "name": spy.get("name") or name,
        "clusters": sorted(clusters),
        "playtime_hours": hours,
        "playtime_sample": hours_n,
        "price_usd": round(price, 2),
        "developer": dev,
        "publisher": pub,
        "self_published": bool(dev) and dev == pub,
        "total_reviews": total,
        "pct_positive": round(100.0 * pos / total, 1) if total else None,
        "est_net_usd": int(total * REVIEW_MULTIPLIER * price * NET_FACTOR),
        "ccu": spy.get("ccu", 0),
    }


def summarise_clusters(records, min_reviews=10):
    out = []
    n = len(records) or 1
    for name in CLUSTERS:
        grp = [r for r in records if name in r["clusters"]]
        if not grp:
            continue
        revs = [r["total_reviews"] for r in grp if r["total_reviews"] > 0]
        prices = [r["price_usd"] for r in grp if r["price_usd"]]
        poss = [r["pct_positive"] for r in grp
                if r["pct_positive"] is not None and r["total_reviews"] >= min_reviews]
        out.append({
            "cluster": name,
            "count": len(grp),
            "share_pct": round(100.0 * len(grp) / n, 1),
            "median_reviews": int(st.median(revs)) if revs else 0,
            "over_1k_reviews": sum(1 for x in revs if x >= 1000),
            "median_price_usd": round(st.median(prices), 2) if prices else 0,
            "median_pct_positive": round(st.median(poss), 1) if poss else None,
            "hybrid_lane": name in HYBRID_LANE,
        })
    out.sort(key=lambda c: -c["count"])
    return out


def main():
    ap = argparse.ArgumentParser()
    iso = dt.date.today().isocalendar()
    ap.add_argument("--week", default=f"{iso[0]}-W{iso[1]:02d}")
    ap.add_argument("--outdir", default="../data")
    args = ap.parse_args()

    week = args.week
    outdir = f"{args.outdir}/{week}"
    os.makedirs(outdir, exist_ok=True)
    print(f"== VN module for {week} ==")

    print("[1/5] building cluster index from VN tag intersections ...")
    index, proven_candidates = build_tag_index()
    print(f"   indexed {len(index)} VN appids across {len(CLUSTERS)} clusters, "
          f"{len(proven_candidates)} proven candidates")

    print("[2/5] finding recent VN releases ...")
    recent = search_appids([VN_TAG_ID], "sort_by=Released_DESC", pages=2)
    cutoff = dt.date.today() - dt.timedelta(days=RECENT_WINDOW_DAYS)
    releases = []
    for appid, name in recent.items():
        rec = record_from_store(appid, name, index.get(appid, set()))
        if not rec:
            continue
        try:
            rd = dt.date.fromisoformat(rec["release_date"])
        except ValueError:
            continue
        if rd < cutoff:
            continue
        releases.append(rec)
        if rec["total_reviews"]:
            print(f"   release: {rec['name'][:42]} ({rec['total_reviews']} reviews) "
                  f"{'/'.join(rec['clusters'][:3])}")
    print(f"   {len(releases)} releases inside the {RECENT_WINDOW_DAYS}-day window")

    print("[3/5] sampling the visible VN market ...")
    market_ids = {}
    market_ids.update(search_appids([VN_TAG_ID], "filter=topsellers", pages=1))
    market_ids.update(search_appids([VN_TAG_ID], "sort_by=Reviews_DESC", pages=1))
    seen = {r["appid"] for r in releases}
    market = []
    for appid, name in market_ids.items():
        if len(market) >= MAX_STEAMSPY:
            break
        if appid in seen:
            continue
        rec = record_from_steamspy(appid, name, index.get(appid, set()))
        if not rec:
            continue
        seen.add(appid)
        market.append(rec)
    print(f"   {len(market)} market titles enriched")

    print("[4/5] proven titles (500+ reviews) ...")
    proven = collect_proven(proven_candidates, index)
    proven_summary = summarise_proven(proven)
    print(f"   {len(proven)} proven titles across {len(proven_summary)} clusters")

    print("[5/5] clustering ...")
    corpus = releases + market
    cluster_summary = summarise_clusters(corpus)
    release_clusters = {}
    for r in releases:
        for c in r["clusters"]:
            release_clusters[c] = release_clusters.get(c, 0) + 1

    lane = sorted([r for r in corpus if any(c in HYBRID_LANE for c in r["clusters"])],
                  key=lambda r: r["total_reviews"], reverse=True)[:15]
    top_releases = sorted(releases, key=lambda r: (r["est_net_usd"], r["total_reviews"]),
                          reverse=True)[:12]
    lane_releases = [r for r in releases if any(c in HYBRID_LANE for c in r["clusters"])]

    payload = {
        "week": week,
        "generated_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "window_days": RECENT_WINDOW_DAYS,
        "counts": {"releases": len(releases), "market_titles": len(market),
                   "corpus": len(corpus), "indexed_vns": len(index),
                   "lane_releases": len(lane_releases), "proven": len(proven)},
        "proven_min_reviews": 500,
        "proven_summary": proven_summary,
        "proven_titles": proven[:60],
        "cluster_summary": cluster_summary,
        "release_clusters": release_clusters,
        "top_releases": top_releases,
        "lane_releases": lane_releases[:12],
        "hybrid_lane": lane,
        "hybrid_lane_clusters": HYBRID_LANE,
        "caveat": ("Cluster membership comes from Steam's own tag intersections. Review and "
                   "price data for established titles comes from SteamSpy, so only VNs with "
                   "public data appear in the market sample: those medians describe survivors, "
                   "not expected outcomes. Most VNs on Steam never reach them."),
    }
    json.dump(payload, open(f"{outdir}/vn.json", "w"), separators=(",", ":"))

    # Rewrite this week's rows rather than appending, so re-running a week does not
    # silently double it up in the long-run record.
    hist = f"{args.outdir}/vn_cluster_history.csv"
    header = ("week,cluster,count,share_pct,median_reviews,over_1k_reviews,"
              "median_price_usd,releases_this_week\n")
    kept = []
    if os.path.exists(hist):
        with open(hist) as f:
            lines = f.readlines()
        kept = [l for l in lines[1:] if not l.startswith(f"{week},")]
    with open(hist, "w") as f:
        f.write(header)
        f.writelines(kept)
        for c in cluster_summary:
            f.write(f'{week},"{c["cluster"]}",{c["count"]},{c["share_pct"]},'
                    f'{c["median_reviews"]},{c["over_1k_reviews"]},'
                    f'{c["median_price_usd"]},{release_clusters.get(c["cluster"], 0)}\n')

    print(f"done. VN snapshot in {outdir}/vn.json")


if __name__ == "__main__":
    main()
