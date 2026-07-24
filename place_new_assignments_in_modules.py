"""
zyBooks Canvas Automator - Module Placement

Places newly imported zyBooks assignments directly beneath their matching
placeholder assignments while preserving the existing Canvas module structure.

Matching uses the module number, exact chapter including any letter suffix,
and assignment type. Extra descriptive words and the word Placeholder are ignored.

Default behavior is a dry run. Use --live only after reviewing the dry-run
output:

    python place_new_assignments_in_modules.py
    python place_new_assignments_in_modules.py --live
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
    """Canvas module plus the module items captured during the course scan."""

    module: Any
    items: list[Any] = field(default_factory=list)

    @property
    def id(self) -> int:
        return int(self.module.id)

    @property
    def name(self) -> str:
        return (getattr(self.module, "name", None) or f"Module {self.id}").strip()


@dataclass
class PlacementPlan:
    """A validated placement action for one imported assignment."""

    match_key: str
    assignment: Any
    placeholder_assignment: Any
    placeholder_item: Any
    target_module: ModuleRecord
    assignment_items: list[tuple[ModuleRecord, Any]]
    target_position: int
    status: str
    reason: str = ""

    @property
    def assignment_name(self) -> str:
        return (getattr(self.assignment, "name", None) or "").strip()

    @property
    def placeholder_name(self) -> str:
        return (getattr(self.placeholder_assignment, "name", None) or "").strip()


@dataclass
class Summary:
    """Counters requested for the final script summary."""

    placeholders_found: int = 0
    new_assignments_matched: int = 0
    already_correct: int = 0
    moved_or_would_move: int = 0
    missing_placeholders: int = 0
    missing_new_assignments: int = 0
    ambiguous_matches: int = 0
    failed_moves: int = 0


def normalize_matching_title(title: str) -> str:
    """
    Return the canonical placement key: module, exact chapter, and type.

    Extra descriptive words and the word Placeholder are deliberately ignored.
    Chapter suffixes remain significant, so Ch1a and Ch1b never share a key.
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
    """Return True for an M# Ch#[suffix] R&P/CA title used by this workflow."""
    return bool(SUPPORTED_TITLE_PATTERN.search(title or ""))


def validate_credentials() -> tuple[bool, str]:
    """Validate required .env values before attempting a Canvas connection."""
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
        return False, f"Missing required .env value(s): {', '.join(missing)}."

    try:
        int(str(COURSE_ID_STR))
    except (TypeError, ValueError):
        return False, f"COURSE_ID must be numeric, but received '{COURSE_ID_STR}'."

    return True, ""


def get_course_and_assignments():
    """Connect to Canvas, validate the course, and retrieve all assignments."""
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)

    try:
        course = canvas.get_course(int(str(COURSE_ID_STR)))
        # Force a real API request so an invalid course or token is detected now.
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
    """Retrieve every module and its current items in Canvas order."""
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
    """
    Index placeholders and new assignments by the normalized full-title key.

    Duplicate objects remain in each list so they can be reported as ambiguous.
    """
    placeholders: dict[str, list[Any]] = defaultdict(list)
    new_assignments: dict[str, list[Any]] = defaultdict(list)

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
            new_assignments[key].append(assignment)

    return dict(placeholders), dict(new_assignments)



def print_matching_diagnostics(
    placeholders: dict[str, list[Any]],
    new_assignments: dict[str, list[Any]],
) -> None:
    """Print recognized matching keys so naming differences are visible."""
    placeholder_keys = set(placeholders)
    new_keys = set(new_assignments)
    shared_keys = sorted(placeholder_keys & new_keys)
    placeholder_only = sorted(placeholder_keys - new_keys)
    new_only = sorted(new_keys - placeholder_keys)

    print("\n==========================================================")
    print("TITLE MATCHING DIAGNOSTICS")
    print("==========================================================")
    print(f"Shared normalized keys:        {len(shared_keys)}")
    print(f"Placeholder-only keys:         {len(placeholder_only)}")
    print(f"Imported-assignment-only keys: {len(new_only)}")

    if shared_keys:
        print("\nKeys found in both sets:")
        for key in shared_keys:
            placeholder_names = " | ".join(
                (getattr(item, "name", None) or "").strip()
                for item in placeholders[key]
            )
            assignment_names = " | ".join(
                (getattr(item, "name", None) or "").strip()
                for item in new_assignments[key]
            )
            print(f"  {key}")
            print(f"    Placeholder: {placeholder_names}")
            print(f"    Imported:    {assignment_names}")

    if placeholder_only:
        print("\nPlaceholder keys with no imported match:")
        for key in placeholder_only:
            names = " | ".join(
                (getattr(item, "name", None) or "").strip()
                for item in placeholders[key]
            )
            print(f"  {key}  <--  {names}")

    if new_only:
        print("\nImported assignment keys with no placeholder match:")
        for key in new_only:
            names = " | ".join(
                (getattr(item, "name", None) or "").strip()
                for item in new_assignments[key]
            )
            print(f"  {key}  <--  {names}")

    print("==========================================================")

def index_assignment_module_items(
    module_records: list[ModuleRecord],
) -> dict[int, list[tuple[ModuleRecord, Any]]]:
    """Map each Canvas assignment ID to every module item where it appears."""
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


def describe_locations(
    locations: list[tuple[ModuleRecord, Any]],
) -> str:
    """Return a readable module-location description."""
    if not locations:
        return "Not currently in a module"

    descriptions = []
    for module_record, item in locations:
        position = getattr(item, "position", "?")
        descriptions.append(f"{module_record.name} (position {position})")
    return "; ".join(descriptions)


def print_plan(plan: PlacementPlan, is_live: bool) -> None:
    """Print all required placement details for a single assignment."""
    current_location = describe_locations(plan.assignment_items)
    action_label = "LIVE" if is_live else "DRY RUN"

    print("\n----------------------------------------------------------")
    print(f"New assignment:       {plan.assignment_name}")
    print(f"Matching placeholder: {plan.placeholder_name}")
    print(f"Current module:       {current_location}")
    print(f"Target module:        {plan.target_module.name}")
    print(f"Intended position:    {plan.target_position}")

    if plan.status == "already_correct":
        print("Status:               ✅ Already correctly placed; no change needed.")
    elif plan.status == "ready":
        verb = "Will place" if is_live else "Would place"
        print(
            f"Status:               {'🔴' if is_live else '🔍'} "
            f"[{action_label}] {verb} directly below the placeholder."
        )
    else:
        print(f"Status:               ⚠️  Cannot safely place: {plan.reason}")


def build_placement_plans(
    placeholders: dict[str, list[Any]],
    new_assignments: dict[str, list[Any]],
    module_records: list[ModuleRecord],
    assignment_item_index: dict[int, list[tuple[ModuleRecord, Any]]],
) -> tuple[list[PlacementPlan], Summary]:
    """Validate all title and module-item matches before any Canvas changes."""
    plans: list[PlacementPlan] = []
    summary = Summary(
        placeholders_found=sum(len(values) for values in placeholders.values())
    )

    all_keys = sorted(set(placeholders) | set(new_assignments))

    for key in all_keys:
        placeholder_matches = placeholders.get(key, [])
        new_matches = new_assignments.get(key, [])

        if len(placeholder_matches) > 1:
            summary.ambiguous_matches += 1
            names = ", ".join(
                f"'{getattr(item, 'name', '')}' (assignment ID {item.id})"
                for item in placeholder_matches
            )
            print("\n⚠️  DUPLICATE PLACEHOLDERS")
            print(f"Match key: {key}")
            print(f"Found: {names}")
            print("This match will be skipped.")
            continue

        if len(new_matches) > 1:
            summary.ambiguous_matches += 1
            names = ", ".join(
                f"'{getattr(item, 'name', '')}' (assignment ID {item.id})"
                for item in new_matches
            )
            print("\n⚠️  DUPLICATE IMPORTED ASSIGNMENTS")
            print(f"Match key: {key}")
            print(f"Found: {names}")
            print("This match will be skipped.")
            continue

        if not placeholder_matches and new_matches:
            summary.missing_placeholders += 1
            assignment = new_matches[0]
            locations = assignment_item_index.get(int(assignment.id), [])
            print("\n⚠️  MISSING PLACEHOLDER")
            print(f"New assignment: {assignment.name}")
            print(f"Current module: {describe_locations(locations)}")
            print("No matching placeholder assignment was found. Skipping.")
            continue

        if placeholder_matches and not new_matches:
            summary.missing_new_assignments += 1
            placeholder = placeholder_matches[0]
            print("\n⚠️  MISSING NEW ASSIGNMENT")
            print(f"Placeholder: {placeholder.name}")
            print("No matching non-placeholder assignment was found. Skipping.")
            continue

        if not placeholder_matches or not new_matches:
            continue

        placeholder = placeholder_matches[0]
        assignment = new_matches[0]

        placeholder_locations = assignment_item_index.get(int(placeholder.id), [])
        assignment_locations = assignment_item_index.get(int(assignment.id), [])

        if len(placeholder_locations) == 0:
            summary.ambiguous_matches += 1
            print("\n⚠️  PLACEHOLDER NOT IN A MODULE")
            print(f"Placeholder: {placeholder.name}")
            print("The placeholder assignment exists but has no module item. Skipping.")
            continue

        if len(placeholder_locations) > 1:
            summary.ambiguous_matches += 1
            print("\n⚠️  DUPLICATE PLACEHOLDER MODULE ITEMS")
            print(f"Placeholder: {placeholder.name}")
            print(f"Locations: {describe_locations(placeholder_locations)}")
            print("The correct target module is ambiguous. Skipping.")
            continue

        if len(assignment_locations) > 1:
            summary.ambiguous_matches += 1
            print("\n⚠️  ASSIGNMENT APPEARS IN MULTIPLE MODULES")
            print(f"New assignment: {assignment.name}")
            print(f"Locations: {describe_locations(assignment_locations)}")
            print("The script will not guess which module item to move. Skipping.")
            continue

        target_module, placeholder_item = placeholder_locations[0]
        placeholder_position = int(getattr(placeholder_item, "position", 0) or 0)
        target_position = placeholder_position + 1

        already_correct = False
        if len(assignment_locations) == 1:
            current_module, assignment_item = assignment_locations[0]
            assignment_position = int(getattr(assignment_item, "position", 0) or 0)
            already_correct = (
                current_module.id == target_module.id
                and assignment_position == target_position
            )

        status = "already_correct" if already_correct else "ready"
        plan = PlacementPlan(
            match_key=key,
            assignment=assignment,
            placeholder_assignment=placeholder,
            placeholder_item=placeholder_item,
            target_module=target_module,
            assignment_items=assignment_locations,
            target_position=target_position,
            status=status,
        )
        plans.append(plan)
        summary.new_assignments_matched += 1

        if already_correct:
            summary.already_correct += 1
        else:
            summary.moved_or_would_move += 1

    return plans, summary


def refresh_module_items(module_record: ModuleRecord) -> list[Any]:
    """Retrieve a module's current item order immediately before a live change."""
    items = list(module_record.module.get_module_items())
    items.sort(key=lambda item: int(getattr(item, "position", 0) or 0))
    return items


def find_item_by_content_id(items: list[Any], assignment_id: int) -> list[Any]:
    """Find Assignment module items with the requested Canvas assignment ID."""
    matches = []
    for item in items:
        if (getattr(item, "type", None) or "").casefold() != "assignment":
            continue
        try:
            if int(getattr(item, "content_id", -1)) == int(assignment_id):
                matches.append(item)
        except (TypeError, ValueError):
            continue
    return matches


def execute_live_plan(plan: PlacementPlan) -> tuple[bool, str]:
    """
    Execute one validated placement using freshly retrieved module positions.

    Existing module items are moved with ModuleItem.edit(). Assignments not yet
    present in any module are added with Module.create_module_item().
    """
    try:
        target_items = refresh_module_items(plan.target_module)
    except Exception as exc:
        return False, f"Could not refresh target module items: {exc}"

    placeholder_matches = find_item_by_content_id(
        target_items, int(plan.placeholder_assignment.id)
    )
    if len(placeholder_matches) != 1:
        return (
            False,
            "The placeholder module item changed after validation "
            f"(found {len(placeholder_matches)} current matches).",
        )

    placeholder_item = placeholder_matches[0]
    target_position = int(getattr(placeholder_item, "position", 0) or 0) + 1

    # Recheck whether the assignment became correctly placed after an earlier move.
    current_target_matches = find_item_by_content_id(
        target_items, int(plan.assignment.id)
    )
    if len(current_target_matches) > 1:
        return False, "The assignment now appears multiple times in the target module."

    if len(current_target_matches) == 1:
        current_item = current_target_matches[0]
        current_position = int(getattr(current_item, "position", 0) or 0)
        if current_position == target_position:
            return True, "Already correctly placed after refreshing Canvas."

    if plan.assignment_items:
        # The validation phase confirmed exactly one existing module item.
        _, module_item = plan.assignment_items[0]
        try:
            module_item.edit(
                module_item={
                    "module_id": plan.target_module.id,
                    "position": target_position,
                }
            )
        except Exception as exc:
            return False, f"Canvas API move failed: {exc}"
    else:
        try:
            plan.target_module.module.create_module_item(
                module_item={
                    "type": "Assignment",
                    "content_id": int(plan.assignment.id),
                    "position": target_position,
                }
            )
        except Exception as exc:
            return False, f"Canvas API module-item creation failed: {exc}"

    # Verify the final placement from a new Canvas response.
    try:
        verified_items = refresh_module_items(plan.target_module)
    except Exception as exc:
        return False, f"Placement was requested, but verification failed: {exc}"

    verified_placeholders = find_item_by_content_id(
        verified_items, int(plan.placeholder_assignment.id)
    )
    verified_assignments = find_item_by_content_id(
        verified_items, int(plan.assignment.id)
    )

    if len(verified_placeholders) != 1 or len(verified_assignments) != 1:
        return (
            False,
            "Canvas did not return exactly one placeholder and one new assignment "
            "during verification.",
        )

    verified_placeholder_position = int(
        getattr(verified_placeholders[0], "position", 0) or 0
    )
    verified_assignment_position = int(
        getattr(verified_assignments[0], "position", 0) or 0
    )

    if verified_assignment_position != verified_placeholder_position + 1:
        return (
            False,
            "Canvas accepted the request, but the assignment is not directly below "
            "the placeholder after verification.",
        )

    return True, (
        f"Verified in {plan.target_module.name} at position "
        f"{verified_assignment_position}."
    )


def print_summary(summary: Summary, is_live: bool) -> None:
    """Display the required end-of-run counts."""
    print("\n==========================================================")
    print("MODULE PLACEMENT SUMMARY")
    print("==========================================================")
    print(f"Placeholders found:                    {summary.placeholders_found}")
    print(f"New assignments matched:               {summary.new_assignments_matched}")
    print(f"Already correctly placed:              {summary.already_correct}")
    print(
        f"Assignments {'moved' if is_live else 'that would be moved'}:".ljust(40)
        + str(summary.moved_or_would_move)
    )
    print(f"Missing placeholders:                  {summary.missing_placeholders}")
    print(f"Missing new assignments:               {summary.missing_new_assignments}")
    print(f"Ambiguous matches:                     {summary.ambiguous_matches}")
    print(f"Failed moves:                          {summary.failed_moves}")
    print("==========================================================")


def place_assignments_in_modules(is_live: bool) -> None:
    """Scan, validate, report, and optionally apply module placement changes."""
    print("==========================================================")
    print("📚 ZYBOOKS MODULE PLACEMENT")
    print("==========================================================")
    print(f"Mode: {'🔴 LIVE' if is_live else '🟢 DRY RUN'}")

    credentials_valid, credentials_error = validate_credentials()
    if not credentials_valid:
        print(f"\n❌ Error: {credentials_error}")
        print("No Canvas changes were made.")
        return

    print("\n🔍 Connecting to Canvas and scanning the full course...")

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

    placeholders, new_assignments = index_assignments(assignments)
    print_matching_diagnostics(placeholders, new_assignments)
    assignment_item_index = index_assignment_module_items(module_records)

    plans, summary = build_placement_plans(
        placeholders=placeholders,
        new_assignments=new_assignments,
        module_records=module_records,
        assignment_item_index=assignment_item_index,
    )

    print("\n==========================================================")
    print("VALIDATED PLACEMENT PLAN")
    print("==========================================================")

    if not plans:
        print("No safe assignment placements were found.")

    for plan in plans:
        print_plan(plan, is_live=is_live)

    if not is_live:
        print_summary(summary, is_live=False)
        print("\nNo Canvas module items were changed during this dry run.")
        print("Review all missing, duplicate, and ambiguous results above.")
        print("\nTo apply only the validated placements, run:")
        print("python place_new_assignments_in_modules.py --live")
        return

    ready_plans = [plan for plan in plans if plan.status == "ready"]

    if not ready_plans:
        print_summary(summary, is_live=True)
        print("\nNo module-item changes were needed or safe to perform.")
        return

    print("\n==========================================================")
    print("APPLYING VALIDATED PLACEMENTS")
    print("==========================================================")

    successful_moves = 0
    for plan in ready_plans:
        print(f"\n🔄 Placing '{plan.assignment_name}'...")
        success, message = execute_live_plan(plan)
        if success:
            print(f"✅ {message}")
            successful_moves += 1
        else:
            print(f"❌ {message}")
            summary.failed_moves += 1

    # In live mode, report only successful changes in the moved count.
    summary.moved_or_would_move = successful_moves
    print_summary(summary, is_live=True)

    if summary.failed_moves:
        print("\n⚠️  Some placements failed. Review the errors and verify Canvas manually.")
    else:
        print("\n✅ All validated placement changes were verified in Canvas.")

    print("Placeholders were not deleted by this script.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Place imported zyBooks assignments directly beneath their matching "
            "Canvas placeholder assignments."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply validated changes to Canvas. Default behavior is a dry run.",
    )
    args = parser.parse_args()
    place_assignments_in_modules(is_live=args.live)


if __name__ == "__main__":
    main()
