# AI Guidelines Question Database Schema

## Purpose

This database contains the 88 checklist rows from the Excel file

## Record fields

- `id`: Original two-digit checklist ID.
- `field`: Stable response key for JSON response storage.
- `lifecycle_phase`: High-level AI/ML lifecycle grouping.
- `lifecycle_stage`: More detailed stage text from the source.
- `cgp_code`: Core Guiding Principle abbreviation.
- `cgp_name`: Expanded Core Guiding Principle name.
- `question`: Original checklist wording, normalized only for whitespace/capitalization artifacts.
- `subquestions`: Extracted lettered prompts when the source row contains a/b/c components.
- `answer_type`: Initial UI/validation hint; this can be refined later.
- `choices`: Suggested choices for yes/no-style questions.
- `tags`: Initial keyword-derived retrieval labels.
- `applicability.status`: Starts as `unmapped`.
- `applicability.applies_if`: Reserved for deterministic applicability rules.
- `applicability.notes`: Guidance for the mapping stage.
- `source`: Traceability back to the Drive document and original question ID.
- `needs_review`: Flags missing source text or missing CGP metadata.

## Recommended next step

Create a canonical-project relevance map separately from this database. Do not overwrite the
source question records with housing-project-specific decisions. A separate evaluation file can
label each question as `ask`, `skip`, or `needs_clarification`, along with the expected reason.