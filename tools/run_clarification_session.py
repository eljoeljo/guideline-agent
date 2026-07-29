import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from process_clarification_response import process_clarification


DEFAULT_RESPONSE_SCHEMA = Path(
    "schema/clarification_response.schema.json"
)
DEFAULT_PROFILE_SCHEMA = Path(
    "schema/project_profile.schema.json"
)
DEFAULT_MODEL = "gemini-2.5-flash"


def load_json(path: Path) -> dict[str, Any]:
    """ Load a JSON file and return its contents as a dict"""
    
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return value


def get_clarification_groups(
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """ Retrieve the list of clarification groups from the project profile metadata."""
    
    metadata = profile.get("extraction_metadata", {})
    groups = metadata.get("clarification_groups", [])

    if not isinstance(groups, list):
        raise TypeError(
            "extraction_metadata.clarification_groups "
            "must be an array."
        )

    return groups


def print_session_summary(
    profile: dict[str, Any],
) -> None:
    """ Print a summary of the clarification session, including remaining groups and
    unresolved fields."""
    
    project_profile = profile["project_profile"]
    metadata = profile["extraction_metadata"]

    remaining_groups = metadata.get(
        "clarification_groups",
        [],
    )
    unresolved_fields = metadata.get(
        "unresolved_fields",
        [],
    )

    print("\nClarification session complete.")
    print(
        f"Project: "
        f"{project_profile.get('project_name') or 'Unnamed project'}"
    )
    print(
        f"Remaining clarification groups: "
        f"{len(remaining_groups)}"
    )
    print(
        f"Remaining unresolved fields: "
        f"{len(unresolved_fields)}"
    )

    if unresolved_fields:
        print("\nFields still unresolved:")

        for record in unresolved_fields:
            field = record.get("field", "<unknown>")
            reason = record.get(
                "reason",
                "No reason recorded.",
            )
            print(f"- {field}: {reason}")


def run_session(
    profile_path: Path,
    output_path: Path,
    response_schema_path: Path,
    profile_schema_path: Path,
    model: str,
) -> None:
    """ Run an interactive clarification session for a project profile,
    allowing the user to answer questions and update the profile"""
    
    working_path = output_path

    if profile_path.resolve() != output_path.resolve():
        initial_profile = load_json(profile_path)

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_text(
            json.dumps(
                initial_profile,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    print("\nProject-profile clarification session")
    print("Type your answer and press Enter.")
    print("Commands:")
    print("  /skip   Leave this group unresolved for now")
    print("  /status Show remaining groups")
    print("  /exit   Save progress and stop the session")

    while True:
        profile = load_json(working_path)
        groups = get_clarification_groups(profile)

        if not groups:
            print_session_summary(profile)
            return

        group = groups[0]
        group_id = group["group_id"]
        question = group["question"]
        resolves_fields = group["resolves_fields"]

        print("\n" + "=" * 72)
        print(f"Group: {group_id}")
        print(f"Question: {question}")
        print(
            "Fields this question may resolve: "
            + ", ".join(resolves_fields)
        )

        try:
            answer = input("\nYour answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession stopped. Progress was saved.")
            return

        if not answer:
            print(
                "Please enter an answer or use "
                "/skip, /status, or /exit."
            )
            continue

        if answer == "/exit":
            print("Session stopped. Progress was saved.")
            return

        if answer == "/status":
            print(
                f"Remaining clarification groups: "
                f"{len(groups)}"
            )

            for remaining_group in groups:
                print(
                    f"- {remaining_group['group_id']}: "
                    f"{remaining_group['resolves_fields']}"
                )

            continue

        if answer == "/skip":
            skipped_group = groups.pop(0)
            groups.append(skipped_group)

            profile["extraction_metadata"][
                "clarification_groups"
            ] = groups

            working_path.write_text(
                json.dumps(
                    profile,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            print(
                "Skipped for now. The group was moved "
                "to the end of the queue."
            )
            continue

        temporary_path = working_path.with_suffix(
            ".processing.json"
        )

        try:
            process_clarification(
                profile_path=working_path,
                output_path=temporary_path,
                group_id=group_id,
                user_answer=answer,
                response_schema_path=response_schema_path,
                profile_schema_path=profile_schema_path,
                model=model,
            )

            temporary_path.replace(working_path)

        except Exception as error:
            if temporary_path.exists():
                temporary_path.unlink()

            print(
                f"Could not process the answer: {error}",
                file=sys.stderr,
            )
            print(
                "The current profile was not changed. "
                "Please try again or use /skip."
            )
            continue


def parse_arguments() -> argparse.Namespace:
    """ Parse command-line args for clarification session tool."""
    
    parser = argparse.ArgumentParser(
        description=(
            "Run an interactive clarification session for "
            "a generated project profile."
        )
    )

    parser.add_argument(
        "profile",
        type=Path,
        help="Input generated project-profile JSON file.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Working profile path where progress is saved.",
    )
    parser.add_argument(
        "--response-schema",
        type=Path,
        default=DEFAULT_RESPONSE_SCHEMA,
    )
    parser.add_argument(
        "--profile-schema",
        type=Path,
        default=DEFAULT_PROFILE_SCHEMA,
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
    args = parse_arguments()

    try:
        run_session(
            profile_path=args.profile,
            output_path=args.output,
            response_schema_path=args.response_schema,
            profile_schema_path=args.profile_schema,
            model=args.model,
        )
    except Exception as error:
        print(
            f"Clarification session failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()