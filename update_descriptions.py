"""
zyBooks Canvas Automator - Placeholder Preparation

Reads the normalized zybooks_data.json created by filter_zybooks.py, adds the
Placeholder suffix, preserves M1 template descriptions, clears descriptions for
all other matched assignments, and creates zybooks_ready_to_upload.json.
"""

import json
import re
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_FILE = SCRIPT_DIR / "zybooks_data.json"
OUTPUT_FILE = SCRIPT_DIR / "zybooks_ready_to_upload.json"

MODULE_PATTERN = re.compile(r"^\s*M(?P<module>\d+)\b", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\bplaceholder\b", re.IGNORECASE)


def add_placeholder_suffix(name: str) -> str:
    """Add the standard placeholder suffix exactly once."""
    cleaned = name.strip()
    if PLACEHOLDER_PATTERN.search(cleaned):
        return cleaned
    return f"{cleaned} - Placeholder"


def get_module_number(name: str) -> int | None:
    """Return the module number from a normalized assignment title."""
    match = MODULE_PATTERN.match(name)
    if not match:
        return None
    return int(match.group("module"))


def load_assignments() -> list[dict[str, Any]]:
    """Load and validate the normalized assignment records."""
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Could not find {INPUT_FILE.name}. Run filter_zybooks.py first."
        )

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        assignments = json.load(file)

    if not isinstance(assignments, list):
        raise ValueError(f"{INPUT_FILE.name} must contain a JSON list.")

    return [item for item in assignments if isinstance(item, dict)]


def prepare_placeholders() -> None:
    try:
        assignments = load_assignments()
        prepared: list[dict[str, Any]] = []
        descriptions_cleared = 0
        descriptions_preserved = 0

        print("==========================================================")
        print("🧩 ZYBOOKS PLACEHOLDER PREPARATION")
        print("==========================================================")

        for assignment in assignments:
            original_name = str(assignment.get("original_name") or assignment.get("name") or "")
            normalized_name = str(assignment.get("name") or "").strip()
            module_number = get_module_number(normalized_name)

            if not normalized_name or module_number is None:
                raise ValueError(
                    f"Cannot determine the module from normalized title '{normalized_name}'."
                )

            placeholder_name = add_placeholder_suffix(normalized_name)
            assignment["name"] = placeholder_name

            if module_number == 1:
                descriptions_preserved += 1
                description_action = "PRESERVE M1 DESCRIPTION"
            else:
                assignment["description"] = ""
                descriptions_cleared += 1
                description_action = "CLEAR DESCRIPTION"

            prepared.append(assignment)

            print(f"\nOriginal:    {original_name}")
            print(f"Placeholder: {placeholder_name}")
            print(f"Description: {description_action}")

        with OUTPUT_FILE.open("w", encoding="utf-8") as file:
            json.dump(prepared, file, indent=4, ensure_ascii=False)

        print("\n==========================================================")
        print("PLACEHOLDER PREPARATION SUMMARY")
        print("==========================================================")
        print(f"Assignments prepared:       {len(prepared)}")
        print(f"M1 descriptions preserved:  {descriptions_preserved}")
        print(f"Descriptions cleared:       {descriptions_cleared}")
        print(f"Output file:                {OUTPUT_FILE}")
        print("==========================================================")

    except FileNotFoundError as exc:
        print(f"❌ Error: {exc}")
    except json.JSONDecodeError as exc:
        print(f"❌ Error: {INPUT_FILE.name} contains invalid JSON: {exc}")
    except (OSError, ValueError) as exc:
        print(f"❌ Error: {exc}")


if __name__ == "__main__":
    prepare_placeholders()
