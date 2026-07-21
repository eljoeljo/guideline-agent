"""Configuration constants for the Checklist Agent."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MODEL = os.getenv("CHECKLIST_MODEL", "gemini-2.5-flash")