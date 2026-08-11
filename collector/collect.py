#!/usr/bin/env python3
"""game-trends weekly collector.

Collects public Steam data for the weekly game-trends snapshot:
  - Most played top 100 (official Steam charts service)
  - Current top sellers (store search, hardware filtered out)
  - New releases of the last 14 days, enriched
  - Tag data via SteamSpy, review summaries via the store API

Revenue is estimated with the Boxleiter method (reviews x multiplier x price).
All estimates are directional, not precise. See README for assumptions.

Usage: python3 collect.py [--week 2026-W33] [--outdir ../data]
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request
import urllib.parse

UA = {"User-Agent": "game-trends-collector/1.0 (weekly research snapshot)"}
REVIEW_MULTIPLIER = 35        # Boxleiter-style: sales ~= total reviews x 35
NET_FACTOR = 0.55             # Steam cut + discounts/regional pricing, rough
NEW_RELEASE_WINDOW_DAYS = 14
REQUEST_DELAY = 0.6           # be polite to public endpoints

KNOWN_BIG_PUBLISHERS = {
    "valve", "electronic arts", "ea", "ubisoft", "activision", "blizzard",
    "bethesda", "xbox game studios", "microsoft", "sony", "playstation",
    "square enix", "capcom", "sega", "bandai namco", "take-two", "2k",
    "rockstar games", "warner bros", "cd projekt", "epic games", "krafton",
    "nexon", "netease", "tencent", "miHoYo".lower(), "hoyoverse", "riot games",
    "paradox interactive", "focus entertainment", "thq nordic", "deep silver",
    "devolver digital", "annapurna interactive", "505 games", "team17",
}
HARDWARE_KEYWORDS = ("steam machine", "steam controller", "steam frame", "steam deck", "valve index")


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! failed {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def get_most_played():
    d = fetch("https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/")
    if not d:
        return []
    ranks = d.get("response", {}).get("ranks", [])
    return [{"rank": r.get("rank"), "appid": r.get("appid"),
             "last_week_rank": r.get("last_week_rank"), "peak_in_game": r.get("peak_in_game")}
            for r in ranks]


def search_items(url):
    d = fetch(url)
    items = (d or {}).get("items", [])
    out = []
    for it in items:
        logo = it.get("logo", "")
        m = re.search(r"/apps/(\d+)/", logo)
        if m:
            out.append({"appid": int(m.group(1)), "name": it.get("name", "")})
    return out


def get_top_sellers(count=50):
    items = search_items(
        f"https://store.steampowered.com/search/results/?filter=topsellers&start=0&count={count}&json=1")
    return [i for i in items if not any(k in i["name"].lower() for k in HARDWARE_KEYWORDS)]


def get_recent_releases(pages=3, per_page=50):
    seen, out = set(), []
    for p in range(pages):
        items = search_items(
            "https://store.steampowered.com/search/results/?query&start=%d&count=%d"
            "&sort_by=Released_DESC&category1=998&supportedlang=english&json=1"
            % (p * per_page, per_page))
        for i in items:
            if i["appid"] not in seen:
                seen.add(i["appid"])
                out.append(i)
        time.sleep(REQUEST_DELAY)
    return out


def get_appdetails(appid):
    d = fetch("https://store.steampowered.com/api/appdetails?appids=%d"
              "&filters=basic,genres,categories,price_overview,release_date,developers,publishers" % appid)
    entry = (d or {}).get(str(appid), {})
    if not entry.get("success"):
        return None
    return entry.get("data")


def get_review_summary(appid):
    d = fetch("https://store.steampowered.com/appreviews/%d?json=1&num_per_page=0"
              "&language=all&purchase_type=all" % appid)
    return (d or {}).get("query_summary")


def get_steamspy(appid):
    return fetch("https://steamspy.com/api.php?request=appdetails&appid=%d" % appid)


def get_ccu(appid):
    d = fetch("https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=%d" % appid)
    return (d or {}).get("response", {}).get("player_count")


def parse_release_date(data):
    rd = (data or {}).get("release_date", {}).get("date", "")
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(rd, fmt).date()
        except ValueError:
            continue
    return None


def classify_team(dev_list, pub_list):
    devs = [d.lower() for d in (dev_list or [])]
    pubs = [p.lower() for p in (pub_list or [])]
    if any(any(big in p for big in KNOWN_BIG_PUBLISHERS) for p in pubs):
        return "aaa_or_publisher"
    if devs and pubs and set(devs) == set(pubs):
        return "self_published_indie"
    return "indie_with_publisher"


def enrich(appid, name):
    data = get_appdetails(appid)
    time.sleep(REQUEST_DELAY)
    reviews = get_review_summary(appid)
    time.sleep(REQUEST_DELAY)
    spy = get_steamspy(appid)
    time.sleep(REQUEST_DELAY)
    if not data:
        return None
    if data.get("type") != "game":
        return None
    price_cents = (data.get("price_overview") or {}).get("initial")
    price = (price_cents / 100.0) if price_cents else 0.0
    total_reviews = (reviews or {}).get("total_reviews", 0) or 0
    positive = (reviews or {}).get("total_positive", 0) or 0
    est_sales = total_reviews * REVIEW_MULTIPLIER
    est_gross = est_sales * price
    est_net = est_gross * NET_FACTOR
    tags = list((spy or {}).get("tags") or {})[:10] if isinstance((spy or {}).get("tags"), dict) else []
    if not tags:
        tags = [g.get("description") for g in (data.get("genres") or []) if g.get("description")][:6]
    rel = parse_release_date(data)
    return {
        "appid": appid,
        "name": data.get("name") or name,
        "release_date": rel.isoformat() if rel else None,
        "price_usd": round(price, 2),
        "is_free": data.get("is_free", False),
        "developers": data.get("developers") or [],
        "publishers": data.get("publishers") or [],
        "team_class": classify_team(data.get("developers"), data.get("publishers")),
        "genres": [g.get("description") for g in (data.get("genres") or [])],
        "tags": tags,
        "total_reviews": total_reviews,
        "positive_reviews": positive,
        "review_score_desc": (reviews or {}).get("review_score_desc"),
        "pct_positive": round(100.0 * positive / total_reviews, 1) if total_reviews else None,
        "est_sales": int(est_sales),
        "est_gross_usd": int(est_gross),
        "est_net_usd": int(est_net),
        "steamspy_owners": (spy or {}).get("owners"),
    }


def main():
    ap = argparse.ArgumentParser()
    iso = dt.date.today().isocalendar()
    ap.add_argument("--week", default=f"{iso[0]}-W{iso[1]:02d}")
    ap.add_argument("--outdir", default="../data")
    args = ap.parse_args()

    week = args.week
    outdir = f"{args.outdir}/{week}"
    import os
    os.makedirs(outdir, exist_ok=True)
    print(f"== game-trends collection for {week} ==")

    print("[1/4] most played top 100 ...")
    most_played = get_most_played()
    names = {}
    for r in most_played:
        d = fetch("https://store.steampowered.com/api/appdetails?appids=%d&filters=basic" % r["appid"])
        entry = (d or {}).get(str(r["appid"]), {})
        if entry.get("success"):
            names[str(r["appid"])] = (entry.get("data") or {}).get("name", "")
        time.sleep(0.3)
    json.dump({"week": week, "ranks": most_played, "names": names},
              open(f"{outdir}/mostplayed.json", "w"), indent=1)

    print("[2/4] top sellers ...")
    sellers = get_top_sellers()
    enriched_sellers = []
    for s in sellers:
        e = enrich(s["appid"], s["name"])
        if e:
            e["ccu_now"] = get_ccu(s["appid"])
            time.sleep(REQUEST_DELAY)
            enriched_sellers.append(e)
            print(f"   seller: {e['name']}")
    json.dump({"week": week, "top_sellers": enriched_sellers},
              open(f"{outdir}/topsellers.json", "w"), indent=1)

    print("[3/4] recent releases ...")
    recent = get_recent_releases()
    cutoff = dt.date.today() - dt.timedelta(days=NEW_RELEASE_WINDOW_DAYS)
    releases = []
    for r in recent:
        e = enrich(r["appid"], r["name"])
        if not e or not e["release_date"]:
            continue
        rd = dt.date.fromisoformat(e["release_date"])
        if rd < cutoff:
            continue
        if e["total_reviews"] < 10:      # ignore games with no traction signal yet
            continue
        e["ccu_now"] = get_ccu(r["appid"])
        time.sleep(REQUEST_DELAY)
        releases.append(e)
        print(f"   release: {e['name']} ({e['total_reviews']} reviews)")
    json.dump({"week": week, "window_days": NEW_RELEASE_WINDOW_DAYS, "releases": releases},
              open(f"{outdir}/new_releases.json", "w"), indent=1)

    print("[4/4] summary ...")
    # Breakouts: indie new releases ranked by est net revenue
    indies = [r for r in releases if r["team_class"] != "aaa_or_publisher"]
    breakouts = sorted(indies, key=lambda r: r["est_net_usd"], reverse=True)[:10]

    # Tag momentum among successful new releases (weight = est net revenue,
    # min $5k to count, capped at $250k per game so one mega-hit can't own the board)
    tag_weight = {}
    for r in indies:
        if r["est_net_usd"] < 5000:
            continue
        w = min(r["est_net_usd"], 250_000)
        for t in (r["tags"] or r["genres"]):
            tag_weight[t] = tag_weight.get(t, 0) + w
    top_tags = sorted(tag_weight.items(), key=lambda kv: kv[1], reverse=True)[:25]

    summary = {
        "week": week,
        "generated_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "counts": {"most_played": len(most_played), "top_sellers": len(enriched_sellers),
                   "new_releases_tracked": len(releases), "indie_new_releases": len(indies)},
        "breakouts": [{k: b[k] for k in ("appid", "name", "release_date", "price_usd",
                                          "team_class", "tags", "total_reviews", "pct_positive",
                                          "est_net_usd", "ccu_now")} for b in breakouts],
        "tag_momentum": [{"tag": t, "weight_usd": int(w)} for t, w in top_tags],
        "assumptions": {"review_multiplier": REVIEW_MULTIPLIER, "net_factor": NET_FACTOR,
                        "note": "Revenue estimates are directional (Boxleiter method)."},
    }
    json.dump(summary, open(f"{outdir}/summary.json", "w"), indent=1)

    # Append to the long-run CSV record
    tag_csv = f"{args.outdir}/tag_momentum_history.csv"
    new_file = not os.path.exists(tag_csv)
    with open(tag_csv, "a") as f:
        if new_file:
            f.write("week,tag,weight_usd\n")
        for t, w in top_tags:
            f.write(f"{week},\"{t}\",{int(w)}\n")

    week_csv = f"{args.outdir}/weekly_summary_history.csv"
    new_file = not os.path.exists(week_csv)
    with open(week_csv, "a") as f:
        if new_file:
            f.write("week,new_releases_tracked,indie_new_releases,top_breakout,top_breakout_est_net_usd\n")
        top = breakouts[0] if breakouts else {"name": "", "est_net_usd": 0}
        f.write(f"{week},{len(releases)},{len(indies)},\"{top['name']}\",{top['est_net_usd']}\n")

    print(f"done. snapshot in {outdir}/")


if __name__ == "__main__":
    main()
