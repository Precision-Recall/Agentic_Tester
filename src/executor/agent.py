"""
Test Executor Agent — high-level orchestrator for test execution.

Uses LangGraph + Gemini 2.5 Flash-Lite with config-based Playwright MCP.
"""

import time
import uuid
import logging
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import Settings
from src.models.test_case import TestCase, TestSuite
from src.models.execution_result import (
    ExecutionResult,
    ExecutionSummary,
    StepResult,
    TestStatus,
)
from src.executor.mcp_config import create_mcp_client
from src.executor.graph import build_executor_graph
from src.executor.prompts import build_execution_prompt
from src.executor.tools.assertion_tools import CUSTOM_TOOLS

logger = logging.getLogger(__name__)


class TestExecutorAgent:
    """Orchestrates test case execution using LangGraph + Gemini + Playwright MCP."""

    def __init__(self, config: Settings):
        self.config = config
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.0,  # Deterministic for test execution
            max_retries=2,
        )

    async def execute_test(self, test_case: TestCase, target_url: Optional[str] = None) -> ExecutionResult:
        """Execute a single test case using config-based Playwright MCP.

        The MCP client spawns the Playwright server on-demand via stdio,
        loads the browser tools, builds the LangGraph, and runs the agent.

        Args:
            test_case: The test case to execute.
            target_url: Override target URL (defaults to test case URL or config).

        Returns:
            ExecutionResult with status, timing, and step details.
        """
        url = target_url or test_case.url or self.config.TARGET_URL
        execution_id = str(uuid.uuid4())
        start_time = time.time()

        logger.info(f"Executing test case: {test_case.title} (ID: {test_case.id})")
        logger.info(f"Target URL: {url}")

        try:
            # Spawn MCP server on-demand and load tools
            async with create_mcp_client() as client:
                mcp_tools = client.get_tools()
                all_tools = mcp_tools + CUSTOM_TOOLS

                logger.info(f"Loaded {len(mcp_tools)} MCP tools + {len(CUSTOM_TOOLS)} custom tools")

                # Build the LangGraph executor
                graph = build_executor_graph(self.llm, all_tools)

                # Build the execution prompt
                test_dict = test_case.model_dump()
                prompt = build_execution_prompt(test_dict, url)

                # Run the agent
                result = await graph.ainvoke({
                    "messages": [HumanMessage(content=prompt)],
                    "test_case": test_dict,
                    "current_step_index": 0,
                    "step_results": [],
                    "screenshots": [],
                    "final_result": None,
                    "retry_count": 0,
                    "error": None,
                })

                elapsed_ms = (time.time() - start_time) * 1000

                # Parse the agent's final response to determine pass/fail
                return self._parse_execution_result(
                    test_case_id=test_case.id,
                    execution_id=execution_id,
                    agent_result=result,
                    elapsed_ms=elapsed_ms,
                )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(f"Test execution failed with error: {e}")
            return ExecutionResult(
                id=str(uuid.uuid4()),
                test_case_id=test_case.id,
                execution_id=execution_id,
                status=TestStatus.ERROR,
                execution_time_ms=elapsed_ms,
                error_message=str(e),
            )

    async def execute_suite(self, suite: TestSuite) -> ExecutionSummary:
        """Execute all test cases in a suite sequentially.

        Args:
            suite: The test suite containing test cases to execute.

        Returns:
            ExecutionSummary with aggregated results.
        """
        execution_id = str(uuid.uuid4())
        results: list[ExecutionResult] = []

        logger.info(f"Executing test suite: {suite.id} ({len(suite.test_cases)} tests)")

        for i, test_case in enumerate(suite.test_cases, 1):
            logger.info(f"--- Test {i}/{len(suite.test_cases)}: {test_case.title} ---")
            result = await self.execute_test(test_case, target_url=suite.target_url)
            results.append(result)
            logger.info(f"Result: {result.status.value}")

        summary = ExecutionSummary.from_results(execution_id, suite.project_id, results)
        logger.info(
            f"Suite complete: {summary.passed}/{summary.total} passed, "
            f"{summary.failed} failed, {summary.errored} errors"
        )
        return summary

    def _parse_execution_result(
        self,
        test_case_id: str,
        execution_id: str,
        agent_result: dict,
        elapsed_ms: float,
    ) -> ExecutionResult:
        """Parse LangGraph agent output into an ExecutionResult.

        Examines the final messages from the agent to determine overall
        pass/fail status based on the agent's reported results.
        """
        messages = agent_result.get("messages", [])

        # Get the last AI message content
        last_message = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                last_message = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        # Determine status from the agent's final report
        status = TestStatus.PASSED
        error_message = None

        lower_msg = last_message.lower()
        if "failed" in lower_msg or "error" in lower_msg:
            status = TestStatus.FAILED
            # Extract error context
            if "error:" in lower_msg:
                error_idx = lower_msg.index("error:")
                error_message = last_message[error_idx:error_idx + 200]
            elif "failed" in lower_msg:
                error_message = "One or more test steps failed. See execution details."

        return ExecutionResult(
            id=str(uuid.uuid4()),
            test_case_id=test_case_id,
            execution_id=execution_id,
            status=status,
            execution_time_ms=elapsed_ms,
            error_message=error_message,
        )
