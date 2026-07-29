import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator


DEFAULT_RESPONSE_SCHEMA = Path(
    "schema/clarification_response.schema.json"
)
DEFAULT_PROFILE_SCHEMA = Path(
    "schema/project_profile.schema.json"
)
DEFAULT_MODEL = "gemini-2.5-flash"

# Load JSON schemas for validation
def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return value


def prepare_generation_schema(
    schema: dict[str, Any],
) -> dict[str, Any]:
    """ Remove JSON Schema metadata that is useful for local validation but
    unnecessary for Gemini structured output."""
    
    generation_schema = deepcopy(schema)
    generation_schema.pop("$schema", None)
    generation_schema.pop("$id", None)
    return generation_schema


def find_clarification_group(
    profile: dict[str, Any],
    group_id: str,
) -> dict[str, Any]:
    """ Find clarification group in project profile metadata by group_id"""
    
    metadata = profile.get("extraction_metadata", {})
    groups = metadata.get("clarification_groups", [])

    for group in groups:
        if group.get("group_id") == group_id:
            return group

    available = [
        group.get("group_id")
        for group in groups
        if group.get("group_id")
    ]

    raise ValueError(
        f"Clarification group not found: {group_id}. "
        f"Available groups: {available}"
    )


def build_prompt(
    group: dict[str, Any],
    user_answer: str,
    current_values: dict[str, Any],
) -> str:
    allowed_fields = group["resolves_fields"]
    
    """ Build a prompt for the model to process a user's clarification answer
    and update the project profile fields accordingly."""

    return f"""
You are processing a user's answer to one project-profile clarification
question.

Clarification group ID:
{group["group_id"]}

Question shown to the user:
{group["question"]}

Fields this answer is allowed to resolve:
{json.dumps(allowed_fields, indent=2)}

Current field values:
{json.dumps(current_values, indent=2)}

User answer:
--- BEGIN USER ANSWER ---
{user_answer}
--- END USER ANSWER ---

Follow these rules strictly:

1. Update only fields listed in the allowed-fields list.
2. Do not return any field outside that list.
3. Interpret each field separately. Do not apply one yes/no value to every
   field merely because they appeared in one grouped question.
4. Use only information stated or clearly implied by the user's answer.
5. Include a field in field_updates only when the user's answer resolves it
   to a non-null value.
6. Do not include unresolved fields in field_updates.
7. Put every allowed field that remains unresolved in unresolved_fields.
8. Do not overwrite a resolved current value unless the user clearly corrects
   or replaces it.
9. Distinguish open-source software from open-source, pretrained, third-party,
   or foundation models.
10. Using an open-source software library does not mean the project uses a
   third-party model.
11. If the user says they do not know, leave the relevant field unresolved.
12. answer_summary must faithfully summarize the user's answer without adding
    unsupported claims.
13. Return only the structured response required by the supplied schema.
""".strip()


def validate_json(
    value: dict[str, Any],
    schema: dict[str, Any],
    label: str,
) -> None:
    
    """ Validate a JSON object against a JSON schema"""
    
    validator = Draft202012Validator(schema)

    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )

    if not errors:
        return

    messages: list[str] = []

    for error in errors:
        location = ".".join(
            str(part) for part in error.absolute_path
        )
        location = location or "<root>"
        messages.append(f"{location}: {error.message}")

    raise ValueError(
        f"{label} failed schema validation:\n- "
        + "\n- ".join(messages)
    )


def validate_update_scope(
    clarification: dict[str, Any],
    group: dict[str, Any],
) -> None:
    
    """ Validate that model's clarification response only updates fields
    allowed by the clarification group and does not attempt to update other fields."""
    
    expected_group_id = group["group_id"]
    returned_group_id = clarification["group_id"]

    if returned_group_id != expected_group_id:
        raise ValueError(
            "The returned group_id does not match the requested group. "
            f"Expected {expected_group_id!r}, got {returned_group_id!r}."
        )

    allowed_fields = set(group["resolves_fields"])
    updated_fields = set(clarification["field_updates"])
    unresolved_fields = set(clarification["unresolved_fields"])

    disallowed_updates = updated_fields - allowed_fields
    disallowed_unresolved = unresolved_fields - allowed_fields

    if disallowed_updates:
        raise ValueError(
            "The model attempted to update fields outside the "
            f"clarification group: {sorted(disallowed_updates)}"
        )

    if disallowed_unresolved:
        raise ValueError(
            "The model returned unresolved fields outside the "
            f"clarification group: {sorted(disallowed_unresolved)}"
        )

    overlap = updated_fields & unresolved_fields

    if overlap:
        raise ValueError(
            "Fields cannot be both updated and unresolved: "
            f"{sorted(overlap)}"
        )


def generate_clarification_result(
    client: genai.Client,
    model: str,
    response_schema: dict[str, Any],
    group: dict[str, Any],
    user_answer: str,
    current_values: dict[str, Any],
) -> dict[str, Any]:
    
    """ Generate a structured clarification response from the model based on the
    user's answer and the current project profile values."""
    
    prompt = build_prompt(
        group=group,
        user_answer=user_answer,
        current_values=current_values,
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=prepare_generation_schema(
                response_schema
            ),
            temperature=0.1,
        ),
    )

    if response.parsed is not None:
        result = response.parsed
    elif response.text:
        result = json.loads(response.text)
    else:
        raise RuntimeError(
            "The model returned no clarification result."
        )

    if not isinstance(result, dict):
        raise TypeError(
            "The clarification result must be a JSON object."
        )

    return result


def make_user_evidence(
    group_id: str,
    user_answer: str,
) -> dict[str, str]: 
    """ Create an evidence item representing the user's answer to a clarification question."""
    
    return {
        "document_id": f"clarification:{group_id}",
        "excerpt": user_answer.strip(),
    }


def update_unresolved_records(
    metadata: dict[str, Any],
    group: dict[str, Any],
    still_unresolved: set[str],
) -> None:
    """ Update the list of unresolved field records in the project profile metadata."""
    
    group_fields = set(group["resolves_fields"])
    records = metadata.get("unresolved_fields", [])

    retained_records = [
        record
        for record in records
        if record.get("field") not in group_fields
        or record.get("field") in still_unresolved
    ]

    metadata["unresolved_fields"] = retained_records


def update_clarification_groups(
    metadata: dict[str, Any],
    group: dict[str, Any],
    still_unresolved: set[str],
) -> None:
    """ Update the clarification groups in the project profile metadata to reflect
    any fields that remain unresolved after processing the user's answer."""
    
    updated_groups: list[dict[str, Any]] = []

    for existing_group in metadata.get(
        "clarification_groups",
        [],
    ):
        if existing_group.get("group_id") != group["group_id"]:
            updated_groups.append(existing_group)
            continue

        if still_unresolved:
            remaining_group = deepcopy(existing_group)
            remaining_group["resolves_fields"] = [
                field
                for field in existing_group["resolves_fields"]
                if field in still_unresolved
            ]
            updated_groups.append(remaining_group)

    metadata["clarification_groups"] = updated_groups


def merge_clarification_result(
    profile: dict[str, Any],
    group: dict[str, Any],
    clarification: dict[str, Any],
    user_answer: str,
) -> dict[str, Any]:
    """ Merge the model's clarification result into the project profile, updating
    field values, metadata, and unresolved records."""
    
    updated_profile = deepcopy(profile)

    project_profile = updated_profile["project_profile"]
    metadata = updated_profile["extraction_metadata"]

    field_updates = clarification["field_updates"]
    still_unresolved = set(clarification["unresolved_fields"])
    evidence = make_user_evidence(
        group_id=group["group_id"],
        user_answer=user_answer,
    )

    for field, value in field_updates.items():
        
        project_profile[field] = value

        metadata.setdefault(
            "field_evidence",
            {},
        ).setdefault(field, []).append(evidence)

        metadata.setdefault(
            "field_confidence",
            {},
        )[field] = 1.0

        # The value was directly supplied by the project representative.
        # The current schema supports explicit, inferred, and unresolved.
        metadata.setdefault(
            "field_status",
            {},
        )[field] = "explicit"

    for field in still_unresolved:
        metadata.setdefault(
            "field_confidence",
            {},
        )[field] = 0.0

        metadata.setdefault(
            "field_status",
            {},
        )[field] = "unresolved"

    metadata.setdefault(
        "clarification_history",
        [],
    ).append(
        {
            "group_id": group["group_id"],
            "question": group["question"],
            "user_answer": user_answer.strip(),
            "answer_summary": clarification["answer_summary"],
            "field_updates": field_updates,
            "unresolved_fields": sorted(still_unresolved),
        }
    )

    update_unresolved_records(
        metadata=metadata,
        group=group,
        still_unresolved=still_unresolved,
    )

    update_clarification_groups(
        metadata=metadata,
        group=group,
        still_unresolved=still_unresolved,
    )

    return updated_profile


def process_clarification(
    profile_path: Path,
    output_path: Path,
    group_id: str,
    user_answer: str,
    response_schema_path: Path,
    profile_schema_path: Path,
    model: str,
) -> None:
    profile = load_json(profile_path)
    response_schema = load_json(response_schema_path)
    profile_schema = load_json(profile_schema_path)

    validate_json(
        value=profile,
        schema=profile_schema,
        label="Input project profile",
    )

    group = find_clarification_group(
        profile=profile,
        group_id=group_id,
    )

    project_profile = profile["project_profile"]

    current_values = {
        field: project_profile.get(field)
        for field in group["resolves_fields"]
    }

    client = genai.Client()

    clarification = generate_clarification_result(
        client=client,
        model=model,
        response_schema=response_schema,
        group=group,
        user_answer=user_answer,
        current_values=current_values,
    )

    validate_json(
        value=clarification,
        schema=response_schema,
        label="Clarification response",
    )

    validate_update_scope(
        clarification=clarification,
        group=group,
    )

    updated_profile = merge_clarification_result(
        profile=profile,
        group=group,
        clarification=clarification,
        user_answer=user_answer,
    )

    validate_json(
        value=updated_profile,
        schema=profile_schema,
        label="Updated project profile",
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            updated_profile,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Processed group: {group_id}")
    print(
        "Updated fields: "
        f"{sorted(clarification['field_updates'])}"
    )
    print(
        "Still unresolved: "
        f"{sorted(clarification['unresolved_fields'])}"
    )
    print(f"Saved updated profile: {output_path}")


def parse_arguments() -> argparse.Namespace:
    """ Parse command-line args for the clarification response tool."""
    
    parser = argparse.ArgumentParser(
        description=(
            "Process one clarification answer and merge validated "
            "field updates into a generated project profile."
        )
    )

    parser.add_argument(
        "profile",
        type=Path,
        help="Path to the generated project-profile JSON file.",
    )
    parser.add_argument(
        "group_id",
        help="Clarification group ID to process.",
    )
    parser.add_argument(
        "answer",
        help="The user's answer to the clarification question.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Path where the updated profile will be saved.",
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
    load_dotenv()
    args = parse_arguments()

    try:
        process_clarification(
            profile_path=args.profile,
            output_path=args.output,
            group_id=args.group_id,
            user_answer=args.answer,
            response_schema_path=args.response_schema,
            profile_schema_path=args.profile_schema,
            model=args.model,
        )
    except Exception as error:
        print(
            f"Clarification processing failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()