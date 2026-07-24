"""
zyBooks Canvas Automator - Semester Date Generator

Scans imported Canvas assignments, identifies normalized module/chapter keys,
and creates semester_dates.csv for the assignment-configuration workflow.

Examples of normalization:
    M1 Ch1a R&P -> M1 Ch1
    M1 Ch1b CA  -> M1 Ch1
    M1 Ch2 R&P  -> M1 Ch2

CSV output columns:
    Chapter, RP_Date, RP_Time, CA_Date, CA_Time
"""

import csv
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from canvasapi import Canvas
from dotenv import load_dotenv


# Always load .env and save the CSV relative to this script, not the terminal's
# current working directory.
SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

CANVAS_URL = os.getenv("CANVAS_URL")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")
COURSE_ID_STR = os.getenv("COURSE_ID")
CSV_FILE = SCRIPT_DIR / "semester_dates.csv"

# Capture the module and numeric chapter only. An optional letter suffix is
# accepted but deliberately excluded from the normalized schedule key.
ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"^\s*M(?P<module>\d+)\s+Ch(?P<chapter>\d+)[A-Za-z]?\b",
    re.IGNORECASE,
)


def get_valid_choice(prompt: str, valid_choices: set[str]) -> str:
    """Prompt until the user enters one of the allowed values."""
    while True:
        value = input(prompt).strip()
        if value in valid_choices:
            return value
        choices = " or ".join(sorted(valid_choices))
        print(f"❌ Invalid input. Please enter {choices}.")


def get_valid_date(prompt: str) -> datetime:
    """Prompt for and validate a date in YYYY-MM-DD format."""
    while True:
        date_str = input(prompt).strip()
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print("❌ Invalid format. Please use YYYY-MM-DD.")


def get_valid_time(prompt: str, default: str = "23:59") -> str:
    """Prompt for and validate a 24-hour time in HH:MM format."""
    while True:
        time_str = input(prompt).strip() or default
        try:
            parsed_time = datetime.strptime(time_str, "%H:%M")
            return parsed_time.strftime("%H:%M")
        except ValueError:
            print("❌ Invalid format. Please use 24-hour HH:MM, such as 08:00 or 23:59.")


def normalize_schedule_key(assignment_name: str) -> tuple[int, int] | None:
    """
    Return a numeric (module, chapter) key from a supported assignment name.

    Letter suffixes are intentionally ignored, so Ch1a and Ch1b both return
    the same key: (1, 1).
    """
    match = ASSIGNMENT_PREFIX_PATTERN.search(assignment_name)
    if not match:
        return None

    return int(match.group("module")), int(match.group("chapter"))


def is_schedulable_zybooks_assignment(assignment_name: str) -> bool:
    """Return True for imported R&P or CA assignments, excluding placeholders."""
    lowered_name = assignment_name.casefold()

    if "placeholder" in lowered_name:
        return False

    has_assignment_type = "r&p" in lowered_name or re.search(r"\bca\b", lowered_name)
    return bool(has_assignment_type and normalize_schedule_key(assignment_name))


def scan_canvas_chapters(course) -> list[tuple[int, int]]:
    """Retrieve assignments and return sorted, normalized module/chapter keys."""
    unique_chapters: set[tuple[int, int]] = set()

    try:
        for assignment in course.get_assignments():
            name = assignment.name or ""
            if is_schedulable_zybooks_assignment(name):
                schedule_key = normalize_schedule_key(name)
                if schedule_key is not None:
                    unique_chapters.add(schedule_key)
    except Exception as exc:
        raise RuntimeError(f"Canvas assignment scan failed: {exc}") from exc

    return sorted(unique_chapters)


def group_chapters_by_module(
    sorted_chapters: list[tuple[int, int]],
) -> dict[int, list[int]]:
    """Group normalized chapter numbers by module while preserving sort order."""
    module_groups: dict[int, list[int]] = defaultdict(list)

    for module_number, chapter_number in sorted_chapters:
        module_groups[module_number].append(chapter_number)

    return dict(module_groups)


def build_schedule_rows(
    module_groups: dict[int, list[int]],
    pacing: str,
    rp_start: datetime,
    ca_start: datetime,
    rp_time: str,
    ca_time: str,
) -> list[dict[str, str]]:
    """Build the chapter-level schedule rows for an 8- or 16-week course."""
    rows: list[dict[str, str]] = []
    week_offset = 0

    for module_number, chapters in module_groups.items():
        if pacing == "16" and len(chapters) > 2:
            print(
                f"⚠️  M{module_number} contains {len(chapters)} normalized chapters. "
                "The first chapter will use the module's first week; all remaining "
                "chapters will use its second week. Review the CSV carefully."
            )

        for chapter_index, chapter_number in enumerate(chapters):
            if pacing == "8":
                chapter_week_offset = week_offset
            else:
                # The first normalized chapter is scheduled in week one of the
                # module block. Remaining normalized chapters use week two.
                chapter_week_offset = week_offset + (0 if chapter_index == 0 else 1)

            current_rp = rp_start + timedelta(weeks=chapter_week_offset)
            current_ca = ca_start + timedelta(weeks=chapter_week_offset)

            rows.append(
                {
                    "Chapter": f"M{module_number} Ch{chapter_number}",
                    "RP_Date": current_rp.strftime("%Y-%m-%d"),
                    "RP_Time": rp_time,
                    "CA_Date": current_ca.strftime("%Y-%m-%d"),
                    "CA_Time": ca_time,
                }
            )

        week_offset += 1 if pacing == "8" else 2

    return rows


def write_schedule_csv(rows: list[dict[str, str]], filename: Path = CSV_FILE) -> None:
    """Write schedule rows using the CSV contract expected by the next script."""
    fieldnames = ["Chapter", "RP_Date", "RP_Time", "CA_Date", "CA_Time"]

    try:
        with filename.open(mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        raise RuntimeError(f"Could not write {filename}: {exc}") from exc


def main() -> None:
    print("==========================================================")
    print("🗓️  ZYBOOKS SMART SEMESTER DATE GENERATOR")
    print("==========================================================\n")

    if not CANVAS_URL or not CANVAS_TOKEN or not COURSE_ID_STR:
        print("❌ Error: Missing CANVAS_URL, CANVAS_TOKEN, or COURSE_ID in the .env file.")
        return

    print("🔍 Connecting to Canvas to scan imported assignments...")
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)

    try:
        course = canvas.get_course(COURSE_ID_STR)
        sorted_chapters = scan_canvas_chapters(course)
    except Exception as exc:
        print(f"❌ Error accessing Canvas course or assignments: {exc}")
        return

    if not sorted_chapters:
        print("❌ Error: No imported zyBooks R&P or CA assignments were found.")
        print("Expected names beginning with a prefix such as 'M1 Ch1a R&P' or 'M1 Ch1 CA'.")
        return

    print(f"✅ Found {len(sorted_chapters)} normalized chapters to schedule:")
    print("   " + ", ".join(f"M{module} Ch{chapter}" for module, chapter in sorted_chapters))

    print("\n--- Course Pacing ---")
    pacing = get_valid_choice(
        "Is this an 8-week or 16-week course? (Enter 8 or 16): ",
        {"8", "16"},
    )

    print("\n--- First Assignment Dates ---")
    print("For live or hybrid courses, R&P can be due before class and CA after class.")
    rp_start = get_valid_date("Enter the due date for the FIRST R&P (YYYY-MM-DD): ")
    ca_start = get_valid_date("Enter the due date for the FIRST CA  (YYYY-MM-DD): ")

    print("\n--- Due Times ---")
    rp_time = get_valid_time(
        "What time are R&P assignments due? (24-hour HH:MM, default 23:59): "
    )
    ca_time = get_valid_time(
        "What time are CA assignments due?  (24-hour HH:MM, default 23:59): "
    )

    module_groups = group_chapters_by_module(sorted_chapters)
    rows = build_schedule_rows(
        module_groups=module_groups,
        pacing=pacing,
        rp_start=rp_start,
        ca_start=ca_start,
        rp_time=rp_time,
        ca_time=ca_time,
    )

    try:
        write_schedule_csv(rows)
    except RuntimeError as exc:
        print(f"❌ Error: {exc}")
        return

    print("\n==========================================================")
    print(f"✅ Success! Generated {len(rows)} schedule rows.")
    print(f"📄 Schedule saved to: {CSV_FILE}")
    print("==========================================================")
    print("⚠️  Review the CSV before running the assignment configuration script.")
    print("Holiday or irregular-week adjustments can be edited directly in the CSV.")
    print("\nNote: configure_new_assignments.py must be revised to read the new")
    print("Chapter, RP_Time, and CA_Time columns before it is run.")


if __name__ == "__main__":
    main()
