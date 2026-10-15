"""
F1 Academy Fan Growth Engine - signal-to-video demo.

Run:   streamlit run demo/app.py
Needs: aws login --profile team-1   (for the live Amazon Bedrock steps)
All data is SYNTHETIC. Steps 1-4 and 6 are real; 5, 7 and 8 are mocked.
"""
import html
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

import pipeline as p

DIAGRAM = Path(__file__).resolve().parent.parent / "docs" / "diagrams" / "signal-to-video-flow.png"
E = html.escape

st.set_page_config(page_title="Fan Growth Engine demo", page_icon=None, layout="wide")


@st.cache_data
def get_data():
    return p.load_data()


d = get_data()

def _public_demo():
    """True on a shared/hosted link: live AWS calls are switched off so nobody can use the host's credentials.
    Set PUBLIC_DEMO=1 (environment variable or Streamlit secret), or run where the AWS CLI is not installed."""
    if os.environ.get("PUBLIC_DEMO") == "1":
        return True
    try:
        if str(st.secrets.get("PUBLIC_DEMO", "")) == "1":
            return True
    except Exception:                      # no secrets file: fine
        pass
    return shutil.which("aws") is None


PUBLIC = _public_demo()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Settings")
    profile, model_id = p.DEFAULT_PROFILE, p.DEFAULT_MODEL
    if PUBLIC:
        live, use_embeddings = False, False
        st.info("Public demo. The Amazon Bedrock results here were saved from a live run, so this link replays "
                "real Claude output. Live calls are switched off.")
    else:
        mode = st.radio("Mode", ["Live (Amazon Bedrock)", "Offline (saved or template)"],
                        help="Offline needs no AWS access. Use it as the backup if Wi-Fi or credentials fail.")
        live = mode.startswith("Live")
        profile = st.text_input("AWS profile", p.DEFAULT_PROFILE)
        model_id = st.text_input("Bedrock model or inference profile", p.DEFAULT_MODEL)
        use_embeddings = st.checkbox("Step 3: use Titan embeddings (AI) for asset search", value=True,
                                     disabled=not live)
        if live and st.button("Test AWS connection"):
            try:
                st.success("Connected as " + p.whoami(profile).split("/")[-1])
            except Exception as ex:
                st.error(f"{type(ex).__name__}: {ex}")
    st.divider()
    st.caption("All data in this demo is synthetic. Team names and venues are real; drivers, fans, "
               "clips and numbers are invented.")

st.title("Fan Growth Engine: from signal to video")
st.caption("F1 Academy under-25 growth. Synthetic data. Steps 1-4 and 6 are real, steps 5, 7 and 8 are mocked.")

with st.expander("How the flow works (which steps use AI)", expanded=False):
    if DIAGRAM.exists():
        st.image(str(DIAGRAM))
    st.markdown("""
| Step | What it does | Uses AI? | Runs | In this demo |
|---|---|---|---|---|
| 1 Signals | Finds what the audience data is telling us | Yes (Bedrock tags comments) | Automatic | Real |
| 2 Decide | Picks segment, platform, hook and length | No (scoring and lift tables) | Automatic | Real |
| 3 Find assets | Searches the footage library | Yes (Titan embeddings) | Automatic | Real, on a fictional catalogue |
| 4 Script and edit plan | Writes hook, clip order, caption | Yes (Claude on Bedrock) | Automatic | Real |
| 5 Assemble | Cuts and formats the video | No (video tooling) | Automatic | Mock (storyboard) |
| 6 Safety and rights | Checks rules, then a person approves | Partly (Guardrails) | Human approves | Real checks, human click |
| 7 Publish | Posts on the best platform | No (platform API) | Automatic after approval | Mock (preview) |
| 8 Measure | Compares with a control and feeds back | No (analytics) | Automatic | Mock (simulated) |
""")

signals = p.build_signals(d)
by_id = {s["id"]: s for s in signals}

_all_tabs = st.tabs(["Goal + audience", "1 Signals (AI)", "2 Decide (no AI)", "3 Assets (AI)", "4 Script (AI)",
                     "5 Assemble (mock)", "6 Check + approve (human)", "7 Publish (mock)", "8 Measure (mock)"])
goal_tab, tabs = _all_tabs[0], _all_tabs[1:]

# ------------------------------------------------------------------ goal + audience
with goal_tab:
    st.subheader("The goal and who is missing")
    st.caption("Starting point for the 8-step flow. Synthetic data; the 14.4% benchmark is an assumption.")
    gb = d["growth_baseline"].set_index("platform")
    allrow = gb.loc["ALL"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Under-25 followers (30 Sep 2026)", f"{int(allrow.under25_followers):,}")
    c2.metric("Target (+20%)", f"{int(allrow.target_under25_plus20pct):,}")
    c3.metric("Gap to close", f"{int(allrow.followers_gap_to_target):,}",
              help="Target minus where organic growth (about 1.3% a month) gets us in 6 months. The 6-month horizon is an assumption.")
    c4.metric("Growth needed per month", f"{allrow.required_monthly_growth_6m:.2%}",
              delta=f"organic today {allrow.organic_monthly_growth_under25:.2%}", delta_color="off")
    st.dataframe(
        gb.reset_index()[["platform", "under25_followers", "under25_share", "target_under25_plus20pct",
                          "followers_gap_to_target"]].rename(columns={
            "platform": "Platform", "under25_followers": "Under-25 followers", "under25_share": "Under-25 share",
            "target_under25_plus20pct": "Target (+20%)", "followers_gap_to_target": "Gap"}),
        hide_index=True, use_container_width=True)

    seg = d["audience_segments"]
    left, right = st.columns(2)
    with left:
        st.markdown("**Who follows F1 Academy versus the platform benchmark**")
        band = seg.drop_duplicates("primary_age_band").set_index("primary_age_band")
        st.bar_chart(pd.DataFrame({"F1 Academy follower share": band.current_follower_share,
                                   "Platform benchmark (assumption)": band.benchmark_share}))
        st.caption("13-17 are 7.2% of followers versus a 14.4% benchmark. 18-24 are close to the benchmark.")
    with right:
        st.markdown("**Opportunity score by audience segment**")
        st.bar_chart(seg.set_index("segment_name").opportunity_score)
        st.caption("Relative ranking from five inputs (size, follower gap, readiness, momentum, engagement). "
                   "Formula and worked example: strategy doc, section 3.4.")
    st.dataframe(seg[["opportunity_rank", "segment_name", "primary_age_band", "opportunity_score", "best_platform",
                      "best_hook", "best_duration_bucket"]].rename(columns={
        "opportunity_rank": "Rank", "segment_name": "Segment", "primary_age_band": "Age", "opportunity_score": "Score",
        "best_platform": "Best platform", "best_hook": "Best hook", "best_duration_bucket": "Best length"}),
        hide_index=True, use_container_width=True)

    st.markdown("**What content reaches young viewers** (under-25 reach index; 1.00 = platform average)")
    cp = d["content_performance"]
    cols = st.columns(3)
    for col, (dim, title) in zip(cols, [("theme", "Theme"), ("hook_type", "Hook"), ("duration_bucket", "Length")]):
        sub = cp[(cp.dimension == dim) & (cp.platform == "all")].set_index("value").under25_reach_index.sort_values()
        col.markdown(f"*{title}*")
        col.bar_chart(sub, horizontal=True)
    st.info("Short videos (30 seconds or less) with a POV, question or story hook, and driver or STEM stories, "
            "reach young viewers best. Long race recaps reach them least. Next: pick a signal in step 1.")

# ------------------------------------------------------------------ 1 signals
with tabs[0]:
    st.subheader("Step 1: Signals")
    st.markdown(":violet[AI: YES in the design] (Bedrock tags comments with intent; this demo uses keyword rules "
                "with the same output) | Runs: automatic | Demo: real data, rule-based tags")
    st.write("Each signal comes from the refined data. Pick one to run through the flow.")
    labels = {s["id"]: f"[{s['type']}] {s['title']}" for s in signals}
    sel = st.radio("Signal", list(labels), format_func=lambda i: labels[i], key="signal_id")
    sig = by_id[sel]
    st.info(sig["detail"])
    if sig["simulated"]:
        st.warning("This event is simulated for the demo. Austin has not been raced yet.")

dec = p.decide(sig, d)

# ------------------------------------------------------------------ 2 decide
with tabs[1]:
    st.subheader("Step 2: Decide segment, platform and format")
    st.markdown(":blue[AI: NO] (scoring and lift tables) | Runs: automatic | Demo: real")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Segment", dec["segment_name"])
    c2.metric("Platform", dec["platform"])
    c3.metric("Theme", dec["theme"].replace("_", " "))
    c4.metric("Hook", dec["hook_type"].replace("_", " "))
    c5.metric("Length", f"{dec['target_seconds']}s")
    st.markdown("**Why (from the data):**")
    for r in dec["reasons"]:
        st.markdown(f"- {r}")
    with st.expander("Facts that will be given to the AI"):
        for f in dec["facts"]:
            st.markdown(f"- {f}")
    st.caption("Platform rule: segment's best platform, switch if the theme does much better elsewhere, "
               "then prefer the platform the signal came from when it is within 10%. "
               "In the synthetic data TikTok often ranks first; that comes from how the data was generated.")

# ------------------------------------------------------------------ 3 assets
with tabs[2]:
    st.subheader("Step 3: Find existing assets")
    st.markdown(":violet[AI: YES] (Titan embeddings for semantic search) | Runs: automatic | "
                "Demo: real search on a fictional catalogue of 30 clips")
    ss = st.session_state.setdefault("shortlists", {})
    key = (sig["id"], live and use_embeddings)
    if key not in ss:
        client, note = None, ""
        if live and use_embeddings:
            try:
                client = p.bedrock_client(profile)
            except Exception as ex:
                note = f"Embedding search skipped ({ex}). Using keyword matching."
        with st.spinner("Searching the clip catalogue..."):
            ss[key] = (*p.match_clips(dec, sig, d["clips"], client), note)
    shortlist, used_ai, note = ss[key]
    if note:
        st.warning(note)
    for w in dec.get("warnings", []):
        st.warning(w)
    st.markdown((":violet[Semantic search used (AI)]" if used_ai else ":gray[Keyword matching only (no AI)]"))
    tbl = pd.DataFrame([{"Clip": c["clip_id"], "Title": c["title"], "Seconds": c["duration_sec"],
                         "Rights": "cleared" if c["rights_status"] == "cleared" else "NEEDS CLEARANCE",
                         "Score": c["score"], "Why it matched": c["why"]} for c in shortlist])
    st.dataframe(tbl, hide_index=True, use_container_width=True)
    st.caption("Step 6 blocks any clip that still needs rights clearance.")

# ------------------------------------------------------------------ 4 script
plan_key = f"{sig['id']}|{dec['platform']}|{','.join(c['clip_id'] for c in shortlist)}"
prompt = p.build_prompt(dec, sig, shortlist)
plans = st.session_state.setdefault("plans", {})

with tabs[3]:
    st.subheader("Step 4: Script and edit plan")
    st.markdown(":violet[AI: YES] (Claude on Amazon Bedrock) | Runs: automatic | Demo: real")
    with st.expander("Show the prompt sent to Bedrock", expanded=False):
        st.code(prompt, language="text")
    if live:
        if st.button("Generate script with Bedrock", type="primary"):
            try:
                with st.spinner("Calling Amazon Bedrock..."):
                    plan = p.generate_plan(p.bedrock_client(profile), model_id, prompt)
                p.save_plan(sig["id"], plan)
                plans[plan_key] = plan
            except Exception as ex:
                st.error(f"Bedrock call failed: {type(ex).__name__}: {ex}")
                st.info("Switch to Offline mode in the sidebar to continue with a saved result.")
    else:
        if st.button("Load saved result (or template)", type="primary"):
            saved = p.load_saved_plan(sig["id"])
            plans[plan_key] = saved if saved else p.template_plan(dec, sig, shortlist)
    plan = plans.get(plan_key)
    if plan is None:
        st.info("No plan yet for this signal. Click the button above.")
    else:
        meta = plan.get("_meta", {})
        src = meta.get("source", "unknown")
        st.markdown((":violet[Source: " + src + "]") if "Bedrock" in src else (":orange[Source: " + src + "]"))
        if meta.get("latency_ms"):
            st.caption(f"Model {meta.get('model')} | {meta['latency_ms']} ms | "
                       f"{meta.get('input_tokens')} input and {meta.get('output_tokens')} output tokens")
        if "Bedrock" in src and not live:
            st.caption("This is a saved Bedrock result from an earlier live run.")
        st.markdown(f"**Hook (first 3 seconds):** {plan.get('hook', '')}")
        st.markdown("**Edit plan**")
        st.dataframe(pd.DataFrame(plan.get("edit_plan", [])), hide_index=True, use_container_width=True)
        st.markdown(f"**Caption:** {plan.get('caption', '')}")
        st.markdown(f"**Hashtags:** {' '.join(plan.get('hashtags', []))}")
        st.markdown(f"**Call to action:** {plan.get('cta', '')}")
        st.markdown(f"**Data reason:** {plan.get('data_reason', '')}")
        with st.expander("Raw JSON"):
            st.json({k: v for k, v in plan.items() if k != "_meta"})
        st.warning("AI output can be wrong. Step 6 checks it, and a person approves it.")

plan = plans.get(plan_key)

# ------------------------------------------------------------------ 5 assemble
with tabs[4]:
    st.subheader("Step 5: Assemble video")
    st.markdown(":blue[AI: NO] (video tooling such as MediaConvert or FFmpeg) | Runs: automatic | "
                ":orange[Demo: MOCK, storyboard only]")
    if not plan:
        st.info("Generate a plan in step 4 first.")
    else:
        rows, total = p.storyboard(plan, d["clips"].to_dict("records"))
        colors = ["#6b4fd8", "#2a7bd6", "#2e9b4f", "#d08a00", "#c2410c", "#0f766e"]
        blocks = "".join(
            f"<div style='flex:{max(r['length'], 0.5)};background:{colors[i % len(colors)]};color:#fff;"
            f"padding:8px;border-radius:6px;min-width:90px'>"
            f"<b>{E(r['clip_id'])}</b> ({r['length']:.0f}s)<br><small>{E(r['title'])}</small><br>"
            f"<small>Text: {E(str(r['text']))}</small></div>" for i, r in enumerate(rows))
        st.markdown(f"<div style='display:flex;gap:6px'>{blocks}</div>", unsafe_allow_html=True)
        st.caption(f"Total {total:.0f}s, vertical 9:16 with captions. In production this is rendered by "
                   "AWS Elemental MediaConvert or FFmpeg. Here it is only a storyboard; no video is made.")

# ------------------------------------------------------------------ 6 check + approve
with tabs[5]:
    st.subheader("Step 6: Safety and rights check, then human approval")
    st.markdown(":violet[AI: PARTLY] (Guardrails would filter text) | Runs: :green[HUMAN approves] | Demo: real checks")
    if not plan:
        st.info("Generate a plan in step 4 first.")
    else:
        checks = p.run_checks(plan, d["clips"], dec)
        icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO"}
        st.dataframe(pd.DataFrame([{"Result": icon[c["status"]], "Check": c["name"], "Detail": c["detail"]}
                                   for c in checks]), hide_index=True, use_container_width=True)
        blocked = [c for c in checks if c["blocking"] and c["status"] == "fail"]
        warned = [c for c in checks if c["status"] == "warn"]
        if blocked:
            st.error("Blocked: fix the failed checks before approval (try another signal or regenerate).")
        elif warned:
            st.warning("Warnings: read them before you approve.")
        else:
            st.success("All checks passed. A person must still approve.")
        reviewed = st.checkbox("I reviewed the script, the clips and their rights.", key=f"rev_{plan_key}")
        if st.button("Approve", disabled=bool(blocked) or not reviewed, type="primary"):
            st.session_state.setdefault("approved", {})[plan_key] = p.log_approval(sig, dec, plan)
        if plan_key in st.session_state.get("approved", {}):
            st.success("Approved by a person (demo user). Go to step 7.")

# ------------------------------------------------------------------ 7 publish
with tabs[6]:
    st.subheader("Step 7: Publish")
    st.markdown(":blue[AI: NO] (platform API) | Runs: automatic after approval | :orange[Demo: MOCK, nothing is posted]")
    if not plan:
        st.info("Generate a plan in step 4 first.")
    else:
        approved = plan_key in st.session_state.get("approved", {})
        status = "MOCK-PUBLISHED (no real post was made)" if approved else "Waiting for human approval (step 6)"
        tags = " ".join(plan.get("hashtags", []))
        st.markdown(
            f"<div style='border:2px solid #2a7bd6;border-radius:10px;padding:14px;max-width:560px'>"
            f"<b>Platform:</b> {E(dec['platform'])}<br><b>Account:</b> F1 Academy (demo account)<br>"
            f"<b>Scheduled:</b> next window {E(dec['post_window'])}<br><br>"
            f"<b>{E(plan.get('hook', ''))}</b><br>{E(plan.get('caption', ''))}<br>{E(tags)}<br>"
            f"<i>{E(plan.get('cta', ''))}</i><br><br><b>Status:</b> {E(status)}</div>", unsafe_allow_html=True)
        st.caption(f"Platform chosen in step 2: {dec['platform']}. Real posting needs the platform's API and "
                   "account approvals, which are not verified here. Adapt the same video for the other platforms.")

# ------------------------------------------------------------------ 8 measure
with tabs[7]:
    st.subheader("Step 8: Measure and learn")
    st.markdown(":blue[AI: NO] (analytics) | Runs: automatic | :orange[Demo: MOCK, simulated]")
    eff = p.expected_effect(dec)
    if eff["index"] is not None:
        a, b = st.columns(2)
        a.metric("Control (platform average)", "1.00")
        b.metric(f"This plan: {dec['theme'].replace('_', ' ')} on {dec['platform']}", f"{eff['index']:.2f}")
    st.caption(eff["note"])
    st.markdown("""
**Pilot (Austin, 23-25 Oct):** run three variants per segment against a control, then compare
under-25 followers, completion rate, share rate, app link clicks and the share of new-fan comments.
The winner goes to Las Vegas (19-21 Nov), and the results feed back into step 1.
""")
