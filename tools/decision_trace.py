"""Append-only trace logging for applicability and interview decisions.

Trace file records every decision and user interaction in JSONL format
for later auditing and debugging.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Standard path for the JSONL trace file created by the interview tooling.
BASE_DIR = Path(__file__).resolve().parents[1]
TRACE_PATH = BASE_DIR / "data" / "decision_trace.jsonl"


def append_trace(
    event_type: str,
    payload: dict[str, Any],
    path: Path = TRACE_PATH,
) -> None:
    """Append one structured event to the JSONL trace file."""

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, default=str))
        file.write("\n")


def clear_trace(path: Path = TRACE_PATH) -> None:
    """Clear the trace file while leaving the parent directory in place."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
