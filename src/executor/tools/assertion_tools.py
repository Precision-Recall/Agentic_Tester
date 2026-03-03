"""
Custom assertion tools for the executor agent.
These are standard LangChain @tool functions that complement the
Playwright MCP tools with test-specific verification capabilities.
"""

from langchain_core.tools import tool


@tool
def report_step_result(
    step_index: int,
    step_action: str,
    status: str,
    details: str = "",
    error: str = "",
) -> str:
    """Report the result of a test step execution.

    Args:
        step_index: The 1-based index of the step.
        step_action: The action that was performed (e.g., 'navigate', 'click').
        status: The result status — must be 'passed' or 'failed'.
        details: Additional details about the step execution.
        error: Error message if the step failed.

    Returns:
        Confirmation string with step result.
    """
    status = status.lower().strip()
    if status not in ("passed", "failed"):
        status = "failed"

    result = f"Step {step_index} [{step_action}]: {status.upper()}"
    if details:
        result += f" — {details}"
    if error:
        result += f" | Error: {error}"
    return result


@tool
def report_test_result(
    test_case_id: str,
    overall_status: str,
    summary: str,
    total_steps: int,
    passed_steps: int,
    failed_steps: int,
) -> str:
    """Report the final result of a complete test case execution.

    Call this AFTER all steps have been executed to provide the final summary.

    Args:
        test_case_id: The ID of the test case that was executed.
        overall_status: Overall result — 'passed' or 'failed'.
        summary: Human-readable summary of the test execution.
        total_steps: Total number of steps in the test case.
        passed_steps: Number of steps that passed.
        failed_steps: Number of steps that failed.

    Returns:
        Final test result summary string.
    """
    overall_status = overall_status.lower().strip()
    return (
        f"TEST RESULT: {overall_status.upper()}\n"
        f"Test Case: {test_case_id}\n"
        f"Steps: {passed_steps}/{total_steps} passed, {failed_steps} failed\n"
        f"Summary: {summary}"
    )


# Collect all custom tools for easy import
CUSTOM_TOOLS = [report_step_result, report_test_result]
