"""JSON-backed response storage helpers for the checklist agent.

The response store persists answers as a JSON object keyed by the question
field name from the question loader. This keeps the data easy to inspect and
compatible with the structured intake flow.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional
from tools.run_context import get_run_paths

# Default file path for response persistence when no explicit path is provided.
def get_default_responses_path() -> Path:
    """Return the response file for the active project workspace."""
    
    return get_run_paths().responses

def _resolve_path(path: Optional[Path | str] = None) -> Path:
    """Resolve a path fallback to the default responses file."""
    
    if path is None:
        return get_default_responses_path()

    return Path(path)


def load_responses(path: Optional[Path | str] = None) -> dict[str, Any]:
    """Load stored responses from disk.

    If the file does not exist or is empty, an empty mapping is returned.
    """
    
    target = _resolve_path(path)
    if not target.exists() or target.stat().st_size == 0:
        # An empty or missing file is treated as "no responses yet".
        return {}

    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("response store JSON must be a top-level object")

    return dict(data)


def save_responses(responses: Mapping[str, Any], path: Optional[Path | str] = None) -> dict[str, Any]:
    """Persist a mapping of responses to disk.

    The file is created if it does not exist and parent directories are created
    as needed.
    """
    
    if not isinstance(responses, Mapping):
        raise TypeError("responses must be a mapping")

    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", encoding="utf-8") as handle:
      
        json.dump(dict(responses), handle, indent=2)
        handle.write("\n")

    return dict(responses)


def set_response(field: str, value: Any, path: Optional[Path | str] = None) -> dict[str, Any]:
    """Store a single response and persist it immediately."""
    
    responses = load_responses(path)
    responses[field] = value
    return save_responses(responses, path)


def get_response(field: str, path: Optional[Path | str] = None, default: Any = None) -> Any:
    """Return a response value by field name, or the provided default."""
    
    responses = load_responses(path)
    return responses.get(field, default)


def update_responses(updates: Mapping[str, Any], path: Optional[Path | str] = None) -> dict[str, Any]:
    """Merge a mapping of responses into the existing store and persist it."""
    
    if not isinstance(updates, Mapping):
        
        raise TypeError("updates must be a mapping")

    responses = load_responses(path)
    # Merge updates into the existing store so separate steps can persist

    responses.update(dict(updates))
    return save_responses(responses, path)


def clear_responses(path: Optional[Path | str] = None) -> dict[str, Any]:
    """Clear all stored responses."""
    
    return save_responses({}, path)


__all__ = [
    "get_default_responses_path",
    "load_responses",
    "save_responses",
    "set_response",
    "get_response",
    "update_responses",
    "clear_responses",
]
