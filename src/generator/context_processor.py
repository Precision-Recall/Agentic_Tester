"""
Context Processor — Uses LLM to convert raw website snapshots into
a structured, usable representation for the Generator.
"""

import json
import logging
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from src.config import Settings
from src.models.website_context import WebsiteContext
from src.generator.prompts import CONTEXT_PROCESSOR_PROMPT

logger = logging.getLogger(__name__)


async def process_website_context(
    context: WebsiteContext,
    settings: Settings,
) -> dict:
    """Process raw website context through LLM to create structured representation.

    Args:
        context: Raw WebsiteContext from the collector.
        settings: Application settings.

    Returns:
        Structured dict with page hierarchy, elements, flows, etc.
    """
    logger.info(f"Processing context for: {context.url} ({len(context.pages)} pages)")

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.0,
        max_retries=2,
    )

    processed_pages = []

    for page in context.pages:
        if not page.raw_snapshot:
            logger.warning(f"Skipping page {page.url} — no raw snapshot")
            continue

        prompt = CONTEXT_PROCESSOR_PROMPT.format(raw_snapshot=page.raw_snapshot[:8000])

        logger.info(f"Processing page: {page.url}")
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        page_data = _parse_llm_json(response.content)
        if page_data:
            page_data["url"] = page.url
            processed_pages.append(page_data)
        else:
            # Fallback: use the raw parsed elements
            processed_pages.append({
                "url": page.url,
                "page_title": page.title,
                "page_type": "unknown",
                "interactive_elements": [
                    {"type": e.type, "text": e.text, "role": e.role}
                    for e in page.elements
                ],
                "navigation": [{"url": link} for link in page.navigation_links],
                "headings": page.headings,
            })

    processed = {
        "base_url": context.url,
        "collected_at": context.collected_at.isoformat(),
        "total_pages": len(processed_pages),
        "pages": processed_pages,
    }

    logger.info(f"Context processing complete: {len(processed_pages)} pages processed")
    return processed


def _parse_llm_json(content: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown fences."""
    text = content.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

    logger.warning("Failed to parse LLM output as JSON")
    return None
