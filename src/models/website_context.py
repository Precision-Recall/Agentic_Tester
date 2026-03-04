"""
Website context models for the Generator Agent.
Represents the structured context extracted from a target website.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UIElement(BaseModel):
    """An interactive UI element on a page."""
    type: str = Field(..., description="Element type: button, input, link, form, select, etc.")
    text: str = Field("", description="Visible text or label")
    selector: Optional[str] = Field(None, description="CSS selector for the element")
    role: str = Field("", description="ARIA role if available")
    attributes: dict = Field(default_factory=dict, description="Extra attributes")


class PageContext(BaseModel):
    """Structured context for a single page."""
    url: str = Field(..., description="Page URL")
    title: str = Field("", description="Page title")
    elements: list[UIElement] = Field(default_factory=list, description="Interactive UI elements")
    navigation_links: list[str] = Field(default_factory=list, description="Navigation link URLs")
    headings: list[str] = Field(default_factory=list, description="Page headings hierarchy")
    forms: list[dict] = Field(default_factory=list, description="Form structures with fields")
    raw_snapshot: str = Field("", description="Raw accessibility snapshot text")


class WebsiteContext(BaseModel):
    """Full website context collected via Playwright."""
    url: str = Field(..., description="Base website URL")
    project_id: str = Field("", description="Associated project ID")
    pages: list[PageContext] = Field(default_factory=list, description="Crawled pages")
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    processed_context: Optional[dict] = Field(None, description="LLM-structured representation")
    context_hash: str = Field("", description="Hash for cache validation")
