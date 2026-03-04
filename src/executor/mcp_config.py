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
      ],
      "transport": "stdio"
    }
}


def create_mcp_client() -> MultiServerMCPClient:
    """Create a configured MCP client for Playwright.

    Usage:
        client = create_mcp_client()
        tools = await client.get_tools()
        # use tools with LangGraph agent

    The client manages the lifecycle of configured MCP servers.
    """
    return MultiServerMCPClient(MCP_SERVERS_CONFIG)
