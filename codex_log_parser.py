from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TOKEN_FIELDS = [
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]


@dataclass
class ParsedSession:
    path: Path
    metadata: dict[str, Any]
    settings: dict[str, Any]
    token_events: list[dict[str, Any]]
    malformed_lines: list[int]
    record_count: int


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _empty_usage() -> dict[str, int]:
    return {field: 0 for field in TOKEN_FIELDS}


def _normalize_usage(value: dict[str, Any] | None) -> dict[str, int]:
    usage = _empty_usage()
    if not isinstance(value, dict):
        return usage

    for field in TOKEN_FIELDS:
        raw_value = value.get(field, 0)
        usage[field] = raw_value if isinstance(raw_value, int) else 0

    return usage


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _extract_settings(payload: dict[str, Any]) -> dict[str, Any]:
    thread_settings = payload.get("thread_settings")
    if not isinstance(thread_settings, dict):
        thread_settings = {}

    collaboration_mode = payload.get("collaboration_mode")
    if not isinstance(collaboration_mode, dict):
        collaboration_mode = {}

    collaboration_settings = collaboration_mode.get("settings")
    if not isinstance(collaboration_settings, dict):
        collaboration_settings = {}

    thread_collaboration = thread_settings.get("collaboration_mode")
    if not isinstance(thread_collaboration, dict):
        thread_collaboration = {}

    thread_collaboration_settings = thread_collaboration.get("settings")
    if not isinstance(thread_collaboration_settings, dict):
        thread_collaboration_settings = {}

    return {
        "model": _first_present(
            payload.get("model"),
            thread_settings.get("model"),
            collaboration_settings.get("model"),
            thread_collaboration_settings.get("model"),
        ),
        "reasoning_effort": _first_present(
            payload.get("reasoning_effort"),
            payload.get("effort"),
            thread_settings.get("reasoning_effort"),
            collaboration_settings.get("reasoning_effort"),
            thread_collaboration_settings.get("reasoning_effort"),
        ),
        "reasoning_summary": thread_settings.get("reasoning_summary"),
        "model_context_window": payload.get("model_context_window"),
    }


def parse_session_log(path: str | Path) -> ParsedSession:
    log_path = Path(path)
    metadata: dict[str, Any] = {}
    settings: dict[str, Any] = {}
    token_events: list[dict[str, Any]] = []
    malformed_lines: list[int] = []
    record_count = 0

    with log_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines.append(line_number)
                continue

            record_count += 1

            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue

            extracted_settings = _extract_settings(payload)
            settings = {
                key: settings.get(key) or value
                for key, value in extracted_settings.items()
            }

            if record.get("type") == "session_meta":
                metadata = payload
                continue

            if record.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    info = {}

                token_events.append(
                    {
                        "line_number": line_number,
                        "timestamp": record.get("timestamp"),
                        "total": _normalize_usage(info.get("total_token_usage")),
                        "last": _normalize_usage(info.get("last_token_usage")),
                        "model_context_window": info.get("model_context_window"),
                    }
                )

    return ParsedSession(
        path=log_path,
        metadata=metadata,
        settings=settings,
        token_events=token_events,
        malformed_lines=malformed_lines,
        record_count=record_count,
    )


def latest_total_usage(parsed: ParsedSession) -> dict[str, int]:
    if not parsed.token_events:
        return _empty_usage()

    return parsed.token_events[-1]["total"]


def token_event_rows(parsed: ParsedSession) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for index, event in enumerate(parsed.token_events, start=1):
        row = {
            "event": index,
            "timestamp": event["timestamp"],
            "line_number": event["line_number"],
            "model_context_window": event["model_context_window"],
        }

        for field, value in event["last"].items():
            row[f"last_{field}"] = value

        for field, value in event["total"].items():
            row[f"total_{field}"] = value

        rows.append(row)

    return rows


def session_summary(parsed: ParsedSession) -> dict[str, Any]:
    started_at = parse_timestamp(parsed.metadata.get("timestamp"))
    last_event_at = parse_timestamp(parsed.token_events[-1]["timestamp"]) if parsed.token_events else None
    total_usage = latest_total_usage(parsed)

    return {
        "session_id": parsed.metadata.get("session_id") or parsed.metadata.get("id") or parsed.path.stem,
        "started_at": started_at,
        "last_token_event_at": last_event_at,
        "cwd": parsed.metadata.get("cwd"),
        "originator": parsed.metadata.get("originator"),
        "model_provider": parsed.metadata.get("model_provider"),
        "model": parsed.settings.get("model") or "Unknown",
        "reasoning_effort": parsed.settings.get("reasoning_effort") or "Unknown",
        "reasoning_summary": parsed.settings.get("reasoning_summary") or "Unknown",
        "model_context_window": parsed.settings.get("model_context_window"),
        "record_count": parsed.record_count,
        "token_event_count": len(parsed.token_events),
        "malformed_line_count": len(parsed.malformed_lines),
        **total_usage,
    }
