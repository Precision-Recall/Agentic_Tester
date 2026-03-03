"""
MCP Server Configuration — Config-based approach (like Claude).

No manual server startup needed. The MultiServerMCPClient spawns the
MCP server on-demand via stdio transport and communicates through it.
Just provide the config and invoke tools.
"""

from langchain_mcp_adapters.client import MultiServerMCPClient


# MCP server config — equivalent to Claude's mcp_servers config JSON.
# The client manages the server lifecycle: spawns on connect, kills on disconnect.
MCP_SERVERS_CONFIG = {
    "playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest"
      ]
    }
}


def create_mcp_client() -> MultiServerMCPClient:
    """Create a configured MCP client for Playwright.

    Usage (as async context manager):
        async with create_mcp_client() as client:
            tools = client.get_tools()
            # use tools with LangGraph agent

    The client spawns the Playwright MCP server process when entering
    the context and cleans it up when exiting — no background server needed.
    """
    return MultiServerMCPClient(MCP_SERVERS_CONFIG)
