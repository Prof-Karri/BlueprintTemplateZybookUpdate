"""
zyBooks Canvas Automator - Assignment Configuration

Reads the chapter-level semester_dates.csv created by setup_dates.py, validates
its contents, and applies the correct R&P or CA template, due date, lock date,
assignment group, and publish status to imported zyBooks assignments.

Default behavior is a dry run. Use --live only after reviewing the dry-run output.
"""

import argparse
import csv
import os
import re
from datetime import datetime
from pathlib import Path

from canvasapi import Canvas
from dotenv import load_dotenv

from setup_dates import (
    is_schedulable_zybooks_assignment,
    normalize_schedule_key,
)


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

CANVAS_URL = os.getenv("CANVAS_URL")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")
COURSE_ID_STR = os.getenv("COURSE_ID")

CSV_FILE = SCRIPT_DIR / "semester_dates.csv"
EXPECTED_COLUMNS = {"Chapter", "RP_Date", "RP_Time", "CA_Date", "CA_Time"}


ZYBOOKS_SUPPORT_BLOCK = """<h2>Technical Support and Grade-Sync Problems</h2>
<p>If you experience a problem with zyBooks, including login, access, assignment completion, scoring, or grade syncing, your<span>&nbsp;</span><strong>first step is to contact zyBooks Support</strong><span>&nbsp;</span>at<span>&nbsp;</span><a href="mailto:support@zybooks.com">support@zybooks.com</a>.</p>
<p>When contacting zyBooks Support, include your course name, the assignment name, the chapter number, a description of the problem, and screenshots when available.</p>
<p>After zyBooks Support responds, forward a copy of their response to me. I may need their findings before I can investigate the issue or make any adjustment in Canvas.</p>
<p>Do not wait until the day this assignment is due to report a zyBooks issue. Contact zyBooks Support as soon as you notice the problem.</p>"""


def customize_template(template_html: str, chapter_number: int) -> str:
    """
    Create the assignment body from an M1 placeholder template.

    Only explicit chapter labels are changed. Other occurrences of the number 1,
    including URLs, numbered instructions, and HTML attributes, are left alone.
    The standardized zyBooks support block is also added or refreshed.
    """
    updated_html = re.sub(
        r"\bChapter\s+1\b",
        f"Chapter {chapter_number}",
        template_html,
        flags=re.IGNORECASE,
    )
    updated_html = re.sub(
        r"\bCh1\b",
        f"Ch{chapter_number}",
        updated_html,
        flags=re.IGNORECASE,
    )

    # Replace an existing Technical Support heading and its first explanatory
    # paragraph. Any resource link or other content that follows remains intact.
    support_section_pattern = re.compile(
        r"<h2>\s*Technical Support(?:\s+and\s+Grade-Sync Problems)?\s*</h2>"
        r"\s*<p>.*?</p>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    if support_section_pattern.search(updated_html):
        updated_html = support_section_pattern.sub(
            ZYBOOKS_SUPPORT_BLOCK,
            updated_html,
            count=1,
        )
    elif "Technical Support and Grade-Sync Problems" not in updated_html:
        updated_html = f"{updated_html.rstrip()}\n{ZYBOOKS_SUPPORT_BLOCK}\n"

    return updated_html


def pause_for_csv_review() -> None:
    """Explain how to proceed whether or not the generated CSV was edited."""
    print("==========================================================")
    print("📘 ZYBOOKS ASSIGNMENT CONFIGURATION")
    print("==========================================================")
    print("\nBefore continuing, review semester_dates.csv.")
    print("\nIf you did NOT make any changes:")
    print("- Leave the existing semester_dates.csv file in place.")
    print("- Press Enter below to continue.")
    print("\nIf you DID make changes in Excel:")
    print("1. Save the file as a CSV using the same filename: semester_dates.csv")
    print("2. Drag the saved file back into this Codespaces folder.")
    print("3. Choose Replace if Codespaces asks to overwrite the existing file.")
    print("\n⚠️  Keep the file in CSV format. Do not save it as an .xlsx workbook.")
    input("\nPress Enter when the correct semester_dates.csv is in Codespaces...")


def parse_datetime(date_value: str, time_value: str, row_number: int, label: str) -> str:
    """Validate date/time values and return a Canvas-compatible ISO string."""
    combined_value = f"{date_value.strip()} {time_value.strip()}"

    try:
        parsed = datetime.strptime(combined_value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(
            f"Row {row_number}: invalid {label} date/time '{combined_value}'. "
            "Use YYYY-MM-DD and 24-hour HH:MM."
        ) from exc

    return parsed.strftime("%Y-%m-%dT%H:%M:00")


def load_schedule(csv_path: Path = CSV_FILE) -> dict[tuple[int, int], dict[str, str]]:
    """Load and validate the chapter-level semester schedule CSV."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Could not find '{csv_path.name}' in {csv_path.parent}. "
            "Run setup_dates.py first, then upload the reviewed CSV."
        )

    schedule: dict[tuple[int, int], dict[str, str]] = {}

    try:
        with csv_path.open(mode="r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)

            if reader.fieldnames is None:
                raise ValueError("The CSV is empty or does not contain a header row.")

            actual_columns = {column.strip() for column in reader.fieldnames if column}
            missing_columns = EXPECTED_COLUMNS - actual_columns
            if missing_columns:
                missing_text = ", ".join(sorted(missing_columns))
                raise ValueError(f"The CSV is missing required column(s): {missing_text}.")

            for row_number, row in enumerate(reader, start=2):
                chapter_value = (row.get("Chapter") or "").strip()

                if not chapter_value:
                    raise ValueError(f"Row {row_number}: Chapter is blank.")

                schedule_key = normalize_schedule_key(chapter_value)
                if schedule_key is None:
                    raise ValueError(
                        f"Row {row_number}: invalid Chapter value '{chapter_value}'. "
                        "Expected a value such as 'M1 Ch1'."
                    )

                if schedule_key in schedule:
                    module_number, chapter_number = schedule_key
                    raise ValueError(
                        f"Row {row_number}: duplicate schedule row for "
                        f"M{module_number} Ch{chapter_number}."
                    )

                rp_date = row.get("RP_Date") or ""
                rp_time = row.get("RP_Time") or ""
                ca_date = row.get("CA_Date") or ""
                ca_time = row.get("CA_Time") or ""

                schedule[schedule_key] = {
                    "R&P": parse_datetime(rp_date, rp_time, row_number, "R&P"),
                    "CA": parse_datetime(ca_date, ca_time, row_number, "CA"),
                }
    except OSError as exc:
        raise RuntimeError(f"Could not read {csv_path}: {exc}") from exc

    if not schedule:
        raise ValueError("The CSV contains no schedule rows.")

    return schedule


def get_assignment_type(assignment_name: str) -> str | None:
    """Return R&P or CA for a supported imported assignment name."""
    lowered_name = assignment_name.casefold()

    if "r&p" in lowered_name:
        return "R&P"
    if re.search(r"\bca\b", lowered_name):
        return "CA"
    return None


def find_templates(all_assignments) -> tuple[str, str]:
    """Extract the R&P and CA HTML descriptions from M1 placeholders."""
    rp_template: str | None = None
    ca_template: str | None = None
    rp_placeholder_found = False
    ca_placeholder_found = False

    for assignment in all_assignments:
        name = assignment.name or ""
        lowered_name = name.casefold()

        if "placeholder" not in lowered_name or not re.match(r"^\s*m1\b", lowered_name):
            continue

        assignment_type = get_assignment_type(name)
        if assignment_type == "R&P" and rp_template is None:
            rp_placeholder_found = True
            rp_template = assignment.description
        elif assignment_type == "CA" and ca_template is None:
            ca_placeholder_found = True
            ca_template = assignment.description

    errors: list[str] = []

    if not rp_placeholder_found:
        errors.append("M1 R&P Placeholder assignment was not found")
    elif not rp_template:
        errors.append("M1 R&P Placeholder was found, but its description is blank")

    if not ca_placeholder_found:
        errors.append("M1 CA Placeholder assignment was not found")
    elif not ca_template:
        errors.append("M1 CA Placeholder was found, but its description is blank")

    if errors:
        raise RuntimeError("; ".join(errors) + ".")

    return rp_template, ca_template


def choose_assignment_group_names(course) -> dict[str, str]:
    """Show existing groups and ask where R&P and CA assignments belong."""
    groups = list(course.get_assignment_groups())

    print("\n--- Canvas Assignment Groups ---")
    if groups:
        print("Existing assignment groups:")
        for index, group in enumerate(groups, start=1):
            print(f"  {index}. {(group.name or '').strip()}")
    else:
        print("No assignment groups were found in this course.")

    print("\nEnter the exact assignment-group name for each assignment type.")
    print("If a name does not exist, it will be created only during a live run.")

    while True:
        rp_group = input("R&P / Participation assignment group: ").strip()
        if rp_group:
            break
        print("❌ The R&P / Participation assignment-group name cannot be blank.")

    while True:
        ca_group = input("CA / Challenge assignment group: ").strip()
        if ca_group:
            break
        print("❌ The CA / Challenge assignment-group name cannot be blank.")

    print("\nAssignment-group selection:")
    print(f"  R&P / Participation → {rp_group}")
    print(f"  CA / Challenge       → {ca_group}")

    return {"R&P": rp_group, "CA": ca_group}


def get_or_create_assignment_groups(
    course,
    selected_names: dict[str, str],
    is_live: bool,
) -> dict[str, int | None]:
    """Resolve the selected group names, creating missing groups in live mode."""
    existing_groups = list(course.get_assignment_groups())
    groups_by_name = {
        (group.name or "").strip().casefold(): group
        for group in existing_groups
        if (group.name or "").strip()
    }

    resolved: dict[str, int | None] = {}
    created_by_name: dict[str, int] = {}

    for assignment_type, requested_name in selected_names.items():
        normalized_name = requested_name.casefold()
        existing_group = groups_by_name.get(normalized_name)

        if existing_group is not None:
            actual_name = (existing_group.name or requested_name).strip()
            print(f"✅ Found {assignment_type} assignment group: {actual_name}")
            resolved[assignment_type] = existing_group.id
            continue

        if normalized_name in created_by_name:
            resolved[assignment_type] = created_by_name[normalized_name]
            continue

        if is_live:
            new_group = course.create_assignment_group(name=requested_name)
            print(f"➕ Created {assignment_type} assignment group: {requested_name}")
            resolved[assignment_type] = new_group.id
            created_by_name[normalized_name] = new_group.id
        else:
            print(
                f"🔍 [DRY RUN] Would create {assignment_type} assignment group: "
                f"{requested_name}"
            )
            resolved[assignment_type] = None

    return resolved


def configure_assignments(is_live: bool) -> None:
    """Validate inputs, scan Canvas, and configure imported zyBooks assignments."""
    pause_for_csv_review()

    if not CANVAS_URL or not CANVAS_TOKEN or not COURSE_ID_STR:
        print("\n❌ Error: Missing CANVAS_URL, CANVAS_TOKEN, or COURSE_ID in the .env file.")
        return

    try:
        schedule = load_schedule()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"\n❌ CSV validation failed: {exc}")
        print("No Canvas changes were made.")
        return

    print(f"\n✅ Validated {len(schedule)} chapter schedule rows from:")
    print(f"   {CSV_FILE}")

    mode_text = "🔴 LIVE MODE" if is_live else "🟢 DRY RUN MODE"
    print(f"\n🚀 Starting assignment configuration in {mode_text}...")

    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)

    try:
        course = canvas.get_course(COURSE_ID_STR)
        all_assignments = list(course.get_assignments())
    except Exception as exc:
        print(f"❌ Error accessing Canvas course {COURSE_ID_STR}: {exc}")
        return

    try:
        rp_template, ca_template = find_templates(all_assignments)
    except RuntimeError as exc:
        print(f"❌ Template error: {exc}")
        return

    print("✅ Found and loaded the M1 R&P and CA placeholder templates.")

    try:
        selected_group_names = choose_assignment_group_names(course)
        target_group_ids = get_or_create_assignment_groups(
            course=course,
            selected_names=selected_group_names,
            is_live=is_live,
        )
    except Exception as exc:
        print(f"❌ Could not resolve the selected assignment groups: {exc}")
        return

    print("\n⚙️  Processing imported zyBooks assignments...")

    matched_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    for assignment in all_assignments:
        name = assignment.name or ""

        if not is_schedulable_zybooks_assignment(name):
            continue

        matched_count += 1
        schedule_key = normalize_schedule_key(name)
        assignment_type = get_assignment_type(name)

        if schedule_key is None or assignment_type is None:
            print(f"  ⚠️  Skipping '{name}': could not determine chapter or assignment type.")
            skipped_count += 1
            continue

        target_date = schedule.get(schedule_key, {}).get(assignment_type)
        if target_date is None:
            module_number, chapter_number = schedule_key
            print(
                f"  ⚠️  Skipping '{name}': no {assignment_type} schedule was found "
                f"for M{module_number} Ch{chapter_number}."
            )
            skipped_count += 1
            continue

        base_template = rp_template if assignment_type == "R&P" else ca_template
        _, chapter_number = schedule_key
        template_body = customize_template(base_template, chapter_number)
        target_group_name = selected_group_names[assignment_type]
        target_group_id = target_group_ids[assignment_type]
        print(f"\nTarget: {name}")

        if not is_live:
            print(f"  🔍 [DRY RUN] Due/lock date: {target_date}")
            print(f"  🔍 [DRY RUN] Assignment group: {target_group_name}")
            print(
                f"  🔍 [DRY RUN] Would apply the {assignment_type} template "
                f"customized for Chapter {chapter_number}, move, and publish."
            )
            updated_count += 1
            continue

        try:
            assignment.edit(
                assignment={
                    "description": template_body,
                    "due_at": target_date,
                    "lock_at": target_date,
                    "assignment_group_id": target_group_id,
                    "published": True,
                }
            )
            print(
                "  ✅ Updated template, dates, assignment group "
                f"'{target_group_name}', and publish status."
            )
            updated_count += 1
        except Exception as exc:
            print(f"  ❌ Update failed: {exc}")
            failed_count += 1

    print("\n==========================================================")
    print("CONFIGURATION SUMMARY")
    print("==========================================================")
    print(f"Matched zyBooks assignments: {matched_count}")
    print(f"{'Updated' if is_live else 'Simulated'} successfully: {updated_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Failed: {failed_count}")

    if not is_live:
        print("\nNo Canvas assignments were changed during this dry run.")
        print("Run the following command after reviewing the results:")
        print("python configure_new_assignments.py --live")

    print("==========================================================")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure imported zyBooks assignments using semester_dates.csv."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply changes to Canvas. Without this flag, the script performs a dry run.",
    )
    args = parser.parse_args()
    configure_assignments(args.live)


if __name__ == "__main__":
    main()
