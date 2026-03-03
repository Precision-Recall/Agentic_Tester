"""
Agentic Tester — Entry Point

Supports two modes:
  1. CLI (local file): python main.py execute --test-file test_cases.json --url https://example.com
  2. CLI (Firebase):   python main.py execute --from-firebase --project demo-project
  3. Server:           python main.py serve --port 8000
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before anything else
load_dotenv()

from src.config import get_settings
from src.models.test_case import TestCase, TestSuite
from src.executor.agent import TestExecutorAgent
from src.storage.firebase_client import FirebaseClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agentic_tester")


def _print_summary(summary):
    """Print formatted execution summary."""
    print("\n" + "=" * 60)
    print(f"  EXECUTION SUMMARY")
    print("=" * 60)
    print(f"  Total:   {summary.total}")
    print(f"  Passed:  {summary.passed}")
    print(f"  Failed:  {summary.failed}")
    print(f"  Errors:  {summary.errored}")
    print(f"  Duration: {summary.total_duration_ms:.0f}ms")
    print("=" * 60)


def _print_result(test_case, result):
    """Print formatted single test result."""
    print("\n" + "=" * 60)
    print(f"  TEST RESULT: {result.status.value.upper()}")
    print(f"  Test: {test_case.title}")
    print(f"  Duration: {result.execution_time_ms:.0f}ms")
    if result.error_message:
        print(f"  Error: {result.error_message}")
    print("=" * 60)


async def run_execute_from_file(args, settings):
    """Execute test cases from a local JSON file."""
    test_file = Path(args.test_file)
    if not test_file.exists():
        logger.error(f"Test file not found: {test_file}")
        sys.exit(1)

    data = json.loads(test_file.read_text(encoding="utf-8"))
    target_url = args.url or settings.TARGET_URL

    agent = TestExecutorAgent(settings)

    if "test_cases" in data:
        # It's a test suite
        suite = TestSuite(**data)
        if target_url:
            suite.target_url = target_url
        logger.info(f"Loaded test suite with {len(suite.test_cases)} test cases")
        summary = await agent.execute_suite(suite)
        _print_summary(summary)

        # Save summary
        output_dir = settings.get_results_path()
        summary_file = output_dir / f"summary_{summary.execution_id}.json"
        summary_file.write_text(
            json.dumps(summary.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        logger.info(f"Results saved to: {summary_file}")
    else:
        # It's a single test case
        test_case = TestCase(**data)
        logger.info(f"Executing single test: {test_case.title}")
        result = await agent.execute_test(test_case, target_url=target_url)
        _print_result(test_case, result)

        # Save result
        output_dir = settings.get_results_path()
        result_file = output_dir / f"{result.id}.json"
        result_file.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        logger.info(f"Result saved to: {result_file}")


async def run_execute_from_firebase(args, settings):
    """Execute test cases fetched from Firebase Firestore."""
    project_id = args.project
    if not project_id:
        logger.error("--project is required when using --from-firebase")
        sys.exit(1)

    # Initialize Firebase client
    firebase = FirebaseClient(
        credentials_path=settings.FIREBASE_CREDENTIALS_PATH,
        project_id=settings.FIREBASE_PROJECT_ID,
    )

    if not firebase.is_connected:
        logger.error(
            "Firebase is not connected. Please check your credentials file "
            f"at {settings.FIREBASE_CREDENTIALS_PATH}"
        )
        sys.exit(1)

    logger.info(f"Fetching test cases from Firebase for project: {project_id}")

    # Fetch test cases
    if args.suite_id:
        # Fetch a specific suite
        suite_data = await firebase.fetch_test_suite(args.suite_id)
        if not suite_data:
            logger.error(f"Test suite '{args.suite_id}' not found in Firestore.")
            sys.exit(1)

        suite = TestSuite(**suite_data)
        logger.info(f"Loaded suite '{args.suite_id}' with {len(suite.test_cases)} test cases from Firebase")
    else:
        # Fetch all test cases for the project
        test_case_dicts = await firebase.fetch_test_cases(project_id)
        if not test_case_dicts:
            logger.error(f"No test cases found in Firebase for project '{project_id}'")
            sys.exit(1)

        test_cases = [TestCase(**tc) for tc in test_case_dicts]
        target_url = args.url or settings.TARGET_URL
        suite = TestSuite(
            id=f"firebase-{project_id}",
            project_id=project_id,
            test_cases=test_cases,
            target_url=target_url,
        )
        logger.info(f"Loaded {len(test_cases)} test cases from Firebase for project '{project_id}'")

    # Override target URL if provided
    if args.url:
        suite.target_url = args.url

    # Execute
    agent = TestExecutorAgent(settings)
    summary = await agent.execute_suite(suite)
    _print_summary(summary)

    # Save summary locally
    output_dir = settings.get_results_path()
    summary_file = output_dir / f"summary_{summary.execution_id}.json"
    summary_file.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    logger.info(f"Results saved to: {summary_file}")

    # Also persist results back to Firebase
    try:
        for result in summary.results:
            await firebase.save_execution_result(result)
        await firebase.save_execution_summary(summary)
        logger.info("Results persisted to Firebase")
    except Exception as e:
        logger.warning(f"Failed to persist results to Firebase: {e}")


async def run_execute(args):
    """Execute test cases (from file or Firebase)."""
    settings = get_settings()

    if args.from_firebase:
        await run_execute_from_firebase(args, settings)
    else:
        if not args.test_file:
            logger.error("Either --test-file or --from-firebase is required")
            sys.exit(1)
        await run_execute_from_file(args, settings)


def run_serve(args):
    """Start the FastAPI server."""
    import uvicorn
    from src.api.app import app

    port = args.port or 8000
    logger.info(f"Starting Agentic Tester API on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Tester — AI-driven E2E Test Executor",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Execute command
    exec_parser = subparsers.add_parser("execute", help="Execute test cases")
    exec_parser.add_argument(
        "--test-file", "-f",
        default=None,
        help="Path to test cases JSON file (for local mode)",
    )
    exec_parser.add_argument(
        "--url", "-u",
        default=None,
        help="Target URL override (defaults to .env TARGET_URL)",
    )
    exec_parser.add_argument(
        "--from-firebase",
        action="store_true",
        default=False,
        help="Fetch test cases from Firebase Firestore instead of a local file",
    )
    exec_parser.add_argument(
        "--project", "-p",
        default=None,
        help="Firebase project ID to fetch test cases for (required with --from-firebase)",
    )
    exec_parser.add_argument(
        "--suite-id",
        default=None,
        help="Specific test suite ID to fetch from Firebase (optional)",
    )

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI API server")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)",
    )

    # TUI command
    subparsers.add_parser("tui", help="Launch interactive TUI for Firebase test selection")

    args = parser.parse_args()

    if args.command == "execute":
        asyncio.run(run_execute(args))
    elif args.command == "serve":
        run_serve(args)
    elif args.command == "tui":
        from src.tui.tui import run_tui
        run_tui(get_settings())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
