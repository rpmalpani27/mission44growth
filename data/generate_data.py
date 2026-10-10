"""
Synthetic RAW data generator - F1 Academy "Fan Growth Engine" hackathon.

IMPORTANT: Everything produced here is SYNTHETIC.
  - Team names, venues and the 2026 race calendar are real and public.
  - Drivers, fans, handles, comments and ALL numbers are invented.
  - Platform audience benchmarks are illustrative assumptions, not platform data.

Standard library only. Seeded, so output is repeatable.
Usage:  python data/generate_data.py
Output: data/raw/*
"""
import csv
import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SEED = 2026
rng = random.Random(SEED)
RAW = Path(__file__).resolve().parent / "raw"
RAW.mkdir(parents=True, exist_ok=True)

AS_OF = date(2026, 10, 10)          # "today" for the project
N_POSTS = 500
N_DUP_POSTS = 5                     # raw data quality issue to clean later
N_COMMENTS = 5000
N_DUP_COMMENTS = 25

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
# (round, venue, country, country_code, start, end, has_opening_race)
ROUNDS = [
    (1, "Shanghai", "China", "CN", date(2026, 3, 13), date(2026, 3, 15), False),
    (2, "Montreal", "Canada", "CA", date(2026, 5, 22), date(2026, 5, 24), True),
    (3, "Silverstone", "Great Britain", "GB", date(2026, 7, 3), date(2026, 7, 5), False),
    (4, "Zandvoort", "Netherlands", "NL", date(2026, 8, 21), date(2026, 8, 23), False),
    (5, "Austin", "United States", "US", date(2026, 10, 23), date(2026, 10, 25), True),
    (6, "Las Vegas", "United States", "US", date(2026, 11, 19), date(2026, 11, 21), False),
]
DONE = [r for r in ROUNDS if r[5] < AS_OF]

# Real team names, FICTIONAL drivers.
DRIVERS = [
    ("D01", "Mira Lindqvist", "Prema Racing"), ("D02", "Tessa Okonkwo", "Prema Racing"),
    ("D03", "Juno Castellanos", "Prema Racing"),
    ("D04", "Elodie Marchetti", "Campos Racing"), ("D05", "Bianca Silveira", "Campos Racing"),
    ("D06", "Zofia Wrona", "Campos Racing"),
    ("D07", "Anneke de Rooij", "MP Motorsport"), ("D08", "Isla Brennan", "MP Motorsport"),
    ("D09", "Saoirse Quill", "MP Motorsport"),
    ("D10", "Harper Lindgren", "Rodin Motorsport"), ("D11", "Camila Duarte", "Rodin Motorsport"),
    ("D12", "Yuki Aramaki", "Rodin Motorsport"),
    ("D13", "Noor Haddad", "ART Grand Prix"), ("D14", "Clara Vasseur", "ART Grand Prix"),
    ("D15", "Maeve Callahan", "ART Grand Prix"),
    ("D16", "Rosalind Achebe", "Hitech"), ("D17", "Daria Volkova", "Hitech"),
    ("D18", "Wild Card Entry", "Hitech"),
]
DRIVER_POP = {d[0]: rng.uniform(0.6, 1.6) for d in DRIVERS}

AGE_BANDS = ["13_17", "18_24", "25_34", "35_plus"]
PLATFORMS = ["tiktok", "instagram", "youtube"]
PLATFORM_W = {"tiktok": 0.40, "instagram": 0.35, "youtube": 0.25}

START_FOLLOWERS = {"tiktok": 380000, "instagram": 520000, "youtube": 210000}
FOLLOWER_MIX = {
    "tiktok":    {"13_17": 0.10, "18_24": 0.34, "25_34": 0.32, "35_plus": 0.24},
    "instagram": {"13_17": 0.06, "18_24": 0.27, "25_34": 0.34, "35_plus": 0.33},
    "youtube":   {"13_17": 0.04, "18_24": 0.20, "25_34": 0.32, "35_plus": 0.44},
}
# Assumed organic monthly follower growth per age band. Deliberately modest, so the
# +20% under-25 goal needs real acceleration rather than happening by itself.
MONTHLY_GROWTH = {"13_17": 0.016, "18_24": 0.013, "25_34": 0.009, "35_plus": 0.006}
# Illustrative general-platform audience (what a "healthy" reach would look like)
BENCHMARK = {
    "tiktok":    {"13_17": 0.20, "18_24": 0.34, "25_34": 0.28, "35_plus": 0.18},
    "instagram": {"13_17": 0.12, "18_24": 0.30, "25_34": 0.30, "35_plus": 0.28},
    "youtube":   {"13_17": 0.10, "18_24": 0.22, "25_34": 0.28, "35_plus": 0.40},
}
FEMALE_BASE = {"tiktok": 0.46, "instagram": 0.52, "youtube": 0.38}

# --------------------------------------------------------------------------
# Content model (latent drivers of performance)
# --------------------------------------------------------------------------
THEMES = {
    # w: base weight, view: view multiplier, like/cmt/shr/sav: engagement multipliers,
    # tilt: age-mix shift (13-17, 18-24, 25-34, 35+), fem: female-share shift
    "race_recap":         dict(w=14, view=0.90, like=0.85, cmt=0.9, shr=0.8, sav=0.7,
                               tilt=(-.04, -.06, .02, .08), fem=-.04),
    "reverse_grid_chaos": dict(w=10, view=1.25, like=1.0, cmt=1.0, shr=1.1, sav=0.9,
                               tilt=(.03, .03, 0, -.06), fem=0.0),
    "driver_story":       dict(w=14, view=1.30, like=1.15, cmt=1.5, shr=1.4, sav=1.1,
                               tilt=(.04, .06, -.02, -.08), fem=.08),
    "stem_engineering":   dict(w=9, view=1.10, like=1.0, cmt=1.3, shr=1.4, sav=1.5,
                               tilt=(.08, .04, 0, -.12), fem=.12),
    "behind_the_scenes":  dict(w=11, view=1.20, like=1.05, cmt=1.0, shr=1.0, sav=1.0,
                               tilt=(.02, .04, 0, -.06), fem=.03),
    "fashion_lifestyle":  dict(w=8, view=1.35, like=1.2, cmt=1.1, shr=1.2, sav=1.4,
                               tilt=(.06, .12, -.04, -.14), fem=.15),
    "gaming_sim":         dict(w=7, view=1.25, like=1.1, cmt=1.4, shr=1.1, sav=1.0,
                               tilt=(.08, .08, -.02, -.14), fem=-.06),
    "data_explainer":     dict(w=7, view=0.85, like=0.75, cmt=1.2, shr=0.7, sav=1.8,
                               tilt=(-.05, .02, .08, -.05), fem=-.12),
    "women_in_sport":     dict(w=7, view=1.00, like=0.95, cmt=1.0, shr=1.0, sav=1.0,
                               tilt=(.02, .08, .02, -.12), fem=.20),
    "memes_trend":        dict(w=13, view=1.40, like=1.3, cmt=0.9, shr=1.8, sav=0.8,
                               tilt=(.10, .08, -.08, -.10), fem=0.0),
}
CREATOR_W = {"official": 0.45, "driver": 0.20, "team": 0.15, "fan_creator": 0.20}
CREATOR_VIEW = {"official": 1.0, "driver": 1.4, "team": 0.9, "fan_creator": 0.8}
CREATOR_THEME_AFFINITY = {
    "official": {"race_recap": 2.0, "reverse_grid_chaos": 1.5},
    "driver": {"driver_story": 2.0, "fashion_lifestyle": 2.0, "behind_the_scenes": 1.5, "race_recap": 0.3},
    "team": {"stem_engineering": 2.0, "behind_the_scenes": 1.5, "race_recap": 1.2},
    "fan_creator": {"memes_trend": 3.0, "gaming_sim": 2.0, "women_in_sport": 1.5, "race_recap": 0.6},
}
PLATFORM_THEME_MULT = {
    "youtube": {"race_recap": 2.0, "data_explainer": 1.8, "memes_trend": 0.4},
    "tiktok": {"memes_trend": 1.6, "fashion_lifestyle": 1.3},
}
HOOK_VIEW = {"question_hook": 1.2, "pov_hook": 1.35, "bold_claim": 1.15,
             "story_tease": 1.25, "result_first": 1.1, "none": 0.8}
HOOK_W = {
    "official": {"none": .35, "question_hook": .15, "pov_hook": .08, "bold_claim": .12, "story_tease": .12, "result_first": .18},
    "driver": {"none": .25, "question_hook": .15, "pov_hook": .15, "bold_claim": .10, "story_tease": .25, "result_first": .10},
    "team": {"none": .30, "question_hook": .15, "pov_hook": .12, "bold_claim": .13, "story_tease": .15, "result_first": .15},
    "fan_creator": {"none": .12, "question_hook": .22, "pov_hook": .28, "bold_claim": .18, "story_tease": .10, "result_first": .10},
}
HOOK_PHRASES = {
    "question_hook": ["Wait, did you see this?", "Who thought this was possible??",
                      "Guess who just took pole?", "Can you spot the move?"],
    "pov_hook": ["POV: you're lined up on the grid.", "POV: lights out and you're P9.",
                 "POV: first lap in the rain."],
    "bold_claim": ["Hot take: this was the overtake of the season.", "Nobody talks about how hard this is.",
                   "This is NOT a support race."],
    "story_tease": ["Her story starts at age 7.", "You won't believe how she got here.",
                    "The reason she never gave up."],
    "result_first": ["She WON from P9.", "Pole by 0.04s.", "Podium on debut."],
    "none": [""],
}
BODIES = {
    "race_recap": ["Feature Race recap from {venue}: all the key moments in 30 seconds.",
                   "Full race highlights from {venue}."],
    "reverse_grid_chaos": ["Reverse grid madness at {venue}! P8 to P1 in three laps.",
                           "Reverse Grid Race chaos, every overtake."],
    "driver_story": ["Meet {driver} of {team}. A day in her life at {venue}.",
                     "{driver} talks nerves, karting and her first F4 win."],
    "stem_engineering": ["How the Tatuus T421-F1A is set up for {venue}, explained by the team engineer.",
                         "Girls in STEM: meet the engineer behind {team}'s car."],
    "behind_the_scenes": ["Paddock access at {venue}: garage, grid walk and pre-race rituals.",
                          "Inside the {team} garage before qualifying."],
    "fashion_lifestyle": ["Helmet designs of the grid, ranked.", "Race suit fit check with {driver}."],
    "gaming_sim": ["Sim racer vs real F4 driver: who is faster around {venue}.",
                   "We let {driver} try the F1 game. Her reaction!"],
    "data_explainer": ["Why every tenth counts: breaking down the qualifying lap at {venue}.",
                       "Telemetry breakdown: where the lap was won."],
    "women_in_sport": ["Women in sport are building something special. F1 Academy x {adjacent}.",
                       "From the court to the track: women's sport is on the rise."],
    "memes_trend": ["Me watching the grid on a Sunday \U0001F602", "Trend audio + onboard = chef's kiss"],
}
THEME_TAGS = {
    "race_recap": ["#Highlights"], "reverse_grid_chaos": ["#ReverseGrid"],
    "driver_story": ["#MeetTheDriver", "#DriveToSurvive"], "stem_engineering": ["#WomenInSTEM", "#STEM"],
    "behind_the_scenes": ["#Paddock", "#BTS"], "fashion_lifestyle": ["#HelmetDesign", "#GRWM"],
    "gaming_sim": ["#F1Game", "#SimRacing"], "data_explainer": ["#F1Data", "#Telemetry"],
    "women_in_sport": ["#WomenInSport", "#WNBA", "#NWSL"], "memes_trend": ["#F1Memes", "#fyp"],
}
HOUR_W = [1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 6, 6, 6, 6, 6, 7, 8, 9, 9, 8, 6, 4, 2, 1]
EMOJIS = ["\U0001F525", "\U0001F60D", "\U0001F4AA", "\U0001F3CE\uFE0F", "\U0001F44F", "\u2728", "\u2764\uFE0F", "\U0001F64C"]
COUNTRIES = ["GB", "US", "NL", "CA", "DE", "BR", "ES", "IT", "FR", "AU", "MX", "IN"]
COUNTRY_W = [14, 14, 9, 8, 7, 7, 6, 5, 5, 4, 4, 3]


def weighted(d):
    keys = list(d)
    return rng.choices(keys, weights=[d[k] for k in keys])[0]


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def weekend_round(day):
    for r in DONE:
        if r[4] - timedelta(days=1) <= day <= r[5] + timedelta(days=1):
            return r
    return None


def sample_post_datetime():
    if rng.random() < 0.62:
        r = rng.choice(DONE)
        day = r[4] - timedelta(days=1) + timedelta(days=rng.randint(0, 4))
    else:
        start, end = date(2026, 3, 1), date(2026, 9, 5)
        day = start + timedelta(days=rng.randint(0, (end - start).days))
    hour = rng.choices(range(24), weights=HOUR_W)[0]
    return datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), tzinfo=timezone.utc)


def sample_duration(platform, theme):
    if platform == "youtube":
        longish = theme in ("race_recap", "data_explainer")
        bucket = weighted({"short": 0.35 if longish else 0.6, "mid": 0.25, "long": 0.4 if longish else 0.15})
        return {"short": rng.randint(15, 60), "mid": rng.randint(61, 300), "long": rng.randint(301, 1200)}[bucket]
    lo, hi = rng.choices([(8, 15), (16, 30), (31, 45), (46, 60), (61, 90), (91, 180)],
                         weights=[12, 30, 20, 16, 12, 10])[0]
    return rng.randint(lo, hi)


def duration_mult(platform, d):
    if platform == "youtube":
        return 1.2 if d <= 60 else (0.8 if d <= 300 else 0.9)
    for limit, m in ((15, 1.25), (30, 1.45), (45, 1.2), (60, 1.0), (90, 0.8)):
        if d <= limit:
            return m
    return 0.6


def watch_ratio(platform, d, hook):
    if platform == "youtube" and d > 300:
        base = rng.uniform(0.28, 0.40)
    elif platform == "youtube":
        base = clip(0.70 - 0.0020 * d, 0.2, 0.75)
    else:
        base = clip(0.78 - 0.0045 * d, 0.14, 0.9)
    if hook != "none":
        base += 0.04
    return clip(base + rng.gauss(0, 0.04), 0.08, 0.97)


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------
def build_posts():
    posts, meta = [], []
    for i in range(N_POSTS):
        platform = weighted(PLATFORM_W)
        creator = weighted(CREATOR_W)
        tw = {}
        for t, cfg in THEMES.items():
            tw[t] = cfg["w"] * CREATOR_THEME_AFFINITY[creator].get(t, 0.6 if creator == "fan_creator" else 1.0) \
                * PLATFORM_THEME_MULT.get(platform, {}).get(t, 1.0)
        theme = weighted(tw)
        cfg = THEMES[theme]
        hook = weighted(HOOK_W[creator])
        dur = sample_duration(platform, theme)
        dt = sample_post_datetime()
        rnd = weekend_round(dt.date())
        venue = rnd[1] if rnd else "the paddock"

        driver = rng.choice(DRIVERS)
        caption_parts = []
        phrase = rng.choice(HOOK_PHRASES[hook])
        if phrase:
            caption_parts.append(phrase)
        body = rng.choice(BODIES[theme]).format(
            venue=venue, driver=driver[1], team=driver[2], adjacent=rng.choice(["WNBA", "NWSL"]))
        caption_parts.append(body)
        if rng.random() < 0.45:
            caption_parts.append(rng.choice(EMOJIS))
        caption = " ".join(caption_parts)
        tags = ["#F1Academy"] + ([ "#F1"] if rng.random() < 0.6 else []) + \
            rng.sample(THEME_TAGS[theme], k=min(len(THEME_TAGS[theme]), rng.randint(1, 2)))

        # ---- performance ----
        base = {"tiktok": 40000, "instagram": 25000, "youtube": 18000}[platform]
        hour_m = 1.15 if 15 <= dt.hour <= 21 else 1.0
        wk_m = 1.5 if rnd else 1.0
        growth_m = 1 + 0.04 * ((dt.date() - date(2026, 3, 1)).days / 45)
        views = base * cfg["view"] * HOOK_VIEW[hook] * duration_mult(platform, dur) * CREATOR_VIEW[creator] \
            * hour_m * wk_m * growth_m * math.exp(rng.gauss(0, 0.55))
        views = max(500, int(views))
        wr = watch_ratio(platform, dur, hook)
        like_rate = 0.065 * cfg["like"] * rng.uniform(0.7, 1.3) * (0.7 + wr)
        likes = int(views * like_rate)
        comments = int(views * 0.0012 * cfg["cmt"] * rng.uniform(0.6, 1.5))
        shares = int(views * 0.006 * cfg["shr"] * rng.uniform(0.6, 1.5))
        saves = int(views * 0.004 * cfg["sav"] * rng.uniform(0.6, 1.5))

        # ---- audience ----
        vec = [FOLLOWER_MIX[platform][b] + cfg["tilt"][k] for k, b in enumerate(AGE_BANDS)]
        if hook in ("pov_hook", "question_hook"):
            vec[0] += 0.02
            vec[3] -= 0.02
        vec = [max(0.01, v * (1 + rng.gauss(0, 0.12))) for v in vec]
        s = sum(vec)
        aud = {f"age_{b}": round(v / s, 3) for b, v in zip(AGE_BANDS, vec)}
        aud["female_pct"] = round(clip(FEMALE_BASE[platform] + cfg["fem"] + rng.gauss(0, 0.04), 0.1, 0.9), 3)
        aud["top_countries"] = [c for c in dict.fromkeys(
            rng.choices(COUNTRIES, weights=COUNTRY_W, k=6))][:3]
        if rnd and rnd[3] not in aud["top_countries"] and rng.random() < 0.6:
            aud["top_countries"][2] = rnd[3]

        pid = f"{ {'tiktok': 'tt', 'instagram': 'ig', 'youtube': 'yt'}[platform] }_{i + 1:05d}"
        handle = {"official": "official_channel_demo", "team": f"team_{driver[2].split()[0].lower()}_demo",
                  "driver": f"driver_{driver[0].lower()}_demo",
                  "fan_creator": "fan_" + hashlib.sha1(f"fan{i}".encode()).hexdigest()[:6]}[creator]
        missing_watch = rng.random() < 0.06

        rec = {"post_id": pid, "platform": platform, "author_type": creator, "author_handle": handle,
               "caption": caption, "hashtags": tags, "duration_sec": dur}
        if platform == "tiktok":
            rec.update({"create_time": int(dt.timestamp()), "play_count": views, "digg_count": likes,
                        "comment_count": comments, "share_count": shares, "collect_count": saves,
                        "avg_watch_ratio": None if missing_watch else round(wr, 3)})
        elif platform == "instagram":
            rec.update({"timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S+0000"), "plays": views, "likes": likes,
                        "comments": comments, "shares": shares, "saves": saves,
                        "avg_watch_ratio": None if missing_watch else round(wr, 3)})
        else:
            rec.update({"publishedAt": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "view_count": views,
                        "like_count": likes, "comment_count": comments, "shares": shares,
                        "averageViewPercentage": None if missing_watch else round(wr * 100, 1)})
        rec["audience"] = aud
        posts.append(rec)
        meta.append(dict(theme=theme, hook=hook, aud=aud, comments=comments, driver=driver, platform=platform))
    return posts, meta


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------
INTENT_BASE = {"supportive_inspired": .22, "wants_more_content": .12, "where_to_watch": .08, "who_is_she": .08,
               "is_this_real_racing": .05, "ask_how_to_start": .04, "rivalry_fandom": .10,
               "criticism_negative": .07, "compare_main_f1": .06, "off_topic": .12, "spam": .03,
               "general_reaction": .03}
INTENT_THEME_MULT = {
    "driver_story": {"who_is_she": 2.2, "supportive_inspired": 1.3},
    "stem_engineering": {"ask_how_to_start": 4.0, "supportive_inspired": 1.3},
    "memes_trend": {"general_reaction": 3.0, "off_topic": 1.2},
    "race_recap": {"where_to_watch": 1.5, "compare_main_f1": 1.5, "criticism_negative": 1.3},
    "fashion_lifestyle": {"wants_more_content": 1.5, "who_is_she": 1.5},
    "gaming_sim": {"is_this_real_racing": 2.5, "compare_main_f1": 1.5},
    "women_in_sport": {"supportive_inspired": 1.5},
    "data_explainer": {"criticism_negative": 1.2, "compare_main_f1": 1.5},
    "reverse_grid_chaos": {"rivalry_fandom": 1.5, "where_to_watch": 1.3},
}
TEXT = {
    "supportive_inspired": ["She's unreal, so inspiring {e}", "this is why I love women in motorsport {e}",
                            "girls can do ANYTHING omg {e}", "watching this made my day, go {d}!!",
                            "queen behavior {e}"],
    "wants_more_content": ["more of this pls!!", "need a part 2 {e}", "make a series of this",
                           "can we get a day in the life of the whole grid?", "more behind the scenes please"],
    "where_to_watch": ["where can I watch the full race?", "is this on F1 TV or just YouTube",
                       "what channel is this on in the UK", "how do i watch the next round live",
                       "when is the next race and where do i stream it"],
    "who_is_she": ["wait who is she??", "who's the driver in the pink helmet", "what's her name?? new fan here",
                   "i need to know more about her, who is she", "which team is she on"],
    "is_this_real_racing": ["wait is this real racing or a game {e}", "is this actual F4?? looks so fast",
                            "these are real cars? how fast do they go", "is this the same track as the F1 race"],
    "ask_how_to_start": ["how do you even start racing?", "how do i become a race engineer",
                         "i want to be a driver one day, where do i start", "any advice for getting into karting",
                         "is there a programme for girls who want to get into motorsport"],
    "rivalry_fandom": ["{t} fans where are we", "{d} deserved that win", "{t} all day",
                       "{d} vs {d2} is the rivalry we needed"],
    "criticism_negative": ["this is boring tbh", "why is the audio so bad", "nobody asked for this",
                           "the racing is too slow", "overhyped", "can't even watch it without ads"],
    "compare_main_f1": ["is it like the F1 races on Sunday", "better than the main race honestly",
                        "why isn't this on the same channel as F1", "I only watch F1 but this is solid"],
    "off_topic": ["first!!", "nice weather today", "anyone else here after the football match",
                  "follow me back pls", "lol"],
    "spam": ["FREE followers click my bio!!", "earn $500/day dm me", "check out my page for crypto tips"],
    "general_reaction": ["\U0001F602\U0001F602\U0001F602", "omg {e}", "no way", "LMAO", "\U0001F480\U0001F480"],
}
FOREIGN = {
    "supportive_inspired": ["Qu\u00e9 crack, me encanta {e}", "Que orgulho dessa menina!", "Wahnsinn, so stark!", "trop forte elle !"],
    "where_to_watch": ["\u00bfD\u00f3nde puedo ver la carrera completa?", "onde assistir a corrida?",
                       "wo kann man das live sehen?", "o\u00f9 regarder la course ?"],
    "wants_more_content": ["Quiero m\u00e1s videos as\u00ed", "mehr davon bitte"],
    "who_is_she": ["\u00bfQui\u00e9n es ella?", "qui est-elle ?"],
}
ADJACENT = {
    "women_in_sport": ("wnba", ["found you through my WNBA feed", "NWSL fan here, love seeing women's sport grow"]),
    "gaming_sim": ("gaming", ["saw this on the F1 game stream", "sim racer here, this looks insane"]),
    "stem_engineering": ("stem", ["engineering is my favourite subject", "robotics club would love this"]),
    "driver_story": ("dts", ["watched Drive to Survive and now I'm here"]),
    "data_explainer": ("data", ["the telemetry nerd in me is happy"]),
}
TEEN_HINTS = ["I'm {a} and this got me hooked", "im {a} lol", "in year 10 and obsessed",
              "my school group chat is losing it"]
YA_HINTS = ["I'm {a}, new fan", "uni friends sent me this", "college student here"]
ADULT_HINTS = ["my daughter {x} loves this", "as a mom I love this", "I'm {a} and been watching F1 for years"]


def build_comments(posts, meta):
    weights = [max(1, m["comments"]) for m in meta]
    idxs = rng.choices(range(len(posts)), weights=weights, k=N_COMMENTS - N_DUP_COMMENTS)
    out = []
    for n, idx in enumerate(idxs):
        p, m = posts[idx], meta[idx]
        w = dict(INTENT_BASE)
        for k, mult in INTENT_THEME_MULT.get(m["theme"], {}).items():
            w[k] *= mult
        intent = weighted(w)
        d1, d2 = rng.sample(DRIVERS, 2)
        e = rng.choice(EMOJIS) if rng.random() < 0.6 else ""
        if intent in FOREIGN and rng.random() < 0.10:
            text = rng.choice(FOREIGN[intent]).format(e=e).strip()
        else:
            text = rng.choice(TEXT[intent]).format(e=e, d=d1[1].split()[0], d2=d2[1].split()[0],
                                                   t=d1[2]).strip()
            if intent not in ("spam", "general_reaction"):
                adj = ADJACENT.get(m["theme"])
                if adj and rng.random() < 0.35:
                    text += ". " + rng.choice(adj[1])
                elif rng.random() < 0.04:
                    text += ". " + rng.choice(sum((v[1] for v in ADJACENT.values()), []))
                if rng.random() < 0.11:
                    band = rng.choices(AGE_BANDS, weights=[m["aud"][f"age_{b}"] for b in AGE_BANDS])[0]
                    if band == "13_17":
                        hint = rng.choice(TEEN_HINTS).format(a=rng.randint(13, 17))
                    elif band == "18_24":
                        hint = rng.choice(YA_HINTS).format(a=rng.randint(18, 24))
                    else:
                        hint = rng.choice(ADULT_HINTS).format(a=rng.randint(26, 52), x=rng.choice(["Mia", "Ella"]))
                    text += ". " + hint
        if rng.random() < 0.30:
            text = text.lower()
        if rng.random() < 0.08:
            text += "!!!"
        # timestamp
        ts_str = p.get("create_time") or p.get("timestamp") or p.get("publishedAt")
        if isinstance(ts_str, int):
            ts = datetime.fromtimestamp(ts_str, tz=timezone.utc)
        else:
            ts = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        ts += timedelta(hours=min(120, rng.expovariate(1 / 6)))
        out.append({
            "comment_id": f"c_{n + 1:05d}", "post_id": p["post_id"], "platform": p["platform"],
            "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "author_id": hashlib.sha1(f"author-{rng.randint(1, 2500)}".encode()).hexdigest()[:10],
            "text": text, "like_count": int(rng.expovariate(1 / 3)),
        })
    out += [dict(c) for c in rng.sample(out, N_DUP_COMMENTS)]   # raw duplicates
    return out


# --------------------------------------------------------------------------
# TV ratings (Nielsen-style, minute by minute) and race events
# --------------------------------------------------------------------------
REGIONS = {"UK": 38000, "US": 30000, "CA": 14000, "NL": 22000, "DE": 12000, "BR": 9000}
REGION_AGE_SHARE = {  # 13-17, 18-24, 25-34, 35+
    "UK": (.03, .06, .15, .76), "US": (.04, .08, .18, .70), "CA": (.04, .07, .17, .72),
    "NL": (.03, .06, .16, .75), "DE": (.03, .05, .14, .78), "BR": (.05, .10, .20, .65)}
TV_BANDS = ["13-17", "18-24", "25-34", "35+"]
SESSION_MULT = {"Qualifying": 0.70, "Opening Race": 0.90, "Reverse Grid Race": 1.00, "Feature Race": 1.25}
ROUND_MULT = {1: 0.85, 2: 1.00, 3: 1.10, 4: 1.05}
HOME_BOOST = {(2, "CA"): 1.5, (3, "UK"): 1.5, (4, "NL"): 1.45}
DROP_AMP = (0.20, 0.16, 0.08, 0.04)       # mid-session audience loss by age band
EVENT_UPLIFT = {  # (young, old)
    "lights_out": (.20, .15), "session_start": (.15, .12), "crash": (.35, .15), "safety_car": (.12, .08),
    "overtake_for_lead": (.40, .20), "fastest_lap": (.05, .03), "chequered_flag": (.25, .18),
    "pole_lap": (.30, .20), "red_flag": (-.10, .05)}
AGE_W = (1.0, 0.85, 0.40, 0.0)


def session_list(r):
    day1 = r[4]
    s = [("Qualifying", day1, 8, 0)]
    if r[6]:
        s.append(("Opening Race", day1, 13, 0))
    s.append(("Reverse Grid Race", day1 + timedelta(days=1), 9, 0))
    s.append(("Feature Race", day1 + timedelta(days=2), 9, 30))
    return s


def build_events():
    events = {}
    for r in DONE:
        for name, *_ in session_list(r):
            ev = []
            if name == "Qualifying":
                ev.append((1, "session_start"))
                if rng.random() < 0.15:
                    ev.append((rng.randint(8, 20), "red_flag"))
                ev.append((rng.randint(26, 29), "pole_lap"))
            else:
                ev.append((1, "lights_out"))
                for _ in range(rng.randint(1, 3)):
                    ev.append((rng.randint(3, 27), rng.choice(["crash", "safety_car", "overtake_for_lead", "fastest_lap"])))
                ev.append((30, "chequered_flag"))
            events[(r[0], name)] = sorted(ev)
    return events


def build_tv(events):
    rows = []
    for r in DONE:
        for name, day, hh, mm in session_list(r):
            start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
            evs = events[(r[0], name)]
            for minute in range(1, 31):
                shape = 0.8 + 0.1 * min(minute, 3) - 0.05 * (min(minute, 20) / 20) + (0.12 if minute >= 28 else 0)
                for region, base in REGIONS.items():
                    for bi, band in enumerate(TV_BANDS):
                        amp = DROP_AMP[bi]
                        drop = 1 - amp * min(minute, 18) / 18 if minute <= 26 else 1 - amp * 0.5
                        eff = 0.0
                        for em, et in evs:
                            if minute >= em:
                                young, old = EVENT_UPLIFT[et]
                                eff += (old + (young - old) * AGE_W[bi]) * math.exp(-(minute - em) / 2.0)
                        v = base * SESSION_MULT[name] * ROUND_MULT[r[0]] * HOME_BOOST.get((r[0], region), 1.0) \
                            * shape * REGION_AGE_SHARE[region][bi] * drop * (1 + eff) * rng.gauss(1, 0.04)
                        val = "" if rng.random() < 0.004 else int(v)
                        reg = "GB" if (region == "UK" and rng.random() < 0.01) else region
                        rows.append([r[0], name, minute,
                                     (start + timedelta(minutes=minute - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     reg, band, val, "synthetic_nielsen_style"])
    return rows


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------
def write_csv(name, header, rows):
    with open(RAW / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    posts, meta = build_posts()
    comments = build_comments(posts, meta)
    posts += [dict(p) for p in rng.sample(posts, N_DUP_POSTS)]     # raw duplicates

    with open(RAW / "posts.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)
    with open(RAW / "comments.json", "w", encoding="utf-8") as f:
        json.dump(comments, f, ensure_ascii=False, indent=1)

    events = build_events()
    write_csv("race_events.csv", ["round", "session", "minute", "event_type"],
              [[k[0], k[1], m, t] for k, evs in events.items() for m, t in evs])
    write_csv("tv_ratings.csv",
              ["round", "session", "minute", "timestamp_utc", "region", "age_band", "viewers", "source"],
              build_tv(events))
    write_csv("race_calendar.csv",
              ["round", "venue", "country", "country_code", "start_date", "end_date", "has_opening_race", "status"],
              [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], "completed" if r[5] < AS_OF else "upcoming"] for r in ROUNDS])
    write_csv("drivers.csv", ["driver_id", "driver_name_fictional", "team"], DRIVERS)
    write_csv("platform_benchmark.csv", ["platform", "age_band", "share_of_platform_audience", "source"],
              [[p, b, BENCHMARK[p][b], "synthetic_assumption"] for p in PLATFORMS for b in AGE_BANDS])

    snaps = []
    for t in range(7):  # 2026-03-31 .. 2026-09-30
        month_end = [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30),
                     date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)][t]
        for p in PLATFORMS:
            for b in AGE_BANDS:
                n = START_FOLLOWERS[p] * FOLLOWER_MIX[p][b] * (1 + MONTHLY_GROWTH[b]) ** t * (1 + rng.gauss(0, 0.004))
                snaps.append([month_end, p, b, int(n)])
    write_csv("followers_snapshot.csv", ["snapshot_date", "platform", "age_band", "followers"], snaps)

    print(f"posts: {len(posts)}  comments: {len(comments)}  tv rows: {sum(1 for _ in open(RAW / 'tv_ratings.csv')) - 1}")


if __name__ == "__main__":
    main()
