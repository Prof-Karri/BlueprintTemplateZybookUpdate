"""
Canvas Cleanup Utility - Empty Modules and Assignment Groups

Scans a Canvas course for empty modules and empty assignment groups, then lets
an instructor choose which empty containers, if any, should be deleted.

Default behavior is a dry run. Use --live only after reviewing the preview:

    python cleanup_empty_canvas_containers.py
    python cleanup_empty_canvas_containers.py --live
"""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canvasapi import Canvas
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

CANVAS_URL = os.getenv("CANVAS_URL")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")
COURSE_ID_STR = os.getenv("COURSE_ID")


@dataclass
class EmptyModuleCandidate:
    module: Any
    name: str
    module_id: int


@dataclass
class EmptyGroupCandidate:
    group: Any
    name: str
    group_id: int


@dataclass
class CleanupSummary:
    modules_scanned: int = 0
    groups_scanned: int = 0
    empty_modules_found: int = 0
    empty_groups_found: int = 0
    modules_selected: int = 0
    groups_selected: int = 0
    modules_deleted: int = 0
    groups_deleted: int = 0
    skipped_after_recheck: int = 0
    failed_deletions: int = 0


def validate_credentials() -> tuple[bool, str]:
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


def get_course():
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
    try:
        course = canvas.get_course(int(str(COURSE_ID_STR)))
        course_name = getattr(course, "name", None) or f"Course {COURSE_ID_STR}"
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Canvas course {COURSE_ID_STR}: {exc}"
        ) from exc
    return course, course_name


def find_empty_modules(course) -> tuple[list[EmptyModuleCandidate], int]:
    try:
        modules = list(course.get_modules())
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve course modules: {exc}") from exc

    candidates: list[EmptyModuleCandidate] = []
    for module in modules:
        name = (getattr(module, "name", None) or f"Module {module.id}").strip()
        try:
            items = list(module.get_module_items())
        except Exception as exc:
            print(f"⚠️  Could not verify module '{name}' (ID {module.id}): {exc}")
            continue

        if len(items) == 0:
            candidates.append(
                EmptyModuleCandidate(
                    module=module,
                    name=name,
                    module_id=int(module.id),
                )
            )

    return candidates, len(modules)


def get_group_assignment_counts(course) -> dict[int, int]:
    """Count assignments by assignment group using one course-wide scan."""
    counts: dict[int, int] = {}
    try:
        assignments = list(course.get_assignments())
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve course assignments: {exc}") from exc

    for assignment in assignments:
        group_id = getattr(assignment, "assignment_group_id", None)
        if group_id is None:
            continue
        try:
            normalized_id = int(group_id)
        except (TypeError, ValueError):
            continue
        counts[normalized_id] = counts.get(normalized_id, 0) + 1

    return counts


def find_empty_assignment_groups(course) -> tuple[list[EmptyGroupCandidate], int]:
    try:
        groups = list(course.get_assignment_groups())
    except Exception as exc:
        raise RuntimeError(f"Could not retrieve assignment groups: {exc}") from exc

    assignment_counts = get_group_assignment_counts(course)
    candidates: list[EmptyGroupCandidate] = []

    for group in groups:
        group_id = int(group.id)
        name = (getattr(group, "name", None) or f"Group {group_id}").strip()
        if assignment_counts.get(group_id, 0) == 0:
            candidates.append(
                EmptyGroupCandidate(
                    group=group,
                    name=name,
                    group_id=group_id,
                )
            )

    return candidates, len(groups)


def display_candidates(title: str, candidates: list[Any], item_type: str) -> None:
    print("\n==========================================================")
    print(title)
    print("==========================================================")

    if not candidates:
        print(f"No empty {item_type} were found.")
        return

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = (
            candidate.module_id
            if isinstance(candidate, EmptyModuleCandidate)
            else candidate.group_id
        )
        print(f"{index}. {candidate.name} (Canvas ID {candidate_id})")


def parse_selection(prompt: str, candidate_count: int) -> list[int]:
    if candidate_count == 0:
        return []

    while True:
        raw_value = input(prompt).strip()

        if not raw_value:
            return []

        if raw_value.casefold() == "all":
            return list(range(candidate_count))

        selected_indexes: list[int] = []
        invalid_values: list[str] = []

        for part in raw_value.split(","):
            value = part.strip()
            try:
                number = int(value)
            except ValueError:
                invalid_values.append(value)
                continue

            if number < 1 or number > candidate_count:
                invalid_values.append(value)
                continue

            index = number - 1
            if index not in selected_indexes:
                selected_indexes.append(index)

        if invalid_values:
            print("❌ Invalid selection(s): " + ", ".join(invalid_values))
            print(
                f"Enter numbers from 1 to {candidate_count}, separated by commas; "
                "enter ALL; or press Enter to keep everything."
            )
            continue

        return selected_indexes


def print_cleanup_plan(
    selected_modules: list[EmptyModuleCandidate],
    selected_groups: list[EmptyGroupCandidate],
    is_live: bool,
) -> None:
    print("\n==========================================================")
    print("CLEANUP PLAN")
    print("==========================================================")
    print(f"Mode: {'🔴 LIVE' if is_live else '🟢 DRY RUN'}")

    if not selected_modules and not selected_groups:
        print("No modules or assignment groups were selected.")
        return

    if selected_modules:
        print("\nModules:")
        for candidate in selected_modules:
            action = "Will delete" if is_live else "Would delete"
            print(f"- {action}: {candidate.name} (Canvas ID {candidate.module_id})")

    if selected_groups:
        print("\nAssignment groups:")
        for candidate in selected_groups:
            action = "Will delete" if is_live else "Would delete"
            print(f"- {action}: {candidate.name} (Canvas ID {candidate.group_id})")


def module_is_still_empty(course, module_id: int) -> tuple[bool, str]:
    try:
        module = course.get_module(module_id)
        items = list(module.get_module_items())
    except Exception as exc:
        return False, f"Could not recheck module: {exc}"

    if items:
        return False, f"Module now contains {len(items)} item(s)."
    return True, ""


def group_is_still_empty(course, group_id: int) -> tuple[bool, str]:
    try:
        counts = get_group_assignment_counts(course)
    except RuntimeError as exc:
        return False, str(exc)

    count = counts.get(group_id, 0)
    if count:
        return False, f"Assignment group now contains {count} assignment(s)."
    return True, ""


def delete_module(course, candidate: EmptyModuleCandidate) -> tuple[bool, str, bool]:
    is_empty, reason = module_is_still_empty(course, candidate.module_id)
    if not is_empty:
        return False, reason, True

    try:
        module = course.get_module(candidate.module_id)
        module.delete()
    except Exception as exc:
        return False, f"Canvas module deletion failed: {exc}", False

    try:
        course.get_module(candidate.module_id)
    except Exception:
        return True, "Deletion verified.", False

    return False, "Canvas still returned the module after deletion.", False


def delete_assignment_group(
    course,
    candidate: EmptyGroupCandidate,
) -> tuple[bool, str, bool]:
    is_empty, reason = group_is_still_empty(course, candidate.group_id)
    if not is_empty:
        return False, reason, True

    try:
        group = course.get_assignment_group(candidate.group_id)
        group.delete()
    except Exception as exc:
        return False, f"Canvas assignment-group deletion failed: {exc}", False

    try:
        course.get_assignment_group(candidate.group_id)
    except Exception:
        return True, "Deletion verified.", False

    return False, "Canvas still returned the assignment group after deletion.", False


def print_summary(summary: CleanupSummary, is_live: bool) -> None:
    print("\n==========================================================")
    print("EMPTY CONTAINER CLEANUP SUMMARY")
    print("==========================================================")
    print(f"Modules scanned:                 {summary.modules_scanned}")
    print(f"Assignment groups scanned:       {summary.groups_scanned}")
    print(f"Empty modules found:             {summary.empty_modules_found}")
    print(f"Empty assignment groups found:   {summary.empty_groups_found}")
    print(f"Modules selected:                {summary.modules_selected}")
    print(f"Assignment groups selected:      {summary.groups_selected}")

    if is_live:
        print(f"Modules deleted:                 {summary.modules_deleted}")
        print(f"Assignment groups deleted:       {summary.groups_deleted}")
        print(f"Skipped after live recheck:      {summary.skipped_after_recheck}")
        print(f"Failed deletions:                {summary.failed_deletions}")
    else:
        print("No Canvas containers were deleted during this dry run.")

    print("==========================================================")


def cleanup_empty_containers(is_live: bool) -> None:
    print("==========================================================")
    print("🧹 CANVAS EMPTY CONTAINER CLEANUP")
    print("==========================================================")
    print(f"Mode: {'🔴 LIVE' if is_live else '🟢 DRY RUN'}")

    credentials_valid, credentials_error = validate_credentials()
    if not credentials_valid:
        print(f"\n❌ Error: {credentials_error}")
        print("No Canvas changes were made.")
        return

    try:
        course, course_name = get_course()
    except RuntimeError as exc:
        print(f"\n❌ Connection failed: {exc}")
        print("No Canvas changes were made.")
        return

    print(f"\n✅ Connected to: {course_name}")
    print(f"✅ Course ID: {COURSE_ID_STR}")
    print("\n🔍 Scanning modules and assignment groups...")

    summary = CleanupSummary()

    try:
        empty_modules, summary.modules_scanned = find_empty_modules(course)
        empty_groups, summary.groups_scanned = find_empty_assignment_groups(course)
    except RuntimeError as exc:
        print(f"\n❌ Cleanup scan failed: {exc}")
        print("No Canvas changes were made.")
        return

    summary.empty_modules_found = len(empty_modules)
    summary.empty_groups_found = len(empty_groups)

    display_candidates("EMPTY MODULES FOUND", empty_modules, "modules")
    selected_module_indexes = parse_selection(
        "\nEnter module numbers to delete, separated by commas; "
        "enter ALL; or press Enter to keep all modules: ",
        len(empty_modules),
    )

    display_candidates(
        "EMPTY ASSIGNMENT GROUPS FOUND",
        empty_groups,
        "assignment groups",
    )
    selected_group_indexes = parse_selection(
        "\nEnter assignment-group numbers to delete, separated by commas; "
        "enter ALL; or press Enter to keep all groups: ",
        len(empty_groups),
    )

    selected_modules = [empty_modules[index] for index in selected_module_indexes]
    selected_groups = [empty_groups[index] for index in selected_group_indexes]

    summary.modules_selected = len(selected_modules)
    summary.groups_selected = len(selected_groups)

    print_cleanup_plan(selected_modules, selected_groups, is_live)

    if not selected_modules and not selected_groups:
        print_summary(summary, is_live=is_live)
        print("\nNo cleanup actions were selected.")
        return

    if not is_live:
        print_summary(summary, is_live=False)
        print("\nReview the cleanup plan above.")
        print("To delete selected empty containers, rerun with:")
        print("python cleanup_empty_canvas_containers.py --live")
        return

    print("\n==========================================================")
    print("PERMANENT DELETION WARNING")
    print("==========================================================")
    print("Only selected containers that are still empty will be deleted.")
    print("Each container will be rechecked immediately before deletion.")
    confirmation = input("\nType DELETE EMPTY CONTAINERS to continue: ").strip()

    if confirmation != "DELETE EMPTY CONTAINERS":
        print("\nLive cleanup canceled. No containers were deleted.")
        return

    print("\n==========================================================")
    print("DELETING SELECTED EMPTY CONTAINERS")
    print("==========================================================")

    for candidate in selected_modules:
        print(f"\n🗑️  Deleting module '{candidate.name}'...")
        success, message, skipped = delete_module(course, candidate)
        if success:
            print(f"✅ {message}")
            summary.modules_deleted += 1
        elif skipped:
            print(f"⚠️  Skipped after recheck: {message}")
            summary.skipped_after_recheck += 1
        else:
            print(f"❌ {message}")
            summary.failed_deletions += 1

    for candidate in selected_groups:
        print(f"\n🗑️  Deleting assignment group '{candidate.name}'...")
        success, message, skipped = delete_assignment_group(course, candidate)
        if success:
            print(f"✅ {message}")
            summary.groups_deleted += 1
        elif skipped:
            print(f"⚠️  Skipped after recheck: {message}")
            summary.skipped_after_recheck += 1
        else:
            print(f"❌ {message}")
            summary.failed_deletions += 1

    print_summary(summary, is_live=True)

    if summary.failed_deletions:
        print("\n⚠️  Some deletions failed. Review Canvas and the errors above.")
    else:
        print("\n✅ Cleanup completed. All successful deletions were verified.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find empty Canvas modules and assignment groups, allow the "
            "instructor to select cleanup targets, and optionally delete them."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Permanently delete selected containers that are still empty.",
    )
    args = parser.parse_args()
    cleanup_empty_containers(is_live=args.live)


if __name__ == "__main__":
    main()
