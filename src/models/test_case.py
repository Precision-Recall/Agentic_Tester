"""
Test case data models matching the Firebase schema from design.md.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Priority(str, Enum):
    """Test case priority levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    """Test case categories."""
    FUNCTIONAL = "functional"
    BOUNDARY = "boundary"
    NEGATIVE = "negative"
    UI = "ui"
    API = "api"


class TestStep(BaseModel):
    """Individual test step within a test case."""
    action: str = Field(..., description="Action to perform (navigate, click, fill, assert, etc.)")
    selector: Optional[str] = Field(None, description="CSS/XPath selector for the target element")
    value: Optional[str] = Field(None, description="Value to input or expected value")
    expected: Optional[str] = Field(None, description="Expected outcome of this step")
    description: str = Field("", description="Human-readable description of the step")


class TestCase(BaseModel):
    """Full test case matching Firebase test_cases collection schema."""
    id: str = Field(..., description="Unique test case identifier")
    project_id: str = Field(..., description="Parent project identifier")
    title: str = Field(..., description="Test case title")
    description: str = Field("", description="Detailed description of what is being tested")
    steps: list[TestStep] = Field(default_factory=list, description="Ordered list of test steps")
    expected_result: str = Field("", description="Overall expected result of the test")
    priority: Priority = Field(Priority.MEDIUM, description="Test priority level")
    category: Category = Field(Category.FUNCTIONAL, description="Test category")
    generated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    requirements_mapping: list[str] = Field(default_factory=list, description="Mapped requirement IDs")
    url: Optional[str] = Field(None, description="Target URL for this test case")


class TestSuite(BaseModel):
    """Collection of test cases for batch execution."""
    id: str = Field(..., description="Suite execution identifier")
    project_id: str = Field(..., description="Parent project identifier")
    test_cases: list[TestCase] = Field(default_factory=list)
    target_url: str = Field(..., description="Base URL for test execution")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
