"""
Sanity checks for the synthetic raw + refined datasets.
Usage:  python data/validate_data.py      (exit code 1 if any check fails)
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW, REF = ROOT / "raw", ROOT / "refined"
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


raw_posts = json.load(open(RAW / "posts.json", encoding="utf-8"))
raw_comments = json.load(open(RAW / "comments.json", encoding="utf-8"))
posts, comments = rows(REF / "posts_enriched.csv"), rows(REF / "comments_tagged.csv")

# --- reconciliation raw -> refined
check(len(raw_posts) - len({p["post_id"] for p in raw_posts}) == 5, "raw posts contain 5 duplicate rows")
check(len(posts) == len({p["post_id"] for p in raw_posts}), f"refined posts = unique raw posts ({len(posts)})")
check(len(raw_comments) - len({c["comment_id"] for c in raw_comments}) == 25, "raw comments contain 25 duplicate rows")
check(len(comments) == len({c["comment_id"] for c in raw_comments}), f"refined comments = unique raw comments ({len(comments)})")

# --- keys and integrity
check(len({p["post_id"] for p in posts}) == len(posts), "refined post_id is unique")
check(len({c["comment_id"] for c in comments}) == len(comments), "refined comment_id is unique")
ids = {p["post_id"] for p in posts}
check(all(c["post_id"] in ids for c in comments), "every comment points to an existing post")

# --- value ranges
check(all(abs(float(p["under25_share"]) - (float(p["teen_share"]) + float(p["young_adult_share"]))) < 0.002 for p in posts),
      "under25_share = teen_share + young_adult_share")
check(all(0 < float(p["watch_pct"]) <= 1 for p in posts), "watch_pct is within (0, 1] after normalising YouTube")
check(all(int(p["views"]) > 0 for p in posts), "views are positive")
check(all(p["theme"] != "other" for p in posts), "every post received a theme")
check(not any(p["watch_pct"] == "" for p in posts), "no missing watch_pct after imputation")
check({c["sentiment"] for c in comments} <= {"positive", "neutral", "negative", "spam"}, "sentiment values are valid")

# --- raw audience shares sum to ~1
check(all(abs(sum(p["audience"][f"age_{b}"] for b in ("13_17", "18_24", "25_34", "35_plus")) - 1) < 0.01
          for p in raw_posts), "raw audience age shares sum to 1")

# --- TV
tv = rows(RAW / "tv_ratings.csv")
check(len(tv) == 9360, f"raw TV rows = 13 sessions x 30 min x 6 regions x 4 bands ({len(tv)})")
check(any(r["region"] == "GB" for r in tv), "raw TV still has the mixed region code (GB) to clean")
check(not any(r["region"] == "GB" for r in rows(REF / "tv_by_age_band.csv")), "refined TV uses a single code (UK)")
check({r["round"] for r in tv} == {"1", "2", "3", "4"}, "TV data only covers completed rounds 1-4")
share = {}
for r in rows(REF / "tv_by_age_band.csv"):
    share.setdefault(r["age_band"], []).append(float(r["share_of_audience"]))
u25 = sum(sum(v) / len(v) for k, v in share.items() if k in ("13-17", "18-24"))
check(0.05 < u25 < 0.15, f"under-25 share of TV audience is low, as expected ({u25:.1%})")

# --- privacy: no emails, phone numbers or real-looking @handles
blob = json.dumps(raw_comments) + json.dumps(raw_posts)
check(not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob), "no email addresses in the data")
check(not re.search(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b", blob), "no phone numbers in the data")
check(not re.search(r"@\w+", " ".join(c["text"] for c in raw_comments)), "no @mentions in comment text")

# --- files exist
for f in ["posts_enriched", "comments_tagged", "tv_by_age_band", "tv_event_uplift", "content_performance",
          "audience_segments", "growth_baseline"]:
    check((REF / f"{f}.csv").exists(), f"refined/{f}.csv exists")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
