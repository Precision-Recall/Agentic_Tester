"""
Test Executor Agent — high-level orchestrator for test execution.

Uses LangGraph + Gemini with config-based Playwright MCP.
Generates per-test MD reports with screenshots and an inference MD report.
"""

import asyncio
import json
import time
import uuid
import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

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

    def __init__(self, config: Settings, mcp_client: Optional[MultiServerMCPClient] = None):
        self.config = config
        self.mcp_client = mcp_client
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.0,
            max_retries=2,
        )

    async def execute_test(
        self,
        test_case: TestCase,
        target_url: Optional[str] = None,
        run_dir: Optional[Path] = None,
    ) -> ExecutionResult:
        """Execute a single test case, capture screenshots, and generate an MD report.

        Args:
            test_case: The test case to execute.
            target_url: Override target URL.
            run_dir: Directory to store screenshots and MD reports.

        Returns:
            ExecutionResult with status, timing, report path, and screenshot paths.
        """
        url = target_url or test_case.url or self.config.TARGET_URL
        execution_id = str(uuid.uuid4())
        start_time = time.time()

        logger.info(f"Executing test case: {test_case.title} (ID: {test_case.id})")
        logger.info(f"Target URL: {url}")

        try:
            client = self.mcp_client or create_mcp_client()
            mcp_tools = await client.get_tools()
            all_tools = mcp_tools + CUSTOM_TOOLS

            if not self.mcp_client:
                logger.info(f"Loaded {len(mcp_tools)} MCP tools (on-demand connection)")
            else:
                logger.info(f"Using global MCP connection ({len(mcp_tools)} tools)")

            graph = build_executor_graph(self.llm, all_tools)

            test_dict = test_case.model_dump()
            prompt = build_execution_prompt(test_dict, url)

            # Retry with exponential backoff for 429 quota errors
            invoke_input = {
                "messages": [HumanMessage(content=prompt)],
                "test_case": test_dict,
                "current_step_index": 0,
                "step_results": [],
                "screenshots": [],
                "final_result": None,
                "retry_count": 0,
                "error": None,
            }
            result = await self._invoke_with_retry(graph, invoke_input)

            elapsed_ms = (time.time() - start_time) * 1000

            # Extract screenshots from the agent message history
            screenshots = self._extract_screenshots(result, test_case.id, run_dir)

            # Parse the execution result
            exec_result = self._parse_execution_result(
                test_case_id=test_case.id,
                execution_id=execution_id,
                agent_result=result,
                elapsed_ms=elapsed_ms,
                screenshots=screenshots,
            )

            # Generate MD report if run_dir is provided
            if run_dir:
                report_path = self._generate_execution_report(
                    test_case=test_case,
                    result=exec_result,
                    messages=result.get("messages", []),
                    run_dir=run_dir,
                    target_url=url,
                )
                exec_result.report_md_path = str(report_path)

            return exec_result

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(f"Test execution failed with error: {e}")

            exec_result = ExecutionResult(
                id=str(uuid.uuid4()),
                test_case_id=test_case.id,
                execution_id=execution_id,
                status=TestStatus.ERROR,
                execution_time_ms=elapsed_ms,
                error_message=str(e),
            )

            # Still generate a report for errors
            if run_dir:
                report_path = self._generate_execution_report(
                    test_case=test_case,
                    result=exec_result,
                    messages=[],
                    run_dir=run_dir,
                    target_url=url,
                )
                exec_result.report_md_path = str(report_path)

            return exec_result

    async def _invoke_with_retry(self, graph, invoke_input: dict, max_retries: int = 3) -> dict:
        """Invoke the graph with exponential backoff on 429 quota errors."""
        backoff_seconds = [30, 60, 120]
        for attempt in range(max_retries + 1):
            try:
                return await graph.ainvoke(invoke_input)
            except Exception as e:
                err_str = str(e).lower()
                is_quota = "429" in err_str or "quota" in err_str or "rate" in err_str or "resource_exhausted" in err_str
                if is_quota and attempt < max_retries:
                    wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                    logger.warning(f"Quota exceeded (attempt {attempt+1}/{max_retries}). Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise

    def _extract_screenshots(
        self, agent_result: dict, test_case_id: str, run_dir: Optional[Path]
    ) -> list[str]:
        """Extract screenshot data from agent tool call results and save to disk."""
        screenshots = []
        if not run_dir:
            return screenshots

        ss_dir = run_dir / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)

        messages = agent_result.get("messages", [])
        ss_index = 0

        for msg in messages:
            # Tool messages may contain screenshot data
            if hasattr(msg, "name") and "screenshot" in str(getattr(msg, "name", "")).lower():
                content = msg.content if hasattr(msg, "content") else ""
                if content:
                    ss_index += 1
                    ss_path = ss_dir / f"{test_case_id}_step_{ss_index}.png"
                    try:
                        # Try to decode if it's base64
                        if isinstance(content, str) and len(content) > 100:
                            # Clean potential data URI prefix
                            data = content
                            if "base64," in data:
                                data = data.split("base64,")[1]
                            img_data = base64.b64decode(data)
                            ss_path.write_bytes(img_data)
                            screenshots.append(str(ss_path))
                            logger.info(f"Saved screenshot: {ss_path}")
                    except Exception:
                        # If not base64, save as text reference
                        ss_path = ss_path.with_suffix(".txt")
                        ss_path.write_text(str(content)[:500], encoding="utf-8")
                        screenshots.append(str(ss_path))

        return screenshots

    def _generate_execution_report(
        self,
        test_case: TestCase,
        result: ExecutionResult,
        messages: list,
        run_dir: Path,
        target_url: str,
    ) -> Path:
        """Generate a detailed Markdown execution report for a test case."""
        report_path = run_dir / f"{test_case.id}_report.md"
        now = datetime.now()

        status_emoji = {
            TestStatus.PASSED: "PASS",
            TestStatus.FAILED: "FAIL",
            TestStatus.ERROR: "ERROR",
            TestStatus.SKIPPED: "SKIP",
        }

        # Extract action timeline from messages
        actions = self._extract_action_timeline(messages)

        lines = [
            f"# Execution Report: {test_case.title}",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Test ID | `{test_case.id}` |",
            f"| Status | **{status_emoji.get(result.status, '?')}** |",
            f"| Target URL | {target_url} |",
            f"| Duration | {result.execution_time_ms:.0f}ms |",
            f"| Timestamp | {now.isoformat()} |",
            f"| Priority | {test_case.priority} |",
            "",
            "## Test Description",
            f"{test_case.description}",
            "",
            "## Steps Defined",
            "",
        ]

        for i, step in enumerate(test_case.steps, 1):
            lines.append(f"{i}. **{step.action}**")
            if step.selector:
                lines.append(f"   - Target: `{step.selector}`")
            if step.value:
                lines.append(f"   - Value: `{step.value}`")
            if step.expected:
                lines.append(f"   - Expected: {step.expected}")

        lines.extend(["", "## Execution Timeline", ""])

        if actions:
            lines.append("| # | Action | Details | Result |")
            lines.append("|---|--------|---------|--------|")
            for a in actions:
                lines.append(
                    f"| {a['index']} | {a['action']} | {a['details'][:60]} | {a['result']} |"
                )
        else:
            lines.append("_No detailed action timeline available._")

        # Screenshots section
        if result.screenshots:
            lines.extend(["", "## Screenshots", ""])
            for ss in result.screenshots:
                ss_name = Path(ss).name
                lines.append(f"- `{ss_name}` — {ss}")

        # Error section
        if result.error_message:
            lines.extend([
                "",
                "## What Stopped the Execution",
                "",
                f"```",
                result.error_message,
                "```",
                "",
                "The test execution was interrupted due to the error above. "
                "Common causes include: network timeouts, quota limits, "
                "missing page elements, or incorrect selectors.",
            ])

        # Final verdict
        lines.extend([
            "",
            "## Verdict",
            "",
            f"**{status_emoji.get(result.status, 'UNKNOWN')}** — "
            f"Completed in {result.execution_time_ms:.0f}ms",
        ])

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Generated execution report: {report_path}")
        return report_path

    def _extract_action_timeline(self, messages: list) -> list[dict]:
        """Extract a timeline of actions from the agent's message history."""
        actions = []
        index = 0

        for msg in messages:
            # Look for tool calls (AI messages that invoked tools)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    index += 1
                    action_name = tc.get("name", "unknown")
                    args = tc.get("args", {})

                    # Summarize the action
                    details = ""
                    if "url" in args:
                        details = f"URL: {args['url']}"
                    elif "selector" in args:
                        details = f"Selector: {args['selector']}"
                    elif "text" in args:
                        details = f"Text: {args['text'][:40]}"
                    elif "value" in args:
                        details = f"Value: {args['value'][:40]}"
                    else:
                        details = json.dumps(args)[:60]

                    actions.append({
                        "index": index,
                        "action": action_name,
                        "details": details,
                        "result": "executed",
                    })

            # Look for tool results (to mark pass/fail)
            if hasattr(msg, "name") and hasattr(msg, "content"):
                tool_name = getattr(msg, "name", "")
                content = str(getattr(msg, "content", ""))

                if "report_step_result" in str(tool_name):
                    if actions:
                        if "PASSED" in content.upper():
                            actions[-1]["result"] = "PASS"
                        elif "FAILED" in content.upper():
                            actions[-1]["result"] = "FAIL"

        return actions

    async def execute_suite(self, suite: TestSuite) -> ExecutionSummary:
        """Execute all test cases in a suite sequentially."""
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
        screenshots: Optional[list[str]] = None,
    ) -> ExecutionResult:
        """Parse LangGraph agent output into an ExecutionResult."""
        messages = agent_result.get("messages", [])

        last_message = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                last_message = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        status = TestStatus.PASSED
        error_message = None

        lower_msg = last_message.lower()
        if "failed" in lower_msg or "error" in lower_msg:
            status = TestStatus.FAILED
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
            screenshots=screenshots or [],
        )


class InferenceAgent:
    """Intelligence layer: analyzes execution logs, generates MD reports, and pinpoints root causes."""

    def __init__(self, config: Settings):
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.2,
        )

    async def generate_inference_report(
        self,
        log_content: str,
        summary: str,
        run_dir: Optional[Path] = None,
    ) -> tuple[dict, Optional[Path]]:
        """Analyze execution logs, generate a JSON result and an MD inference report.

        Returns:
            Tuple of (inference_dict, report_path).
        """
        system_prompt = (
            "You are a Senior QA Automation Engineer. Analyze the test execution log below and provide:\n"
            "1. The single most likely root cause of failure (one sentence)\n"
            "2. Category: 'network', 'quota', 'assertion', 'selector', or 'system'\n"
            "3. Severity: 'high', 'medium', or 'low'\n"
            "4. A list of 1-3 recommended fixes\n\n"
            "Return JSON format:\n"
            '{"inferred_reason": "...", "category": "...", "severity": "...", "recommended_fixes": ["...", "..."]}'
        )

        user_prompt = (
            f"Execution Summary: {summary}\n\n"
            f"Recent Logs:\n{log_content[-3000:]}\n\n"
            "Provide your analysis:"
        )

        inference = {
            "inferred_reason": "Analysis not available",
            "category": "system",
            "severity": "low",
            "recommended_fixes": [],
        }
        md_path = None

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])

            text = response.content
            if "```json" in text:
                text = text.split("```json")[-1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            inference = json.loads(text)

        except Exception as e:
            logger.error(f"Inference failed: {e}")
            inference["inferred_reason"] = f"Inference engine error: {e}"

        # Generate Markdown report
        if run_dir:
            md_path = self._write_inference_md(inference, summary, run_dir)

        return inference, md_path

    def _write_inference_md(
        self, inference: dict, summary: str, run_dir: Path
    ) -> Path:
        """Write the inference analysis to a Markdown file."""
        md_path = run_dir / "inference_report.md"
        now = datetime.now()

        reason = inference.get("inferred_reason", "Unknown")
        category = inference.get("category", "system")
        severity = inference.get("severity", "medium")
        fixes = inference.get("recommended_fixes", [])

        severity_label = {
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
        }.get(severity, severity.upper())

        lines = [
            "# Inference Report -- AI Failure Analysis",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Generated | {now.isoformat()} |",
            f"| Summary | {summary} |",
            f"| Severity | **{severity_label}** |",
            f"| Category | `{category}` |",
            "",
            "## Root Cause Analysis",
            "",
            f"> {reason}",
            "",
            "## Failure Category",
            "",
            f"This failure falls under the **{category}** category, which typically indicates:",
            "",
        ]

        category_explanations = {
            "network": "- Network connectivity issues, DNS failures, or page load timeouts",
            "quota": "- API rate limits exceeded (e.g., Gemini 429 errors)",
            "assertion": "- Expected content or elements not found on the page",
            "selector": "- CSS/ARIA selectors could not locate the target element",
            "system": "- Internal system error, configuration issues, or infrastructure problems",
        }
        lines.append(category_explanations.get(
            category, f"- {category} related issues"
        ))

        if fixes:
            lines.extend(["", "## Recommended Fixes", ""])
            for i, fix in enumerate(fixes, 1):
                lines.append(f"{i}. {fix}")

        lines.extend([
            "",
            "---",
            f"_Generated by Agentic Tester Inference Agent at {now.strftime('%H:%M:%S')}_",
        ])

        md_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Generated inference report: {md_path}")
        return md_path

    # Legacy compatibility
    async def infer_failure(self, log_content: str, summary: str) -> dict:
        """Legacy wrapper — calls generate_inference_report and returns just the dict."""
        inference, _ = await self.generate_inference_report(log_content, summary)
        return inference
