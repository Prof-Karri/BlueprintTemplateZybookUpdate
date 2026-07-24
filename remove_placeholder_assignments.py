"""
zyBooks Canvas Automator - Placeholder Removal

Safely removes zyBooks placeholder assignments only after confirming that each
placeholder has exactly one matching imported assignment and that the imported
assignment is directly beneath the placeholder in the same Canvas module.

Matching uses:
- module number
- exact chapter, including any letter suffix
- assignment type (R&P or CA)

Default behavior is a dry run. Use --live only after reviewing the dry-run output:

    python remove_placeholder_assignments.py
    python remove_placeholder_assignments.py --live
"""

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from canvasapi import Canvas
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

CANVAS_URL = os.getenv("CANVAS_URL")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")
COURSE_ID_STR = os.getenv("COURSE_ID")

PLACEHOLDER_PATTERN = re.compile(r"\bplaceholder\b", re.IGNORECASE)
SUPPORTED_TITLE_PATTERN = re.compile(
    r"^\s*M(?P<module>\d+)\s+Ch(?P<chapter>\d+[A-Za-z]?)\s+"
    r"(?P<assignment_type>R\s*&\s*P|CA)\b",
    re.IGNORECASE,
)


@dataclass
class ModuleRecord:
    """Canvas module plus its currently retrieved module items."""

    module: Any
    items: list[Any] = field(default_factory=list)

    @property
    def id(self) -> int:
        return int(self.module.id)

    @property
    def name(self) -> str:
        return (getattr(self.module, "name", None) or f"Module {self.id}").strip()


@dataclass
class RemovalPlan:
    """One placeholder that has passed all safety checks."""

    match_key: str
    placeholder: Any
    imported_assignment: Any
    module_record: ModuleRecord
    placeholder_item: Any
    imported_item: Any

    @property
    def placeholder_name(self) -> str:
        return (getattr(self.placeholder, "name", None) or "").strip()

    @property
    def imported_name(self) -> str:
        return (getattr(self.imported_assignment, "name", None) or "").strip()


@dataclass
class Summary:
    """Final dry-run or live-run counters."""

    placeholders_found: int = 0
    safe_to_remove: int = 0
    removed: int = 0
    missing_imported_assignment: int = 0
    duplicate_placeholders: int = 0
    duplicate_imported_assignments: int = 0
    placeholder_not_in_module: int = 0
    placeholder_in_multiple_modules: int = 0
    imported_not_in_same_module: int = 0
    imported_in_multiple_modules: int = 0
    imported_not_directly_below: int = 0
    failed_removals: int = 0


def normalize_matching_title(title: str) -> str:
    """
    Return the canonical match key: module, exact chapter, and assignment type.

    Extra words and the word Placeholder are ignored. Letter suffixes remain
    significant, so Ch1a and Ch1b are separate keys.
    """
    match = SUPPORTED_TITLE_PATTERN.search(title or "")
    if not match:
        return ""

    module_number = int(match.group("module"))
    chapter = match.group("chapter").casefold()
    assignment_type = re.sub(
        r"\s+", "", match.group("assignment_type")
    ).casefold()

    return f"m{module_number} ch{chapter} {assignment_type}"


def is_placeholder_assignment(title: str) -> bool:
    """Return True when the title contains the standalone word Placeholder."""
    return bool(PLACEHOLDER_PATTERN.search(title or ""))


def is_supported_zybooks_title(title: str) -> bool:
    """Return True for a supported M# Ch#[suffix] R&P/CA assignment title."""
    return bool(SUPPORTED_TITLE_PATTERN.search(title or ""))


def validate_credentials() -> tuple[bool, str]:
    """Validate the required private Codespaces values."""
    missing = [
        name
        for name, value in (
            ("CANVAS_URL", CANVAS_URL),
            ("CANVAS_TOKEN", CANVAS_TOKEN),
            ("COURSE_ID", COURSE_ID_STR),
        )
        if not value
    ]

    if missing:
        return False, f"Missing required value(s): {', '.join(missing)}."

    try:
        int(str(COURSE_ID_STR))
    except (TypeError, ValueError):
        return False, f"COURSE_ID must be numeric, but received '{COURSE_ID_STR}'."

    return True, ""


def get_course_and_assignments():
    """Connect to Canvas and retrieve the course and its assignments."""
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)

    try:
        course = canvas.get_course(int(str(COURSE_ID_STR)))
        course_name = getattr(course, "name", None) or f"Course {COURSE_ID_STR}"
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Canvas course {COURSE_ID_STR}: {exc}"
        ) from exc

    try:
        assignments = list(course.get_assignments())
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve course assignments: {exc}") from exc

    return course, course_name, assignments


def get_modules_with_items(course) -> list[ModuleRecord]:
    """Retrieve every module and its module items in Canvas order."""
    try:
        modules = list(course.get_modules())
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve course modules: {exc}") from exc

    records: list[ModuleRecord] = []

    for module in modules:
        try:
            items = list(module.get_module_items())
        except Exception as exc:
            module_name = getattr(module, "name", None) or f"Module {module.id}"
            raise RuntimeError(
                f"Could not retrieve items for module '{module_name}': {exc}"
            ) from exc

        items.sort(key=lambda item: int(getattr(item, "position", 0) or 0))
        records.append(ModuleRecord(module=module, items=items))

    return records


def index_assignments(assignments):
    """Index placeholders and imported assignments by their normalized title."""
    placeholders: dict[str, list[Any]] = defaultdict(list)
    imported: dict[str, list[Any]] = defaultdict(list)

    for assignment in assignments:
        title = (getattr(assignment, "name", None) or "").strip()

        if not is_supported_zybooks_title(title):
            continue

        key = normalize_matching_title(title)
        if not key:
            continue

        if is_placeholder_assignment(title):
            placeholders[key].append(assignment)
        else:
            imported[key].append(assignment)

    return dict(placeholders), dict(imported)


def index_assignment_module_items(
    module_records: list[ModuleRecord],
) -> dict[int, list[tuple[ModuleRecord, Any]]]:
    """Map each assignment ID to all module items where it appears."""
    item_index: dict[int, list[tuple[ModuleRecord, Any]]] = defaultdict(list)

    for module_record in module_records:
        for item in module_record.items:
            if (getattr(item, "type", None) or "").casefold() != "assignment":
                continue

            content_id = getattr(item, "content_id", None)
            if content_id is None:
                continue

            try:
                item_index[int(content_id)].append((module_record, item))
            except (TypeError, ValueError):
                continue

    return dict(item_index)


def build_removal_plans(
    placeholders: dict[str, list[Any]],
    imported: dict[str, list[Any]],
    module_item_index: dict[int, list[tuple[ModuleRecord, Any]]],
) -> tuple[list[RemovalPlan], Summary]:
    """
    Build removal plans only when every required safety condition is satisfied.
    """
    plans: list[RemovalPlan] = []
    summary = Summary(
        placeholders_found=sum(len(items) for items in placeholders.values())
    )

    for key in sorted(placeholders):
        placeholder_matches = placeholders[key]
        imported_matches = imported.get(key, [])

        if len(placeholder_matches) > 1:
            summary.duplicate_placeholders += 1
            print("\n⚠️  DUPLICATE PLACEHOLDERS")
            print(f"Match key: {key}")
            for item in placeholder_matches:
                print(f"  - {item.name} (assignment ID {item.id})")
            print("Skipping this match.")
            continue

        placeholder = placeholder_matches[0]

        if not imported_matches:
            summary.missing_imported_assignment += 1
            print("\n⚠️  MISSING IMPORTED ASSIGNMENT")
            print(f"Placeholder: {placeholder.name}")
            print("No matching non-placeholder assignment was found. Skipping.")
            continue

        if len(imported_matches) > 1:
            summary.duplicate_imported_assignments += 1
            print("\n⚠️  DUPLICATE IMPORTED ASSIGNMENTS")
            print(f"Placeholder: {placeholder.name}")
            for item in imported_matches:
                print(f"  - {item.name} (assignment ID {item.id})")
            print("Skipping this match.")
            continue

        imported_assignment = imported_matches[0]

        placeholder_locations = module_item_index.get(int(placeholder.id), [])
        imported_locations = module_item_index.get(int(imported_assignment.id), [])

        if not placeholder_locations:
            summary.placeholder_not_in_module += 1
            print("\n⚠️  PLACEHOLDER NOT IN A MODULE")
            print(f"Placeholder: {placeholder.name}")
            print("Skipping.")
            continue

        if len(placeholder_locations) > 1:
            summary.placeholder_in_multiple_modules += 1
            print("\n⚠️  PLACEHOLDER APPEARS IN MULTIPLE MODULES")
            print(f"Placeholder: {placeholder.name}")
            print("Skipping.")
            continue

        if len(imported_locations) > 1:
            summary.imported_in_multiple_modules += 1
            print("\n⚠️  IMPORTED ASSIGNMENT APPEARS IN MULTIPLE MODULES")
            print(f"Imported assignment: {imported_assignment.name}")
            print("Skipping.")
            continue

        if not imported_locations:
            summary.imported_not_in_same_module += 1
            print("\n⚠️  IMPORTED ASSIGNMENT NOT IN A MODULE")
            print(f"Imported assignment: {imported_assignment.name}")
            print("Skipping.")
            continue

        placeholder_module, placeholder_item = placeholder_locations[0]
        imported_module, imported_item = imported_locations[0]

        if placeholder_module.id != imported_module.id:
            summary.imported_not_in_same_module += 1
            print("\n⚠️  IMPORTED ASSIGNMENT IS IN A DIFFERENT MODULE")
            print(f"Placeholder: {placeholder.name}")
            print(f"Imported:    {imported_assignment.name}")
            print(f"Placeholder module: {placeholder_module.name}")
            print(f"Imported module:    {imported_module.name}")
            print("Skipping.")
            continue

        placeholder_position = int(getattr(placeholder_item, "position", 0) or 0)
        imported_position = int(getattr(imported_item, "position", 0) or 0)

        if imported_position != placeholder_position + 1:
            summary.imported_not_directly_below += 1
            print("\n⚠️  IMPORTED ASSIGNMENT IS NOT DIRECTLY BELOW THE PLACEHOLDER")
            print(f"Module:      {placeholder_module.name}")
            print(f"Placeholder: {placeholder.name} (position {placeholder_position})")
            print(f"Imported:    {imported_assignment.name} (position {imported_position})")
            print("Skipping.")
            continue

        plans.append(
            RemovalPlan(
                match_key=key,
                placeholder=placeholder,
                imported_assignment=imported_assignment,
                module_record=placeholder_module,
                placeholder_item=placeholder_item,
                imported_item=imported_item,
            )
        )
        summary.safe_to_remove += 1

    return plans, summary


def print_plan(plan: RemovalPlan, is_live: bool) -> None:
    """Display one validated placeholder-removal plan."""
    placeholder_position = int(
        getattr(plan.placeholder_item, "position", 0) or 0
    )
    imported_position = int(
        getattr(plan.imported_item, "position", 0) or 0
    )

    print("\n----------------------------------------------------------")
    print(f"Placeholder:          {plan.placeholder_name}")
    print(f"Replacement:          {plan.imported_name}")
    print(f"Module:               {plan.module_record.name}")
    print(f"Placeholder position: {placeholder_position}")
    print(f"Replacement position: {imported_position}")

    if is_live:
        print("Status:               🔴 Will permanently delete placeholder assignment.")
    else:
        print("Status:               🔍 [DRY RUN] Would delete placeholder assignment.")


def refresh_module_items(module_record: ModuleRecord) -> list[Any]:
    """Retrieve current module items immediately before a live deletion."""
    items = list(module_record.module.get_module_items())
    items.sort(key=lambda item: int(getattr(item, "position", 0) or 0))
    return items


def find_item_by_content_id(items: list[Any], assignment_id: int) -> list[Any]:
    """Find assignment module items with the requested Canvas assignment ID."""
    matches: list[Any] = []

    for item in items:
        if (getattr(item, "type", None) or "").casefold() != "assignment":
            continue

        try:
            if int(getattr(item, "content_id", -1)) == int(assignment_id):
                matches.append(item)
        except (TypeError, ValueError):
            continue

    return matches


def execute_live_removal(plan: RemovalPlan) -> tuple[bool, str]:
    """
    Revalidate placement, delete the placeholder assignment, and verify removal.

    Deleting the Canvas assignment also removes its associated module item.
    """
    try:
        current_items = refresh_module_items(plan.module_record)
    except Exception as exc:
        return False, f"Could not refresh module items: {exc}"

    placeholder_matches = find_item_by_content_id(
        current_items, int(plan.placeholder.id)
    )
    imported_matches = find_item_by_content_id(
        current_items, int(plan.imported_assignment.id)
    )

    if len(placeholder_matches) != 1:
        return (
            False,
            f"Expected one current placeholder module item, found {len(placeholder_matches)}.",
        )

    if len(imported_matches) != 1:
        return (
            False,
            f"Expected one current imported-assignment module item, found {len(imported_matches)}.",
        )

    placeholder_position = int(
        getattr(placeholder_matches[0], "position", 0) or 0
    )
    imported_position = int(
        getattr(imported_matches[0], "position", 0) or 0
    )

    if imported_position != placeholder_position + 1:
        return (
            False,
            "The imported assignment is no longer directly below the placeholder.",
        )

    try:
        plan.placeholder.delete()
    except Exception as exc:
        return False, f"Canvas assignment deletion failed: {exc}"

    try:
        verified_items = refresh_module_items(plan.module_record)
    except Exception as exc:
        return False, f"Placeholder was deleted, but module verification failed: {exc}"

    remaining_placeholder_items = find_item_by_content_id(
        verified_items, int(plan.placeholder.id)
    )
    remaining_imported_items = find_item_by_content_id(
        verified_items, int(plan.imported_assignment.id)
    )

    if remaining_placeholder_items:
        return False, "The placeholder module item still appears after deletion."

    if len(remaining_imported_items) != 1:
        return (
            False,
            "The replacement assignment was not found exactly once after deletion.",
        )

    return True, (
        f"Verified placeholder removal from {plan.module_record.name}; "
        "the replacement assignment remains in the module."
    )


def print_summary(summary: Summary, is_live: bool) -> None:
    """Print the final removal summary."""
    print("\n==========================================================")
    print("PLACEHOLDER REMOVAL SUMMARY")
    print("==========================================================")
    print(f"Placeholders found:                     {summary.placeholders_found}")
    print(f"Validated as safe to remove:            {summary.safe_to_remove}")
    print(
        f"{'Removed' if is_live else 'Would be removed'}:".ljust(41)
        + str(summary.removed if is_live else summary.safe_to_remove)
    )
    print(f"Missing imported assignments:           {summary.missing_imported_assignment}")
    print(f"Duplicate placeholders:                 {summary.duplicate_placeholders}")
    print(f"Duplicate imported assignments:         {summary.duplicate_imported_assignments}")
    print(f"Placeholders not in a module:           {summary.placeholder_not_in_module}")
    print(f"Placeholders in multiple modules:       {summary.placeholder_in_multiple_modules}")
    print(f"Imported assignment placement issues:   {summary.imported_not_in_same_module}")
    print(f"Imported assignments in multiple modules:{summary.imported_in_multiple_modules}")
    print(f"Not directly below placeholder:         {summary.imported_not_directly_below}")
    print(f"Failed removals:                         {summary.failed_removals}")
    print("==========================================================")


def remove_placeholders(is_live: bool) -> None:
    """Scan, validate, report, and optionally delete safe placeholders."""
    print("==========================================================")
    print("🗑️  ZYBOOKS PLACEHOLDER REMOVAL")
    print("==========================================================")
    print(f"Mode: {'🔴 LIVE' if is_live else '🟢 DRY RUN'}")

    credentials_valid, credentials_error = validate_credentials()
    if not credentials_valid:
        print(f"\n❌ Error: {credentials_error}")
        print("No Canvas changes were made.")
        return

    print("\n🔍 Connecting to Canvas and validating placeholder replacements...")

    try:
        course, course_name, assignments = get_course_and_assignments()
        module_records = get_modules_with_items(course)
    except RuntimeError as exc:
        print(f"\n❌ Course scan failed: {exc}")
        print("No Canvas changes were made.")
        return

    print(f"✅ Course: {course_name}")
    print(f"✅ Retrieved {len(assignments)} assignments.")
    print(f"✅ Retrieved {len(module_records)} modules and their current items.")

    placeholders, imported = index_assignments(assignments)
    module_item_index = index_assignment_module_items(module_records)

    plans, summary = build_removal_plans(
        placeholders=placeholders,
        imported=imported,
        module_item_index=module_item_index,
    )

    print("\n==========================================================")
    print("VALIDATED PLACEHOLDER REMOVAL PLAN")
    print("==========================================================")

    if not plans:
        print("No placeholders passed all safety checks.")

    for plan in plans:
        print_plan(plan, is_live=is_live)

    if not is_live:
        print_summary(summary, is_live=False)
        print("\nNo Canvas assignments were deleted during this dry run.")
        print("Review every skipped, duplicate, missing, and placement issue above.")
        print("\nTo permanently delete only the validated placeholders, run:")
        print("python remove_placeholder_assignments.py --live")
        return

    if not plans:
        print_summary(summary, is_live=True)
        print("\nNo placeholder assignments were safe to delete.")
        return

    print("\n==========================================================")
    print("PERMANENT DELETION WARNING")
    print("==========================================================")
    print("This live run will permanently delete the validated placeholder assignments.")
    print("Their matching imported assignments will remain in the modules.")
    confirmation = input(
        "\nType DELETE PLACEHOLDERS to continue: "
    ).strip()

    if confirmation != "DELETE PLACEHOLDERS":
        print("\nLive removal canceled. No placeholder assignments were deleted.")
        return

    print("\n==========================================================")
    print("REMOVING VALIDATED PLACEHOLDERS")
    print("==========================================================")

    for plan in plans:
        print(f"\n🗑️  Removing '{plan.placeholder_name}'...")
        success, message = execute_live_removal(plan)

        if success:
            print(f"✅ {message}")
            summary.removed += 1
        else:
            print(f"❌ {message}")
            summary.failed_removals += 1

    print_summary(summary, is_live=True)

    if summary.failed_removals:
        print("\n⚠️  Some removals failed. Review the errors and verify Canvas manually.")
    else:
        print("\n✅ All validated placeholders were removed and verified.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Safely remove zyBooks placeholder assignments only after confirming "
            "that each replacement is directly below its placeholder."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Permanently delete validated placeholder assignments.",
    )
    args = parser.parse_args()
    remove_placeholders(is_live=args.live)


if __name__ == "__main__":
    main()
