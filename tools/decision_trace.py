"""Append-only trace logging for applicability and interview decisions.

Trace file records every decision and user interaction in JSONL format
for later auditing and debugging.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.run_context import get_run_paths

# Standard path for the JSONL trace file created by the interview tooling.
BASE_DIR = Path(__file__).resolve().parents[1]
def get_default_trace_path() -> Path:
    """Return the trace file for the active project workspace."""
    
    return get_run_paths().trace


def append_trace(
    event_type: str,
    payload: dict[str, Any],
    path: Path | None=None,
) -> None:
    """Append one structured event to the JSONL trace file."""

    target = path if path is not None else get_default_trace_path()
    
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }

    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, default=str))
        file.write("\n")


def clear_trace(path: Path | None = None ) -> None:
    """Clear the trace file while leaving the parent directory in place."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
