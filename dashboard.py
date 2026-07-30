#!/usr/bin/env python3
"""
Northline Lead Ops — operator dashboard.

Non-technical view over the same pipeline the OpenClaw/Lobster workflows run:
discover public listings, score on CPU rules, draft outreach, approve, send.

    streamlit run dashboard.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from common import ROOT as SCRIPT_ROOT, connect, db_path, load_weights  # noqa: E402
from draft_outreach import TEMPLATE_ID, render, suppressed  # noqa: E402
from fetch_public_listings import collect_candidates, upsert  # noqa: E402
from osm_source import known_categories, known_metros  # noqa: E402
from score_leads import score_row  # noqa: E402
from send_outreach import gog_account, process_drafts  # noqa: E402
from qualify_replies import (  # noqa: E402
    ensure_reply_schema,
    fetch_gmail_candidates,
    load_demo_replies,
    process_messages,
    seed_contacted_for_demo,
)


STATUS_COLORS = {
    "new": "#94a3b8",
    "qualified": "#22c55e",
    "queued": "#f59e0b",
    "contacted": "#3b82f6",
    "replied": "#8b5cf6",
    "won": "#16a34a",
    "lost": "#ef4444",
    "suppressed": "#64748b",
}


st.set_page_config(page_title="Northline Lead Ops", page_icon="📍", layout="wide")


def schema_ready() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1 FROM leads LIMIT 1")
        return True
    except Exception:
        return False


def init_db() -> None:
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(schema)
        conn.commit()


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def discovery_options() -> tuple[list[str], list[str]]:
    metros = set(known_metros())
    cats = set(known_categories())
    sample = Path(os.getenv("NORTHLINE_SAMPLE_PATH", "data/samples/public_listings.jsonl"))
    if not sample.is_absolute():
        sample = ROOT / sample
    if sample.exists():
        for line in sample.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("metro"):
                metros.add(row["metro"])
            if row.get("category"):
                cats.add(row["category"])
    return sorted(metros), sorted(cats)


def run_discovery(metro: str, category: str, limit: int, live: bool, source: str) -> tuple[list[dict], str, str | None]:
    candidates, used, warning = collect_candidates(
        metro=metro or None,
        category=category or None,
        limit=limit,
        source=source,
    )
    upserted = [upsert(c, live=live) for c in candidates]
    return upserted, used, warning


def run_scoring(min_score: int) -> pd.DataFrame:
    weights = load_weights()
    updated = []
    with connect() as conn:
        rows = conn.execute("SELECT * FROM leads WHERE status NOT IN ('won','lost','suppressed')").fetchall()
        for row in rows:
            total, breakdown = score_row(row, weights)
            new_status = row["status"]
            if total >= min_score and row["status"] in ("new", "qualified"):
                new_status = "qualified"
            conn.execute(
                "UPDATE leads SET score=?, score_breakdown=?, status=?, updated_at=datetime('now') WHERE id=?",
                (total, json.dumps(breakdown), new_status, row["id"]),
            )
            updated.append(
                {
                    "id": row["id"],
                    "business_name": row["business_name"],
                    "score": total,
                    "status": new_status,
                    "website_status": row["website_status"],
                    **{f"pts_{k}": v for k, v in breakdown.items() if k != "total"},
                }
            )
        conn.commit()
    df = pd.DataFrame(updated)
    return df.sort_values("score", ascending=False) if not df.empty else df


def run_drafting(limit: int, min_score: int) -> list[dict]:
    from_name = os.getenv("OUTREACH_FROM_NAME", "Northline Home Services")
    drafts = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status IN ('qualified','queued')
              AND score >= ?
              AND email IS NOT NULL AND email != ''
            ORDER BY score DESC LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
        for lead in rows:
            if suppressed(conn, lead["email"]):
                continue
            subject, body = render(lead, from_name)
            conn.execute(
                """
                INSERT INTO outreach_events (lead_id, template_id, subject, body, status, actor)
                VALUES (?, ?, ?, ?, 'drafted', 'dashboard')
                """,
                (lead["id"], TEMPLATE_ID, subject, body),
            )
            conn.execute("UPDATE leads SET status='queued', updated_at=datetime('now') WHERE id=?", (lead["id"],))
            drafts.append({"lead_id": lead["id"], "business_name": lead["business_name"], "subject": subject})
        conn.commit()
    return drafts


def send_drafts(limit: int, execute: bool = False, simulate: bool = False) -> list[dict]:
    return process_drafts(limit, execute=execute, simulate=simulate)


def run_reply_qualification(source: str, max_results: int = 15) -> dict:
    ensure_reply_schema()
    warning = None
    if source == "gmail":
        try:
            messages = fetch_gmail_candidates("in:inbox newer_than:14d -in:chats", max_results)
            source_used = "gmail"
        except Exception as e:
            warning = f"Gmail fetch failed ({e}); using demo replies."
            demo = ROOT / "data" / "samples" / "inbound_replies.jsonl"
            seed_contacted_for_demo(demo)
            messages = load_demo_replies(demo)
            source_used = "demo"
    else:
        demo = ROOT / "data" / "samples" / "inbound_replies.jsonl"
        seed_contacted_for_demo(demo)
        messages = load_demo_replies(demo)
        source_used = "demo"
    results = process_messages(messages)
    applied = [r for r in results if not r.get("skipped")]
    return {
        "source_used": source_used,
        "warning": warning,
        "scanned": len(messages),
        "applied": len(applied),
        "results": results,
    }

st.title("📍 Northline Lead Ops")
st.caption("Local-first prospecting: discover public listings → score → outreach, with approval before anything sends.")

with st.sidebar:
    st.subheader("Workspace")
    st.write(f"**Database**\n\n`{db_path().name}`")
    if not schema_ready():
        st.warning("CRM not initialized yet.")
        if st.button("Create CRM tables", type="primary", use_container_width=True):
            init_db()
            st.rerun()
        st.stop()
    else:
        st.success("CRM ready")

    metros, categories = discovery_options()
    st.divider()
    st.subheader("Discovery filters")
    data_source = st.selectbox(
        "Data source",
        options=["auto", "osm", "sample"],
        format_func=lambda x: {
            "auto": "OpenStreetMap (fallback to sample)",
            "osm": "OpenStreetMap only",
            "sample": "Offline sample file only",
        }[x],
        help="OSM Overpass is free public open data — no API key.",
    )
    metro = st.selectbox("Metro", metros, index=metros.index("Austin, TX") if "Austin, TX" in metros else 0)
    category = st.selectbox("Category", ["All"] + categories)
    live_check = st.toggle("Verify websites over HTTP", value=False, help="Off = offline heuristics only")
    st.caption("Live OSM needs internet. No API key required. Set how many to find on the Run pipeline tab.")

    st.divider()
    st.subheader("Qualification")
    min_score = st.slider("Minimum score to qualify", 0, 100, int(load_weights().get("min_queue_score", 55)), step=5)

    st.divider()
    if st.button("Reset all data", use_container_width=True):
        with connect() as conn:
            conn.executescript(
                "DELETE FROM outreach_events; DELETE FROM leads; DELETE FROM agent_runs;"
            )
            conn.commit()
        st.rerun()

metro_arg = metro
category_arg = "" if category == "All" else category

leads_df = query_df("SELECT * FROM leads")
events_df = query_df(
    """
    SELECT e.id, l.business_name, l.email, e.status, e.template_id, e.subject, e.created_at
    FROM outreach_events e JOIN leads l ON l.id = e.lead_id
    ORDER BY e.created_at DESC
    """
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Leads in CRM", len(leads_df))
c2.metric("Qualified", int((leads_df["status"] == "qualified").sum()) if not leads_df.empty else 0)
c3.metric("Contacted", int((leads_df["status"] == "contacted").sum()) if not leads_df.empty else 0)
c4.metric("Replied / warm", int(leads_df["status"].isin(["replied", "won"]).sum()) if not leads_df.empty else 0)
c5.metric(
    "Reply labels",
    int(leads_df["qualification"].notna().sum())
    if (not leads_df.empty and "qualification" in leads_df.columns)
    else 0,
)

tab_run, tab_leads, tab_outreach, tab_qualify, tab_insights = st.tabs(
    ["▶️ Run pipeline", "🗂 Leads", "✉️ Outreach", "✅ Qualify replies", "📊 Insights"]
)

with tab_run:
    st.subheader("Pipeline")
    st.write("Each step is the same logic the OpenClaw agent runs through its Lobster workflows.")

    s1, s2, s3 = st.columns(3)

    with s1:
        st.markdown("**1. Discover**")
        st.caption("Pull public businesses from OpenStreetMap (or sample fallback).")
        find_count = st.number_input(
            "How many businesses to find",
            min_value=1,
            max_value=100,
            value=25,
            step=1,
            key="find_count",
        )
        if st.button("Find businesses", type="primary", use_container_width=True):
            with st.spinner(f"Finding up to {int(find_count)} businesses…"):
                found, used, warning = run_discovery(
                    metro_arg, category_arg, int(find_count), live_check, data_source
                )
            st.session_state["last_discovery"] = found
            st.session_state["last_source"] = used
            st.session_state["last_warning"] = warning
            if warning:
                st.warning(warning)
            st.success(f"Added or refreshed {len(found)} of {int(find_count)} requested from **{used}**.")
            st.rerun()

    with s2:
        st.markdown("**2. Score**")
        st.caption("Ranks each lead with fixed rules on website, contacts, and category fit.")
        if st.button("Score leads", use_container_width=True):
            scored = run_scoring(min_score)
            st.session_state["last_scored"] = scored
            st.success(f"Scored {len(scored)} leads.")
            st.rerun()

    with s3:
        st.markdown("**3. Draft outreach**")
        st.caption("Writes email drafts for review. Nothing leaves your machine yet.")
        draft_limit = st.number_input("How many drafts", 1, 50, 5, key="draft_limit")
        if st.button("Prepare drafts", use_container_width=True):
            drafts = run_drafting(int(draft_limit), min_score)
            st.success(f"Prepared {len(drafts)} drafts.")
            st.rerun()

    if st.session_state.get("last_source"):
        st.info(f"Last discovery source: **{st.session_state['last_source']}** (no API key).")
    if st.session_state.get("last_warning"):
        st.warning(st.session_state["last_warning"])

    if st.session_state.get("last_discovery"):
        st.divider()
        st.markdown("**Latest discovery result**")
        st.dataframe(pd.DataFrame(st.session_state["last_discovery"]), use_container_width=True, hide_index=True)

    if isinstance(st.session_state.get("last_scored"), pd.DataFrame) and not st.session_state["last_scored"].empty:
        st.divider()
        st.markdown("**Score breakdown**")
        st.dataframe(st.session_state["last_scored"], use_container_width=True, hide_index=True)

with tab_leads:
    if leads_df.empty:
        st.info("No leads yet. Run discovery on the **Run pipeline** tab.")
    else:
        f1, f2, f3 = st.columns(3)
        status_filter = f1.multiselect("Status", sorted(leads_df["status"].unique()), default=[])
        website_filter = f2.multiselect("Website", sorted(leads_df["website_status"].unique()), default=[])
        score_floor = f3.slider("Score at least", 0, 100, 0, step=5, key="leads_score")

        view = leads_df.copy()
        if status_filter:
            view = view[view["status"].isin(status_filter)]
        if website_filter:
            view = view[view["website_status"].isin(website_filter)]
        view = view[view["score"] >= score_floor]

        cols = [
            "id",
            "business_name",
            "category",
            "metro",
            "city",
            "phone",
            "email",
            "website_status",
            "source",
            "score",
            "status",
            "qualification",
            "updated_at",
        ]
        cols = [c for c in cols if c in view.columns]
        st.dataframe(
            view[cols].sort_values("score", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")},
        )

        st.download_button(
            "⬇️ Export leads to CSV",
            data=view[cols].to_csv(index=False).encode("utf-8"),
            file_name=f"northline-leads-{datetime.now():%Y%m%d-%H%M%S}.csv",
            mime="text/csv",
        )

with tab_outreach:
    drafted = events_df[events_df["status"] == "drafted"] if not events_df.empty else pd.DataFrame()
    st.subheader("Approval queue")

    if drafted.empty:
        st.info("No drafts waiting. Prepare drafts on the **Run pipeline** tab.")
    else:
        st.dataframe(
            drafted[["business_name", "email", "subject", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("Preview a message"):
            choice = st.selectbox("Draft", drafted["id"].tolist(), format_func=lambda i: drafted.set_index("id").loc[i, "business_name"])
            body = query_df("SELECT subject, body FROM outreach_events WHERE id=?", (int(choice),))
            if not body.empty:
                st.text_input("Subject", body.iloc[0]["subject"], disabled=True)
                st.text_area("Body", body.iloc[0]["body"], height=220, disabled=True)

        send_limit = st.number_input("How many to process", 1, 50, min(5, len(drafted)))
        account = gog_account() or "(set OUTREACH_GMAIL_ACCOUNT in .env)"
        st.caption(f"Gmail account for live send: {account}")

        p1, p2, p3 = st.columns(3)
        with p1:
            if st.button("Preview send list", use_container_width=True):
                st.session_state["send_preview"] = send_drafts(int(send_limit), execute=False)
        with p2:
            approved = st.checkbox("I reviewed these recipients and approve sending")
            if st.button("Send via Gmail (gog)", type="primary", disabled=not approved, use_container_width=True):
                out = send_drafts(int(send_limit), execute=True)
                failures = [r for r in out if r["status"] == "failed"]
                if failures:
                    st.error(f"{len(failures)} failed.")
                    st.code(failures[0].get("error") or failures[0].get("detail") or "unknown error")
                else:
                    st.success(f"Sent {len(out)} emails.")
                st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)
        with p3:
            sim_ok = st.checkbox("Demo only: mark as sent locally")
            if st.button("Simulate send", disabled=not sim_ok, use_container_width=True):
                out = send_drafts(int(send_limit), simulate=True)
                st.warning(f"Marked {len(out)} as sent locally (no Gmail call).")
                st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)

        if st.session_state.get("send_preview"):
            st.markdown("**Would send to:**")
            st.dataframe(pd.DataFrame(st.session_state["send_preview"]), use_container_width=True, hide_index=True)

    if not events_df.empty:
        st.divider()
        st.subheader("Outreach history")
        st.dataframe(
            events_df[["business_name", "email", "status", "template_id", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_qualify:
    st.subheader("Post-reply lead qualification")
    st.caption(
        "After outreach, inbound replies are matched to CRM leads and classified with deterministic rules "
        "(interested, meeting, question, not interested, unsubscribe, OOO). No LLM required."
    )
    q1, q2 = st.columns(2)
    with q1:
        reply_source = st.radio(
            "Reply source",
            options=["demo", "gmail"],
            format_func=lambda x: "Demo replies (offline)" if x == "demo" else "Live Gmail inbox (gog)",
            horizontal=True,
        )
    with q2:
        max_replies = st.number_input("Max messages to scan", 1, 50, 15)

    if st.button("Qualify replies now", type="primary"):
        with st.spinner("Classifying replies…"):
            out = run_reply_qualification(reply_source, int(max_replies))
        st.session_state["last_qualify"] = out
        if out.get("warning"):
            st.warning(out["warning"])
        st.success(
            f"Scanned {out['scanned']} messages via **{out['source_used']}**. "
            f"Updated {out['applied']} lead(s)."
        )
        st.dataframe(pd.DataFrame(out["results"]), use_container_width=True, hide_index=True)
        st.rerun()

    if st.session_state.get("last_qualify"):
        st.markdown("**Last qualification run**")
        st.dataframe(pd.DataFrame(st.session_state["last_qualify"]["results"]), use_container_width=True, hide_index=True)

    try:
        replies_df = query_df(
            """
            SELECT r.id, l.business_name, r.from_email, r.classification, r.lead_status_after,
                   r.confidence, r.subject, r.created_at
            FROM reply_events r
            LEFT JOIN leads l ON l.id = r.lead_id
            ORDER BY r.created_at DESC
            LIMIT 100
            """
        )
    except Exception:
        replies_df = pd.DataFrame()
        st.info("Reply tables not initialized yet. Click Qualify replies once (or Create CRM tables).")

    if not replies_df.empty:
        st.divider()
        st.markdown("**Reply history**")
        st.dataframe(replies_df, use_container_width=True, hide_index=True)

    if not leads_df.empty and "qualification" in leads_df.columns:
        labeled = leads_df[leads_df["qualification"].notna()][
            ["business_name", "email", "status", "qualification", "qualification_reason", "last_reply_at"]
        ]
        if not labeled.empty:
            st.markdown("**Leads with reply qualification**")
            st.dataframe(labeled, use_container_width=True, hide_index=True)

with tab_insights:
    if leads_df.empty:
        st.info("Nothing to chart yet.")
    else:
        i1, i2 = st.columns(2)
        with i1:
            st.markdown("**Pipeline by status**")
            st.bar_chart(leads_df["status"].value_counts())
        with i2:
            st.markdown("**Website presence**")
            st.bar_chart(leads_df["website_status"].value_counts())

        st.markdown("**Leads by metro**")
        st.bar_chart(leads_df.groupby("metro")["id"].count())

        st.markdown("**Scoring weights in use**")
        st.json(load_weights(), expanded=False)
