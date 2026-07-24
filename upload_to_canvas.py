import json
import os
import argparse
from dotenv import load_dotenv
from canvasapi import Canvas

# Load environment variables from .env file
load_dotenv()

# Retrieve Canvas API credentials from environment variables
CANVAS_URL = os.getenv('CANVAS_URL')
CANVAS_TOKEN = os.getenv('CANVAS_TOKEN')
COURSE_ID_STR = os.getenv('COURSE_ID')

INPUT_FILE = 'zybooks_ready_to_upload.json'
TARGET_GROUP_NAME = 'Assignment Template'

def update_canvas_assignments(is_live):
    # 1. Verify credentials were loaded successfully
    if not CANVAS_URL or not CANVAS_TOKEN or not COURSE_ID_STR:
        print("❌ Error: Missing Canvas credentials. Please check your .env file.")
        return

    # 2. Initialize the Canvas API object
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)

    try:
        # Fetch the specific course using your environment variable
        course = canvas.get_course(COURSE_ID_STR)
    except Exception as e:
        print(f"❌ Error: Could not access course ID {COURSE_ID_STR}. Details: {e}")
        return

    # 3. Read the prepared JSON file
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as file:
            assignments = json.load(file)
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{INPUT_FILE}'.")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: '{INPUT_FILE}' contains invalid JSON.")
        return

    # Display which mode the script is running in
    mode_text = "🔴 LIVE MODE (Actual updates will be saved to Canvas)" if is_live else "🟢 DRY RUN MODE (Safe Mode - No changes will be made)"
    print(f"\n🚀 Starting script in {mode_text}")
    course_name = getattr(course, "name", f"Course {COURSE_ID_STR}")
    print(f"📘 Course: {course_name}")
    print(f"📂 Found {len(assignments)} assignments to process...\n")

    # 4. Check for or create the target assignment group
    print(f"🔍 Checking for assignment group: '{TARGET_GROUP_NAME}'...")
    target_group_id = None
    groups = course.get_assignment_groups()
    
    for group in groups:
        if group.name == TARGET_GROUP_NAME:
            target_group_id = group.id
            print(f"  ✅ Found existing group (ID: {target_group_id}).\n")
            break
            
    if not target_group_id:
        if is_live:
            new_group = course.create_assignment_group(name=TARGET_GROUP_NAME)
            target_group_id = new_group.id
            print(f"  ➕ Created new group '{TARGET_GROUP_NAME}' (ID: {target_group_id}).\n")
        else:
            target_group_id = "<NEW_GROUP_ID_MOCK>"
            print(f"  🔍 [DRY RUN] Would create new group '{TARGET_GROUP_NAME}'.\n")

    success_count = 0
    error_count = 0

    # 5. Loop through each assignment
    for assignment_data in assignments:
        assignment_id = assignment_data.get('id')
        name = assignment_data.get('name', 'Unknown Assignment')
        new_description = assignment_data.get('description', '')
        
        print(f"Target: {name} (ID: {assignment_id})")
        
        if is_live:
            # LIVE MODE: Push the description update, unpublish, and move to group
            try:
                assignment = course.get_assignment(assignment_id)
                assignment.edit(assignment={
                    'name': name,
                    'description': new_description,
                    'published': False,
                    'assignment_group_id': target_group_id
                })
                print("  ✅ Successfully updated, UNPUBLISHED, and MOVED!")
                success_count += 1
            except Exception as e:
                print(f"  ❌ Failed. Error details: {e}")
                error_count += 1
        else:
            # DRY RUN MODE: Only print what would happen
            if new_description == "":
                desc_action = "CLEARED (Empty)"
            else:
                desc_action = f"SET to {len(new_description)} characters"
                
            print(f"  🔍 [DRY RUN] Would update: Description {desc_action}, set to UNPUBLISHED, and MOVE to group '{TARGET_GROUP_NAME}'")
            success_count += 1

    # 6. Print the final summary
    print("\n=================================================================")
    print("PROCESS COMPLETE")
    print("=================================================================")
    
    if is_live:
        print(f"Successfully updated: {success_count}")
        print(f"Failed updates: {error_count}")
    else:
        print(f"Simulated {success_count} updates successfully.")
        print("\n⚠️  Remember: This was a safe mode test.")
        print("To make these actual changes in Canvas, run the command with the --live flag:")
        print("    python upload_to_canvas.py --live")

if __name__ == '__main__':
    # Set up argument parsing to accept the --live flag
    parser = argparse.ArgumentParser(description="Update, unpublish, and move Canvas assignments.")
    parser.add_argument('--live', action='store_true', help="Execute actual API calls to update Canvas")
    args = parser.parse_args()
    
    # Pass the boolean flag into our main function
    update_canvas_assignments(args.live)