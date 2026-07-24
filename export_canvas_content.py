"""
Canvas Course Content Exporter - Version 2

Exports Canvas course content to canvas_course_content.json.

Exported content:
1. Course information
2. Assignments
3. Classic Quizzes and their questions
4. New Quizzes and their items
5. Canvas Pages and their full HTML bodies

Required environment variables:
    CANVAS_URL
    CANVAS_TOKEN
    COURSE_ID

Required packages:
    canvasapi
    python-dotenv
    requests
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from canvasapi import Canvas
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "canvas_course_content.json"

load_dotenv(SCRIPT_DIR / ".env")

CANVAS_URL = os.getenv("CANVAS_URL", "").strip().rstrip("/")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN", "").strip()
COURSE_ID_STR = os.getenv("COURSE_ID", "").strip()


def confirm_course(course_name: str, course_id: int) -> bool:
    """Display the selected Canvas course and ask the user to confirm it."""
    print("\nSuccessfully connected.")
    print(f"Course Name: {course_name}")
    print(f"Course ID: {course_id}")

    while True:
        response = input(
            "\nIs this the correct Canvas course? Enter Y to continue or N to cancel: "
        ).strip().lower()

        if response in {"y", "yes"}:
            return True

        if response in {"n", "no"}:
            return False

        print("Please enter Y or N.")


def validate_configuration() -> int:
    """Validate environment variables and return the numeric course ID."""

    missing_variables = []

    if not CANVAS_URL:
        missing_variables.append("CANVAS_URL")

    if not CANVAS_TOKEN:
        missing_variables.append("CANVAS_TOKEN")

    if not COURSE_ID_STR:
        missing_variables.append("COURSE_ID")

    if missing_variables:
        missing_text = ", ".join(missing_variables)
        raise ValueError(
            f"Missing required environment variables: {missing_text}\n\n"
            "Your .env file should contain:\n"
            "CANVAS_URL=https://your-institution.instructure.com\n"
            "CANVAS_TOKEN=your_canvas_api_token\n"
            "COURSE_ID=123456"
        )

    try:
        return int(COURSE_ID_STR)
    except ValueError as error:
        raise ValueError(
            "COURSE_ID must contain only the numeric Canvas course ID.\n"
            f"Current value: {COURSE_ID_STR}"
        ) from error


def make_json_safe(value: Any) -> Any:
    """Convert CanvasAPI objects and other values into JSON-safe data."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]

    if hasattr(value, "__dict__"):
        return {
            key: make_json_safe(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return str(value)


def canvas_object_to_dict(canvas_object: Any) -> dict[str, Any]:
    """Convert a CanvasAPI object into a JSON-safe dictionary."""

    converted = make_json_safe(canvas_object)

    if isinstance(converted, dict):
        return converted

    return {"value": converted}


class CanvasRestClient:
    """Read-only REST client for Canvas endpoints such as New Quizzes."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )

    def get_json(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Make a GET request and return JSON."""

        if endpoint.startswith(("http://", "https://")):
            url = endpoint
        else:
            url = f"{self.base_url}/{endpoint.lstrip('/')}"

        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()

        if not response.content:
            return None

        return response.json()

    def get_paginated_list(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Retrieve all pages from a paginated Canvas endpoint."""

        if endpoint.startswith(("http://", "https://")):
            next_url = endpoint
        else:
            next_url = f"{self.base_url}/{endpoint.lstrip('/')}"

        request_params = dict(params or {})
        request_params.setdefault("per_page", 100)

        results: list[Any] = []

        while next_url:
            response = self.session.get(
                next_url,
                params=request_params,
                timeout=60,
            )
            response.raise_for_status()

            page_data = response.json()

            if isinstance(page_data, list):
                results.extend(page_data)
            else:
                return page_data

            next_url = response.links.get("next", {}).get("url")
            request_params = {}

        return results


def record_error(
    errors: list[dict[str, Any]],
    content_type: str,
    item_name: str,
    error: Exception,
    item_id: Optional[Any] = None,
) -> None:
    """Record a nonfatal export error."""

    errors.append(
        {
            "content_type": content_type,
            "item_name": item_name,
            "item_id": item_id,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    )

    print(
        f"   Warning: Could not completely export "
        f"{content_type} '{item_name}': {error}"
    )


def export_assignments(
    course: Any,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Export all assignments."""

    print("\nExporting assignments...")
    exported_assignments: list[dict[str, Any]] = []

    try:
        assignments = course.get_assignments(
            include=[
                "all_dates",
                "assignment_visibility",
                "overrides",
                "score_statistics",
            ]
        )

        for assignment_summary in assignments:
            assignment_name = getattr(
                assignment_summary,
                "name",
                "Untitled assignment",
            )
            assignment_id = getattr(assignment_summary, "id", None)

            try:
                assignment = course.get_assignment(
                    assignment_id,
                    include=[
                        "all_dates",
                        "assignment_visibility",
                        "overrides",
                        "score_statistics",
                    ],
                )

                assignment_data = canvas_object_to_dict(assignment)
                assignment_data.setdefault(
                    "description",
                    getattr(assignment, "description", None),
                )

                exported_assignments.append(assignment_data)
                print(f"   Exported: {assignment_name}")

            except Exception as error:
                fallback_data = canvas_object_to_dict(assignment_summary)
                fallback_data["_export_warning"] = str(error)
                exported_assignments.append(fallback_data)

                record_error(
                    errors,
                    "assignment",
                    assignment_name,
                    error,
                    assignment_id,
                )

    except Exception as error:
        record_error(
            errors,
            "assignments collection",
            "All assignments",
            error,
        )

    print(f"Exported {len(exported_assignments)} assignments.")
    return exported_assignments


def export_classic_quizzes(
    course: Any,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Export Classic Quizzes and their questions."""

    print("\nExporting Classic Quizzes...")
    exported_quizzes: list[dict[str, Any]] = []

    try:
        quizzes = course.get_quizzes()

        for quiz_summary in quizzes:
            quiz_title = getattr(quiz_summary, "title", "Untitled quiz")
            quiz_id = getattr(quiz_summary, "id", None)

            try:
                quiz = course.get_quiz(quiz_id)
                quiz_data = canvas_object_to_dict(quiz)
                questions: list[dict[str, Any]] = []

                try:
                    for question in quiz.get_questions():
                        questions.append(canvas_object_to_dict(question))

                except Exception as question_error:
                    quiz_data["_question_export_warning"] = str(
                        question_error
                    )

                    record_error(
                        errors,
                        "Classic Quiz questions",
                        quiz_title,
                        question_error,
                        quiz_id,
                    )

                quiz_data["questions"] = questions
                quiz_data["question_count_exported"] = len(questions)

                exported_quizzes.append(quiz_data)

                print(
                    f"   Exported: {quiz_title} "
                    f"({len(questions)} questions)"
                )

            except Exception as error:
                fallback_data = canvas_object_to_dict(quiz_summary)
                fallback_data["questions"] = []
                fallback_data["_export_warning"] = str(error)
                exported_quizzes.append(fallback_data)

                record_error(
                    errors,
                    "Classic Quiz",
                    quiz_title,
                    error,
                    quiz_id,
                )

    except Exception as error:
        record_error(
            errors,
            "Classic Quizzes collection",
            "All Classic Quizzes",
            error,
        )

    print(f"Exported {len(exported_quizzes)} Classic Quizzes.")
    return exported_quizzes


def extract_list_from_response(
    response_data: Any,
    possible_keys: tuple[str, ...],
) -> list[Any]:
    """Extract a list from a Canvas API response."""

    if isinstance(response_data, list):
        return response_data

    if isinstance(response_data, dict):
        for key in possible_keys:
            value = response_data.get(key)

            if isinstance(value, list):
                return value

    return []


def export_new_quizzes(
    rest_client: CanvasRestClient,
    course_id: int,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Export New Quizzes and their items."""

    print("\nExporting New Quizzes...")
    exported_quizzes: list[dict[str, Any]] = []

    list_endpoint = f"/api/quiz/v1/courses/{course_id}/quizzes"

    try:
        response_data = rest_client.get_paginated_list(
            list_endpoint,
            params={"per_page": 100},
        )

        new_quizzes = extract_list_from_response(
            response_data,
            ("quizzes", "quiz_list", "items"),
        )

        for quiz_summary in new_quizzes:
            if not isinstance(quiz_summary, dict):
                continue

            quiz_id = quiz_summary.get("id")
            quiz_title = quiz_summary.get("title", "Untitled New Quiz")

            quiz_data = dict(quiz_summary)
            quiz_data["items"] = []

            try:
                detailed_quiz = rest_client.get_json(
                    f"/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}"
                )

                if isinstance(detailed_quiz, dict):
                    quiz_data.update(detailed_quiz)

            except Exception as detail_error:
                quiz_data["_detail_export_warning"] = str(detail_error)

                record_error(
                    errors,
                    "New Quiz details",
                    quiz_title,
                    detail_error,
                    quiz_id,
                )

            try:
                items_response = rest_client.get_paginated_list(
                    f"/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/items",
                    params={"per_page": 100},
                )

                items = extract_list_from_response(
                    items_response,
                    ("items", "quiz_items"),
                )

                quiz_data["items"] = items
                quiz_data["item_count_exported"] = len(items)

            except Exception as item_error:
                quiz_data["_item_export_warning"] = str(item_error)

                record_error(
                    errors,
                    "New Quiz items",
                    quiz_title,
                    item_error,
                    quiz_id,
                )

            exported_quizzes.append(make_json_safe(quiz_data))

            print(
                f"   Exported: {quiz_title} "
                f"({len(quiz_data.get('items', []))} items)"
            )

    except requests.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status_code in {401, 403, 404}:
            print(
                "   New Quizzes could not be listed. The course may not "
                "contain New Quizzes, or the API token may not have access."
            )
        else:
            record_error(
                errors,
                "New Quizzes collection",
                "All New Quizzes",
                error,
            )

    except Exception as error:
        record_error(
            errors,
            "New Quizzes collection",
            "All New Quizzes",
            error,
        )

    print(f"Exported {len(exported_quizzes)} New Quizzes.")
    return exported_quizzes


def export_pages(
    course: Any,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Export all Canvas Pages, including full HTML bodies."""

    print("\nExporting Canvas Pages...")
    exported_pages: list[dict[str, Any]] = []

    try:
        page_summaries = course.get_pages(
            sort="title",
            order="asc",
            include=["body"],
        )

        for page_summary in page_summaries:
            page_title = getattr(page_summary, "title", "Untitled page")
            page_url = getattr(page_summary, "url", None)
            page_id = getattr(page_summary, "page_id", None)

            try:
                page = course.get_page(page_url)

                page_data = canvas_object_to_dict(page)
                page_data.setdefault(
                    "body",
                    getattr(page, "body", None),
                )

                exported_pages.append(page_data)
                print(f"   Exported: {page_title}")

            except Exception as error:
                fallback_data = canvas_object_to_dict(page_summary)
                fallback_data["_export_warning"] = str(error)
                exported_pages.append(fallback_data)

                record_error(
                    errors,
                    "Canvas Page",
                    page_title,
                    error,
                    page_id or page_url,
                )

    except Exception as error:
        record_error(
            errors,
            "Canvas Pages collection",
            "All Canvas Pages",
            error,
        )

    print(f"Exported {len(exported_pages)} Canvas Pages.")
    return exported_pages


def main() -> None:
    """Connect to Canvas and export the requested course content."""

    course_id = validate_configuration()

    print("=" * 65)
    print("CANVAS COURSE CONTENT EXPORT")
    print("=" * 65)
    print(f"\nConnecting to Canvas: {CANVAS_URL}")

    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
    rest_client = CanvasRestClient(CANVAS_URL, CANVAS_TOKEN)

    try:
        print(f"Fetching course {course_id}...")
        course = canvas.get_course(course_id)

    except Exception as error:
        print("\nCanvas connection failed.")
        print(f"Error: {error}")
        print("\nCheck the following:")
        print("   - CANVAS_URL contains your institution's Canvas URL")
        print("   - CANVAS_TOKEN is valid and has not expired")
        print("   - COURSE_ID is the numeric ID from the course URL")
        print("   - Your Canvas account has access to the course")
        raise

    course_name = getattr(course, "name", "Unknown course")

    if not confirm_course(course_name, course_id):
        print("\nExport canceled. No export file was created.")
        return

    errors: list[dict[str, Any]] = []

    export_data = {
        "export_information": {
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "canvas_url": CANVAS_URL,
            "output_file": str(OUTPUT_FILE),
            "export_format_version": "1.0",
            "included_content": [
                "course_information",
                "assignments",
                "classic_quizzes",
                "classic_quiz_questions",
                "new_quizzes",
                "new_quiz_items",
                "pages",
            ],
        },
        "course": canvas_object_to_dict(course),
        "assignments": export_assignments(course, errors),
        "classic_quizzes": export_classic_quizzes(course, errors),
        "new_quizzes": export_new_quizzes(
            rest_client,
            course_id,
            errors,
        ),
        "pages": export_pages(course, errors),
        "export_errors": errors,
    }

    export_data["summary"] = {
        "assignment_count": len(export_data["assignments"]),
        "classic_quiz_count": len(export_data["classic_quizzes"]),
        "new_quiz_count": len(export_data["new_quizzes"]),
        "page_count": len(export_data["pages"]),
        "error_count": len(errors),
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as json_file:
        json.dump(
            export_data,
            json_file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print("\n" + "=" * 65)
    print("EXPORT COMPLETE")
    print("=" * 65)
    print(f"\nFile: {OUTPUT_FILE.resolve()}")
    print(f"Assignments: {len(export_data['assignments'])}")
    print(f"Classic Quizzes: {len(export_data['classic_quizzes'])}")
    print(f"New Quizzes: {len(export_data['new_quizzes'])}")
    print(f"Pages: {len(export_data['pages'])}")
    print(f"Nonfatal errors: {len(errors)}")

    if errors:
        print(
            "\nThe export completed, but some content could not be retrieved."
        )
        print(
            "Review the 'export_errors' section in the JSON file."
        )
    else:
        print("\nAll available requested content was exported.")


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nExport canceled by user.")
        sys.exit(130)

    except Exception as error:
        print(f"\nExport failed: {error}")
        sys.exit(1)
