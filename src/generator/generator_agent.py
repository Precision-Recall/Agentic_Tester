"""
Generator Agent — Uses Gemini to produce structured test cases
combining website context, local requirements, and user instructions.
"""

import json
import logging
import uuid
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import Settings
from src.models.test_case import TestCase
from src.generator.prompts import GENERATOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def generate_test_cases(
    website_context: dict,
    user_prompt: str,
    settings: Settings,
    document_context: str = "",
) -> list[TestCase]:
    """Generate structured test cases using Gemini.

    Args:
        website_context: Structured JSON dict from the context processor.
        user_prompt: The user's specific instructions.
        settings: Application settings.
        document_context: Retrieved textual context from local documents.

    Returns:
        A list of generated TestCase model instances.
    """
    logger.info("Starting test case generation...")
    
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.2, # slightly higher for creativity, but low for structure
        max_retries=2,
    )

    # Convert structured context back to a robust string representation
    context_str = json.dumps(website_context, indent=2)
    # Trim if it's absurdly large, though gemini-2.5-pro has a huge context window
    if len(context_str) > 500000:
        logger.warning(f"Context string is very large ({len(context_str)} chars), truncating.")
        context_str = context_str[:500000]

    sys_prompt = GENERATOR_SYSTEM_PROMPT.format(
        website_context=context_str,
        document_context=document_context if document_context else "No external documents provided.",
        user_prompt=user_prompt,
    )

    logger.info("Sending generation request to LLM")
    
    response = await llm.ainvoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content="Generate the test cases exactly as requested in the JSON format.")
    ])

    test_cases_data = _parse_llm_json_array(response.content)
    
    if not test_cases_data:
        logger.error("Failed to parse test cases from LLM output")
        return []

    logger.info(f"Successfully generated {len(test_cases_data)} test cases")
    
    test_cases = []
    project_id = website_context.get("project_id", "default")
    
    for item in test_cases_data:
        try:
            # Ensure valid ID and project_id inject
            if "id" not in item:
                item["id"] = f"tc-gen-{str(uuid.uuid4())[:8]}"
            item["project_id"] = project_id
            
            # Map url if not present and available in context
            if "url" not in item and "base_url" in website_context:
                item["url"] = website_context["base_url"]
                
            tc = TestCase(**item)
            test_cases.append(tc)
        except Exception as e:
            logger.warning(f"Failed to validate generated test case: {e}\nData: {item}")

    return test_cases


def _parse_llm_json_array(content: str) -> list[dict]:
    """Parse JSON array from LLM response, handling markdown fences."""
    text = content.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "test_cases" in data:
            return data["test_cases"]
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

    return []
