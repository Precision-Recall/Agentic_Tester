import asyncio
from src.config import get_settings
from src.generator.context_collector import collect_website_context
from src.generator.context_processor import process_website_context
from src.generator.document_indexer import index_documents, retrieve_relevant_context
from src.generator.generator_agent import generate_test_cases
from src.executor.mcp_config import create_mcp_client
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

async def main():
    settings = get_settings()
    url = "https://example.com"
    logger.info(f"Target URL: {url}")
    
    # 1. Provide a dummy doc for testing
    import os
    os.makedirs("test_docs", exist_ok=True)
    with open("test_docs/requirements.txt", "w") as f:
        f.write("The system shall allow users to log in with email and password. A 'Forgot Password' link should be available. Successful login should redirect to the dashboard.")
    
    # 2. Index Documents
    logger.info("Indexing local documents...")
    vector_store = await index_documents("test_docs", settings)
    
    # 3. Retrieve Context
    prompt = "Create authentication test cases"
    doc_context = ""
    if vector_store:
        logger.info(f"Retrieving context for prompt: '{prompt}'")
        doc_context = await retrieve_relevant_context(vector_store, prompt, settings)
        logger.info(f"Retrieved Document Context: {doc_context}")

    # 4. Dummy Website Context (to bypass Playwright crawl for pure module test)
    dummy_website_context = {
        "url": url,
        "pages": [{"url": url, "title": "Example Domain", "elements": [], "navigation_links": [], "raw_snapshot": ""}],
        "collected_at": "2023-10-27T10:00:00Z",
        "processed_context": {
            "page_title": "Example Domain",
            "page_type": "informative",
            "interactive_elements": [{"type": "link", "text": "More Information", "selector": "a"}],
            "forms": [],
            "navigation": [],
            "content_sections": ["This domain is for use in illustrative examples in documents."]
        }
    }

    # 5. Generate Test Cases
    logger.info("Generating test cases...")
    test_cases = await generate_test_cases(
        website_context=dummy_website_context,
        user_prompt=prompt,
        settings=settings,
        document_context=doc_context
    )
    
    logger.info(f"Generated {len(test_cases)} test cases:")
    for tc in test_cases:
        logger.info(f"\nID: {tc.id} | Priority: {tc.priority} | Category: {tc.category}")
        logger.info(f"Title: {tc.title}")
        logger.info(f"Steps: {len(tc.steps)}")
        for step in tc.steps:
            logger.info(f"  - {step.action} '{step.value or ''}' on '{step.selector or ''}' -> {step.expected or ''}")

if __name__ == "__main__":
    asyncio.run(main())
