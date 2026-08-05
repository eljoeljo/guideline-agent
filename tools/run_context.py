from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class RunPaths:
    workspace: Path
    profile: Path
    plan: Path
    responses: Path
    trace: Path


def get_run_paths() -> RunPaths:
    workspace = Path(
        os.getenv("CHECKLIST_RUN_DIR", "data/runs/default")
    )

    return RunPaths(
        workspace=workspace,
        profile=workspace / "project_profile.json",
        plan=workspace / "applicability_plan.json",
        responses=workspace / "user_responses.json",
        trace=workspace / "decision_trace.jsonl",
    )