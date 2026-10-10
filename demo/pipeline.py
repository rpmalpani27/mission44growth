"""
Signal-to-video pipeline for the F1 Academy "Fan Growth Engine" demo.

REAL steps : 1 Signals, 2 Decide, 3 Find assets (Titan embeddings), 4 Script (Claude on Bedrock),
             6 Safety and rights checks.
MOCKED     : 5 Assemble (storyboard only), 7 Publish (preview only), 8 Measure (simulated).

All data is SYNTHETIC. No real footage, no real people.
"""
import hashlib
import json
import math
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config

ROOT = Path(__file__).resolve().parent
REFINED = ROOT.parent / "data" / "refined"
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

REGION = "us-east-1"
DEFAULT_PROFILE = os.environ.get("AWS_PROFILE", "team-1")
DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
PLATFORMS = ["tiktok", "instagram", "youtube"]

THEME_TO_SEGMENT = {"stem_engineering": "S4", "driver_story": "S5", "gaming_sim": "S3",
                    "women_in_sport": "S2", "data_explainer": "S6"}
PERSONA = {
    "S1": "Teen Scrollers (13-17): live on TikTok and Reels, stop for fast, personality-led clips.",
    "S2": "Women's-sport crossover fans (18-24): already follow women's leagues, want role models.",
    "S3": "Gamers and sim racers (18-24): know the racing games, curious about the real thing.",
    "S4": "Future STEM girls (13-17): love engineering and robotics, want to see women doing it.",
    "S5": "Drive-to-Survive curious (18-24): hooked by personal stories, friendships and rivalry.",
    "S6": "Data lovers (18-24): enjoy telemetry and lap-time detail.",
}
DURATION_SECONDS = {"0-15s": 15, "16-30s": 25, "31-45s": 40, "46-60s": 55, "61-90s": 60}
BANNED_TERMS = ["@", "http", "www.", ".com", "guarantee", "official partner", "free followers"]


class AwsAccessError(RuntimeError):
    pass


# ---------------------------------------------------------------- data
def load_data():
    names = ["audience_segments", "content_performance", "comments_tagged", "tv_event_uplift",
             "growth_baseline", "posts_enriched"]
    d = {n: pd.read_csv(REFINED / f"{n}.csv") for n in names}
    d["clips"] = pd.read_csv(ROOT / "clip_catalogue.csv")
    return d


# ---------------------------------------------------------------- AWS access
_CRED = {}


def get_session(profile):
    """Temporary credentials via the AWS CLI (the `aws login` profile), kept in memory only."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile or ""):
        raise AwsAccessError("Profile name may only contain letters, digits, '.', '_' and '-'.")
    now = datetime.now(timezone.utc)
    cached = _CRED.get(profile)
    if cached and cached["exp"] - now > timedelta(minutes=5):
        return cached["session"]
    try:
        out = subprocess.run(["aws", "configure", "export-credentials", "--profile", profile,
                              "--format", "process"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise AwsAccessError("AWS CLI not found on PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise AwsAccessError("Timed out reading AWS credentials.") from e
    if out.returncode != 0:
        raise AwsAccessError(f"No valid credentials for profile '{profile}'. Run: aws login --profile {profile}")
    cred = json.loads(out.stdout)
    exp = (datetime.fromisoformat(cred["Expiration"].replace("Z", "+00:00"))
           if cred.get("Expiration") else now + timedelta(hours=1))
    session = boto3.Session(aws_access_key_id=cred["AccessKeyId"], aws_secret_access_key=cred["SecretAccessKey"],
                            aws_session_token=cred.get("SessionToken"), region_name=REGION)
    _CRED[profile] = {"session": session, "exp": exp}
    return session


def bedrock_client(profile):
    return get_session(profile).client("bedrock-runtime", config=Config(
        retries={"max_attempts": 3, "mode": "standard"}, read_timeout=60))


def whoami(profile):
    return get_session(profile).client("sts").get_caller_identity()["Arn"]


# ---------------------------------------------------------------- STEP 1: signals
def build_signals(d):
    sigs = []
    tv = d["tv_event_uplift"]

    def uplift(event, band):
        r = tv[(tv.event_type == event) & (tv.age_band == band)]
        return (float(r.avg_uplift_vs_prior_3min.iloc[0]), int(r.n_events.iloc[0])) if len(r) else (None, 0)

    teen, n = uplift("crash", "13-17")
    old, _ = uplift("crash", "35+")
    if teen is not None:
        sigs.append(dict(
            id="live_crash", type="Live race event (SIMULATED)", segment_id="S1", theme=None, event_type="crash",
            source_platform=None, simulated=True,
            title="SIMULATED: crash at minute 14 of the Austin Feature Race",
            detail=f"In our TV data, crashes lift 13-17 viewing {teen:+.0%} versus {old:+.0%} for 35+ (n={n} events)."))
    t2, n2 = uplift("overtake_for_lead", "13-17")
    o2, _ = uplift("overtake_for_lead", "35+")
    if t2 is not None:
        sigs.append(dict(
            id="tv_overtake", type="TV spike", segment_id="S1", theme=None, event_type="overtake_for_lead",
            source_platform=None, simulated=False,
            title="TV spike: overtakes for the lead pull in teen viewers",
            detail=f"13-17 viewing rises {t2:+.0%} after a lead change versus {o2:+.0%} for 35+ (n={n2} events)."))

    c = d["comments_tagged"]
    c = c[c.is_spam == 0]
    overall = c.new_fan_signal.mean()
    g = c.groupby("post_theme").agg(n=("comment_id", "count"), share=("new_fan_signal", "mean"))
    g = g[g.n >= 150].sort_values("share", ascending=False).head(3)
    for theme, row in g.iterrows():
        sub = c[(c.post_theme == theme) & (c.new_fan_signal == 1)]
        plat = sub.platform.value_counts().idxmax() if len(sub) else "tiktok"
        sigs.append(dict(
            id=f"comment_{theme}", type="Comment intent", segment_id=THEME_TO_SEGMENT.get(theme, "S1"),
            theme=theme, event_type=None, source_platform=plat, simulated=False,
            title=f"Comments on {theme.replace('_', ' ')} posts: new-fan questions are high",
            detail=(f"{row.share:.0%} of {int(row.n):,} comments ask who she is, where to watch or how to start "
                    f"(all posts: {overall:.0%}). Most of them are on {plat}.")))

    seg = d["audience_segments"]
    for _, r in seg[seg.follower_gap > 0.05].iterrows():
        sigs.append(dict(
            id=f"gap_{r.segment_id}", type="Follower gap", segment_id=r.segment_id, theme=None, event_type=None,
            source_platform=r.best_platform, simulated=False,
            title=f"Follower gap: {r.segment_name} ({r.primary_age_band})",
            detail=(f"{r.primary_age_band} are {r.current_follower_share:.1%} of followers versus a "
                    f"{r.benchmark_share:.1%} platform benchmark (assumption).")))
    return sigs


# ---------------------------------------------------------------- STEP 2: decide
def decide(signal, d):
    seg = d["audience_segments"].set_index("segment_id").loc[signal["segment_id"]]
    cp = d["content_performance"]
    theme, hook, bucket = seg.best_theme, seg.best_hook, seg.best_duration_bucket
    reasons, facts = [], []

    th = cp[(cp.dimension == "theme") & (cp.value == theme) & (cp.platform.isin(PLATFORMS))] \
        .set_index("platform").under25_reach_index
    # Platform rule: 1) the segment's best platform; 2) switch if the theme does much better elsewhere;
    # 3) post where the signal came from if that platform is within 10% of the choice.
    platform = seg.best_platform
    reasons.append(f"The segment's best platform in audience_segments is {platform}.")
    if len(th):
        if platform in th.index and th[platform] < 0.8 * th.max():
            platform = th.idxmax()
            reasons.append(f"But theme '{theme}' does much better on {platform} (index {th.max():.2f}), so we switch.")
        src = signal.get("source_platform")
        if src in th.index and platform in th.index and src != platform and th[src] >= 0.9 * th[platform]:
            platform = src
            reasons.append(f"The signal came from {src} and its index ({th[src]:.2f}) is within 10% of "
                           f"{th[platform]:.2f}, so we post there.")
        facts.append("Under-25 reach index for theme '%s' (1.00 = platform average): %s." % (
            theme, ", ".join(f"{p} {v:.2f}" for p, v in th.items())))

    def idx(dim, val):
        r = cp[(cp.dimension == dim) & (cp.value.astype(str) == str(val)) & (cp.platform == "all")]
        return float(r.under25_reach_index.iloc[0]) if len(r) else None

    hi, bi = idx("hook_type", hook), idx("duration_bucket", bucket)
    none_i = idx("hook_type", "none")
    if hi is not None:
        facts.append(f"Hook '{hook}' under-25 reach index {hi:.2f}; posts with no hook {none_i:.2f}.")
        reasons.append(f"Hook '{hook}' has reach index {hi:.2f} versus {none_i:.2f} for no hook.")
    if bi is not None:
        facts.append(f"Videos of length {bucket} have under-25 reach index {bi:.2f}.")
        reasons.append(f"Length {bucket} has reach index {bi:.2f}.")
    facts.append(f"Segment '{seg.segment_name}': follower share {seg.current_follower_share:.1%} versus "
                 f"{seg.benchmark_share:.1%} benchmark; {seg.conversion_readiness:.0%} of its comments are "
                 f"new-fan questions.")
    facts.append(f"Signal: {signal['detail']}")

    tp = cp[(cp.dimension == "teen_prime_hour") & (cp.platform == "all")]
    tp = {str(v): float(i) for v, i in zip(tp.value, tp.under25_reach_index)}
    window = "15:00-21:00 UTC"
    if "1" in tp and "0" in tp:
        reasons.append(f"Post in {window} (reach index {tp['1']:.2f} versus {tp['0']:.2f} at other hours).")
    return dict(segment_id=signal["segment_id"], segment_name=seg.segment_name, band=seg.primary_age_band,
                platform=platform, theme=theme, hook_type=hook, duration_bucket=bucket,
                target_seconds=DURATION_SECONDS.get(bucket, 25), post_window=window,
                reasons=reasons, facts=facts, persona=PERSONA.get(signal["segment_id"], ""),
                platform_index={p: float(v) for p, v in th.items()} if len(th) else {})


# ---------------------------------------------------------------- STEP 3: find assets
def _embed(client, text):
    r = client.invoke_model(modelId=EMBED_MODEL, body=json.dumps(
        {"inputText": text, "dimensions": 256, "normalize": True}))
    return json.loads(r["body"].read())["embedding"]


def _clip_embeddings(client, clips):
    path = CACHE / "clip_embeddings.json"
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    changed = False
    for _, c in clips.iterrows():
        text = f"{c.title}. {c.description}"
        h = hashlib.sha1(text.encode()).hexdigest()
        if store.get(c.clip_id, {}).get("h") != h:
            store[c.clip_id] = {"h": h, "v": _embed(client, text)}
            changed = True
    if changed:
        path.write_text(json.dumps(store), encoding="utf-8")
    return {k: v["v"] for k, v in store.items()}


def match_clips(decision, signal, clips, client=None, top_k=4):
    """Hybrid search: keyword score (explainable) plus Titan embedding similarity (AI) when a client is given."""
    words = set(re.findall(r"[a-z]{4,}", f"{signal['title']} {signal['detail']} {decision['theme']}".lower()))
    sims, used_ai = {}, False
    if client is not None:
        try:
            emb = _clip_embeddings(client, clips)
            q = _embed(client, f"{decision['persona']} {decision['theme'].replace('_', ' ')} "
                               f"{signal['title']} {signal['detail']}")
            sims = {k: sum(a * b for a, b in zip(q, v)) for k, v in emb.items()}
            used_ai = True
        except Exception as e:  # fall back to keywords only
            sims = {}
            decision.setdefault("warnings", []).append(f"Embedding search unavailable ({type(e).__name__}); used keywords.")
    rows = []
    for _, c in clips.iterrows():
        score, why = 0.0, []
        if c.theme == decision["theme"]:
            score += 3
            why.append("theme match")
        if signal.get("event_type") and c.event_type == signal["event_type"]:
            score += 3
            why.append(f"event match ({c.event_type})")
        hits = [t for t in str(c.tags).split("|") if any(w in t for w in words)]
        if hits:
            score += min(2, len(hits))
            why.append("tags: " + ", ".join(hits[:2]))
        if c.duration_sec <= decision["target_seconds"] + 10:
            score += 1
        if c.clip_id in sims:
            score += 5 * max(0.0, sims[c.clip_id])
            why.append(f"semantic similarity {sims[c.clip_id]:.2f}")
        rows.append(dict(clip_id=c.clip_id, title=c.title, theme=c.theme, event_type=c.event_type,
                         duration_sec=int(c.duration_sec), rights_status=c.rights_status,
                         description=c.description, score=round(score, 2), why="; ".join(why) or "weak match"))
    rows.sort(key=lambda r: -r["score"])
    return rows[:top_k], used_ai


# ---------------------------------------------------------------- STEP 4: script and edit plan
def build_prompt(decision, signal, shortlist):
    clip_lines = "\n".join(f"{c['clip_id']} | {c['title']} | {c['duration_sec']}s | {c['description']}"
                           for c in shortlist)
    facts = "\n".join(f"- {f}" for f in decision["facts"])
    t = decision["target_seconds"]
    return f"""You are a social content strategist for F1 Academy, an all-female junior motorsport series.
Everything below is SYNTHETIC demo data. Use ONLY the clips listed. Never mention real people or brands.

TASK: Plan a {t}-second {decision['platform']} video for this audience: {decision['persona']}
SIGNAL: {signal['title']}. {signal['detail']}
THEME: {decision['theme'].replace('_', ' ')}
HOOK STYLE: {decision['hook_type']} (pov_hook = open with "POV:"; question_hook = open with a question; story_tease = tease a story)

FACTS (the ONLY numbers you may cite):
{facts}

AVAILABLE CLIPS (use only these IDs; start_sec and end_sec must stay inside the clip duration):
{clip_lines}

Return ONLY valid JSON with exactly these keys:
{{"hook": "first 3 seconds, spoken or on-screen",
  "edit_plan": [{{"clip_id": "C00", "start_sec": 0, "end_sec": 5, "on_screen_text": "short text"}}],
  "caption": "one or two sentences",
  "hashtags": ["#one", "#two", "#three"],
  "cta": "a call to action that sends viewers into the F1 Academy fan app",
  "data_reason": "one sentence citing only numbers from FACTS"}}
Rules: total edit length within 3 seconds of {t}; exactly 3 hashtags; family-friendly; no emojis; no @mentions or links."""


def generate_plan(client, model_id, prompt):
    resp = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                           inferenceConfig={"maxTokens": 900, "temperature": 0.4})
    text = resp["output"]["message"]["content"][0]["text"]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("Model did not return JSON.")
    plan = json.loads(text[start:end + 1])
    plan["_meta"] = dict(source="Amazon Bedrock", model=model_id, latency_ms=resp.get("metrics", {}).get("latencyMs"),
                         input_tokens=resp["usage"]["inputTokens"], output_tokens=resp["usage"]["outputTokens"])
    return plan


def template_plan(decision, signal, shortlist):
    """Deterministic fallback. NOT AI - used only when Bedrock is unavailable."""
    hooks = {"pov_hook": "POV: the race just changed in one second",
             "question_hook": "Wait, did you see this?", "story_tease": "You won't believe how she got here."}
    remaining, plan, t = decision["target_seconds"], [], 0
    for c in shortlist:
        if remaining <= 0:
            break
        length = min(c["duration_sec"], remaining, 10)
        plan.append(dict(clip_id=c["clip_id"], start_sec=0, end_sec=length, on_screen_text=c["title"]))
        remaining -= length
    return dict(hook=hooks.get(decision["hook_type"], shortlist[0]["title"]), edit_plan=plan,
                caption="A big moment on the grid. Follow F1 Academy for more.",
                hashtags=["#F1Academy", "#" + decision["theme"].title().replace("_", ""), "#Racing"],
                cta="Open the F1 Academy fan app for the full story.",
                data_reason=decision["facts"][0] if decision["facts"] else "",
                _meta=dict(source="Offline template (not AI)", model="none"))


def save_plan(signal_id, plan):
    (CACHE / f"plan_{signal_id}.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")


def load_saved_plan(signal_id):
    p = CACHE / f"plan_{signal_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- STEP 5 (mock): storyboard
def storyboard(plan, clips):
    by_id = {c["clip_id"]: c for c in clips}
    t, rows = 0.0, []
    for seg in plan.get("edit_plan", []):
        length = max(0.0, float(seg["end_sec"]) - float(seg["start_sec"]))
        c = by_id.get(seg["clip_id"], {})
        rows.append(dict(start=t, length=length, clip_id=seg["clip_id"], title=c.get("title", "UNKNOWN CLIP"),
                         text=seg.get("on_screen_text", "")))
        t += length
    return rows, t


# ---------------------------------------------------------------- STEP 6: safety and rights checks
def run_checks(plan, catalogue, decision):
    by_id = {r["clip_id"]: r for r in catalogue.to_dict("records")}
    res = []

    def add(name, status, detail, blocking=False):
        res.append(dict(name=name, status=status, detail=detail, blocking=blocking))

    need = {"hook", "edit_plan", "caption", "hashtags", "cta", "data_reason"}
    missing = need - set(plan)
    add("Plan has all required fields", "fail" if missing else "pass",
        f"Missing: {', '.join(sorted(missing))}" if missing else "hook, edit plan, caption, hashtags, CTA, data reason", True)
    if missing:
        return res
    segs = plan["edit_plan"]
    unknown = [s["clip_id"] for s in segs if s["clip_id"] not in by_id]
    add("Every clip exists in the catalogue", "fail" if unknown else "pass",
        f"Unknown clip IDs: {', '.join(unknown)}" if unknown else f"{len(segs)} clips, all found", True)
    uncleared = [s["clip_id"] for s in segs if by_id.get(s["clip_id"], {}).get("rights_status") != "cleared"]
    add("Rights: all clips are cleared", "fail" if uncleared else "pass",
        f"Needs clearance: {', '.join(uncleared)}" if uncleared else "All clips cleared for use", True)
    oob = [s["clip_id"] for s in segs if s["clip_id"] in by_id and
           (s["start_sec"] < 0 or s["end_sec"] <= s["start_sec"] or s["end_sec"] > by_id[s["clip_id"]]["duration_sec"])]
    add("Cuts stay inside each clip", "fail" if oob else "pass",
        f"Out of range: {', '.join(oob)}" if oob else "All in/out points are valid", True)
    total = sum(max(0, s["end_sec"] - s["start_sec"]) for s in segs)
    tgt = decision["target_seconds"]
    add("Length is close to the target", "pass" if abs(total - tgt) <= 3 else "warn",
        f"{total:.0f}s planned versus {tgt}s target")
    tags = plan["hashtags"]
    ok = len(tags) == 3 and all(str(t).startswith("#") for t in tags)
    add("Exactly 3 hashtags", "pass" if ok else "warn", ", ".join(map(str, tags)))
    text = " ".join([plan["hook"], plan["caption"], plan["cta"], plan["data_reason"]] +
                    [s.get("on_screen_text", "") for s in segs]).lower()
    hits = [b for b in BANNED_TERMS if b in text]
    add("No links, @mentions or risky claims", "fail" if hits else "pass",
        f"Found: {', '.join(hits)}" if hits else "Nothing flagged", True)
    num = r"(?<![A-Za-z\d.])\d+(?:\.\d+)?"          # ignores digits inside words such as F1
    fact_nums = set(re.findall(num, " ".join(decision["facts"] + [str(tgt)])))
    claim_text = " ".join([plan["hook"], plan["caption"], plan["cta"], plan["data_reason"]] +
                          [s.get("on_screen_text", "") for s in segs])
    # corner, lap, round and grid-position references (for example "turn 1", "lap 3", "P8") are not statistics
    claim_text = re.sub(r"(?i)\b(?:turn|corner|lap|laps|round|p|race)\s*\d+\b", "", claim_text)
    bad = sorted({n for n in re.findall(num, claim_text) if n not in fact_nums})
    add("Every number in the text comes from the facts", "warn" if bad else "pass",
        f"Not found in the facts: {', '.join(bad)} (check the hook, caption and data reason)" if bad
        else "All numbers are grounded. Note: this checks numbers, not meaning.")
    add("Bedrock Guardrails", "info", "Not configured in this demo. In production this check runs here.")
    return res


# ---------------------------------------------------------------- STEP 7 / 8 (mock)
def log_approval(signal, decision, plan):
    rec = dict(time=datetime.now(timezone.utc).isoformat(timespec="seconds"), signal=signal["id"],
               segment=decision["segment_name"], platform=decision["platform"], approver="demo user",
               status="MOCK-PUBLISHED (no real post)", source=plan.get("_meta", {}).get("source"))
    with open(CACHE / "approvals_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def expected_effect(decision):
    idx = decision["platform_index"].get(decision["platform"])
    return dict(index=idx, note="Under-25 reach index of this theme on this platform (1.00 = platform average). "
                                "This is a pattern from synthetic data, not a forecast.")
