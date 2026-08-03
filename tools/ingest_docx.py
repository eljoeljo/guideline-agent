import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from jsonschema import Draft202012Validator


DEFAULT_SCHEMA_PATH = Path("schema/ingested_document.schema.json")


def load_json(path: Path) -> dict[str, Any]:
    """ Load JSON file and return contents as a dict"""
    
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return value


def serialize_datetime(value: datetime | None) -> str | None:
    """ Serialize a datetime object to a string"""
    
    if value is None:
        return None

    return value.isoformat()


def make_document_id(path: Path) -> str:
    """ Make a normalized doc ID from the file name"""
    
    normalized = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        path.stem,
    ).strip("_")

    return normalized.lower() or "document"


def get_heading_level(style_name: str | None) -> int | None:
    """ Return the heading level from a style name"""
    
    if not style_name:
        return None

    match = re.match(
        r"Heading\s+(\d+)",
        style_name,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return int(match.group(1))


def classify_paragraph(
    paragraph: Paragraph,
    is_first_content_block: bool,
) -> tuple[str, int | None]:
    """ Identify the type of paragraph (heading, title, list item, normal paragraph)"""
    
    style_name = (
        paragraph.style.name
        if paragraph.style is not None
        else None
    )

    heading_level = get_heading_level(style_name)

    if heading_level is not None:
        return "heading", heading_level

    if style_name and style_name.lower() == "title":
        return "title", None

    if style_name and style_name.lower().startswith("list"):
        return "list_item", None

    if paragraph._p.pPr is not None:
        numbering = paragraph._p.pPr.numPr

        if numbering is not None:
            return "list_item", None

    if is_first_content_block and paragraph.text.strip():
        if style_name and "title" in style_name.lower():
            return "title", None

    return "paragraph", None


def normalize_paragraph_text(paragraph: Paragraph) -> str:
    """ Normalize paragraph text"""
    
    return " ".join(paragraph.text.split())


def normalize_table_text(table: Table) -> tuple[str, int, int]:
    """ Normalize text from a table"""
    
    rows: list[str] = []
    maximum_columns = 0

    for row in table.rows:
        cells = [
            " ".join(cell.text.split())
            for cell in row.cells
        ]

        maximum_columns = max(
            maximum_columns,
            len(cells),
        )

        rows.append(" | ".join(cells))

    return "\n".join(rows), len(table.rows), maximum_columns


def ingest_docx(source_path: Path) -> dict[str, Any]:
    """ Ingest DOCX file and return normalized document structure"""
    
    if source_path.suffix.lower() != ".docx":
        raise ValueError(
            f"Expected a .docx file, got: {source_path.suffix}"
        )

    document = Document(source_path)
    properties = document.core_properties

    blocks: list[dict[str, Any]] = []
    plain_text_parts: list[str] = []
    warnings: list[str] = []

    block_index = 0
    table_index = 0
    first_content_block = True

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = normalize_paragraph_text(item)

            if not text:
                continue

            block_type, heading_level = classify_paragraph(
                paragraph=item,
                is_first_content_block=first_content_block,
            )

            style_name = (
                item.style.name
                if item.style is not None
                else None
            )

            blocks.append(
                {
                    "block_id": f"block_{block_index}",
                    "block_type": block_type,
                    "text": text,
                    "location": {
                        "block_index": block_index,
                        "page": None,
                        "slide": None,
                        "table_index": None,
                    },
                    "metadata": {
                        "style": style_name,
                        "heading_level": heading_level,
                        "rows": None,
                        "columns": None,
                    },
                }
            )

            plain_text_parts.append(text)
            block_index += 1
            first_content_block = False
            continue

        if isinstance(item, Table):
            text, row_count, column_count = (
                normalize_table_text(item)
            )

            if not text.strip():
                warnings.append(
                    f"Skipped empty table at index {table_index}."
                )
                table_index += 1
                continue

            style_name = (
                item.style.name
                if item.style is not None
                else None
            )

            blocks.append(
                {
                    "block_id": f"block_{block_index}",
                    "block_type": "table",
                    "text": text,
                    "location": {
                        "block_index": block_index,
                        "page": None,
                        "slide": None,
                        "table_index": table_index,
                    },
                    "metadata": {
                        "style": style_name,
                        "heading_level": None,
                        "rows": row_count,
                        "columns": column_count,
                    },
                }
            )

            plain_text_parts.append(
                f"[Table {table_index + 1}]\n{text}"
            )

            block_index += 1
            table_index += 1
            first_content_block = False

    if not blocks:
        warnings.append(
            "No non-empty paragraphs or top-level tables were extracted."
        )

    title = properties.title.strip() if properties.title else None

    if title is None:
        for block in blocks:
            if block["block_type"] == "title":
                title = block["text"]
                break

    return {
        "document_id": make_document_id(source_path),
        "file_name": source_path.name,
        "file_type": "docx",
        "title": title,
        "metadata": {
            "author": (
                properties.author.strip()
                if properties.author
                else None
            ),
            "created": serialize_datetime(properties.created),
            "modified": serialize_datetime(properties.modified),
        },
        "blocks": blocks,
        "plain_text": "\n\n".join(plain_text_parts),
        "warnings": warnings,
    }


def validate_ingested_document(
    document: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    """ Validate ingested document against the provided JSON schema"""
    
    validator = Draft202012Validator(schema)

    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )

    if not errors:
        return

    messages: list[str] = []

    for error in errors:
        location = ".".join(
            str(part)
            for part in error.absolute_path
        )
        location = location or "<root>"
        messages.append(f"{location}: {error.message}")

    raise ValueError(
        "Ingested document failed schema validation:\n- "
        + "\n- ".join(messages)
    )


def write_ingested_document(
    document: dict[str, Any],
    output_path: Path,
) -> None:
    """ Write the ingested document to a JSON file"""
    
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            document,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_arguments() -> argparse.Namespace:
    """ Parse command-line args for DOCX ingestion tool"""
    
    parser = argparse.ArgumentParser(
        description=(
            "Extract ordered paragraphs and tables from a DOCX file "
            "into the normalized ingestion format."
        )
    )

    parser.add_argument(
        "source",
        type=Path,
        help="Path to the source DOCX file.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Path where the ingested JSON will be saved.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Schema path. Default: {DEFAULT_SCHEMA_PATH}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    try:
        if not args.source.exists():
            raise FileNotFoundError(
                f"Source file not found: {args.source}"
            )

        schema = load_json(args.schema)
        ingested_document = ingest_docx(args.source)

        validate_ingested_document(
            document=ingested_document,
            schema=schema,
        )

        write_ingested_document(
            document=ingested_document,
            output_path=args.output,
        )

        print(f"Ingested DOCX: {args.source}")
        print(
            f"Extracted blocks: "
            f"{len(ingested_document['blocks'])}"
        )
        print(
            f"Warnings: "
            f"{len(ingested_document['warnings'])}"
        )
        print(f"Saved normalized document: {args.output}")

    except Exception as error:
        print(
            f"DOCX ingestion failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()