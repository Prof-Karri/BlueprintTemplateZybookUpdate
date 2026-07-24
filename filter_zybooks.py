"""
zyBooks Canvas Automator - Assignment Filter and Name Normalizer

Reads an exported Canvas course JSON file, asks which supported zyBooks naming
flow the course currently uses, previews title normalization, validates for
conflicts, and writes zybooks_data.json.

Supported naming flows:
1. Standard automation format
   M1 Ch1a R&P
   M1 Ch1b CA

2. Legacy Zy/PA format
   M1 Zy Ch1 PA  -> M1 Ch1a R&P
   M1 Zy Ch1 CA  -> M1 Ch1b CA

The original Canvas title is preserved in the output as original_name.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "zybooks_data.json"
INPUT_CANDIDATES = (
    SCRIPT_DIR / "canvas_course_content.json",
    SCRIPT_DIR / "CIS150_coursecontent.json",
)

STANDARD_PATTERN = re.compile(
    r"^\s*M(?P<module>\d+)\s+Ch(?P<chapter>\d+)(?P<suffix>[A-Za-z]?)\s+"
    r"(?P<assignment_type>R\s*&\s*P|CA)\b(?P<remainder>.*)$",
    re.IGNORECASE,
)

LEGACY_PATTERN = re.compile(
    r"^\s*M(?P<module>\d+)\s+Zy\s+Ch\s*(?P<chapter>\d+)\s+"
    r"(?P<assignment_type>PA|CA)\b(?P<remainder>.*)$",
    re.IGNORECASE,
)

def find_input_file() -> Path:
    """Return the first supported export filename found beside this script."""
    for candidate in INPUT_CANDIDATES:
        if candidate.exists():
            return candidate

    expected = " or ".join(path.name for path in INPUT_CANDIDATES)
    raise FileNotFoundError(
        f"Could not find {expected} in {SCRIPT_DIR}. Run the Canvas export first."
    )


def get_assignments(export_data: Any) -> list[dict[str, Any]]:
    """Extract the assignment list from supported Canvas export structures."""
    if isinstance(export_data, dict):
        assignments = export_data.get("assignments", [])
    elif isinstance(export_data, list):
        assignments = export_data
    else:
        raise ValueError("The export JSON must contain an object or a list.")

    if not isinstance(assignments, list):
        raise ValueError("The export JSON 'assignments' value is not a list.")

    return [item for item in assignments if isinstance(item, dict)]


def detect_profile_counts(assignments: list[dict[str, Any]]) -> Counter:
    """Count assignments matching each supported naming profile."""
    counts: Counter = Counter()

    for assignment in assignments:
        name = str(assignment.get("name") or "")
        if STANDARD_PATTERN.match(name):
            counts["standard"] += 1
        if LEGACY_PATTERN.match(name):
            counts["legacy"] += 1

    return counts


def choose_naming_profile(assignments: list[dict[str, Any]]) -> str:
    """Ask the user which current course naming flow should be normalized."""
    counts = detect_profile_counts(assignments)

    print("==========================================================")
    print("📘 ZYBOOKS ASSIGNMENT FILTER AND NAME NORMALIZER")
    print("==========================================================")
    print("\nSupported current naming flows:")
    print("1. Standard automation format")
    print("   M1 Ch1a R&P / M1 Ch1b CA")
    print(f"   Recognized in export: {counts['standard']}")
    print("\n2. Legacy Zy/PA format")
    print("   M1 Zy Ch1 PA / M1 Zy Ch1 CA")
    print(f"   Recognized in export: {counts['legacy']}")

    if counts["standard"] and not counts["legacy"]:
        suggested = "1"
    elif counts["legacy"] and not counts["standard"]:
        suggested = "2"
    else:
        suggested = ""

    while True:
        prompt = "\nEnter 1 or 2"
        if suggested:
            prompt += f" (press Enter to use detected option {suggested})"
        choice = input(f"{prompt}: ").strip() or suggested

        if choice == "1":
            return "standard"
        if choice == "2":
            return "legacy"

        print("❌ Please enter 1 or 2.")


def normalize_standard_name(name: str) -> str | None:
    """Return a consistently formatted standard title, preserving extra text."""
    match = STANDARD_PATTERN.match(name)
    if not match:
        return None

    module_number = int(match.group("module"))
    chapter_number = int(match.group("chapter"))
    suffix = match.group("suffix").lower()
    assignment_type_raw = re.sub(r"\s+", "", match.group("assignment_type")).upper()
    assignment_type = "R&P" if assignment_type_raw == "R&P" else "CA"
    remainder = match.group("remainder").strip()

    normalized = f"M{module_number} Ch{chapter_number}{suffix} {assignment_type}"
    if remainder:
        normalized += f" {remainder}"
    return normalized


def normalize_legacy_name(name: str) -> str | None:
    """Convert M# Zy Ch# PA/CA titles into the standard a/b naming format."""
    match = LEGACY_PATTERN.match(name)
    if not match:
        return None

    module_number = int(match.group("module"))
    chapter_number = int(match.group("chapter"))
    legacy_type = match.group("assignment_type").upper()
    remainder = match.group("remainder").strip()

    if legacy_type == "PA":
        suffix = "a"
        assignment_type = "R&P"
    else:
        suffix = "b"
        assignment_type = "CA"

    normalized = f"M{module_number} Ch{chapter_number}{suffix} {assignment_type}"
    if remainder:
        normalized += f" {remainder}"
    return normalized


def looks_like_possible_zybooks(name: str) -> bool:
    """Identify titles worth reporting when they do not match the selected flow."""
    lowered = name.casefold()
    return bool(
        re.search(r"\bm\d+\b", lowered)
        and ("ch" in lowered or "chapter" in lowered)
        and any(token in lowered for token in ("r&p", "r & p", " pa", "ca"))
    )


def build_filtered_records(
    assignments: list[dict[str, Any]], profile: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize matching assignments and collect likely unrecognized titles."""
    normalizer = normalize_standard_name if profile == "standard" else normalize_legacy_name
    records: list[dict[str, Any]] = []
    unrecognized: list[str] = []

    for assignment in assignments:
        original_name = str(assignment.get("name") or "").strip()
        normalized_name = normalizer(original_name)

        if normalized_name is None:
            if looks_like_possible_zybooks(original_name):
                unrecognized.append(original_name)
            continue

        records.append(
            {
                "id": assignment.get("id"),
                "original_name": original_name,
                "name": normalized_name,
                "html_url": assignment.get("html_url", ""),
                "description": assignment.get("description", ""),
                "points_possible": assignment.get("points_possible", 0),
            }
        )

    return records, unrecognized


def find_duplicate_normalized_titles(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return normalized titles produced by more than one original assignment."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        grouped[str(record["name"]).casefold()].append(str(record["original_name"]))

    return {
        str(records_by_name[0] if False else key): originals
        for key, originals in grouped.items()
        if len(originals) > 1
    }


def print_preview(records: list[dict[str, Any]], profile: str) -> None:
    """Display every original and normalized assignment title."""
    print("\n==========================================================")
    print("NORMALIZATION PREVIEW")
    print("==========================================================")
    print(f"Selected profile: {'Standard automation' if profile == 'standard' else 'Legacy Zy/PA'}")

    for record in records:
        original = str(record["original_name"])
        normalized = str(record["name"])
        print(f"\nCurrent: {original}")
        print(f"New:     {normalized}")

    print("\n==========================================================")
    print(f"Assignments matched: {len(records)}")
    print("==========================================================")


def validate_records(records: list[dict[str, Any]]) -> list[str]:
    """Return blocking validation errors."""
    errors: list[str] = []

    if not records:
        errors.append("No assignments matched the selected naming flow.")

    missing_ids = [record["original_name"] for record in records if not record.get("id")]
    if missing_ids:
        errors.append(
            "The following matched assignments do not have Canvas IDs: "
            + ", ".join(str(name) for name in missing_ids)
        )

    grouped: dict[str, list[str]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for record in records:
        key = str(record["name"]).casefold()
        grouped[key].append(str(record["original_name"]))
        display_names[key] = str(record["name"])

    for key, originals in grouped.items():
        if len(originals) > 1:
            errors.append(
                f"Multiple assignments would become '{display_names[key]}': "
                + " | ".join(originals)
            )

    return errors


def confirm_write() -> bool:
    """Require explicit confirmation before creating the normalized JSON."""
    while True:
        value = input("\nCreate zybooks_data.json with these titles? (Y/N): ").strip().casefold()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("❌ Please enter Y or N.")


def filter_zybooks() -> None:
    try:
        input_file = find_input_file()
        with input_file.open("r", encoding="utf-8") as file:
            export_data = json.load(file)

        assignments = get_assignments(export_data)
        print(f"Found {len(assignments)} total assignments in {input_file.name}.")

        profile = choose_naming_profile(assignments)
        records, unrecognized = build_filtered_records(assignments, profile)
        print_preview(records, profile)

        errors = validate_records(records)
        if errors:
            print("\n❌ Validation failed. No output file was created.")
            for error in errors:
                print(f"- {error}")
            return

        if unrecognized:
            print("\n⚠️  Possible zyBooks titles not recognized by the selected flow:")
            for name in unrecognized:
                print(f"- {name}")
            print("These assignments will not be included in zybooks_data.json.")

        if not confirm_write():
            print("\nCanceled. No output file was created.")
            return

        with OUTPUT_FILE.open("w", encoding="utf-8") as file:
            json.dump(records, file, indent=4, ensure_ascii=False)

        print(f"\n✅ Success! Prepared {len(records)} zyBooks assignments.")
        print(f"📂 Normalized data saved to: {OUTPUT_FILE}")
        print("The original assignment names are preserved in original_name.")

    except FileNotFoundError as exc:
        print(f"❌ Error: {exc}")
    except json.JSONDecodeError as exc:
        print(f"❌ Error: The export file contains invalid JSON: {exc}")
    except (OSError, ValueError) as exc:
        print(f"❌ Error: {exc}")
    except KeyboardInterrupt:
        print("\nCanceled by user. No output file was created.")


if __name__ == "__main__":
    filter_zybooks()
