# zyBooks Canvas Course Automation System

A Python-based workflow that uses the Canvas API to prepare reusable Canvas course templates and configure newly imported zyBooks assignments.

The system is designed primarily for instructors who regularly prepare 8-week and 16-week Canvas courses using zyBooks. It reduces the repetitive work involved in creating assignment placeholders, building semester schedules, applying assignment instructions, setting due dates, organizing assignments, publishing content, and removing temporary course-template items.

## Project Overview

The system uses a two-part workflow.

### Part 1: Download zyBook Assignments

Part 1 once you have downloaded this Repo you will need to download the zyBook Assignments from your zyBook. Instructions are in the [user guide](https://docs.google.com/document/d/1Bb7GmNe1R2CU2lEyqnv5ApVvDndPat3J/edit?usp=sharing&ouid=115508625765389809270&rtpof=true&sd=true).


### Part 2: Course Configuration

Part 2 configures newly imported zyBooks assignments in a copied Canvas course.

It:

* Generates semester assignment dates
* Creates separate R&P and CA due dates and times
* Supports chapter variations such as `Ch1a` and `Ch1b`
* Applies standardized HTML assignment descriptions
* Sets due dates and lock dates
* Places assignments into the correct assignment group
* Publishes imported assignments
* Places assignments beneath their matching placeholders
* Safely removes verified placeholders
* Identifies empty modules and assignment groups for optional cleanup

## Project Status

This is a completed and tested project.

The automated schedule generator currently supports standard 8-week and 16-week course pacing.

The workflow has also been tested successfully with a 10-week course. For course lengths other than 8 or 16 weeks, the generated `semester_dates.csv` file can be manually adjusted before the assignment configuration is applied.

A planned future enhancement is to allow instructors to generate schedules automatically for additional course lengths.

## User Guide 

Complete setup, operating, verification, and troubleshooting instructions are available in the:

[Mesa CC CIS Blueprint Canvas Course zyBook Automation System User Guide](https://docs.google.com/document/d/1wTXeAjO6-IEqiqb9vbfO2oBCa9-itUXx/edit?usp=sharing&ouid=115508625765389809270&rtpof=true&sd=true)

Review the user guide before running the workflow for the first time.

## Requirements

You will need:

* A GitHub account
* GitHub Codespaces or VS Code with Dev Containers
* A Canvas account with API access
* Permission to modify the target Canvas course
* A Canvas API token
* The numeric Canvas course ID
* A Canvas course containing the required zyBooks assignments or placeholders

## Create a Repository from This Template

1. Select **Use this template** on GitHub.
2. Create a new repository.
3. Open the new repository in GitHub Codespaces.
4. Wait for the development container to finish loading.
5. Add the required Canvas credentials.

## Configure Canvas Credentials

In the GitHub repository, go to:

**Settings → Secrets and variables → Codespaces**

Create the following secrets:

```text
CANVAS_URL
CANVAS_TOKEN
COURSE_ID
```

Example values:

```text
CANVAS_URL=https://your-institution.instructure.com
CANVAS_TOKEN=your_canvas_api_token
COURSE_ID=123456
```

Do not place real credentials directly in the Python files.

## Test the Canvas Connection

Run:

```text
python canvas_template.py
```

Confirm that the terminal displays:

* A successful Canvas connection
* The expected course name
* The expected course ID
* The course module names

Stop if the wrong course is displayed.

## Important Safety Information

Several scripts can modify or permanently delete Canvas course content.

Always:

* Run the dry-run version of a script before using `--live`
* Confirm that the correct Canvas course is connected
* Review skipped, missing, duplicate, and ambiguous results
* Manually verify Canvas after each live operation
* Keep a clean reusable course template or backup

Do not run a live command when the dry-run output is unexpected.

## Supported Assignment Names

The workflow supports zyBooks assignment names beginning with patterns such as:

```text
M1 Ch1a R&P
M1 Ch1b CA
M2 Ch2 R&P
M2 Ch2 CA
```

Placeholder assignments include the word:

```text
Placeholder
```

Do not manually rename newly imported zyBooks assignments before running the Part 2 workflow.

## Security

Treat the Canvas API token like a password.

Never commit or share:

* Canvas API tokens
* `.env` files
* Codespaces secret values
* Student information
* Course exports containing protected or private information

If a token is exposed, revoke it in Canvas and create a new one immediately.

## Disclaimer

This project is not affiliated with, endorsed by, or maintained by Instructure or zyBooks.

Canvas, Instructure, and zyBooks are trademarks of their respective owners.

Users are responsible for protecting credentials, following institutional policies, reviewing all proposed changes, and verifying Canvas after live operations.


Canvas, Instructure, and zyBooks are trademarks of their respective owners.

Users are responsible for protecting credentials, following institutional policies, reviewing all proposed changes, and verifying Canvas after live operations.

