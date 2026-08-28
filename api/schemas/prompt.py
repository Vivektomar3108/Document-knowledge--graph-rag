"""
Pydantic schemas for prompt-related endpoints.
"""

from pydantic import BaseModel, Field, UUID4, validator
from typing import Optional, List
from datetime import datetime


class PromptResponse(BaseModel):
    """Response for GET /api/v1/prompts/extraction"""

    id: UUID4
    version: int
    prompt_name: str
    prompt_content: str
    is_active: bool
    created_at: datetime
    created_by: Optional[str] = None
    change_notes: Optional[str] = None
    character_count: int

    @validator("character_count", pre=True, always=True)
    def calculate_character_count(cls, v, values):
        if "prompt_content" in values:
            return len(values["prompt_content"])
        return v

    class Config:
        from_attributes = True


class PromptUpdateRequest(BaseModel):
    """Request for PUT /api/v1/prompts/extraction"""

    prompt_content: str = Field(..., min_length=100)
    change_notes: Optional[str] = None
    activate_immediately: bool = True

    @validator("prompt_content")
    def validate_prompt_content(cls, v):
        # Basic security check - no code execution patterns
        dangerous_patterns = [
            "import os",
            "import sys",
            "subprocess",
            "eval(",
            "exec(",
            "__import__",
        ]
        for pattern in dangerous_patterns:
            if pattern in v:
                raise ValueError(
                    f"Prompt content contains potentially dangerous pattern: {pattern}"
                )
        return v


class PromptUpdateResponse(BaseModel):
    """Response for PUT /api/v1/prompts/extraction"""

    id: UUID4
    version: int
    prompt_name: str
    is_active: bool
    created_at: datetime
    message: str
    previous_version: Optional[int] = None
    character_count: int

    class Config:
        from_attributes = True


class PromptVersionSummary(BaseModel):
    """Summary of a prompt version for history listing."""

    id: UUID4
    version: int
    is_active: bool
    created_at: datetime
    created_by: Optional[str] = None
    change_notes: Optional[str] = None
    content_preview: str  # First 100 characters
    character_count: int

    class Config:
        from_attributes = True


class PaginationInfo(BaseModel):
    """Pagination metadata."""

    page: int
    per_page: int
    total_items: int
    total_pages: int


class PromptHistoryResponse(BaseModel):
    """Response for GET /api/v1/prompts/extraction/history"""

    versions: List[PromptVersionSummary]
    pagination: PaginationInfo

    class Config:
        from_attributes = True


class PromptVersionResponse(BaseModel):
    """Response for GET /api/v1/prompts/extraction/{version}"""

    id: UUID4
    version: int
    prompt_name: str
    prompt_content: str
    is_active: bool
    created_at: datetime
    created_by: Optional[str] = None
    change_notes: Optional[str] = None
    character_count: int

    class Config:
        from_attributes = True


class PromptActivateResponse(BaseModel):
    """Response for POST /api/v1/prompts/extraction/{version}/activate"""

    id: UUID4
    version: int
    is_active: bool
    message: str
    previous_active_version: Optional[int] = None
    activated_at: datetime

    class Config:
        from_attributes = True


class DefaultPromptResponse(BaseModel):
    """Response for GET /api/v1/prompts/extraction/default"""

    prompt_name: str
    prompt_content: str
    description: str
    character_count: int

    class Config:
        from_attributes = True
