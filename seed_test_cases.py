"""
Temporary script to seed Firebase Firestore with sample test cases
targeting Wikipedia (https://en.wikipedia.org).

Usage:
    python seed_test_cases.py
"""

import json
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore

from src.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Sample test cases targeting Wikipedia ────────────────────────────

TEST_CASES = [
    {
        "id": "tc-wiki-001",
        "project_id": "wikipedia-tests",
        "title": "Verify Wikipedia Homepage Loads",
        "description": "Navigate to Wikipedia homepage and verify the logo and search bar are present.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Main_Page",
                "description": "Navigate to Wikipedia Main Page"
            },
            {
                "action": "assert",
                "expected": "Wikipedia",
                "description": "Verify the page title contains 'Wikipedia'"
            },
            {
                "action": "snapshot",
                "description": "Take a snapshot of the homepage"
            }
        ],
        "expected_result": "Wikipedia Main Page loads with logo and search bar visible",
        "priority": "high",
        "category": "functional"
    },
    {
        "id": "tc-wiki-002",
        "project_id": "wikipedia-tests",
        "title": "Search for 'Artificial Intelligence' on Wikipedia",
        "description": "Use the search bar to search for 'Artificial Intelligence' and verify results.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Main_Page",
                "description": "Navigate to Wikipedia Main Page"
            },
            {
                "action": "fill",
                "selector": "input#searchInput",
                "value": "Artificial Intelligence",
                "description": "Type 'Artificial Intelligence' in the search box"
            },
            {
                "action": "click",
                "selector": "button.cdx-button",
                "description": "Click the search button"
            },
            {
                "action": "assert",
                "expected": "Artificial intelligence",
                "description": "Verify the article title is 'Artificial intelligence'"
            }
        ],
        "expected_result": "The Artificial Intelligence article page loads",
        "priority": "high",
        "category": "functional"
    },
    {
        "id": "tc-wiki-003",
        "project_id": "wikipedia-tests",
        "title": "Verify Wikipedia Navigation Sidebar",
        "description": "Check that the navigation sidebar contains expected links like 'Main page', 'Contents', 'Current events'.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Main_Page",
                "description": "Navigate to Wikipedia Main Page"
            },
            {
                "action": "snapshot",
                "description": "Take a DOM snapshot to inspect sidebar"
            },
            {
                "action": "assert",
                "selector": "#n-mainpage-description a",
                "expected": "Main page",
                "description": "Verify 'Main page' link exists in sidebar"
            },
            {
                "action": "assert",
                "selector": "#n-contents a",
                "expected": "Contents",
                "description": "Verify 'Contents' link exists in sidebar"
            }
        ],
        "expected_result": "Sidebar contains navigation links",
        "priority": "medium",
        "category": "ui"
    },
    {
        "id": "tc-wiki-004",
        "project_id": "wikipedia-tests",
        "title": "Verify Wikipedia Article Has Table of Contents",
        "description": "Navigate to a long article and check that it has a table of contents.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Python_(programming_language)",
                "description": "Navigate to the Python programming language article"
            },
            {
                "action": "assert",
                "expected": "Python (programming language)",
                "description": "Verify article title"
            },
            {
                "action": "snapshot",
                "description": "Take a snapshot to inspect the page"
            },
            {
                "action": "assert",
                "selector": "#toc, .toc, [id*='toc']",
                "expected": "Contents",
                "description": "Verify table of contents is present"
            }
        ],
        "expected_result": "Article loads with a table of contents",
        "priority": "medium",
        "category": "ui"
    },
    {
        "id": "tc-wiki-005",
        "project_id": "wikipedia-tests",
        "title": "Verify 'Random Article' Link Works",
        "description": "Click the 'Random article' link in the sidebar and verify a new article loads.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Main_Page",
                "description": "Navigate to Wikipedia Main Page"
            },
            {
                "action": "click",
                "selector": "#n-randompage a",
                "description": "Click the 'Random article' link"
            },
            {
                "action": "snapshot",
                "description": "Take a snapshot of the random article"
            },
            {
                "action": "assert",
                "expected": "Wikipedia",
                "description": "Verify we are still on Wikipedia (title contains 'Wikipedia')"
            }
        ],
        "expected_result": "A random Wikipedia article loads successfully",
        "priority": "low",
        "category": "functional"
    },
    {
        "id": "tc-wiki-006",
        "project_id": "wikipedia-tests",
        "title": "Verify Wikipedia Language Links",
        "description": "Check that the Main Page has language links available.",
        "steps": [
            {
                "action": "navigate",
                "value": "https://en.wikipedia.org/wiki/Main_Page",
                "description": "Navigate to Wikipedia Main Page"
            },
            {
                "action": "snapshot",
                "description": "Take a snapshot to inspect language links"
            },
            {
                "action": "assert",
                "selector": "#p-lang, .interlanguage-links, [class*='language']",
                "expected": "",
                "description": "Verify language links section exists"
            }
        ],
        "expected_result": "Language links section is present on the page",
        "priority": "low",
        "category": "ui"
    }
]


def seed_firestore():
    """Upload test cases to Firestore."""
    settings = get_settings()

    # Initialize Firebase
    cred_path = settings.FIREBASE_CREDENTIALS_PATH
    # Resolve relative paths against the project root (script directory)
    cred_path_resolved = Path(cred_path)
    if not cred_path_resolved.is_absolute():
        cred_path_resolved = Path(__file__).parent / cred_path

    logger.info(f"Looking for credentials at: {cred_path_resolved.resolve()}")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        if cred_path_resolved.exists():
            cred = credentials.Certificate(str(cred_path_resolved))
            app = firebase_admin.initialize_app(cred, {
                "projectId": settings.FIREBASE_PROJECT_ID,
            })
        else:
            # Try Application Default Credentials
            try:
                app = firebase_admin.initialize_app(options={
                    "projectId": settings.FIREBASE_PROJECT_ID,
                })
                logger.info("Using Application Default Credentials")
            except Exception as e:
                logger.error(
                    f"Firebase credentials not found at '{cred_path}' "
                    f"and ADC not available ({e}).\n"
                    "Option 1: Run 'gcloud auth application-default login'\n"
                    "Option 2: Download service account key from Firebase Console\n\n"
                    "Falling back to saving test cases as a local JSON file..."
                )
                save_local()
                return

    db = firestore.client()

    logger.info(f"Seeding {len(TEST_CASES)} test cases into Firestore...")

    for tc in TEST_CASES:
        doc_ref = db.collection("test_cases").document(tc["id"])
        doc_ref.set(tc)
        logger.info(f"  ✅ {tc['id']} — {tc['title']}")

    logger.info(f"\nDone! {len(TEST_CASES)} test cases seeded for project 'wikipedia-tests'.")
    logger.info("You can now run: python main.py tui")
    logger.info("Enter project ID: wikipedia-tests")


def save_local():
    """Fallback: save test cases as a local JSON file."""
    output = {
        "id": "suite-wikipedia",
        "project_id": "wikipedia-tests",
        "target_url": "https://en.wikipedia.org",
        "test_cases": TEST_CASES,
    }
    out_path = Path("wikipedia_test_cases.json")
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    logger.info(f"Saved {len(TEST_CASES)} test cases to: {out_path}")
    logger.info("You can run: python main.py execute --test-file wikipedia_test_cases.json")


if __name__ == "__main__":
    seed_firestore()
