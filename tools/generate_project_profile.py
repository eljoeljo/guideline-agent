import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator


DEFAULT_SCHEMA_PATH = Path("schema/project_profile.schema.json")
DEFAULT_MODEL = "gemini-2.5-flash"


def load_json(path: Path) -> dict[str, Any]:
    """ Reading JSON file and returning contents as a dictionary"""
    
    with path.open("r", encoding="utf-8") as file:
        
        return json.load(file)


def load_source_document(
    path: Path,
) -> tuple[str, str, str]:
    suffix = path.suffix.lower()

    if suffix == ".txt":
        text = path.read_text(
            encoding="utf-8",
        ).strip()

        if not text:
            raise ValueError(
                f"Source document is empty: {path}"
            )

        return text, path.stem, path.name

    if suffix == ".json":
        ingested = load_json(path)

        required_fields = {
            "document_id",
            "file_name",
            "plain_text",
        }

        missing_fields = (
            required_fields - set(ingested)
        )

        if missing_fields:
            raise ValueError(
                "Ingested document is missing required fields: "
                f"{sorted(missing_fields)}"
            )

        text = ingested["plain_text"]

        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "Ingested document plain_text is empty."
            )

        document_id = ingested["document_id"]
        file_name = ingested["file_name"]

        if not isinstance(document_id, str):
            raise TypeError(
                "document_id must be a string."
            )

        if not isinstance(file_name, str):
            raise TypeError(
                "file_name must be a string."
            )

        return (
            text.strip(),
            document_id,
            file_name,
        )

    raise ValueError(
        f"Unsupported source type: {suffix}. "
        "Expected .txt or normalized ingestion .json."
    )


def prepare_generation_schema(
    schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Remove JSON Schema metadata that is useful for local validation but
    unnecessary for Gemini structured output.
    """
    
    generation_schema = dict(schema)
    generation_schema.pop("$schema", None)
    return generation_schema


def build_prompt(
    document_text: str,
    document_id: str,
    file_name: str,
) -> str:
    return f"""
You are extracting a structured Responsible AI project profile from a project
document.

Follow these rules strictly:

1. Use only information supported by the document.
2. Do not interpret missing information as false.
3. Use null when a scalar field cannot be determined.
4. Use an empty array when no supported array values are available.
5. Mark field_status as:
   - explicit: directly stated in the document
   - inferred: strongly supported by multiple concrete details
   - unresolved: insufficient evidence
6. Every explicit or inferred field should include a short verbatim evidence
   excerpt where possible.
7. Do not claim that a project does not use a technology merely because that
   technology is not mentioned.
8. Add unresolved fields that materially affect Responsible AI applicability.
9. Each unresolved field must include one concise clarification question.
10. Keep confidence conservative:
    - explicit: generally 0.85 to 1.0
    - inferred: generally 0.50 to 0.84
    - unresolved: 0.0
11. Distinguish open-source software libraries from third-party or pretrained
    models.
12. Return only the structured response required by the supplied schema.
13. "Explicit" means the document directly states the field value.
    If a value is logically derived from other statements, mark it as
    "inferred", not "explicit".

14. Internal employees or analysts who operate the system do not
    automatically count as end users. Set interacts_with_end_users to true
    only when the system directly interacts with external users, clients,
    respondents, members of the public, or affected individuals.

15. A model producing a prediction does not automatically mean it makes or
    supports decisions. Set makes_or_supports_decisions to true only when the
    document describes a decision, action, recommendation, prioritization, or
    allocation that uses the model output.

16. "Trained from scratch" may support an inferred value of false for
    external pretrained or foundation model use, but it is not an explicit
    statement unless the document directly says those components are not used.

17. Do not create a clarification question for every unresolved technical
    subtype. Include only unresolved fields that could materially change
    checklist selection or applicability.

18. Prefer one broader clarification need when a single answer could resolve
    several closely related technical fields.

19. The phrase "predictions are used" is not sufficient evidence that the
system makes or supports decisions. A decision-related value requires a
described decision, action, recommendation, ranking, allocation, approval,
or operational outcome.

20. A project being in development or having intended users does not by
itself prove that deployment is planned. Set planned_for_deployment to true
only when the document mentions deployment, production, implementation,
rollout, operationalization, launch, or intended operational use.

21. The document summary must not introduce claims that are stronger than
the extracted evidence. It may summarize supported facts, but must not add
unstated purposes, decisions, risks, users, or deployment intentions.

22. Keep unresolved_fields at the individual field level for traceability.

23. Also produce clarification_groups for the questions that should actually
    be shown to the user.

24. Group closely related unresolved fields when one concise question can
    resolve them together.

25. Each clarification group must contain:
    - a stable snake_case group_id
    - one concise user-facing question
    - every field the answer is expected to resolve

26. Do not include fields in clarification_groups when they are already
    resolved as true or false.

27. Prefer approximately 4 to 8 clarification groups rather than one question
    per unresolved field.

28. Do not combine unrelated concepts merely to reduce the number of
    questions. A user must be able to answer each grouped question clearly.
    
29. Naming algorithms or model families does not prove that open-source
software is used. Set uses_open_source_software only when a library, tool,
license, repository, or open-source implementation is stated.

30. The phrase "internal datasets" does not prove that no third-party data
is used. It only establishes that at least some internal data is used.

31. A numeric output does not prove that the output cannot contain or be
linked to personal data. Consider identifiers, record-level linkage,
addresses, and output granularity.

32. Do not combine independent yes/no concepts in one clarification group.
If the user could reasonably answer one part yes and another part no,
create separate groups.

Source document metadata:
- document_id: {document_id}
- file_name: {file_name}

Document content:
--- BEGIN DOCUMENT ---
{document_text}
--- END DOCUMENT ---
""".strip()


def validate_generated_profile(
    profile: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    """ Validate generated project profile against the provided JSON schema."""
    
    validator = Draft202012Validator(schema)

    errors = sorted(
        validator.iter_errors(profile),
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
        "Generated profile failed schema validation:\n- "
        + "\n- ".join(messages)
    )


def generate_project_profile(
    source_path: Path,
    output_path: Path,
    schema_path: Path,
    model: str,
) -> None:
    """ Generate structured project profile from a text document using Gemini and validate it
    against the provided JSON schema."""
    
    schema = load_json(schema_path)
    
    (
    document_text,
    document_id,
    source_file_name,
    ) = load_source_document(source_path)
    
    
    
    prompt = build_prompt(
        document_text=document_text,
        document_id=document_id,
        file_name=source_file_name
    )

    client = genai.Client()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=prepare_generation_schema(schema),
            temperature=0.1,
        ),
    )

    if response.parsed is not None:
        profile = response.parsed
        
    elif response.text:
        profile = json.loads(response.text)
        
    else:
        raise RuntimeError("The model returned no project profile.")

    if not isinstance(profile, dict):
        raise TypeError("The generated profile must be a JSON object.")

    validate_generated_profile(profile, schema)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Generated valid project profile: {output_path}")


def parse_arguments() -> argparse.Namespace:
    """ Parse command-line arguments for the project profile generation tool."""
    
    parser = argparse.ArgumentParser(
        description=(
            "Generate a structured project profile from a text document."
        )
    )

    parser.add_argument(
        "source",
        type=Path,
        help="Path to the source .txt document or normalized ingested JSON file ",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Path where the generated profile will be saved.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Schema path. Default: {DEFAULT_SCHEMA_PATH}",
    )
    parser.add_argument(
        "--model",
        default=os.getenv(
            "PROJECT_PROFILE_MODEL",
            DEFAULT_MODEL,
        ),
        help=f"Gemini model. Default: {DEFAULT_MODEL}",
    )

    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_arguments()

    try:
        generate_project_profile(
            source_path=args.source,
            output_path=args.output,
            schema_path=args.schema,
            model=args.model,
        )
    except Exception as error:
        print(f"Profile generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()