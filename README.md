# Codex Session Analyzer

A local Streamlit app for inspecting Codex Desktop session JSONL logs and summarizing token usage.

The app reads logs from the Codex sessions folder, keeps the raw logs read-only, and calculates usage from `token_count` events in each session.

## Features

- Inspect one Codex session log at a time.
- View total, input, cached input, cache-write, output, and reasoning output tokens.
- Select a date range and summarize usage across all sessions in that range.
- Group range usage by model and reasoning effort.
- View daily usage totals and per-session usage rows.
- Upload a standalone `.jsonl` session log for one-off inspection.

## Requirements

- Python 3.12 or newer
- Streamlit
- pandas

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Run

From this project folder:

```powershell
streamlit run app.py
```

Then open:

```text
http://localhost:8501
```

## Default Log Location

The app defaults to:

```text
C:\Users\320086703\.codex\sessions
```

Codex session logs are expected under date folders like:

```text
C:\Users\320086703\.codex\sessions\2026\07\29
```

You can change the session root from the sidebar.

## Views

### Session Log

Use this view to inspect a single `.jsonl` session.

It shows:

- session metadata
- model and reasoning effort, when present
- final cumulative token usage
- token usage breakdown
- token-count event history

### Usage Statistic

Use this view to analyze a date range.

Set:

- `From date`
- `To date`

The app then scans session logs in that range and shows:

- aggregate token totals
- daily usage totals
- usage grouped by model and reasoning effort
- per-session usage table

## Notes

- Token totals are based on the latest cumulative `total_token_usage` event in each session.
- Logs without model or reasoning metadata are grouped as `Unknown`.
- Logs without token events are included in session counts but contribute `0` tokens.

