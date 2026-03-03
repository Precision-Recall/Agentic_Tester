"""
LangGraph StateGraph definition for the executor agent.

Follows the standard ReAct pattern from langchain-mcp-adapters:
  call_model → (tool_calls?) → tools → call_model → ... → END
"""

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from src.executor.state import ExecutorState
from src.executor.prompts import EXECUTOR_SYSTEM_PROMPT


def build_executor_graph(llm, tools: list):
    """Build the LangGraph StateGraph for test execution.

    This creates a standard ReAct agent loop:
    1. call_model: LLM decides what to do (call a tool or finish)
    2. tools: Execute the tool(s) selected by the LLM
    3. Loop back to call_model until the LLM stops calling tools

    Args:
        llm: The ChatGoogleGenerativeAI model instance.
        tools: Combined list of Playwright MCP tools and custom assertion tools.

    Returns:
        Compiled LangGraph graph ready for invocation.
    """
    # Bind tools so the LLM knows what tools are available
    model_with_tools = llm.bind_tools(tools)

    def call_model(state: ExecutorState) -> dict:
        """LLM reasoning node — decides which tool to call next."""
        messages = state["messages"]

        # Inject system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=EXECUTOR_SYSTEM_PROMPT)] + messages

        response = model_with_tools.invoke(messages)
        return {"messages": [response]}

    # Build the graph
    builder = StateGraph(ExecutorState)

    # Add nodes
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(tools))

    # Edges: START → call_model
    builder.add_edge(START, "call_model")

    # Conditional edge: call_model → tools (if tool calls) or END (if done)
    builder.add_conditional_edges("call_model", tools_condition)

    # After tool execution, loop back to call_model
    builder.add_edge("tools", "call_model")

    return builder.compile()
