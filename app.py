from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from codex_log_parser import TOKEN_FIELDS, parse_session_log, session_summary, token_event_rows


DEFAULT_SESSION_ROOT = Path.home() / ".codex" / "sessions"
CACHE_VERSION = 2


def discover_logs(root: Path) -> list[Path]:
    if not root.exists():
        return []

    return sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)


def log_date(path: Path) -> date | None:
    parts = path.parts
    for index in range(len(parts) - 2):
        year, month, day = parts[index : index + 3]
        if year.isdigit() and month.isdigit() and day.isdigit():
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                continue

    match = pd.Series([path.name]).str.extract(r"(\d{4})-(\d{2})-(\d{2})").iloc[0]
    if match.notna().all():
        return date(int(match[0]), int(match[1]), int(match[2]))

    return datetime.fromtimestamp(path.stat().st_mtime).date()


def logs_in_range(logs: list[Path], start_date: date, end_date: date) -> list[Path]:
    return [
        path
        for path in logs
        if (path_date := log_date(path)) is not None and start_date <= path_date <= end_date
    ]


def format_int(value: int) -> str:
    return f"{value:,}"


@st.cache_data(show_spinner=False)
def parse_session_summary_cached(path_text: str, modified_time_ns: int, cache_version: int) -> dict:
    parsed = parse_session_log(path_text)
    summary = session_summary(parsed)
    path = Path(path_text)
    summary["path"] = path_text
    summary["file_name"] = path.name
    summary["log_date"] = log_date(path)
    return summary


def normalize_summary_df(summary_df: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "model": "Unknown",
        "reasoning_effort": "Unknown",
        "reasoning_summary": "Unknown",
        "model_provider": "Unknown",
        "cwd": "",
        "token_event_count": 0,
        "malformed_line_count": 0,
    }

    for field in TOKEN_FIELDS:
        defaults[field] = 0

    for column, default_value in defaults.items():
        if column not in summary_df.columns:
            summary_df[column] = default_value
        else:
            summary_df[column] = summary_df[column].fillna(default_value)

    for field in TOKEN_FIELDS + ["token_event_count", "malformed_line_count"]:
        summary_df[field] = pd.to_numeric(summary_df[field], errors="coerce").fillna(0).astype(int)

    return summary_df


def render_usage_metrics(summary: dict) -> None:
    metric_fields = [
        ("Total", "total_tokens"),
        ("Input", "input_tokens"),
        ("Cached Input", "cached_input_tokens"),
        ("Cache Write", "cache_write_input_tokens"),
        ("Output", "output_tokens"),
        ("Reasoning Output", "reasoning_output_tokens"),
    ]

    columns = st.columns(3)
    for index, (label, field) in enumerate(metric_fields):
        columns[index % 3].metric(label, format_int(int(summary.get(field, 0))))


def render_usage_breakdown(summary: dict) -> None:
    rows = [
        {"token_type": field, "tokens": int(summary.get(field, 0))}
        for field in TOKEN_FIELDS
        if field != "total_tokens"
    ]
    usage_df = pd.DataFrame(rows)

    if usage_df.empty:
        st.info("No token usage fields were found.")
        return

    st.bar_chart(usage_df, x="token_type", y="tokens", use_container_width=True)
    st.dataframe(usage_df, hide_index=True, use_container_width=True)


def render_single_session_view(logs: list[Path]) -> None:
    with st.sidebar:
        uploaded_file = st.file_uploader("Or upload a .jsonl file", type=["jsonl"])

        selected_path = None
        if logs:
            labels = [str(path) for path in logs[:250]]
            selected_label = st.selectbox("Pick a recent session", labels)
            selected_path = Path(selected_label)
        else:
            st.warning("No .jsonl session logs found under this root.")

    parsed = None
    source_label = None

    if uploaded_file is not None:
        temp_path = Path(".streamlit_uploaded_session.jsonl")
        temp_path.write_bytes(uploaded_file.getvalue())
        parsed = parse_session_log(temp_path)
        source_label = uploaded_file.name
    elif selected_path is not None:
        parsed = parse_session_log(selected_path)
        source_label = str(selected_path)

    if parsed is None:
        st.info("Pick or upload a Codex session log to begin.")
        return

    summary = session_summary(parsed)
    st.subheader("Selected Session")
    st.code(source_label, language="text")

    details = {
        "Session ID": summary["session_id"],
        "Started": summary["started_at"],
        "Last token event": summary["last_token_event_at"],
        "Working directory": summary["cwd"],
        "Originator": summary["originator"],
        "Model provider": summary["model_provider"],
        "Model": summary["model"],
        "Reasoning effort": summary["reasoning_effort"],
        "Reasoning summary": summary["reasoning_summary"],
        "Records parsed": summary["record_count"],
        "Token events": summary["token_event_count"],
        "Malformed lines": summary["malformed_line_count"],
    }
    st.dataframe(
        pd.DataFrame([{"field": key, "value": value} for key, value in details.items()]),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Token Usage")
    render_usage_metrics(summary)

    left, right = st.columns([2, 3])
    with left:
        st.markdown("#### Breakdown")
        render_usage_breakdown(summary)

    with right:
        st.markdown("#### Token Events")
        events_df = pd.DataFrame(token_event_rows(parsed))
        if events_df.empty:
            st.info("This log does not contain token_count events.")
        else:
            st.line_chart(
                events_df,
                x="event",
                y=["total_input_tokens", "total_output_tokens", "total_total_tokens"],
                use_container_width=True,
            )
            st.dataframe(events_df, hide_index=True, use_container_width=True)


def render_usage_statistics_view(logs: list[Path]) -> None:
    dated_logs = [(path, path_date) for path in logs if (path_date := log_date(path)) is not None]
    if not dated_logs:
        st.info("No dated session logs were found under this root.")
        return

    available_dates = [path_date for _, path_date in dated_logs]
    latest_date = max(available_dates)
    default_start = max(min(available_dates), latest_date.replace(day=1))

    st.subheader("Usage Statistic")

    filter_left, filter_right = st.columns(2)
    with filter_left:
        start_date = st.date_input(
            "From date",
            value=default_start,
            min_value=min(available_dates),
            max_value=latest_date,
        )
    with filter_right:
        end_date = st.date_input(
            "To date",
            value=latest_date,
            min_value=min(available_dates),
            max_value=latest_date,
        )

    if start_date > end_date:
        st.warning("Start date must be before or equal to end date.")
        return

    selected_logs = logs_in_range(logs, start_date, end_date)
    st.caption(f"{start_date.isoformat()} to {end_date.isoformat()}")

    if not selected_logs:
        st.info("No session logs found in this date range.")
        return

    with st.spinner(f"Parsing {len(selected_logs)} session logs..."):
        summaries = [
            parse_session_summary_cached(str(path), path.stat().st_mtime_ns, CACHE_VERSION)
            for path in selected_logs
        ]

    summary_df = normalize_summary_df(pd.DataFrame(summaries))
    daily_df = (
        summary_df[["log_date", *TOKEN_FIELDS]]
        .groupby("log_date", as_index=False)[TOKEN_FIELDS]
        .sum()
        .sort_values("log_date")
    )
    model_reasoning_df = (
        summary_df[["model", "reasoning_effort", *TOKEN_FIELDS, "session_id"]]
        .groupby(["model", "reasoning_effort"], as_index=False)
        .agg(
            sessions=("session_id", "count"),
            input_tokens=("input_tokens", "sum"),
            cached_input_tokens=("cached_input_tokens", "sum"),
            cache_write_input_tokens=("cache_write_input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            reasoning_output_tokens=("reasoning_output_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
        )
        .sort_values("total_tokens", ascending=False)
    )

    totals = {field: int(summary_df[field].sum()) for field in TOKEN_FIELDS}
    render_usage_metrics(totals)

    extra_columns = st.columns(3)
    extra_columns[0].metric("Sessions", format_int(len(summary_df)))
    extra_columns[1].metric("With Token Events", format_int(int((summary_df["token_event_count"] > 0).sum())))
    extra_columns[2].metric("Malformed Lines", format_int(int(summary_df["malformed_line_count"].sum())))

    left, right = st.columns([2, 3])
    with left:
        st.markdown("#### Range Breakdown")
        render_usage_breakdown(totals)

    with right:
        st.markdown("#### Daily Totals")
        st.line_chart(
            daily_df,
            x="log_date",
            y=["input_tokens", "output_tokens", "total_tokens"],
            use_container_width=True,
        )
        st.dataframe(daily_df, hide_index=True, use_container_width=True)

    st.markdown("#### By Model And Reasoning Effort")
    st.bar_chart(
        model_reasoning_df,
        x="model",
        y="total_tokens",
        color="reasoning_effort",
        use_container_width=True,
    )
    st.dataframe(model_reasoning_df, hide_index=True, use_container_width=True)

    st.markdown("#### Sessions")
    session_columns = [
        "log_date",
        "session_id",
        "model",
        "reasoning_effort",
        "cwd",
        "token_event_count",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "path",
    ]
    st.dataframe(
        summary_df[session_columns].sort_values(["log_date", "total_tokens"], ascending=[False, False]),
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(page_title="Codex Session Analyzer", layout="wide")

    st.title("Codex Session Analyzer")
    st.caption("Local JSONL token usage views for Codex session logs.")

    with st.sidebar:
        view = st.radio("View", ["Session Log", "Usage Statistic"])
        st.header("Source")
        root_text = st.text_input("Session root", value=str(DEFAULT_SESSION_ROOT))
        root = Path(root_text).expanduser()
        logs = discover_logs(root)

    if view == "Session Log":
        render_single_session_view(logs)
    else:
        render_usage_statistics_view(logs)


if __name__ == "__main__":
    main()
