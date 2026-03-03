"""
LangGraph executor agent state schema.
"""

from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

from src.models.test_case import TestCase
from src.models.execution_result import StepResult, ExecutionResult


class ExecutorState(TypedDict):
    """State schema for the LangGraph executor agent.

    The `messages` field uses LangGraph's `add_messages` reducer to maintain
    the full conversation history between the LLM and tools.
    """
    # LangGraph message history (LLM ↔ tools conversation)
    messages: Annotated[list, add_messages]

    # Current test case being executed
    test_case: Optional[dict]

    # Index of the current step being executed
    current_step_index: int

    # Results collected for each step
    step_results: list[dict]

    # Screenshot file paths captured during execution
    screenshots: list[str]

    # Final aggregated execution result
    final_result: Optional[dict]

    # Current retry attempt count
    retry_count: int

    # Last error encountered
    error: Optional[str]
