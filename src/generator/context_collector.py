"""
Context Collector — Crawls a website using Playwright MCP and extracts structured context.

Uses browser_navigate + browser_snapshot to get the accessibility tree,
then parses it into a WebsiteContext model.
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.config import Settings
from src.models.website_context import WebsiteContext, PageContext, UIElement
from src.generator.prompts import CRAWL_INSTRUCTION_PROMPT
from src.executor.mcp_config import create_mcp_client
from src.executor.graph import build_executor_graph

logger = logging.getLogger(__name__)


async def collect_website_context(
    url: str,
    settings: Settings,
    mcp_client: Optional[MultiServerMCPClient] = None,
) -> WebsiteContext:
    """Crawl a website using Playwright MCP and extract structured context.

    Args:
        url: The base URL to crawl.
        settings: Application settings.
        mcp_client: Optional shared MCP client.

    Returns:
        WebsiteContext with raw snapshots of crawled pages.
    """
    logger.info(f"Collecting website context for: {url}")

    client = mcp_client or create_mcp_client()
    mcp_tools = await client.get_tools()

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.0,
        max_retries=2,
    )

    graph = build_executor_graph(llm, mcp_tools)

    # Crawl the main page
    prompt = CRAWL_INSTRUCTION_PROMPT.format(url=url)

    logger.info(f"Crawling main page: {url}")
    result = await graph.ainvoke({
        "messages": [HumanMessage(content=prompt)],
        "test_case": {"id": "context-crawl", "title": f"Crawl {url}", "steps": []},
        "current_step_index": 0,
        "step_results": [],
        "screenshots": [],
        "final_result": None,
        "retry_count": 0,
        "error": None,
    })

    # Extract the snapshot from the agent's response
    raw_snapshot = _extract_snapshot_from_messages(result.get("messages", []))

    page = PageContext(
        url=url,
        title=_extract_title(raw_snapshot),
        raw_snapshot=raw_snapshot,
        elements=_parse_elements(raw_snapshot),
        navigation_links=_parse_nav_links(raw_snapshot, url),
        headings=_parse_headings(raw_snapshot),
    )

    context_hash = hashlib.md5(raw_snapshot.encode()).hexdigest()

    context = WebsiteContext(
        url=url,
        pages=[page],
        collected_at=datetime.utcnow(),
        context_hash=context_hash,
    )

    logger.info(f"Context collected: {len(page.elements)} elements, {len(page.navigation_links)} nav links")
    return context


def _extract_snapshot_from_messages(messages: list) -> str:
    """Extract the accessibility snapshot text from agent messages."""
    snapshot_text = ""
    for msg in reversed(messages):
        content = ""
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                content = msg.content
            elif isinstance(msg.content, list):
                content = " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in msg.content
                )
        if content and len(content) > 200:
            snapshot_text = content
            break
    return snapshot_text


def _extract_title(snapshot: str) -> str:
    """Extract page title from snapshot."""
    for line in snapshot.split("\n"):
        line = line.strip()
        if line.lower().startswith("title:"):
            return line.split(":", 1)[1].strip()
        if "- document" in line.lower() or "- webpage" in line.lower():
            return line.strip("- ").strip()
    return "Untitled Page"


def _parse_elements(snapshot: str) -> list[UIElement]:
    """Parse interactive elements from the accessibility snapshot."""
    elements = []
    interactive_types = {
        "button", "link", "textbox", "input", "checkbox",
        "radio", "combobox", "searchbox", "menuitem", "tab",
        "slider", "switch", "option", "select",
    }

    for line in snapshot.split("\n"):
        line_lower = line.strip().lower()
        for etype in interactive_types:
            if etype in line_lower:
                text = line.strip().lstrip("- ").strip()
                # Remove the role prefix
                if ":" in text:
                    text = text.split(":", 1)[1].strip()
                elements.append(UIElement(
                    type=etype,
                    text=text[:100],
                    role=etype,
                ))
                break

    return elements


def _parse_nav_links(snapshot: str, base_url: str) -> list[str]:
    """Parse navigation links from the snapshot."""
    links = []
    for line in snapshot.split("\n"):
        line = line.strip()
        if "link" in line.lower() and ("http" in line or "/" in line):
            # Extract URL-like patterns
            parts = line.split()
            for part in parts:
                if part.startswith("http") or (part.startswith("/") and len(part) > 1):
                    links.append(part)
                    break
    return links[:20]  # Cap at 20 links


def _parse_headings(snapshot: str) -> list[str]:
    """Parse headings from the snapshot."""
    headings = []
    for line in snapshot.split("\n"):
        line_lower = line.strip().lower()
        if "heading" in line_lower:
            text = line.strip().lstrip("- ").strip()
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            if text:
                headings.append(text[:100])
    return headings
