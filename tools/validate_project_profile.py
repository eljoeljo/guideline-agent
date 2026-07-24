import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA_PATH = Path("schema/project_profile.schema.json")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_profile(profile_path: Path) -> bool:
    schema = load_json(SCHEMA_PATH)
    profile = load_json(profile_path)

    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(profile),
        key=lambda error: list(error.absolute_path),
    )

    if not errors:
        print(f"Valid project profile: {profile_path}")
        return True

    print(f"Invalid project profile: {profile_path}")

    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path)
        location = location or "<root>"
        print(f"- {location}: {error.message}")

    return False


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python tools/validate_project_profile.py "
            "<project-profile.json>"
        )
        raise SystemExit(2)

    profile_path = Path(sys.argv[1])
    
    # File existence check
    if not profile_path.exists():
        
        print(f"File not found: {profile_path}")
        raise SystemExit(2)

    is_valid = validate_profile(profile_path)
    raise SystemExit(0 if is_valid else 1)


if __name__ == "__main__":
    main()