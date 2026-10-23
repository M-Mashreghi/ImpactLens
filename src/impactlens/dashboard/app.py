"""ImpactLens Streamlit dashboard: ``streamlit run src/impactlens/dashboard/app.py``.

Presentation only: every number shown comes from the API (deterministic services).
"""

from __future__ import annotations

import streamlit as st

from impactlens.dashboard.client import ApiClientError, DashboardClient, make_client

DISCLAIMER = (
    "Impact scores are deterministic **priority** measures for triage — not expected returns or "
    "investment advice. Historical figures show observed association, not causation."
)
PAGES = ["Portfolio", "Impact Feed", "News Detail", "Impact Detail", "Historical Context", "Alerts / System"]


def get_client() -> DashboardClient:
    if "client" not in st.session_state:
        st.session_state["client"] = DashboardClient(make_client())
    return st.session_state["client"]


def page_portfolio(client: DashboardClient) -> None:
    st.header("Portfolio")
    portfolios = client.portfolios()
    if not portfolios:
        st.info("No portfolio yet. Import a CSV below (synthetic demo data only).")
    for p in portfolios:
        st.subheader(p["name"])
        if p["latest_snapshot_id"]:
            snap = client.snapshot(p["latest_snapshot_id"])
            st.caption(
                f"Snapshot {snap['snapshot_id']} · as of {snap['as_of']} · basis {snap['weight_basis']}"
            )
            st.dataframe(
                [
                    {
                        "Ticker": x["ticker"],
                        "Name": x["display_name"],
                        "Exchange": x["exchange"],
                        "Weight %": round(x["weight"] * 100, 2),
                        "Market value": x["market_value"],
                        "Currency": x["currency"],
                    }
                    for x in snap["positions"]
                ],
                use_container_width=True,
            )
    with st.expander("Import portfolio CSV"):
        name = st.text_input("Portfolio name", "Demo Portfolio")
        upload = st.file_uploader("CSV file", type=["csv"])
        as_of = st.text_input("Snapshot as of (ISO-8601, optional)", "")
        if st.button("Import") and upload is not None:
            try:
                result = client.import_portfolio(name, upload.getvalue().decode("utf-8"), as_of or None)
                st.success(f"Created snapshot {result['snapshot']['snapshot_id']}")
                for w in result["warnings"]:
                    st.warning(w)
            except ApiClientError as exc:
                st.error(str(exc))


def page_feed(client: DashboardClient) -> None:
    st.header("Impact Feed")
    level = st.selectbox("Minimum level", ["All", "Medium", "High", "Critical"])
    feed = client.feed(min_level=None if level == "All" else level)
    if not feed:
        st.info("No scored impacts yet.")
        return
    st.dataframe(
        [
            {
                "Impact": i["impact_id"],
                "Level": i["impact_level"],
                "Priority": i["absolute_priority"],
                "Signed": i["signed_score"],
                "Headline": (i.get("news") or {}).get("title"),
                "Published": (i.get("news") or {}).get("published_at"),
                "Snapshot": i["snapshot_id"],
            }
            for i in feed
        ],
        use_container_width=True,
    )
    st.caption("Ranked by absolute priority (ties: newer news first). " + DISCLAIMER)


def page_news(client: DashboardClient) -> None:
    st.header("News Detail")
    items = client.news_list()
    if not items:
        st.info("No news ingested yet.")
    else:
        choice = st.selectbox("News item", [f"{n['news_id']} — {n['title'][:90]}" for n in items])
        detail = client.news(int(choice.split(" — ")[0]))
        st.markdown(f"**{detail['title']}**")
        st.caption(
            f"{detail['source_name']} · published {detail['published_at'] or 'unknown'} "
            f"({detail['published_at_quality']}) · retrieved {detail['retrieved_at']} · "
            f"status {detail['ingestion_status']}"
        )
        if detail["canonical_news_id"]:
            st.info(f"Duplicate of news {detail['canonical_news_id']}")
        st.text_area(
            "Normalized text (untrusted source content)", detail["normalized_text"], height=180, disabled=True
        )
        analysis = detail.get("analysis")
        if analysis:
            st.subheader(f"Analysis — {analysis['status']}")
            st.write(
                {
                    k: analysis[k]
                    for k in (
                        "event_type",
                        "direction",
                        "severity",
                        "confidence",
                        "time_horizon",
                        "event_summary",
                    )
                }
            )
            st.caption(
                f"{analysis['model_provider']}/{analysis['model_name']} · {analysis['prompt_version']} · "
                f"{analysis['schema_version']}"
            )
            if analysis.get("analysis"):
                st.markdown("**Evidence**")
                grounded = {
                    s["id"]: s["grounded"] for s in (analysis.get("evidence_report") or {}).get("spans", [])
                }
                for ev in analysis["analysis"]["evidence"]:
                    mark = "✅" if grounded.get(ev["id"]) else "❌"
                    st.markdown(
                        f"{mark} [E{ev['id']}] “{ev['quote']}” — supports {', '.join(ev['supports'])}"
                    )
            if analysis.get("resolution"):
                st.markdown("**Entity resolution**")
                st.dataframe(
                    [
                        {
                            "Entity": e["name"],
                            "Type": e["entity_type"],
                            "Role": e["role"],
                            "Status": e["status"],
                            "Securities": ", ".join(e["security_ids"]),
                            "Factor": e["factor_key"],
                            "Evidence": e["evidence_supported"],
                            "Notes": "; ".join(e["notes"]),
                        }
                        for e in analysis["resolution"]["entities"]
                    ],
                    use_container_width=True,
                )
    with st.expander("Analyze pasted news text"):
        title = st.text_input("Title")
        text = st.text_area("Article text")
        published = st.text_input("Published at (ISO-8601, optional)")
        if st.button("Ingest & analyze"):
            try:
                st.json(client.ingest(title, text, published or None))
            except ApiClientError as exc:
                st.error(str(exc))


def page_impact(client: DashboardClient) -> None:
    st.header("Portfolio Impact Detail")
    feed = client.feed()
    if not feed:
        st.info("No scored impacts yet.")
        return
    choice = st.selectbox(
        "Impact",
        [
            f"{i['impact_id']} — {i['impact_level']} — {(i.get('news') or {}).get('title', '')[:80]}"
            for i in feed
        ],
    )
    impact = client.impact(int(choice.split(" — ")[0]))
    exp = impact["explanation"]
    st.subheader(exp["headline"])
    st.write(exp["event_line"])
    st.caption(
        f"Scoring {impact['scoring_version']} · rules {impact['rules_version']} · snapshot "
        f"{impact['snapshot_id']} · {impact['result']['semantics']}"
    )
    st.markdown("**Score decomposition** (computed in Python)")
    st.dataframe(
        [
            {
                k: c[k]
                for k in (
                    "ticker",
                    "relationship_type",
                    "direction",
                    "position_weight",
                    "exposure_magnitude",
                    "relationship_weight",
                    "severity_value",
                    "confidence",
                    "relevance_weight",
                    "signed_component",
                    "position_priority",
                    "counted",
                )
            }
            for c in impact["result"]["components"]
        ],
        use_container_width=True,
    )
    for pos in exp["positions"]:
        st.markdown(f"- {pos['text']}")
        for cite in pos["citations"]:
            st.caption(f"[E{cite['evidence_id']}] “{cite['quote']}” — {cite['source_name']}")
    fmt = st.radio("Export", ["md", "json", "csv"], horizontal=True)
    st.download_button(
        "Download export",
        client.export(impact["impact_id"], fmt),
        file_name=f"impact-{impact['impact_id']}.{fmt}",
    )


def page_history(client: DashboardClient) -> None:
    st.header("Historical Context")
    st.caption("Observed market reactions and past analogs — association, not causation.")
    items = [n for n in client.news_list() if n["canonical_news_id"] is None]
    if not items:
        st.info("No news yet.")
        return
    choice = st.selectbox("News item", [f"{n['news_id']} — {n['title'][:90]}" for n in items])
    news_id = int(choice.split(" — ")[0])
    if st.button("Run event study"):
        try:
            client.run_studies(news_id)
        except ApiClientError as exc:
            st.error(str(exc))
    for study in client.studies(news_id):
        res = study["result"]
        st.markdown(
            f"**{res['security_symbol']}** vs {res['benchmark_symbol']} — anchor "
            f"{res['alignment']['anchor_date']} ({res['alignment']['session']})"
        )
        st.dataframe(
            [
                {
                    "Window": f"[{w['window'][0]},+{w['window'][1]}]",
                    "Status": w["status"],
                    "Security": w["security_return"],
                    "Benchmark": w["benchmark_return"],
                    "Abnormal (bps)": w["abnormal_return_bps"],
                }
                for w in res["windows"]
            ],
            use_container_width=True,
        )
        for note in res["notes"]:
            st.caption(note)
    detail = client.news(news_id)
    if detail.get("analysis") and detail["analysis"]["status"] == "Valid":
        analogs = client.analogs(detail["analysis"]["analysis_id"])
        st.markdown(f"**Historical analogs** (published before {analogs['cutoff']})")
        st.dataframe(
            [
                {
                    "News": a["news_id"],
                    "Title": a["title"],
                    "When": a["event_time"],
                    "Similarity": a["similarity"],
                    **a["components"],
                }
                for a in analogs["analogs"]
            ],
            use_container_width=True,
        )


def page_system(client: DashboardClient) -> None:
    st.header("Alerts / System")
    st.json(client.ready())
    st.subheader("Alert history")
    st.dataframe(client.alerts(), use_container_width=True)
    st.subheader("Safe configuration")
    st.json(client.config())


RENDERERS = {
    "Portfolio": page_portfolio,
    "Impact Feed": page_feed,
    "News Detail": page_news,
    "Impact Detail": page_impact,
    "Historical Context": page_history,
    "Alerts / System": page_system,
}


def main() -> None:
    st.set_page_config(page_title="ImpactLens", layout="wide")
    st.title("ImpactLens")
    st.caption(DISCLAIMER)
    page = st.sidebar.radio("Page", PAGES, key="page")
    client = get_client()
    try:
        RENDERERS[page](client)
    except ApiClientError as exc:
        st.error(f"API error: {exc}")
    except Exception as exc:  # connection problems etc.
        st.error(f"Cannot reach the ImpactLens API: {type(exc).__name__}")


main()
