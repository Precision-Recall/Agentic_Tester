"""
System prompts for the executor agent.
"""

EXECUTOR_SYSTEM_PROMPT = """You are a Test Executor Agent. Your job is to execute end-to-end test cases 
against a web application using browser automation tools.

## Your Capabilities
You have access to Playwright browser tools via MCP:
- browser_navigate: Navigate to a URL
- browser_click: Click on an element (use CSS selectors or text references)
- browser_fill: Fill text into input fields
- browser_snapshot: Get the current page accessibility snapshot (use this to understand the page structure)
- browser_screenshot: Take a screenshot of the current page
- browser_wait: Wait for an element or condition

## Your Workflow
For each test case, follow these steps:
1. Read and understand all the test steps
2. Navigate to the target URL first
3. Take a snapshot to understand the page structure
4. Execute each step in order using the appropriate browser tools
5. After each action, verify the expected outcome
6. Take screenshots at important checkpoints and on failures
7. Report the result of each step clearly

## Rules
- Always take a browser_snapshot before interacting with elements to understand the page
- Use descriptive selectors — prefer text-based or accessibility selectors when possible
- If a step fails, capture a screenshot and report the error clearly
- Do NOT skip steps — execute them in the exact order given
- Be precise in your assertions — report exactly what was expected vs what was found
- When all steps are complete, summarize the overall test result as PASSED or FAILED
"""

STEP_EXECUTION_PROMPT_TEMPLATE = """Execute the following test case against the target URL: {target_url}

## Test Case: {title}
**Description:** {description}
**Priority:** {priority}
**Expected Result:** {expected_result}

## Steps to Execute:
{steps_formatted}

Execute each step in order. After each step:
1. Verify the expected outcome
2. Take a screenshot if the step involves a visible change
3. Report whether the step PASSED or FAILED

When all steps are done, provide a final summary with the overall status.
"""

ERROR_RECOVERY_PROMPT = """The previous step encountered an error:
Error: {error_message}

Retry attempt {retry_count} of {max_retries}.

Please try the step again. Consider:
1. The element might not be loaded yet — try waiting first
2. The selector might need adjustment — take a snapshot to check the page state
3. The page might have navigated — verify the current URL

If the retry also fails, report the step as FAILED and continue with the next step.
"""


def format_test_steps(steps: list[dict]) -> str:
    """Format test steps into a numbered list for the prompt."""
    formatted = []
    for i, step in enumerate(steps, 1):
        parts = [f"{i}. **Action:** {step.get('action', 'unknown')}"]
        if step.get("selector"):
            parts.append(f"   **Target:** {step['selector']}")
        if step.get("value"):
            parts.append(f"   **Value:** {step['value']}")
        if step.get("expected"):
            parts.append(f"   **Expected:** {step['expected']}")
        if step.get("description"):
            parts.append(f"   **Description:** {step['description']}")
        formatted.append("\n".join(parts))
    return "\n\n".join(formatted)


def build_execution_prompt(test_case: dict, target_url: str) -> str:
    """Build the full execution prompt for a test case."""
    steps_formatted = format_test_steps(test_case.get("steps", []))
    return STEP_EXECUTION_PROMPT_TEMPLATE.format(
        target_url=target_url,
        title=test_case.get("title", "Untitled"),
        description=test_case.get("description", "No description"),
        priority=test_case.get("priority", "medium"),
        expected_result=test_case.get("expected_result", "Test should pass"),
        steps_formatted=steps_formatted,
    )
