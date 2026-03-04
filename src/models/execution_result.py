"""
Execution result data models matching the Firebase execution_results schema.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TestStatus(str, Enum):
    """Test execution status."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class StepResult(BaseModel):
    """Result of a single test step execution."""
    step_index: int = Field(..., description="Index of the step in the test case")
    action: str = Field(..., description="Action that was performed")
    status: TestStatus = Field(..., description="Step execution status")
    screenshot_path: Optional[str] = Field(None, description="Path to step screenshot")
    error: Optional[str] = Field(None, description="Error message if step failed")
    duration_ms: float = Field(0.0, description="Step execution time in milliseconds")
    details: str = Field("", description="Additional execution details")


class ExecutionResult(BaseModel):
    """Full execution result for a single test case.
    Matches Firebase execution_results collection schema.
    """
    id: str = Field(..., description="Unique execution result identifier")
    test_case_id: str = Field(..., description="Reference to the executed test case")
    execution_id: str = Field(..., description="Batch execution identifier")
    status: TestStatus = Field(..., description="Overall test execution status")
    execution_time_ms: float = Field(0.0, description="Total execution time in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if test failed")
    screenshot_url: Optional[str] = Field(None, description="URL/path to final screenshot")
    trace_url: Optional[str] = Field(None, description="URL/path to execution trace")
    step_results: list[StepResult] = Field(default_factory=list, description="Individual step results")
    screenshots: list[str] = Field(default_factory=list, description="Paths to step screenshots")
    report_md_path: Optional[str] = Field(None, description="Path to generated MD execution report")
    executed_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class ExecutionSummary(BaseModel):
    """Aggregated results for a test suite execution run."""
    execution_id: str = Field(..., description="Batch execution identifier")
    project_id: str = Field(..., description="Project identifier")
    total: int = Field(0, description="Total number of test cases")
    passed: int = Field(0, description="Number of passed tests")
    failed: int = Field(0, description="Number of failed tests")
    skipped: int = Field(0, description="Number of skipped tests")
    errored: int = Field(0, description="Number of errored tests")
    total_duration_ms: float = Field(0.0, description="Total execution duration")
    results: list[ExecutionResult] = Field(default_factory=list)
    executed_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_results(cls, execution_id: str, project_id: str, results: list[ExecutionResult]) -> "ExecutionSummary":
        """Create a summary from a list of execution results."""
        return cls(
            execution_id=execution_id,
            project_id=project_id,
            total=len(results),
            passed=sum(1 for r in results if r.status == TestStatus.PASSED),
            failed=sum(1 for r in results if r.status == TestStatus.FAILED),
            skipped=sum(1 for r in results if r.status == TestStatus.SKIPPED),
            errored=sum(1 for r in results if r.status == TestStatus.ERROR),
            total_duration_ms=sum(r.execution_time_ms for r in results),
            results=results,
        )
