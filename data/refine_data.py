"""
Raw -> Refined layer for the F1 Academy "Fan Growth Engine".

Reads  data/raw/*      (messy: platform-native fields, duplicates, gaps, mixed codes)
Writes data/refined/*  (clean, unified schema, model-ready)

Tagging here is RULE-BASED so the demo runs offline. In the AWS build the same
columns are produced by Amazon Bedrock (Claude) / Amazon Comprehend inside a
Glue or Lambda step - the output schema stays identical.
Usage:  python data/refine_data.py
"""
import csv
import json
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, REF = ROOT / "raw", ROOT / "refined"
REF.mkdir(exist_ok=True)

BANDS = ["13_17", "18_24", "25_34", "35_plus"]


def read_csv(name):
    with open(RAW / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(name, header, rows):
    with open(REF / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  refined/{name}: {len(rows)} rows")


def med(xs):
    return st.median(xs) if xs else 0


def r(x, n=4):
    return round(x, n)


# --------------------------------------------------------------------------
# Rules (documented in docs/fan-growth-strategy.md)
# --------------------------------------------------------------------------
THEME_RULES = [
    ("stem_engineering", ["girls in stem", "engineer", "set up for"]),
    ("reverse_grid_chaos", ["reverse grid"]),
    ("driver_story", ["meet ", "talks nerves", "a day in her life"]),
    ("behind_the_scenes", ["paddock access", "inside the", "garage"]),
    ("fashion_lifestyle", ["helmet designs", "race suit", "fit check"]),
    ("gaming_sim", ["sim racer", "f1 game"]),
    ("women_in_sport", ["women in sport", "women's sport", "from the court"]),
    ("memes_trend", ["me watching", "trend audio"]),
    ("data_explainer", ["telemetry", "breaking down"]),
    ("race_recap", ["recap", "highlights"]),
]


def detect_theme(caption):
    c = caption.lower()
    for theme, kws in THEME_RULES:
        if any(k in c for k in kws):
            return theme
    return "other"


def detect_hook(caption):
    c = caption.strip().lower()
    if c.startswith("pov"):
        return "pov_hook"
    if c.startswith(("hot take", "nobody talks", "this is not a support race")):
        return "bold_claim"
    if c.startswith(("her story", "you won't believe", "the reason she")):
        return "story_tease"
    if c.startswith(("she won from", "pole by", "podium on debut")):
        return "result_first"
    first = re.match(r"^[^.!?]*[.!?]+", c)
    if first and first.group(0).endswith("?"):
        return "question_hook"
    return "none"


def duration_bucket(d):
    for limit, label in ((15, "0-15s"), (30, "16-30s"), (45, "31-45s"), (60, "46-60s"),
                         (90, "61-90s"), (180, "91-180s"), (300, "3-5min")):
        if d <= limit:
            return label
    return "5min+"


INTENT_RULES = [
    ("spam", ["click my bio", "dm me", "earn $", "free followers", "crypto"]),
    ("ask_how_to_start", ["how do you even start", "become a", "want to be a", "where do i start",
                          "getting into", "programme for girls"]),
    ("where_to_watch", ["where can i watch", "f1 tv", "what channel", "how do i watch", "stream it",
                        "d\u00f3nde puedo ver", "onde assistir", "wo kann man", "o\u00f9 regarder"]),
    ("who_is_she", ["who is she", "who's the driver", "what's her name", "which team is she",
                    "qui\u00e9n es ella", "qui est-elle"]),
    ("is_this_real_racing", ["real racing", "actual f4", "real cars", "same track"]),
    ("compare_main_f1", ["main race", "like the f1 races", "same channel as f1", "only watch f1"]),
    ("wants_more_content", ["more of this", "part 2", "make a series", "day in the life of",
                            "more behind the scenes", "quiero m\u00e1s", "mehr davon"]),
    ("criticism_negative", ["boring", "nobody asked", "overhyped", "audio so bad", "too slow", "without ads"]),
    ("rivalry_fandom", ["fans where are we", "deserved that win", "all day", "rivalry"]),
    ("supportive_inspired", ["inspiring", "love women", "anything", "made my day", "queen", "unreal",
                             "me encanta", "que orgulho", "wahnsinn", "trop forte"]),
]
NEW_FAN_INTENTS = {"who_is_she", "where_to_watch", "is_this_real_racing", "ask_how_to_start"}
POSITIVE_INTENTS = {"supportive_inspired", "wants_more_content"}
NEGATIVE_WORDS = ["boring", "nobody asked", "overhyped", "audio so bad", "too slow", "without ads"]
POSITIVE_WORDS = ["inspiring", "love", "made my day", "queen", "unreal", "deserved", "solid",
                  "better than", "more of this", "happy", "insane"]
ADJACENT_RULES = [
    ("women_sport", ["wnba", "nwsl"]),
    ("gaming", ["f1 game", "sim racer"]),
    ("stem", ["engineering", "robotics"]),
    ("drive_to_survive", ["drive to survive"]),
    ("data", ["telemetry"]),
]
EMOJI_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)


def detect_intent(text):
    t = text.lower()
    for intent, kws in INTENT_RULES:
        if any(k in t for k in kws):
            return intent
    if EMOJI_ONLY.match(t) or t in ("no way", "lmao") or t.startswith("omg"):
        return "general_reaction"
    return "off_topic"


def detect_sentiment(text, intent):
    t = text.lower()
    if intent == "spam":
        return "spam"
    if intent == "criticism_negative" or any(w in t for w in NEGATIVE_WORDS):
        return "negative"
    if intent in POSITIVE_INTENTS or any(w in t for w in POSITIVE_WORDS):
        return "positive"
    return "neutral"


def detect_language(text):
    t = text.lower()
    if any(k in t for k in ("\u00bf", "qu\u00e9", "me encanta", "d\u00f3nde", "quiero")):
        return "es"
    if any(k in t for k in ("que orgulho", "onde assistir", "menina")):
        return "pt"
    if any(k in t for k in ("wahnsinn", "wo kann man", "mehr davon")):
        return "de"
    if any(k in t for k in ("trop forte", "o\u00f9 regarder", "qui est-elle")):
        return "fr"
    return "en"


def detect_age_hint(text):
    t = text.lower()
    m = re.search(r"\b(?:i'?m|im|i am)\s+(\d{2})\b", t)
    if m:
        a = int(m.group(1))
        return "13-17" if 13 <= a <= 17 else "18-24" if 18 <= a <= 24 else "25+" if a >= 25 else "unknown"
    if any(k in t for k in ("year 10", "school group chat", "grade ")):
        return "13-17"
    if any(k in t for k in ("uni friends", "college student")):
        return "18-24"
    if any(k in t for k in ("my daughter", "as a mom", "as a mum")):
        return "25+"
    return "unknown"


def detect_adjacent(text):
    t = text.lower()
    for tag, kws in ADJACENT_RULES:
        if any(k in t for k in kws):
            return tag
    return ""


# --------------------------------------------------------------------------
# 1. posts_enriched
# --------------------------------------------------------------------------
def parse_post_time(p):
    if "create_time" in p:
        return datetime.fromtimestamp(p["create_time"], tz=timezone.utc)
    s = p.get("timestamp") or p["publishedAt"]
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def build_posts(calendar, drivers):
    raw = json.load(open(RAW / "posts.json", encoding="utf-8"))
    seen, posts = set(), []
    for p in raw:
        if p["post_id"] in seen:
            continue
        seen.add(p["post_id"])
        posts.append(p)

    done = [(int(c["round"]), date.fromisoformat(c["start_date"]), date.fromisoformat(c["end_date"]))
            for c in calendar if c["status"] == "completed"]
    names = [d["driver_name_fictional"].lower() for d in drivers if "wild card" not in d["driver_name_fictional"].lower()]

    rows = []
    for p in posts:
        dt = parse_post_time(p)
        plat = p["platform"]
        if plat == "tiktok":
            views, likes, cmts, shares, saves, wr = (p["play_count"], p["digg_count"], p["comment_count"],
                                                     p["share_count"], p["collect_count"], p["avg_watch_ratio"])
        elif plat == "instagram":
            views, likes, cmts, shares, saves, wr = (p["plays"], p["likes"], p["comments"], p["shares"],
                                                     p["saves"], p["avg_watch_ratio"])
        else:
            views, likes, cmts, shares, saves = (p["view_count"], p["like_count"], p["comment_count"],
                                                 p["shares"], 0)
            wr = None if p["averageViewPercentage"] is None else p["averageViewPercentage"] / 100
        rnd = next((n for n, s, e in done if s - timedelta(days=1) <= dt.date() <= e + timedelta(days=1)), 0)
        a = p["audience"]
        cap = p["caption"]
        rows.append(dict(
            post_id=p["post_id"], platform=plat, creator_type=p["author_type"],
            posted_at=dt.strftime("%Y-%m-%dT%H:%M:%SZ"), post_hour_utc=dt.hour,
            teen_prime_hour=int(15 <= dt.hour <= 21), round=rnd, race_weekend=int(rnd > 0),
            duration_sec=p["duration_sec"], duration_bucket=duration_bucket(p["duration_sec"]),
            theme=detect_theme(cap), hook_type=detect_hook(cap),
            driver_featured=int(p["author_type"] == "driver" or any(n in cap.lower() for n in names)),
            views=views, likes=likes, comments=cmts, shares=shares, saves=saves,
            engagement_rate=r((likes + cmts + shares + saves) / views),
            share_rate=r(shares / views, 5),
            watch_pct=wr, watch_pct_imputed=int(wr is None),
            teen_share=a["age_13_17"], young_adult_share=a["age_18_24"],
            under25_share=r(a["age_13_17"] + a["age_18_24"], 3),
            female_share=a["female_pct"], top_countries="|".join(a["top_countries"]),
            hashtags="|".join(p["hashtags"])))

    # impute missing watch_pct with the median of same platform + duration bucket
    groups = defaultdict(list)
    for x in rows:
        if x["watch_pct"] is not None:
            groups[(x["platform"], x["duration_bucket"])].append(x["watch_pct"])
    plat_med = {pl: med([x["watch_pct"] for x in rows if x["platform"] == pl and x["watch_pct"] is not None])
                for pl in {x["platform"] for x in rows}}
    for x in rows:
        if x["watch_pct"] is None:
            g = groups.get((x["platform"], x["duration_bucket"]))
            x["watch_pct"] = med(g) if g and len(g) >= 3 else plat_med[x["platform"]]
        x["watch_pct"] = r(x["watch_pct"], 3)

    header = list(rows[0].keys())
    write_csv("posts_enriched.csv", header, [[x[h] for h in header] for x in rows])
    return rows, len(raw) - len(posts)


# --------------------------------------------------------------------------
# 2. comments_tagged
# --------------------------------------------------------------------------
def build_comments(posts):
    theme_of = {p["post_id"]: p["theme"] for p in posts}
    raw = json.load(open(RAW / "comments.json", encoding="utf-8"))
    seen, rows = set(), []
    for c in raw:
        if c["comment_id"] in seen:
            continue
        seen.add(c["comment_id"])
        intent = detect_intent(c["text"])
        rows.append(dict(
            comment_id=c["comment_id"], post_id=c["post_id"], platform=c["platform"],
            created_at=c["created_at"], author_id=c["author_id"], text=c["text"],
            language=detect_language(c["text"]), intent=intent,
            sentiment=detect_sentiment(c["text"], intent), age_hint=detect_age_hint(c["text"]),
            adjacent_interest=detect_adjacent(c["text"]), is_spam=int(intent == "spam"),
            new_fan_signal=int(intent in NEW_FAN_INTENTS), post_theme=theme_of.get(c["post_id"], "other"),
            like_count=c["like_count"]))
    header = list(rows[0].keys())
    write_csv("comments_tagged.csv", header, [[x[h] for h in header] for x in rows])
    return rows, len(raw) - len(rows)


# --------------------------------------------------------------------------
# 3. TV: tv_by_age_band + tv_event_uplift
# --------------------------------------------------------------------------
def build_tv():
    events = read_csv("race_events.csv")
    cell = defaultdict(dict)          # (round, session, region, band) -> {minute: viewers}
    missing = 0
    for row in read_csv("tv_ratings.csv"):
        region = "UK" if row["region"] == "GB" else row["region"]
        key = (int(row["round"]), row["session"], region, row["age_band"])
        if row["viewers"] == "":
            missing += 1
            continue
        cell[key][int(row["minute"])] = int(row["viewers"])

    # per (round, session, region): total of band averages -> share of audience
    totals = defaultdict(float)
    for (rd, ses, reg, band), m in cell.items():
        totals[(rd, ses, reg)] += st.mean(m.values())
    out = []
    for (rd, ses, reg, band), m in sorted(cell.items()):
        avg = st.mean(m.values())
        early = [v for k, v in m.items() if k <= 5]
        late = [v for k, v in m.items() if 20 <= k <= 30]
        out.append([rd, ses, reg, band, int(avg), max(m.values()),
                    r(avg / totals[(rd, ses, reg)]), r(st.mean(late) / st.mean(early), 3)])
    write_csv("tv_by_age_band.csv",
              ["round", "session", "region", "age_band", "avg_viewers", "peak_viewers",
               "share_of_audience", "late_vs_early_ratio"], out)

    # event uplift: viewers in the 3 minutes from the event vs the 3 minutes before it
    session_band_minute = defaultdict(lambda: defaultdict(int))
    for (rd, ses, reg, band), m in cell.items():
        for minute, v in m.items():
            session_band_minute[(rd, ses, band)][minute] += v
    acc = defaultdict(list)
    for e in events:
        em, et = int(e["minute"]), e["event_type"]
        if em < 4 or em > 27:
            continue
        for band in ("13-17", "18-24", "25-34", "35+"):
            sbm = session_band_minute[(int(e["round"]), e["session"], band)]
            before = [sbm[m] for m in range(em - 3, em) if m in sbm]
            after = [sbm[m] for m in range(em, em + 3) if m in sbm]
            if before and after:
                acc[(et, band)].append(st.mean(after) / st.mean(before) - 1)
    up = [[et, band, len(v), r(st.mean(v))] for (et, band), v in sorted(acc.items())]
    write_csv("tv_event_uplift.csv", ["event_type", "age_band", "n_events", "avg_uplift_vs_prior_3min"], up)
    return missing


# --------------------------------------------------------------------------
# 4. content_performance
# --------------------------------------------------------------------------
def build_performance(posts):
    plat_stats = {}
    for pl in ["tiktok", "instagram", "youtube"]:
        sub = [p for p in posts if p["platform"] == pl]
        plat_stats[pl] = (med([p["views"] for p in sub]),
                          st.mean(p["under25_share"] for p in sub))
    all_med = med([p["views"] for p in posts])
    all_u25 = st.mean(p["under25_share"] for p in posts)
    plat_stats["all"] = (all_med, all_u25)

    dims = ["theme", "hook_type", "duration_bucket", "creator_type", "teen_prime_hour", "race_weekend"]
    rows = []
    for dim in dims:
        for pl in ["all", "tiktok", "instagram", "youtube"]:
            groups = defaultdict(list)
            for p in posts:
                if pl == "all" or p["platform"] == pl:
                    groups[p[dim]].append(p)
            pm, pu = plat_stats[pl]
            for val, g in sorted(groups.items(), key=lambda kv: str(kv[0])):
                if len(g) < 8:
                    continue
                mv = med([p["views"] for p in g])
                mu = st.mean(p["under25_share"] for p in g)
                rows.append([dim, val, pl, len(g), int(mv), r(med([p["engagement_rate"] for p in g])),
                             r(med([p["watch_pct"] for p in g]), 3), r(mu, 3),
                             r(st.mean(p["teen_share"] for p in g), 3), r(st.mean(p["female_share"] for p in g), 3),
                             r(mv / pm, 3), r((mv * mu) / (pm * pu), 3)])
    write_csv("content_performance.csv",
              ["dimension", "value", "platform", "n_posts", "median_views", "median_engagement_rate",
               "median_watch_pct", "mean_under25_share", "mean_teen_share", "mean_female_share",
               "view_lift_vs_platform_median", "under25_reach_index"], rows)
    return rows


# --------------------------------------------------------------------------
# 5. audience_segments
# --------------------------------------------------------------------------
BENCH = {}
SEGMENTS = [
    dict(id="S1", name="Teen Scrollers", band="13_17", tag=None, themes=None),
    dict(id="S2", name="Women's-sport crossover fans", band="18_24", tag="women_sport", themes={"women_in_sport"}),
    dict(id="S3", name="Gamers and sim racers", band="18_24", tag="gaming", themes={"gaming_sim"}),
    dict(id="S4", name="Future STEM girls", band="13_17", tag="stem", themes={"stem_engineering"}),
    dict(id="S5", name="Drive-to-Survive curious", band="18_24", tag="drive_to_survive", themes={"driver_story"}),
    dict(id="S6", name="Data lovers", band="18_24", tag="data", themes={"data_explainer"}),
]
BAND_FIELD = {"13_17": "teen_share", "18_24": "young_adult_share"}


def norm(vals):
    lo, hi = min(vals), max(vals)
    return [0.0 if hi == lo else (v - lo) / (hi - lo) for v in vals]


def build_segments(posts, comments, tv_rows):
    for row in read_csv("platform_benchmark.csv"):
        BENCH[(row["platform"], row["age_band"])] = float(row["share_of_platform_audience"])
    good = [c for c in comments if not c["is_spam"]]
    cut = sorted(c["created_at"] for c in good)[len(good) // 2]

    # TV late-vs-early retention per age band (mean across the whole dataset)
    tv_ret = defaultdict(list)
    for row in tv_rows:
        tv_ret[row[3]].append(row[7])
    tv_ret = {b: st.mean(v) for b, v in tv_ret.items()}
    band_tv = {"13_17": "13-17", "18_24": "18-24"}

    # Follower-level gap: who follows F1 Academy vs who is on the platform (latest snapshot).
    snaps = read_csv("followers_snapshot.csv")
    last = max(x["snapshot_date"] for x in snaps)
    fol = defaultdict(lambda: defaultdict(int))
    for x in snaps:
        if x["snapshot_date"] == last:
            fol[x["platform"]][x["age_band"]] += int(x["followers"])
    grand = sum(sum(v.values()) for v in fol.values())

    stats = []
    for s in SEGMENTS:
        rel = [p for p in posts if s["themes"] is None or p["theme"] in s["themes"]]
        f = BAND_FIELD[s["band"]]
        tot_views = sum(p["views"] for p in rel)
        current = sum(p["views"] * p[f] for p in rel) / tot_views          # content reach share
        weight = sum(p["views"] * p[f] for p in rel)
        intensity = sum(p["views"] * p[f] * p["engagement_rate"] for p in rel) / weight
        follower_share = sum(v[s["band"]] for v in fol.values()) / grand
        bench = sum(sum(v.values()) * BENCH[(pl, s["band"])] for pl, v in fol.items()) / grand
        gap = max(0.0, bench - follower_share)

        if s["tag"] is None:
            sig = [c for c in good if c["age_hint"] == "13-17"]
        else:
            sig = [c for c in good if c["adjacent_interest"] == s["tag"]]
        n = len(sig)
        ready = sum(c["new_fan_signal"] for c in sig) / n if n else 0
        early = sum(1 for c in sig if c["created_at"] < cut)
        late = n - early
        momentum = (late + 1) / (early + 1) - 1

        # best platform / hook / duration by band-weighted views
        score = lambda p: p["views"] * p[f]
        by = lambda key, pool, minn=8: max(
            ((k, med([score(p) for p in g])) for k, g in
             ((k, [p for p in pool if p[key] == k]) for k in {p[key] for p in pool}) if len(g) >= minn),
            key=lambda kv: kv[1], default=("n/a", 0))[0]
        best_theme = by("theme", rel) if s["themes"] is None else sorted(s["themes"])[0]
        pool = rel if len(rel) >= 40 else posts
        stats.append(dict(s=s, follower_share=follower_share, bench=bench, gap=gap, content_reach=current,
                          intensity=intensity, n=n, ready=ready, momentum=momentum,
                          platform=by("platform", rel, 5), hook=by("hook_type", pool), dur=by("duration_bucket", pool),
                          theme=best_theme, n_posts=len(rel), tv=tv_ret.get(band_tv[s["band"]], 0)))

    # opportunity = 0.30 size + 0.25 follower gap + 0.20 readiness + 0.15 momentum + 0.10 engagement
    # (each input min-max normalised across the six segments, so the score is a RELATIVE ranking)
    nm = {k: norm([x[k] for x in stats]) for k in ("n", "gap", "ready", "momentum", "intensity")}
    rows = []
    for i, x in enumerate(stats):
        x["opp"] = 100 * (0.30 * nm["n"][i] + 0.25 * nm["gap"][i] + 0.20 * nm["ready"][i]
                          + 0.15 * nm["momentum"][i] + 0.10 * nm["intensity"][i])
    ranked = sorted(stats, key=lambda x: -x["opp"])
    for rank, x in enumerate(ranked, 1):
        s = x["s"]
        rows.append([rank, s["id"], s["name"], s["band"].replace("_", "-"), x["n_posts"], x["n"],
                     r(x["follower_share"], 3), r(x["bench"], 3), r(x["gap"], 3), r(x["content_reach"], 3),
                     r(x["intensity"], 3), r(x["ready"], 3), r(x["momentum"], 3), r(x["tv"], 3), r(x["opp"], 1),
                     x["platform"], x["theme"], x["hook"], x["dur"]])
    write_csv("audience_segments.csv",
              ["opportunity_rank", "segment_id", "segment_name", "primary_age_band", "relevant_posts",
               "interest_signal_comments", "current_follower_share", "benchmark_share", "follower_gap",
               "content_reach_share", "engagement_intensity", "conversion_readiness", "momentum",
               "tv_late_vs_early_ratio", "opportunity_score",
               "best_platform", "best_theme", "best_hook", "best_duration_bucket"], rows)
    return rows


# --------------------------------------------------------------------------
# 6. growth_baseline
# --------------------------------------------------------------------------
HORIZON_MONTHS = 6          # assumption: confirm with the organiser
TARGET_GROWTH = 0.20


def build_growth():
    snaps = read_csv("followers_snapshot.csv")
    dates = sorted({s["snapshot_date"] for s in snaps})
    first, last = dates[0], dates[-1]
    months = len(dates) - 1
    res = {}
    for s in snaps:
        key = s["platform"]
        res.setdefault(key, defaultdict(lambda: defaultdict(int)))
        res[key][s["snapshot_date"]][s["age_band"]] += int(s["followers"])
    rows, tot = [], defaultdict(float)
    for pl in ["tiktok", "instagram", "youtube"]:
        u25 = lambda d: res[pl][d]["13_17"] + res[pl][d]["18_24"]
        total = sum(res[pl][last].values())
        base, start = u25(last), u25(first)
        organic = (base / start) ** (1 / months) - 1
        target = base * (1 + TARGET_GROWTH)
        projected = base * (1 + organic) ** HORIZON_MONTHS
        req = (1 + TARGET_GROWTH) ** (1 / HORIZON_MONTHS) - 1
        rows.append([pl, last, total, base, r(base / total, 3), r(organic, 4), int(target), r(req, 4),
                     int(projected), int(target - projected)])
        for k, v in (("total", total), ("base", base), ("target", target), ("projected", projected)):
            tot[k] += v
    organic_all = sum(rw[3] * rw[5] for rw in rows) / tot["base"]
    rows.append(["ALL", last, int(tot["total"]), int(tot["base"]), r(tot["base"] / tot["total"], 3),
                 r(organic_all, 4), int(tot["target"]), r((1 + TARGET_GROWTH) ** (1 / HORIZON_MONTHS) - 1, 4),
                 int(tot["projected"]), int(tot["target"] - tot["projected"])])
    write_csv("growth_baseline.csv",
              ["platform", "baseline_date", "total_followers", "under25_followers", "under25_share",
               "organic_monthly_growth_under25", f"target_under25_plus{int(TARGET_GROWTH * 100)}pct",
               f"required_monthly_growth_{HORIZON_MONTHS}m", f"projected_organic_after_{HORIZON_MONTHS}m",
               "followers_gap_to_target"], rows)


def main():
    print("Refining raw -> refined ...")
    calendar, drivers = read_csv("race_calendar.csv"), read_csv("drivers.csv")
    posts, dup_posts = build_posts(calendar, drivers)
    comments, dup_comments = build_comments(posts)
    missing_tv = build_tv()
    tv_rows = list(csv.reader(open(REF / "tv_by_age_band.csv", encoding="utf-8")))[1:]
    tv_rows = [[int(x[0]), x[1], x[2], x[3], int(x[4]), int(x[5]), float(x[6]), float(x[7])] for x in tv_rows]
    build_performance(posts)
    build_segments(posts, comments, tv_rows)
    build_growth()
    print(f"  cleaned: {dup_posts} duplicate posts, {dup_comments} duplicate comments, "
          f"{missing_tv} missing TV minutes, "
          f"{sum(p['watch_pct_imputed'] for p in posts)} imputed watch_pct values")
    print("  themes:", dict(Counter(p["theme"] for p in posts)))
    print("  intents:", dict(Counter(c["intent"] for c in comments)))


if __name__ == "__main__":
    main()
