"""
Execution API routes for the Agentic Tester.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config import get_settings
from src.models.test_case import TestCase, TestSuite
from src.models.execution_result import ExecutionResult, ExecutionSummary
from src.executor.agent import TestExecutorAgent
from src.storage.firebase_client import FirebaseClient

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response Models ---

class ExecuteTestRequest(BaseModel):
    """Request body for executing a single test case."""
    test_case: TestCase
    target_url: Optional[str] = None


class ExecuteTestsRequest(BaseModel):
    """Request body for executing multiple test cases."""
    test_suite: TestSuite


class ExecuteFromFirebaseRequest(BaseModel):
    """Request body for executing test cases fetched from Firebase."""
    target_url: Optional[str] = None
    test_case_ids: Optional[list[str]] = Field(
        None,
        description="Optional list of specific test case IDs to execute. "
                    "If omitted, all test cases for the project are executed.",
    )
    suite_id: Optional[str] = Field(
        None,
        description="Optional suite ID. If provided, fetch and execute that suite.",
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.1.0"
    firebase_connected: bool = False


# --- Endpoints ---

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    from src.api.app import app_state
    firebase: Optional[FirebaseClient] = app_state.get("firebase")
    return HealthResponse(
        firebase_connected=firebase.is_connected if firebase else False,
    )


@router.get("/projects/{project_id}/test-cases")
async def get_test_cases(project_id: str):
    """Fetch test cases for a project from Firebase Firestore.

    Args:
        project_id: The project to fetch test cases for.

    Returns:
        List of test case dictionaries from Firestore.
    """
    from src.api.app import app_state
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    if not firebase or not firebase.is_connected:
        raise HTTPException(status_code=503, detail="Firebase not connected")

    test_cases = await firebase.fetch_test_cases(project_id)
    return {"project_id": project_id, "count": len(test_cases), "test_cases": test_cases}


@router.post("/projects/{project_id}/execute-test", response_model=ExecutionResult)
async def execute_single_test(project_id: str, request: ExecuteTestRequest):
    """Execute a single test case.

    Args:
        project_id: The project this test belongs to.
        request: Test case and optional target URL override.

    Returns:
        ExecutionResult with status and details.
    """
    from src.api.app import app_state
    settings = app_state.get("settings", get_settings())
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    try:
        agent = TestExecutorAgent(settings)
        result = await agent.execute_test(request.test_case, request.target_url)

        # Persist to Firebase
        if firebase:
            await firebase.save_execution_result(result)

        return result

    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/execute-tests", response_model=ExecutionSummary)
async def execute_test_suite(project_id: str, request: ExecuteTestsRequest):
    """Execute a full test suite.

    Args:
        project_id: The project this suite belongs to.
        request: Test suite with test cases.

    Returns:
        ExecutionSummary with aggregated results.
    """
    from src.api.app import app_state
    settings = app_state.get("settings", get_settings())
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    try:
        agent = TestExecutorAgent(settings)
        summary = await agent.execute_suite(request.test_suite)

        # Persist results to Firebase
        if firebase:
            for result in summary.results:
                await firebase.save_execution_result(result)
            await firebase.save_execution_summary(summary)

        return summary

    except Exception as e:
        logger.error(f"Suite execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/execute-from-firebase", response_model=ExecutionSummary)
async def execute_from_firebase(project_id: str, request: ExecuteFromFirebaseRequest):
    """Fetch test cases from Firebase and execute them.

    This endpoint combines fetching test cases from Firestore and executing
    them in a single call. Optionally filter by specific test case IDs or
    run a specific suite.

    Args:
        project_id: The project to fetch and execute test cases for.
        request: Optional filters (test_case_ids, suite_id, target_url).

    Returns:
        ExecutionSummary with aggregated results.
    """
    from src.api.app import app_state
    settings = app_state.get("settings", get_settings())
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    if not firebase or not firebase.is_connected:
        raise HTTPException(status_code=503, detail="Firebase not connected")

    try:
        # Fetch test cases from Firebase
        if request.suite_id:
            suite_data = await firebase.fetch_test_suite(request.suite_id)
            if not suite_data:
                raise HTTPException(
                    status_code=404,
                    detail=f"Test suite '{request.suite_id}' not found",
                )
            suite = TestSuite(**suite_data)
        else:
            # Fetch all or filtered test cases
            all_test_cases = await firebase.fetch_test_cases(project_id)

            if request.test_case_ids:
                # Filter to specific IDs
                all_test_cases = [
                    tc for tc in all_test_cases
                    if tc.get("id") in request.test_case_ids
                ]

            if not all_test_cases:
                raise HTTPException(
                    status_code=404,
                    detail=f"No test cases found for project '{project_id}'",
                )

            test_cases = [TestCase(**tc) for tc in all_test_cases]
            target_url = request.target_url or settings.TARGET_URL
            suite = TestSuite(
                id=f"firebase-{project_id}",
                project_id=project_id,
                test_cases=test_cases,
                target_url=target_url,
            )

        if request.target_url:
            suite.target_url = request.target_url

        logger.info(
            f"Executing {len(suite.test_cases)} test cases from Firebase "
            f"for project '{project_id}'"
        )

        # Execute
        agent = TestExecutorAgent(settings)
        summary = await agent.execute_suite(suite)

        # Persist results back to Firebase
        for result in summary.results:
            await firebase.save_execution_result(result)
        await firebase.save_execution_summary(summary)

        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Firebase execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/results")
async def get_results(project_id: str):
    """Get execution results for a project.

    Args:
        project_id: The project to query results for.

    Returns:
        List of execution results.
    """
    from src.api.app import app_state
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    if not firebase or not firebase.is_connected:
        raise HTTPException(status_code=503, detail="Firebase not connected")

    results = await firebase.get_results(project_id)
    return results


@router.get("/projects/{project_id}/results/{execution_id}")
async def get_result_detail(project_id: str, execution_id: str):
    """Get a specific execution result.

    Args:
        project_id: The project identifier.
        execution_id: The execution result ID.

    Returns:
        Execution result details.
    """
    from src.api.app import app_state
    firebase: Optional[FirebaseClient] = app_state.get("firebase")

    if not firebase or not firebase.is_connected:
        raise HTTPException(status_code=503, detail="Firebase not connected")

    result = await firebase.get_result_by_id(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution result not found")

    return result
