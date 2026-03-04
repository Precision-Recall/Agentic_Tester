"""
Firebase Firestore + Storage client for persisting execution results
and fetching test cases.
Uses firebase-admin Python SDK with project agentic-tester-ded1d.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore, storage

from src.models.execution_result import ExecutionResult, ExecutionSummary

logger = logging.getLogger(__name__)


class FirebaseClient:
    """Firebase Firestore and Storage client for the Agentic Tester."""

    def __init__(self, credentials_path: str, project_id: str):
        """Initialize Firebase connection.

        Args:
            credentials_path: Path to the Firebase service account JSON file.
            project_id: Firebase project ID.
        """
        self.project_id = project_id
        self._initialized = False

        try:
            # Check if already initialized
            self.app = firebase_admin.get_app()
            logger.info("Firebase app already initialized")
        except ValueError:
            # Try service account JSON first — resolve relative paths against project root
            cred_path = Path(credentials_path)
            if not cred_path.is_absolute():
                # Resolve relative to project root (this file is at src/storage/firebase_client.py)
                project_root = Path(__file__).resolve().parent.parent.parent
                cred_path = project_root / cred_path.name
            logger.info(f"Looking for Firebase credentials at: {cred_path}")

            if cred_path.exists():
                cred = credentials.Certificate(str(cred_path))
                self.app = firebase_admin.initialize_app(cred, {
                    "projectId": project_id,
                    "storageBucket": f"{project_id}.firebasestorage.app",
                })
                logger.info(f"Firebase initialized with service account: {project_id}")
            else:
                # Fallback: Application Default Credentials (ADC)
                # Works if `gcloud auth` or `firebase login` has been run
                try:
                    self.app = firebase_admin.initialize_app(options={
                        "projectId": project_id,
                        "storageBucket": f"{project_id}.firebasestorage.app",
                    })
                    logger.info(
                        f"Firebase initialized with Application Default Credentials: {project_id}"
                    )
                except Exception as adc_err:
                    logger.warning(
                        f"Firebase credentials not found at {credentials_path} "
                        f"and ADC not available ({adc_err}). "
                        "Running in local-only mode."
                    )
                    self.app = None
                    return

        self.db = firestore.client()
        self._initialized = True

    @property
    def is_connected(self) -> bool:
        """Check if Firebase is properly initialized."""
        return self._initialized and self.app is not None

    # ─── INPUT: Fetch test cases from Firestore ───────────────────────

    async def fetch_project_ids(self) -> list[str]:
        """Fetch all distinct project IDs from Firestore test_cases collection.

        Returns:
            Sorted list of unique project IDs.
        """
        if not self.is_connected:
            logger.error("Firebase not connected. Cannot fetch project IDs.")
            return []

        try:
            docs = self.db.collection("test_cases").stream()
            project_ids = set()
            for doc in docs:
                pid = doc.to_dict().get("project_id")
                if pid:
                    project_ids.add(pid)
            logger.info(f"Found {len(project_ids)} project(s): {sorted(project_ids)}")
            return sorted(project_ids)
        except Exception as e:
            logger.error(f"Failed to fetch project IDs: {e}")
            return []


    async def fetch_test_cases(self, project_id: str) -> list[dict]:
        """Fetch all test cases for a project from Firestore.

        Queries the `test_cases` collection where `project_id` matches.

        Args:
            project_id: The project to fetch test cases for.

        Returns:
            List of test case dictionaries ready to be parsed into TestCase models.
        """
        if not self.is_connected:
            logger.error("Firebase not connected. Cannot fetch test cases.")
            return []

        try:
            # Note: avoid .order_by on a different field than the .where filter
            # as it requires a composite Firestore index. Sort in Python instead.
            docs = (
                self.db.collection("test_cases")
                .where("project_id", "==", project_id)
                .stream()
            )
            test_cases = []
            for doc in docs:
                tc = doc.to_dict()
                # Ensure the doc ID is included as `id` if not already set
                if "id" not in tc or not tc["id"]:
                    tc["id"] = doc.id
                test_cases.append(tc)

            # Sort by priority in Python (high > medium > low)
            priority_order = {"high": 0, "medium": 1, "low": 2}
            test_cases.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))

            logger.info(f"Fetched {len(test_cases)} test cases for project '{project_id}'")
            return test_cases

        except Exception as e:
            logger.error(f"Failed to fetch test cases: {e}")
            return []

    async def fetch_test_case_by_id(self, test_case_id: str) -> Optional[dict]:
        """Fetch a single test case by its document ID.

        Args:
            test_case_id: The Firestore document ID of the test case.

        Returns:
            Test case dictionary, or None if not found.
        """
        if not self.is_connected:
            logger.error("Firebase not connected. Cannot fetch test case.")
            return None

        try:
            doc = self.db.collection("test_cases").document(test_case_id).get()
            if doc.exists:
                tc = doc.to_dict()
                if "id" not in tc or not tc["id"]:
                    tc["id"] = doc.id
                return tc
            logger.warning(f"Test case '{test_case_id}' not found in Firestore.")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch test case '{test_case_id}': {e}")
            return None

    async def fetch_test_suite(self, suite_id: str) -> Optional[dict]:
        """Fetch a test suite from Firestore by ID.

        Reads from the `test_suites` collection. Each suite document is
        expected to contain a `test_case_ids` list. This method also
        resolves those IDs to full test case documents.

        Args:
            suite_id: The Firestore document ID of the test suite.

        Returns:
            Suite dictionary with resolved test cases, or None if not found.
        """
        if not self.is_connected:
            logger.error("Firebase not connected. Cannot fetch test suite.")
            return None

        try:
            doc = self.db.collection("test_suites").document(suite_id).get()
            if not doc.exists:
                logger.warning(f"Test suite '{suite_id}' not found in Firestore.")
                return None

            suite_data = doc.to_dict()
            if "id" not in suite_data or not suite_data["id"]:
                suite_data["id"] = doc.id

            # If suite has test_case_ids, resolve them to full test cases
            test_case_ids = suite_data.get("test_case_ids", [])
            if test_case_ids:
                resolved = []
                for tc_id in test_case_ids:
                    tc = await self.fetch_test_case_by_id(tc_id)
                    if tc:
                        resolved.append(tc)
                suite_data["test_cases"] = resolved
                logger.info(
                    f"Resolved {len(resolved)}/{len(test_case_ids)} "
                    f"test cases for suite '{suite_id}'"
                )

            # If suite already has embedded test_cases (alternative schema), keep them
            elif "test_cases" not in suite_data:
                suite_data["test_cases"] = []

            return suite_data

        except Exception as e:
            logger.error(f"Failed to fetch test suite '{suite_id}': {e}")
            return None

    # ─── OUTPUT: Save results ─────────────────────────────────────────

    async def save_execution_result(self, result: ExecutionResult) -> str:
        """Save an execution result to Firestore.

        Args:
            result: The ExecutionResult to persist.

        Returns:
            The Firestore document ID.
        """
        if not self.is_connected:
            return self._save_local(result)

        doc_ref = self.db.collection("execution_results").document(result.id)
        doc_ref.set(result.model_dump(mode="json"))
        logger.info(f"Saved execution result {result.id} to Firestore")
        return result.id

    async def save_execution_summary(self, summary: ExecutionSummary) -> str:
        """Save an execution summary to Firestore.

        Args:
            summary: The ExecutionSummary to persist.

        Returns:
            The Firestore document ID.
        """
        if not self.is_connected:
            return self._save_local_summary(summary)

        doc_ref = self.db.collection("execution_summaries").document(summary.execution_id)
        doc_ref.set(summary.model_dump(mode="json"))
        logger.info(f"Saved execution summary {summary.execution_id} to Firestore")
        return summary.execution_id

    async def save_execution_audit(self, execution_id: str, audit_data: dict) -> str:
        """Save AI-inferred audit insights (failure analysis) to Firestore.

        Args:
            execution_id: The ID of the execution being audited.
            audit_data: Dictionary containing `inferred_reason`, `severity`, etc.

        Returns:
            The Firestore document ID.
        """
        if not self.is_connected:
            logger.warning("Firebase not connected. Audit not saved.")
            return execution_id

        doc_ref = self.db.collection("execution_audits").document(execution_id)
        doc_ref.set(audit_data)
        logger.info(f"Saved execution audit for {execution_id} to Firestore")
        return execution_id

    async def upload_report(self, file_path: str, execution_id: str) -> Optional[str]:
        """Upload an MD report to Firebase Storage and return the public URL.

        Args:
            file_path: Local path to the MD report file.
            execution_id: The execution ID to associate with the report.

        Returns:
            Public URL of the uploaded file, or None if upload fails.
        """
        if not self.is_connected:
            logger.warning("Firebase not connected. Report stays local.")
            return file_path

        try:
            bucket = storage.bucket(app=self.app)
            blob_name = f"reports/{execution_id}/{Path(file_path).name}"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(file_path, content_type="text/markdown")
            blob.make_public()
            logger.info(f"Uploaded report: {blob.public_url}")

            # Save reference in Firestore
            doc_ref = self.db.collection("execution_reports").document(execution_id)
            doc_ref.set({
                "execution_id": execution_id,
                "report_url": blob.public_url,
                "filename": Path(file_path).name,
                "uploaded_at": datetime.utcnow().isoformat(),
            }, merge=True)

            return blob.public_url
        except Exception as e:
            logger.error(f"Failed to upload report: {e}")
            return file_path

    async def upload_screenshot(self, file_path: str) -> Optional[str]:
        """Upload a screenshot to Firebase Storage.

        Args:
            file_path: Local path to the screenshot file.

        Returns:
            Public URL of the uploaded file, or None if upload fails.
        """
        if not self.is_connected:
            logger.warning("Firebase not connected. Screenshot stays local.")
            return file_path

        try:
            bucket = storage.bucket(app=self.app)
            blob_name = f"screenshots/{Path(file_path).name}"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(file_path)
            blob.make_public()
            logger.info(f"Uploaded screenshot: {blob.public_url}")
            return blob.public_url
        except Exception as e:
            logger.error(f"Failed to upload screenshot: {e}")
            return file_path

    async def get_results(self, project_id: str) -> list[dict]:
        """Query execution results for a project.

        Args:
            project_id: The project to query results for.

        Returns:
            List of execution result dictionaries.
        """
        if not self.is_connected:
            return []

        results = []
        docs = (
            self.db.collection("execution_results")
            .where("test_case_id", ">=", "")  # Get all
            .order_by("executed_at", direction=firestore.Query.DESCENDING)
            .limit(100)
            .stream()
        )
        for doc in docs:
            results.append(doc.to_dict())
        return results

    async def get_result_by_id(self, execution_id: str) -> Optional[dict]:
        """Get a specific execution result by ID.

        Args:
            execution_id: The execution result ID.

        Returns:
            Execution result dictionary or None.
        """
        if not self.is_connected:
            return None

        doc = self.db.collection("execution_results").document(execution_id).get()
        return doc.to_dict() if doc.exists else None

    # ─── Local fallbacks ──────────────────────────────────────────────

    def _save_local(self, result: ExecutionResult) -> str:
        """Fallback: save result to local JSON file."""
        output_dir = Path("./outputs/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{result.id}.json"
        file_path.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
        logger.info(f"Saved execution result locally: {file_path}")
        return result.id

    def _save_local_summary(self, summary: ExecutionSummary) -> str:
        """Fallback: save summary to local JSON file."""
        output_dir = Path("./outputs/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"summary_{summary.execution_id}.json"
        file_path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2))
        logger.info(f"Saved execution summary locally: {file_path}")
        return summary.execution_id
