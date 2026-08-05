import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from generate_project_profile import generate_project_profile
from ingest_docx import (
    ingest_docx,
    validate_ingested_document as validate_docx_ingestion,
)
from ingest_pptx import (
    ingest_pptx,
    validate_ingested_document as validate_pptx_ingestion,
)

from tools.applicability_engine import (
    create_applicability_plan,
    get_default_plan_path,
    get_default_project_profile_path,
    save_project_profile,
)

from tools.run_context import get_run_paths

DEFAULT_INGESTION_SCHEMA = Path(
    "schema/ingested_document.schema.json"
)
DEFAULT_PROFILE_SCHEMA = Path(
    "schema/project_profile.schema.json"
)
DEFAULT_MODEL = "gemini-2.5-flash"


def load_json(path: Path) -> dict[str, Any]:
    """ Load JSON file from disk and return as a dict"""
    
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return value


def write_json(
    value: dict[str, Any],
    path: Path,
) -> None:
    """ Write a dict to a JSON file"""
    
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def make_project_id(source_path: Path) -> str:
    """ Generate normalized project ID from source document filename"""
    
    project_id = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        source_path.stem,
    ).strip("_").lower()

    return project_id or "project"


def ingest_source_document(
    source_path: Path,
    ingestion_schema: dict[str, Any],
) -> dict[str, Any]:
    """ Ingest DOCX or PPTX source document and validate against ingestion schema"""
    
    suffix = source_path.suffix.lower()

    if suffix == ".docx":
        document = ingest_docx(source_path)

        validate_docx_ingestion(
            document=document,
            schema=ingestion_schema,
        )

        return document

    if suffix == ".pptx":
        document = ingest_pptx(source_path)

        validate_pptx_ingestion(
            document=document,
            schema=ingestion_schema,
        )

        return document

    raise ValueError(
        f"Unsupported project document type: {suffix}. "
        "Currently supported: .docx and .pptx."
    )


def count_profile_statuses(
    profile: dict[str, Any],
) -> dict[str, int]:
    """ Count number of fields in each status category"""
    
    statuses = profile[
        "extraction_metadata"
    ].get("field_status", {})

    counts = {
        "explicit": 0,
        "inferred": 0,
        "unresolved": 0,
    }

    for status in statuses.values():
        if status in counts:
            counts[status] += 1

    return counts


def prepare_project_for_interview(
    source_path: Path,
    workspace_dir: Path,
    ingestion_schema_path: Path,
    profile_schema_path: Path,
    model: str,
) -> Path:
    """ Ingest a project document and generate a validated project profile for interview"""
    
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source document not found: {source_path}"
        )

    if source_path.suffix.lower() not in {
        ".docx",
        ".pptx",
    }:
        raise ValueError(
            "Only DOCX and PPTX documents are currently supported."
        )

    project_id = make_project_id(source_path)

    workspace_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_copy_path = (
        workspace_dir
        / f"source_document{source_path.suffix.lower()}"
    )
    ingested_path = (
        workspace_dir
        / "ingested_document.json"
    )
    draft_profile_path = (
        workspace_dir
        / "draft_project_profile.json"
    )
    completed_profile_path = (
        workspace_dir
        / "completed_project_profile.json"
    )
    run_manifest_path = (
        workspace_dir
        / "run_manifest.json"
    )

    ingestion_schema = load_json(
        ingestion_schema_path
    )

    print(f"Project ID: {project_id}")
    print(f"Source document: {source_path}")
    print(f"Workspace: {workspace_dir}")

    print("\n[1/4] Copying source document...")
    shutil.copy2(
        source_path,
        source_copy_path,
    )

    print("[2/4] Ingesting document...")
    ingested_document = ingest_source_document(
        source_path=source_path,
        ingestion_schema=ingestion_schema,
    )

    write_json(
        value=ingested_document,
        path=ingested_path,
    )

    print(
        "      Extracted blocks: "
        f"{len(ingested_document['blocks'])}"
    )
    print(
        "      Ingestion warnings: "
        f"{len(ingested_document['warnings'])}"
    )

    print("[3/4] Generating project profile...")
    generate_project_profile(
        source_path=ingested_path,
        output_path=draft_profile_path,
        schema_path=profile_schema_path,
        model=model,
    )

    draft_profile = load_json(
        draft_profile_path
    )

    clarification_groups = draft_profile[
        "extraction_metadata"
    ].get(
        "clarification_groups",
        [],
    )

    unresolved_fields = draft_profile[
        "extraction_metadata"
    ].get(
        "unresolved_fields",
        [],
    )

    status_counts = count_profile_statuses(
        draft_profile
    )

    print("[4/4] Preparing interview profile...")

    # If no clarification is required, the draft profile is already complete.
    if not clarification_groups:
        shutil.copy2(
            draft_profile_path,
            completed_profile_path,
        )
        profile_status = "ready_for_applicability"
        active_profile_path = completed_profile_path
    else:
        profile_status = "needs_clarification"
        active_profile_path = draft_profile_path

    manifest = {
        "project_id": project_id,
        "status": profile_status,
        "source_document": str(source_copy_path),
        "ingested_document": str(ingested_path),
        "draft_project_profile": str(
            draft_profile_path
        ),
        "completed_project_profile": (
            str(completed_profile_path)
            if completed_profile_path.exists()
            else None
        ),
        "active_profile": str(
            active_profile_path
        ),
        "source_file_type": (
            source_path.suffix.lower().lstrip(".")
        ),
        "extracted_blocks": len(
            ingested_document["blocks"]
        ),
        "ingestion_warnings": (
            ingested_document["warnings"]
        ),
        "profile_status_counts": status_counts,
        "remaining_clarification_groups": len(
            clarification_groups
        ),
        "remaining_unresolved_fields": len(
            unresolved_fields
        ),
        "applicability_plan": None,
        "user_responses": None,
        "decision_trace": None,
    }

    write_json(
        value=manifest,
        path=run_manifest_path,
    )

    print("\nProject preparation complete.")
    print(f"Status: {profile_status}")
    print(
        "Explicit fields: "
        f"{status_counts['explicit']}"
    )
    print(
        "Inferred fields: "
        f"{status_counts['inferred']}"
    )
    print(
        "Unresolved fields: "
        f"{status_counts['unresolved']}"
    )
    print(
        "Clarification groups: "
        f"{len(clarification_groups)}"
    )
    print(f"Manifest: {run_manifest_path}")

    if clarification_groups:
        print(
            "\nThe project profile requires clarification."
        )
        print("Run:")

        print(
            "python tools/run_clarification_session.py "
            f"{draft_profile_path} "
            f"{completed_profile_path}"
        )
    else:
        print(
            "\nThe completed project profile is ready "
            "for applicability planning:"
        )
        print(completed_profile_path)

    return active_profile_path

def activate_completed_project(
    completed_profile_path: Path,
    workspace_dir: Path,
) -> dict[str, Any]:
    """
    Convert completed generated profile into the flat operational profile
    used by applicability planning and the interview.
    """

    if not completed_profile_path.exists():
        raise FileNotFoundError(
            "Completed project profile not found: "
            f"{completed_profile_path}"
        )

    run_paths = get_run_paths()

    expected_workspace = workspace_dir.resolve()
    active_workspace = run_paths.workspace.resolve()

    if active_workspace != expected_workspace:
        raise ValueError(
            "CHECKLIST_RUN_DIR does not match the workspace being activated. "
            f"Environment workspace: {active_workspace}. "
            f"Requested workspace: {expected_workspace}."
        )

    generated_profile = load_json(
        completed_profile_path
    )

    project_profile = generated_profile.get(
        "project_profile"
    )

    if not isinstance(project_profile, dict):
        raise ValueError(
            "Completed profile does not contain a valid "
            "'project_profile' object."
        )

    metadata = generated_profile.get(
        "extraction_metadata",
        {},
    )

    clarification_groups = metadata.get(
        "clarification_groups",
        [],
    )
    unresolved_fields = metadata.get(
        "unresolved_fields",
        [],
    )

    if clarification_groups or unresolved_fields:
        raise ValueError(
            "The completed profile still contains unresolved "
            "fields or clarification groups."
        )

    profile_path = get_default_project_profile_path()
    plan_path = get_default_plan_path()

    print(f"Creating operational profile: {profile_path}")

    save_project_profile(
        profile=project_profile,
        path=profile_path,
    )

    print(f"Generating applicability plan: {plan_path}")

    plan = create_applicability_plan(
        project_profile=project_profile,
        output_path=plan_path,
    )

    decision_counts: dict[str, int] = {}

    for decision in plan["decisions"]:
        decision_name = decision["decision"]
        decision_counts[decision_name] = (
            decision_counts.get(decision_name, 0) + 1
        )

    manifest_path = (
        workspace_dir / "run_manifest.json"
    )

    if manifest_path.exists():
        manifest = load_json(manifest_path)
    else:
        manifest = {}

    manifest.update(
        {
            "status": "ready_for_interview",
            "completed_project_profile": str(
                completed_profile_path
            ),
            "operational_project_profile": str(
                profile_path
            ),
            "applicability_plan": str(
                plan_path
            ),
            "user_responses": str(
                run_paths.responses
            ),
            "decision_trace": str(
                run_paths.trace
            ),
            "decision_counts": decision_counts,
        }
    )

    write_json(
        value=manifest,
        path=manifest_path,
    )

    print("\nProject activated successfully.")
    print(
        f"Project: "
        f"{project_profile.get('project_name')}"
    )
    print(
        f"Total questions: "
        f"{plan['total_questions']}"
    )
    print(
        f"Decision counts: {decision_counts}"
    )
    print(f"Workspace: {run_paths.workspace}")
    print(f"Operational profile: {profile_path}")
    print(f"Applicability plan: {plan_path}")
    print(f"Responses: {run_paths.responses}")
    print(f"Trace: {run_paths.trace}")

    return plan


def parse_arguments() -> argparse.Namespace:
    """ Parse command-line args for project preparation tool"""
    
    parser = argparse.ArgumentParser(
        description=(
            "Ingest a DOCX or PPTX project document and "
            "generate a validated project profile for the "
            "Responsible AI interview pipeline."
        )
    )
    

    parser.add_argument(
        "source",
        type=Path,
        help="Path to the source DOCX or PPTX document.",
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help=(
            "Directory where run artifacts will be saved."
        ),
    )
    parser.add_argument(
        "--ingestion-schema",
        type=Path,
        default=DEFAULT_INGESTION_SCHEMA,
    )
    parser.add_argument(
        "--profile-schema",
        type=Path,
        default=DEFAULT_PROFILE_SCHEMA,
    )
    
    parser.add_argument(
        "--activate",
        action="store_true",
        help=(
            "Activate an existing completed profile in the "
            "workspace and generate the applicability plan."
        ),
    )
    
    parser.add_argument(
        "--model",
        default=os.getenv(
            "PROJECT_PROFILE_MODEL",
            DEFAULT_MODEL,
        ),
    )

    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_arguments()

    try:
        
        if args.activate:
            completed_profile_path = (
                args.workspace
                / "completed_project_profile.json"
            )

            activate_completed_project(
                completed_profile_path=completed_profile_path,
                workspace_dir=args.workspace,
            )
            
            return
        
        prepare_project_for_interview(
            source_path=args.source,
            workspace_dir=args.workspace,
            ingestion_schema_path=(
                args.ingestion_schema
            ),
            profile_schema_path=(
                args.profile_schema
            ),
            model=args.model,
        )
    except Exception as error:
        print(
            f"Project preparation failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()